import asyncio
import json

from claude_code_thy.mcp.types import McpToolDefinition
from claude_code_thy.models import SessionTranscript
from claude_code_thy.config import AppConfig
from claude_code_thy.providers.base import Provider, ProviderResponse, ToolCallRequest
from claude_code_thy.providers.openai_responses import OpenAIResponsesProvider
from claude_code_thy.query_engine import QueryEngine
from claude_code_thy.runtime import ConversationRuntime
from claude_code_thy.session.store import SessionStore
from claude_code_thy.tools import ToolRuntime, build_builtin_tools


class FakeProvider(Provider):
    """实现 `Fake` 提供方。"""
    name = "fake-provider"

    async def complete(self, session, tools):
        """完成当前流程。"""
        return ProviderResponse(
            display_text=f"echo:{session.messages[-1].text}",
            content_blocks=[{"type": "text", "text": f"echo:{session.messages[-1].text}"}],
        )


class ToolCallingProvider(Provider):
    """实现 `ToolCalling` 提供方。"""
    name = "tool-calling-provider"

    async def complete(self, session, tools):
        """完成当前流程。"""
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
    """测试 `query_engine_appends_user_and_assistant_messages` 场景。"""
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
    """测试 `query_engine_runs_tool_loop` 场景。"""
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


class _FakeOpenAIResponse:
    """保存 `_FakeOpenAIResponse`。"""
    def __init__(self, payload: dict[str, object]) -> None:
        """初始化实例状态。"""
        self._body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def __enter__(self):
        """进入上下文。"""
        return self

    def __exit__(self, exc_type, exc, tb):
        """退出上下文。"""
        return False

    def read(self) -> bytes:
        """读取 当前流程。"""
        return self._body


def test_query_engine_runs_tool_loop_with_openai_responses_provider(monkeypatch, tmp_path):
    """测试 `query_engine_runs_tool_loop_with_openai_responses_provider` 场景。"""
    captured_payloads: list[dict[str, object]] = []
    readme = tmp_path / "README.md"
    readme.write_text("tool loop content", encoding="utf-8")
    store = SessionStore(root_dir=tmp_path / "sessions")
    session = store.create(cwd=str(tmp_path), model="gpt-5.4", provider_name="openai-responses-compatible")
    provider = OpenAIResponsesProvider(
        AppConfig(
            provider="openai-responses-compatible",
            model="gpt-5.4",
            openai_responses_api_key="test-openai-key",
            openai_responses_base_url="https://example.com",
        )
    )
    engine = QueryEngine(
        provider=provider,
        session_store=store,
        tool_runtime=ToolRuntime(build_builtin_tools()),
    )

    def fake_urlopen(request, timeout):
        """处理 `fake_urlopen`。"""
        _ = timeout
        payload = json.loads(request.data.decode("utf-8"))
        captured_payloads.append(payload)
        if len(captured_payloads) == 1:
            return _FakeOpenAIResponse(
                {
                    "output": [
                        {
                            "type": "function_call",
                            "call_id": "call_read_1",
                            "name": "read",
                            "arguments": "{\"file_path\":\"README.md\",\"offset\":1,\"limit\":20}",
                        }
                    ]
                }
            )
        return _FakeOpenAIResponse(
            {
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "我已经读取了文件内容。"}],
                    }
                ]
            }
        )

    monkeypatch.setattr("claude_code_thy.providers.openai_responses.urlopen", fake_urlopen)

    updated = asyncio.run(engine.submit(session, "请读取 README.md"))

    roles = [message.role for message in updated.messages]
    assert roles == ["user", "assistant", "tool", "assistant"]
    assert "tool loop content" in updated.messages[2].text
    assert updated.messages[-1].text == "我已经读取了文件内容。"
    assert len(captured_payloads) == 2
    second_input = captured_payloads[1]["input"]
    assert any(
        item.get("type") == "function_call_output" and item.get("call_id") == "call_read_1"
        for item in second_input
        if isinstance(item, dict)
    )


class DummyProvider(Provider):
    """实现 `Dummy` 提供方。"""
    name = "dummy"

    async def complete(self, session, tools):
        """完成当前流程。"""
        return ProviderResponse(display_text="done", content_blocks=[{"type": "text", "text": "done"}], tool_calls=[])


