import json

from claude_code_thy.config import AppConfig
from claude_code_thy.models import SessionTranscript
from claude_code_thy.providers.anthropic import AnthropicCompatibleProvider


class _FakeHttpResponse:
    """保存 `_FakeHttpResponse`。"""
    def __init__(self, body: dict[str, object]) -> None:
        """初始化实例状态。"""
        self._body = json.dumps(body, ensure_ascii=False).encode("utf-8")

    def __enter__(self):
        """进入上下文。"""
        return self

    def __exit__(self, exc_type, exc, tb):
        """退出上下文。"""
        return False

    def read(self) -> bytes:
        """读取 当前流程。"""
        return self._body


def test_anthropic_provider_ignores_null_error_field(monkeypatch):
    """测试 `anthropic_provider_ignores_null_error_field` 场景。"""
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
        """处理 `fake_urlopen`。"""
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
