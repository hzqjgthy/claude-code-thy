from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


_DOTENV_LOADED = False


@dataclass(slots=True)
class AppConfig:
    """保存模型提供方、鉴权和请求参数等运行配置。"""
    provider: str
    model: str
    anthropic_api_key: str | None = None
    anthropic_auth_token: str | None = None
    anthropic_base_url: str = "https://api.anthropic.com"
    openai_responses_api_key: str | None = None
    openai_responses_base_url: str = "https://api.openai.com"
    openai_responses_reasoning_effort: str | None = None
    openai_responses_enable_stream: bool = False
    openai_responses_use_previous_response_id: bool = False
    api_timeout_ms: int = 600_000
    max_tokens: int = 4096
    query_max_iterations: int = 1000

    @classmethod
    def from_env(cls) -> "AppConfig":
        """从环境变量和 `.env` 文件组装应用配置。"""
        _load_dotenv_if_present()

        explicit_provider = os.environ.get("CLAUDE_CODE_THY_PROVIDER", "").strip()
        global_model = os.environ.get("CLAUDE_CODE_THY_MODEL", "").strip()
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        auth_token = os.environ.get("ANTHROPIC_AUTH_TOKEN")
        anthropic_model = os.environ.get("ANTHROPIC_MODEL", "glm-4.5")
        anthropic_base_url = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
        openai_api_key = os.environ.get("OPENAI_RESPONSES_API_KEY")
        openai_model = os.environ.get("OPENAI_RESPONSES_MODEL", "gpt-5.4")
        openai_base_url = os.environ.get("OPENAI_RESPONSES_BASE_URL", "https://api.openai.com")
        openai_reasoning_effort = os.environ.get("OPENAI_RESPONSES_REASONING_EFFORT", "").strip() or None
        openai_enable_stream = _bool_env("OPENAI_RESPONSES_ENABLE_STREAM", default=False)
        openai_use_previous_response_id = _bool_env("OPENAI_RESPONSES_USE_PREVIOUS_RESPONSE_ID", default=False)
        timeout_ms = _int_env("API_TIMEOUT_MS", default=600_000)
        max_tokens = _int_env("CLAUDE_CODE_THY_MAX_TOKENS", default=4096)
        query_max_iterations = max(
            1,
            _int_env("CLAUDE_CODE_THY_QUERY_MAX_ITERATIONS", default=1000),
        )

        provider = explicit_provider or _infer_provider(
            anthropic_api_key=api_key,
            anthropic_auth_token=auth_token,
            openai_responses_api_key=openai_api_key,
        )
        model = _resolve_model(
            provider=provider,
            global_model=global_model,
            anthropic_model=anthropic_model,
            openai_model=openai_model,
        )

        return cls(
            provider=provider,
            model=model,
            anthropic_api_key=api_key,
            anthropic_auth_token=auth_token,
            anthropic_base_url=anthropic_base_url,
            openai_responses_api_key=openai_api_key,
            openai_responses_base_url=openai_base_url,
            openai_responses_reasoning_effort=openai_reasoning_effort,
            openai_responses_enable_stream=openai_enable_stream,
            openai_responses_use_previous_response_id=openai_use_previous_response_id,
            api_timeout_ms=timeout_ms,
            max_tokens=max_tokens,
            query_max_iterations=query_max_iterations,
        )


def _int_env(name: str, default: int) -> int:
    """读取整数环境变量，格式不合法时回退到默认值。"""
    value = os.environ.get(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _bool_env(name: str, default: bool) -> bool:
    """读取布尔环境变量，兼容常见的真值写法。"""
    value = os.environ.get(name)
    if not value:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _infer_provider(
    *,
    anthropic_api_key: str | None,
    anthropic_auth_token: str | None,
    openai_responses_api_key: str | None,
) -> str:
    """根据现有凭证自动推断默认 provider。"""
    if anthropic_api_key or anthropic_auth_token:
        return "anthropic-compatible"
    if openai_responses_api_key:
        return "openai-responses-compatible"
    return "unconfigured"


def _resolve_model(
    *,
    provider: str,
    global_model: str,
    anthropic_model: str,
    openai_model: str,
) -> str:
    """在全局模型和 provider 专属模型之间选出最终模型名。"""
    if global_model:
        return global_model
    if provider == "openai-responses-compatible":
        return openai_model
    return anthropic_model


def _load_dotenv_if_present() -> None:
    """仅在首次读取配置时加载当前目录链上的 `.env` 文件。"""
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
    """从当前目录向上查找最近的 `.env` 文件。"""
    current = start.resolve()
    while True:
        candidate = current / ".env"
        if candidate.exists() and candidate.is_file():
            return candidate
        if current.parent == current:
            return None
        current = current.parent
