from fastapi.testclient import TestClient

from claude_code_thy.config import AppConfig
from claude_code_thy.providers.base import Provider, ProviderResponse
from claude_code_thy.runtime import ConversationRuntime
from claude_code_thy.server.app import create_app
from claude_code_thy.server.context import WebAppContext
from claude_code_thy.session.store import SessionStore


class DummyProvider(Provider):
    """用于 Web prompt 预览接口测试的最小 provider。"""
    name = "anthropic-compatible"

    async def complete(self, session, tools, prompt=None):
        """当前测试不会真正调用模型。"""
        _ = (session, tools, prompt)
        return ProviderResponse(display_text="ok")


def test_runtime_prompt_preview_endpoint_returns_rendered_prompt(tmp_path):
    """测试 `/api/runtime/prompt-preview` 会返回渲染后的 prompt 和 sections。"""
    (tmp_path / "CLAUDE.md").write_text("Remember to keep answers concise.\n", encoding="utf-8")
    sessions_root = tmp_path / ".claude-code-thy" / "sessions"
    store = SessionStore(root_dir=sessions_root)
    provider = DummyProvider()
    runtime = ConversationRuntime(provider=provider, session_store=store)
    session = store.create(
        cwd=str(tmp_path),
        model="glm-4.5",
        provider_name=provider.name,
    )
    store.save(session)

    app = create_app(
        WebAppContext(
            workspace_root=tmp_path.resolve(),
            config=AppConfig(
                provider="anthropic-compatible",
                model="glm-4.5",
                anthropic_api_key="test-key",
            ),
            provider=provider,
            session_store=store,
            runtime=runtime,
        )
    )
    client = TestClient(app)

    response = client.get(
        "/api/runtime/prompt-preview",
        params={"session_id": session.session_id},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["session_id"] == session.session_id
    assert "Skill 使用规则" in data["system_text"]
    assert "Remember to keep answers concise." in data["user_context_text"]
    assert any(section["id"] == "skill_usage" for section in data["sections"])
    assert data["request_preview"]["provider"] == "anthropic-compatible"
    assert data["request_preview"]["json_body"]["system"] == data["system_text"]
    assert data["request_preview"]["headers"]["x-api-key"] == "***"