class FailIfCalledAgainProvider(Provider):
    """实现 `FailIfCalledAgain` 提供方。"""
    name = "fail-if-called-again"

    def __init__(self) -> None:
        """初始化实例状态。"""
        self.calls = 0

    async def complete(self, session, tools):
        """完成当前流程。"""
        self.calls += 1
        if self.calls > 1:
            raise AssertionError("provider.complete should not be called again after MCP tool result")
        return ProviderResponse(
            display_text="调用 MCP 工具",
            content_blocks=[
                {
                    "type": "tool_use",
                    "id": "toolu_mcp_1",
                    "name": "mcp__xiaohongshu_mcp__check_login_status",
                    "input": {},
                }
            ],
            tool_calls=[
                ToolCallRequest(
                    id="toolu_mcp_1",
                    name="mcp__xiaohongshu_mcp__check_login_status",
                    input={},
                )
            ],
        )


def test_runtime_explicit_mcp_tool_request_executes_without_model_tool_choice(tmp_path):
    """测试 `runtime_explicit_mcp_tool_request_executes_without_model_tool_choice` 场景。"""
    store = SessionStore(root_dir=tmp_path / "sessions")
    runtime = ConversationRuntime(provider=DummyProvider(), session_store=store)
    session = store.create(cwd=str(tmp_path), model="dummy", provider_name="dummy")
    store.save(session)
    services = runtime.tool_runtime.services_for(session)

    class DummyMgr:
        """表示 `DummyMgr`。"""
        async def refresh_all(self):
            """刷新 `all`。"""
            return []

        def cached_tools(self):
            """处理 `cached_tools`。"""
            return {
                "xiaohongshu-mcp": [
                    McpToolDefinition(
                        name="check_login_status",
                        description="check login",
                        input_schema={"type": "object", "properties": {}, "required": []},
                        annotations={"readOnlyHint": True, "original_name": "check_login_status"},
                    )
                ]
            }

        def cached_prompts(self):
            """处理 `cached_prompts`。"""
            return {}

        def cached_resources(self):
            """处理 `cached_resources`。"""
            return {}

        async def call_tool(self, server_name, tool_name, arguments=None):
            """处理 `call_tool`。"""
            return {"content": "logged-in"}

    services.mcp_manager = DummyMgr()

    outcome = asyncio.run(
        runtime.handle(
            session,
            "使用mcp__xiaohongshu_mcp__check_login_status帮我查看当前小红书登录状态",
        )
    )

    assert any(message.role == "tool" for message in outcome.session.messages)


def test_runtime_approved_non_readonly_mcp_tool_does_not_prompt_again(tmp_path):
    """测试 `runtime_approved_non_readonly_mcp_tool_does_not_prompt_again` 场景。"""
    store = SessionStore(root_dir=tmp_path / "sessions")
    runtime = ConversationRuntime(provider=DummyProvider(), session_store=store)
    session = store.create(cwd=str(tmp_path), model="dummy", provider_name="dummy")
    session.runtime_state["approved_permissions"] = [
        "mcp__xiaohongshu_mcp__like_feed:command:mcp__xiaohongshu_mcp__like_feed"
    ]
    store.save(session)
    services = runtime.tool_runtime.services_for(session)

    class DummyMgr:
        """表示 `DummyMgr`。"""
        async def refresh_all(self):
            """刷新 `all`。"""
            return []

        def cached_tools(self):
            """处理 `cached_tools`。"""
            return {
                "xiaohongshu-mcp": [
                    McpToolDefinition(
                        name="like_feed",
                        description="like feed",
                        input_schema={"type": "object", "properties": {}, "required": []},
                        annotations={"original_name": "like_feed"},
                    )
                ]
            }

        def cached_prompts(self):
            """处理 `cached_prompts`。"""
            return {}

        def cached_resources(self):
            """处理 `cached_resources`。"""
            return {}

        async def call_tool(self, server_name, tool_name, arguments=None):
            """处理 `call_tool`。"""
            return {"content": "liked"}

    services.mcp_manager = DummyMgr()

    outcome = asyncio.run(
        runtime.handle(
            session,
            "使用mcp__xiaohongshu_mcp__like_feed帮我点赞这条笔记",
        )
    )

    assistant_messages = [message for message in outcome.session.messages if message.role == "assistant"]
    assert not any("回复 `yes`" in message.text for message in assistant_messages)
    assert any(message.role == "tool" for message in outcome.session.messages)


