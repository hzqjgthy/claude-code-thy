import json

from claude_code_thy.config import AppConfig
from claude_code_thy.models import SessionTranscript
from claude_code_thy.providers.anthropic import AnthropicCompatibleProvider


class _FakeHttpResponse:
    def __init__(self, body: dict[str, object]) -> None:
        self._body = json.dumps(body, ensure_ascii=False).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return self._body


def test_anthropic_provider_ignores_null_error_field(monkeypatch):
    config = AppConfig(
        provider="anthropic-compatible",
        model="glm-4.5",
        anthropic_api_key="test-key",
        anthropic_base_url="https://example.com",
    )
    provider = AnthropicCompatibleProvider(config)
    session = SessionTranscript(session_id="s1", cwd="/tmp", model="glm-4.5", provider_name=provider.name)
    session.add_message("user", "你好", content_blocks=[{"type": "text", "text": "你好"}])

    def fake_urlopen(request, timeout):
        _ = (request, timeout)
        return _FakeHttpResponse(
            {
                "error": None,
                "content": [
                    {
                        "type": "text",
                        "text": "你好！",
                    }
                ],
            }
        )

    monkeypatch.setattr("claude_code_thy.providers.anthropic.urlopen", fake_urlopen)

    response = provider._request(session, [])

    assert response.display_text == "你好！"
