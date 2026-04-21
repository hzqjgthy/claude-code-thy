from claude_code_thy.config import AppConfig


def test_app_config_defaults_without_api_credentials(monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_THY_PROVIDER", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_THY_MODEL", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_RESPONSES_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_RESPONSES_MODEL", raising=False)

    config = AppConfig.from_env()

    assert config.provider == "unconfigured"
    assert config.model == "glm-4.5"


def test_app_config_selects_anthropic_provider(monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_THY_PROVIDER", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_THY_MODEL", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-sonnet-4-5")
    monkeypatch.delenv("OPENAI_RESPONSES_API_KEY", raising=False)

    config = AppConfig.from_env()

    assert config.provider == "anthropic-compatible"
    assert config.model == "claude-sonnet-4-5"


def test_app_config_selects_openai_responses_provider(monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_THY_PROVIDER", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_THY_MODEL", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("OPENAI_RESPONSES_API_KEY", "test-openai-key")
    monkeypatch.setenv("OPENAI_RESPONSES_MODEL", "gpt-5.4")
    monkeypatch.setenv("OPENAI_RESPONSES_USE_PREVIOUS_RESPONSE_ID", "true")

    config = AppConfig.from_env()

    assert config.provider == "openai-responses-compatible"
    assert config.model == "gpt-5.4"
    assert config.openai_responses_use_previous_response_id is True


def test_app_config_prefers_explicit_provider_and_global_model(monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_THY_PROVIDER", "openai-responses-compatible")
    monkeypatch.setenv("CLAUDE_CODE_THY_MODEL", "gpt-5.3")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_RESPONSES_API_KEY", "test-openai-key")

    config = AppConfig.from_env()

    assert config.provider == "openai-responses-compatible"
    assert config.model == "gpt-5.3"