def test_query_engine_pauses_after_mcp_tool_result_without_second_provider_round(tmp_path):
    """测试 `query_engine_pauses_after_mcp_tool_result_without_second_provider_round` 场景。"""
    store = SessionStore(root_dir=tmp_path / "sessions")
    provider = FailIfCalledAgainProvider()
    session = store.create(cwd=str(tmp_path), model="dummy", provider_name="dummy")
    engine = QueryEngine(
        provider=provider,
        session_store=store,
        tool_runtime=ToolRuntime(build_builtin_tools()),
    )
    services = engine.tool_runtime.services_for(session)

    class DummyMgr:
        """表示 `DummyMgr`。"""
        async def refresh_all(self):
            """刷新 `all`。"""
            return []

        def cached_tools(self):
            """处理 `cached_tools`。"""
            return {
                "xiaohongshu-mcp": [
                    McpToolDefinition(
                        name="check_login_status",
                        description="check login",
                        input_schema={"type": "object", "properties": {}, "required": []},
                        annotations={"readOnlyHint": True, "original_name": "check_login_status"},
                    )
                ]
            }

        def cached_prompts(self):
            """处理 `cached_prompts`。"""
            return {}

        def cached_resources(self):
            """处理 `cached_resources`。"""
            return {}

        async def call_tool(self, server_name, tool_name, arguments=None):
            """处理 `call_tool`。"""
            return {"content": "logged-in"}

    services.mcp_manager = DummyMgr()

    updated = asyncio.run(engine.submit(session, "帮我查看当前小红书的登录状态"))

    roles = [message.role for message in updated.messages]
    assert roles == ["user", "assistant", "tool"]
    assert provider.calls == 1


def test_resume_pending_mcp_tool_call_pauses_after_tool_result(tmp_path):
    """测试 `resume_pending_mcp_tool_call_pauses_after_tool_result` 场景。"""
    store = SessionStore(root_dir=tmp_path / "sessions")
    provider = DummyProvider()
    session = store.create(cwd=str(tmp_path), model="dummy", provider_name="dummy")
    engine = QueryEngine(
        provider=provider,
        session_store=store,
        tool_runtime=ToolRuntime(build_builtin_tools()),
    )
    services = engine.tool_runtime.services_for(session)

    class DummyMgr:
        """表示 `DummyMgr`。"""
        async def refresh_all(self):
            """刷新 `all`。"""
            return []

        def cached_tools(self):
            """处理 `cached_tools`。"""
            return {
                "xiaohongshu-mcp": [
                    McpToolDefinition(
                        name="like_feed",
                        description="like feed",
                        input_schema={"type": "object", "properties": {}, "required": []},
                        annotations={"original_name": "like_feed"},
                    )
                ]
            }

        def cached_prompts(self):
            """处理 `cached_prompts`。"""
            return {}

        def cached_resources(self):
            """处理 `cached_resources`。"""
            return {}

        async def call_tool(self, server_name, tool_name, arguments=None):
            """处理 `call_tool`。"""
            return {"content": "liked"}

    services.mcp_manager = DummyMgr()

    pending = {
        "source_type": "tool_call",
        "tool_name": "mcp__xiaohongshu_mcp__like_feed",
        "tool_use_id": "toolu_resume_1",
        "input_data": {},
        "original_input": {},
        "request": {
            "request_id": "req1",
            "tool_name": "mcp__xiaohongshu_mcp__like_feed",
            "target": "command",
            "value": "mcp__xiaohongshu_mcp__like_feed",
            "reason": "need permission",
            "approval_key": "mcp__xiaohongshu_mcp__like_feed:command:mcp__xiaohongshu_mcp__like_feed",
            "matched_rule_pattern": "",
            "matched_rule_description": "",
        },
    }
    session.runtime_state["approved_permissions"] = [
        "mcp__xiaohongshu_mcp__like_feed:command:mcp__xiaohongshu_mcp__like_feed"
    ]

    updated = asyncio.run(
        engine.resume_pending_tool_call(
            session,
            pending,
            approved=True,
        )
    )

    roles = [message.role for message in updated.messages]
    assert roles == ["tool"]


