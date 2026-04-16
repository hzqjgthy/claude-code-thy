from claude_code_thy.config import AppConfig
from claude_code_thy.providers import AnthropicCompatibleProvider, build_provider
from claude_code_thy.providers.base import ProviderConfigurationError


def test_build_provider_returns_real_provider_when_configured():
    config = AppConfig(
        provider="anthropic-compatible",
        model="claude-sonnet-4-5",
        anthropic_api_key="test-key",
    )

    provider = build_provider(config)

    assert isinstance(provider, AnthropicCompatibleProvider)


def test_build_provider_raises_when_unconfigured():
    config = AppConfig(
        provider="unconfigured",
        model="glm-4.5",
    )

    try:
        build_provider(config)
    except ProviderConfigurationError as error:
        assert "ANTHROPIC_API_KEY" in str(error)
    else:
        raise AssertionError("Expected ProviderConfigurationError")
