from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


_DOTENV_LOADED = False


@dataclass(slots=True)
class AppConfig:
    provider: str
    model: str
    anthropic_api_key: str | None = None
    anthropic_auth_token: str | None = None
    anthropic_base_url: str = "https://api.anthropic.com"
    api_timeout_ms: int = 600_000
    max_tokens: int = 4096

    @classmethod
    def from_env(cls) -> "AppConfig":
        _load_dotenv_if_present()

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        auth_token = os.environ.get("ANTHROPIC_AUTH_TOKEN")
        model = os.environ.get("ANTHROPIC_MODEL", "glm-4.5")
        base_url = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
        timeout_ms = _int_env("API_TIMEOUT_MS", default=600_000)
        max_tokens = _int_env("CLAUDE_CODE_THY_MAX_TOKENS", default=4096)

        provider = "anthropic-compatible" if (api_key or auth_token) else "unconfigured"

        return cls(
            provider=provider,
            model=model,
            anthropic_api_key=api_key,
            anthropic_auth_token=auth_token,
            anthropic_base_url=base_url,
            api_timeout_ms=timeout_ms,
            max_tokens=max_tokens,
        )


def _int_env(name: str, default: int) -> int:
    value = os.environ.get(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _load_dotenv_if_present() -> None:
    global _DOTENV_LOADED
    if _DOTENV_LOADED:
        return

    dotenv_path = _find_dotenv(Path.cwd())
    if dotenv_path is None:
        _DOTENV_LOADED = True
        return

    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()

        if value and len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]

        os.environ.setdefault(key, value)

    _DOTENV_LOADED = True


def _find_dotenv(start: Path) -> Path | None:
    current = start.resolve()
    while True:
        candidate = current / ".env"
        if candidate.exists() and candidate.is_file():
            return candidate
        if current.parent == current:
            return None
        current = current.parent
