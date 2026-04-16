from claude_code_thy.config import AppConfig


def test_app_config_defaults_without_api_credentials(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)

    config = AppConfig.from_env()

    assert config.provider == "unconfigured"
    assert config.model == "glm-4.5"


def test_app_config_selects_anthropic_provider(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-sonnet-4-5")

    config = AppConfig.from_env()

    assert config.provider == "anthropic-compatible"
    assert config.model == "claude-sonnet-4-5"
