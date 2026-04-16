import asyncio

from claude_code_thy.providers.base import Provider, ProviderResponse, ToolCallRequest
from claude_code_thy.query_engine import QueryEngine
from claude_code_thy.session.store import SessionStore
from claude_code_thy.tools import ToolRuntime, build_builtin_tools


class FakeProvider(Provider):
    name = "fake-provider"

    async def complete(self, session, tools):
        return ProviderResponse(
            display_text=f"echo:{session.messages[-1].text}",
            content_blocks=[{"type": "text", "text": f"echo:{session.messages[-1].text}"}],
        )


class ToolCallingProvider(Provider):
    name = "tool-calling-provider"

    async def complete(self, session, tools):
        has_tool_result = any(message.role == "tool" for message in session.messages)
        if not has_tool_result:
            return ProviderResponse(
                display_text="调用工具：read",
                content_blocks=[
                    {
                        "type": "tool_use",
                        "id": "toolu_123",
                        "name": "read",
                        "input": {"file_path": "README.md", "offset": 1, "limit": 20},
                    }
                ],
                tool_calls=[
                    ToolCallRequest(
                        id="toolu_123",
                        name="read",
                        input={"file_path": "README.md", "offset": 1, "limit": 20},
                    )
                ],
            )

        return ProviderResponse(
            display_text="我已经读取了文件内容。",
            content_blocks=[{"type": "text", "text": "我已经读取了文件内容。"}],
        )


def test_query_engine_appends_user_and_assistant_messages(tmp_path):
    store = SessionStore(root_dir=tmp_path / "sessions")
    session = store.create(cwd=str(tmp_path), model="glm-4.5", provider_name="fake-provider")
    engine = QueryEngine(
        provider=FakeProvider(),
        session_store=store,
        tool_runtime=ToolRuntime(build_builtin_tools()),
    )

    updated = asyncio.run(engine.submit(session, "你好"))

    assert len(updated.messages) == 2
    assert updated.messages[0].role == "user"
    assert updated.messages[1].role == "assistant"
    assert updated.messages[1].text == "echo:你好"


def test_query_engine_runs_tool_loop(tmp_path):
    store = SessionStore(root_dir=tmp_path / "sessions")
    (tmp_path / "README.md").write_text("tool loop content", encoding="utf-8")
    session = store.create(cwd=str(tmp_path), model="glm-4.5", provider_name="tool-calling-provider")
    engine = QueryEngine(
        provider=ToolCallingProvider(),
        session_store=store,
        tool_runtime=ToolRuntime(build_builtin_tools()),
    )

    updated = asyncio.run(engine.submit(session, "请读取 README.md"))

    roles = [message.role for message in updated.messages]
    assert roles == ["user", "assistant", "tool", "assistant"]
    assert "tool loop content" in updated.messages[2].text
    assert updated.messages[-1].text == "我已经读取了文件内容。"
