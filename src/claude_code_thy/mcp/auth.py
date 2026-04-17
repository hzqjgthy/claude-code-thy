from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen

from claude_code_thy.mcp.names import normalize_name_for_mcp

from .errors import McpRuntimeError
from .oauth_port import OAuthCallbackServer
from .types import McpServerConfig


TOKEN_DIRNAME = "mcp-auth"


@dataclass(slots=True)
class OAuthServerSettings:
    client_id: str
    client_secret: str | None
    callback_port: int
    metadata_url: str
    scopes: tuple[str, ...]


def supports_oauth(config: McpServerConfig) -> bool:
    return oauth_settings_for_config(config) is not None


def oauth_settings_for_config(config: McpServerConfig) -> OAuthServerSettings | None:
    raw = config.oauth
    if not raw and isinstance(config.raw_config.get("oauth"), dict):
        raw = {
            str(key): value
            for key, value in config.raw_config["oauth"].items()  # type: ignore[index]
        }
    if not raw:
        return None
    metadata_url = str(raw.get("authServerMetadataUrl", "")).strip()
    if not metadata_url and config.url:
        metadata_url = urljoin(config.url, "/.well-known/oauth-authorization-server")
    if not metadata_url:
        return None
    scopes_raw = raw.get("scopes")
    scopes: tuple[str, ...]
    if isinstance(scopes_raw, list):
        scopes = tuple(str(item).strip() for item in scopes_raw if str(item).strip())
    elif isinstance(scopes_raw, str) and scopes_raw.strip():
        scopes = tuple(part.strip() for part in scopes_raw.split() if part.strip())
    else:
        scopes = ("openid", "profile", "offline_access")
    return OAuthServerSettings(
        client_id=str(raw.get("clientId", "claude-code-thy")).strip() or "claude-code-thy",
        client_secret=(
            str(raw.get("clientSecret")).strip()
            if raw.get("clientSecret") is not None and str(raw.get("clientSecret")).strip()
            else None
        ),
        callback_port=max(1, int(raw.get("callbackPort", 8765) or 8765)),
        metadata_url=metadata_url,
        scopes=scopes,
    )


def get_oauth_authorization_header(config: McpServerConfig) -> dict[str, str]:
    if not supports_oauth(config):
        return {}
    token = load_access_token(config.name)
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}"}


def load_access_token(server_name: str) -> str | None:
    data = _load_token_payload(server_name)
    if not data:
        return None
    expires_at = float(data.get("expires_at", 0) or 0)
    if expires_at and expires_at <= time.time():
        return None
    token = str(data.get("access_token", "")).strip()
    return token or None


def clear_oauth_tokens(server_name: str) -> None:
    path = _token_path(server_name)
    try:
        path.unlink()
    except OSError:
        return


def start_oauth_flow(
    server_name: str,
    config: McpServerConfig,
    *,
    on_complete,
) -> str:
    settings = oauth_settings_for_config(config)
    if settings is None:
        raise McpRuntimeError(f"MCP server `{server_name}` 没有可用的 OAuth 配置")

    metadata = _fetch_oauth_metadata(settings.metadata_url)
    authorization_endpoint = str(metadata.get("authorization_endpoint", "")).strip()
    token_endpoint = str(metadata.get("token_endpoint", "")).strip()
    if not authorization_endpoint or not token_endpoint:
        raise McpRuntimeError("OAuth metadata 缺少 authorization_endpoint 或 token_endpoint")

    state = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(48)
    challenge = _pkce_challenge(verifier)
    callback_server = OAuthCallbackServer(settings.callback_port, state)
    auth_url = f"{authorization_endpoint}?{urlencode({
        'response_type': 'code',
        'client_id': settings.client_id,
        'redirect_uri': callback_server.redirect_uri,
        'scope': ' '.join(settings.scopes),
        'state': state,
        'code_challenge': challenge,
        'code_challenge_method': 'S256',
    })}"

    def complete_flow() -> None:
        try:
            result = callback_server.wait_for_result()
            if result.error:
                on_complete(False, result.error)
                return
            if not result.code:
                on_complete(False, "OAuth callback 没有返回授权码")
                return
            token_payload = _exchange_code_for_token(
                token_endpoint=token_endpoint,
                code=result.code,
                redirect_uri=callback_server.redirect_uri,
                client_id=settings.client_id,
                client_secret=settings.client_secret,
                code_verifier=verifier,
            )
            _save_token_payload(server_name, token_payload)
            on_complete(True, None)
        except Exception as error:  # noqa: BLE001
            on_complete(False, str(error))
        finally:
            callback_server.close()

    threading.Thread(
        target=complete_flow,
        name=f"mcp-oauth-flow-{normalize_name_for_mcp(server_name)}",
        daemon=True,
    ).start()
    return auth_url


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")


def _fetch_oauth_metadata(metadata_url: str) -> dict[str, object]:
    request = Request(metadata_url, headers={"Accept": "application/json"})
    with urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def _exchange_code_for_token(
    *,
    token_endpoint: str,
    code: str,
    redirect_uri: str,
    client_id: str,
    client_secret: str | None,
    code_verifier: str,
) -> dict[str, object]:
    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "code_verifier": code_verifier,
    }
    if client_secret:
        payload["client_secret"] = client_secret
    request = Request(
        token_endpoint,
        data=urlencode(payload).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urlopen(request, timeout=30) as response:
        data = json.loads(response.read().decode("utf-8"))
    if not isinstance(data, dict):
        raise McpRuntimeError("OAuth token 响应不是 object")
    if "access_token" not in data:
        raise McpRuntimeError("OAuth token 响应缺少 access_token")
    expires_in = int(data.get("expires_in", 3600) or 3600)
    data["expires_at"] = time.time() + max(expires_in - 30, 30)
    return data


def _save_token_payload(server_name: str, payload: dict[str, object]) -> None:
    path = _token_path(server_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_token_payload(server_name: str) -> dict[str, object] | None:
    path = _token_path(server_name)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _token_path(server_name: str) -> Path:
    configured_home = os.environ.get("CLAUDE_CODE_THY_HOME")
    if configured_home:
        base_dir = Path(configured_home).expanduser().resolve()
    else:
        base_dir = Path.home() / ".claude-code-thy"
    return base_dir / TOKEN_DIRNAME / f"{normalize_name_for_mcp(server_name)}.json"
