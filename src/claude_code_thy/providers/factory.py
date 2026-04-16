from __future__ import annotations

from claude_code_thy.config import AppConfig
from claude_code_thy.providers.anthropic import AnthropicCompatibleProvider
from claude_code_thy.providers.base import Provider, ProviderConfigurationError


def build_provider(config: AppConfig) -> Provider:
    if config.provider == "anthropic-compatible":
        return AnthropicCompatibleProvider(config)
    raise ProviderConfigurationError(
        "未检测到真实 API 配置。请在环境变量或 .env 中设置 "
        "ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN。"
    )