def test_query_engine_mcp_tool_call_does_not_block_event_loop(tmp_path):
    """测试 `query_engine_mcp_tool_call_does_not_block_event_loop` 场景。"""
    store = SessionStore(root_dir=tmp_path / "sessions")
    provider = FailIfCalledAgainProvider()
    session = store.create(cwd=str(tmp_path), model="dummy", provider_name="dummy")
    engine = QueryEngine(
        provider=provider,
        session_store=store,
        tool_runtime=ToolRuntime(build_builtin_tools()),
    )
    services = engine.tool_runtime.services_for(session)

    class DummyMgr:
        """表示 `DummyMgr`。"""
        async def refresh_all(self):
            """刷新 `all`。"""
            return []

        def cached_tools(self):
            """处理 `cached_tools`。"""
            return {
                "xiaohongshu-mcp": [
                    McpToolDefinition(
                        name="check_login_status",
                        description="check login",
                        input_schema={"type": "object", "properties": {}, "required": []},
                        annotations={"readOnlyHint": True, "original_name": "check_login_status"},
                    )
                ]
            }

        def cached_prompts(self):
            """处理 `cached_prompts`。"""
            return {}

        def cached_resources(self):
            """处理 `cached_resources`。"""
            return {}

        async def call_tool(self, server_name, tool_name, arguments=None):
            """处理 `call_tool`。"""
            await asyncio.sleep(0.05)
            return {"content": "logged-in"}

    services.mcp_manager = DummyMgr()
    tick_count = 0
    done = False

    async def ticker():
        """处理 `ticker`。"""
        nonlocal tick_count
        while not done:
            tick_count += 1
            await asyncio.sleep(0.005)

    async def run():
        """运行当前流程。"""
        nonlocal done
        ticker_task = asyncio.create_task(ticker())
        try:
            updated = await engine.submit(session, "帮我查看当前小红书的登录状态")
        finally:
            done = True
            await ticker_task
        return updated

    updated = asyncio.run(run())

    assert [message.role for message in updated.messages] == ["user", "assistant", "tool"]
    assert tick_count >= 3


def test_resume_pending_mcp_tool_call_does_not_block_event_loop(tmp_path):
    """测试 `resume_pending_mcp_tool_call_does_not_block_event_loop` 场景。"""
    store = SessionStore(root_dir=tmp_path / "sessions")
    provider = DummyProvider()
    session = store.create(cwd=str(tmp_path), model="dummy", provider_name="dummy")
    engine = QueryEngine(
        provider=provider,
        session_store=store,
        tool_runtime=ToolRuntime(build_builtin_tools()),
    )
    services = engine.tool_runtime.services_for(session)

    class DummyMgr:
        """表示 `DummyMgr`。"""
        async def refresh_all(self):
            """刷新 `all`。"""
            return []

        def cached_tools(self):
            """处理 `cached_tools`。"""
            return {
                "xiaohongshu-mcp": [
                    McpToolDefinition(
                        name="like_feed",
                        description="like feed",
                        input_schema={"type": "object", "properties": {}, "required": []},
                        annotations={"original_name": "like_feed"},
                    )
                ]
            }

        def cached_prompts(self):
            """处理 `cached_prompts`。"""
            return {}

        def cached_resources(self):
            """处理 `cached_resources`。"""
            return {}

        async def call_tool(self, server_name, tool_name, arguments=None):
            """处理 `call_tool`。"""
            await asyncio.sleep(0.05)
            return {"content": "liked"}

    services.mcp_manager = DummyMgr()
    pending = {
        "source_type": "tool_call",
        "tool_name": "mcp__xiaohongshu_mcp__like_feed",
        "tool_use_id": "toolu_resume_2",
        "input_data": {},
        "original_input": {},
        "request": {
            "request_id": "req2",
            "tool_name": "mcp__xiaohongshu_mcp__like_feed",
            "target": "command",
            "value": "mcp__xiaohongshu_mcp__like_feed",
            "reason": "need permission",
            "approval_key": "mcp__xiaohongshu_mcp__like_feed:command:mcp__xiaohongshu_mcp__like_feed",
            "matched_rule_pattern": "",
            "matched_rule_description": "",
        },
    }
    session.runtime_state["approved_permissions"] = [
        "mcp__xiaohongshu_mcp__like_feed:command:mcp__xiaohongshu_mcp__like_feed"
    ]
    tick_count = 0
    done = False

    async def ticker():
        """处理 `ticker`。"""
        nonlocal tick_count
        while not done:
            tick_count += 1
            await asyncio.sleep(0.005)

    async def run():
        """运行当前流程。"""
        nonlocal done
        ticker_task = asyncio.create_task(ticker())
        try:
            updated = await engine.resume_pending_tool_call(
                session,
                pending,
                approved=True,
            )
        finally:
            done = True
            await ticker_task
        return updated

    updated = asyncio.run(run())

    assert [message.role for message in updated.messages] == ["tool"]
    assert tick_count >= 3
