from __future__ import annotations

from claude_code_thy.config import AppConfig
from claude_code_thy.providers.anthropic import AnthropicCompatibleProvider
from claude_code_thy.providers.openai_responses import OpenAIResponsesProvider
from claude_code_thy.providers.base import Provider, ProviderConfigurationError


def build_provider(config: AppConfig) -> Provider:
    if config.provider == "anthropic-compatible":
        if not (config.anthropic_api_key or config.anthropic_auth_token):
            raise ProviderConfigurationError(
                "当前 provider=anthropic-compatible，但未配置凭证。请在环境变量或 .env 中设置 "
                "ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN。"
            )
        return AnthropicCompatibleProvider(config)
    if config.provider == "openai-responses-compatible":
        if not config.openai_responses_api_key:
            raise ProviderConfigurationError(
                "当前 provider=openai-responses-compatible，但未配置凭证。请在环境变量或 .env 中设置 "
                "OPENAI_RESPONSES_API_KEY。"
            )
        return OpenAIResponsesProvider(config)
    raise ProviderConfigurationError(
        "未检测到可用 provider。请设置 CLAUDE_CODE_THY_PROVIDER，或补充 "
        "ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN / OPENAI_RESPONSES_API_KEY。"
    )
