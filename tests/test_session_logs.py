import asyncio
import json

from claude_code_thy.models import SessionTranscript
from claude_code_thy.prompts.types import PromptBundle, PromptContextData, RenderedPrompt
from claude_code_thy.providers.base import Provider, ProviderError, ProviderResponse, ToolCallRequest
from claude_code_thy.runtime import ConversationRuntime
from claude_code_thy.session.store import SessionStore
from claude_code_thy.session_logs import SessionLogManager
from claude_code_thy.settings import SessionLogSettings
from claude_code_thy.tools.base import ToolResult


class EchoProvider(Provider):
    """返回固定 assistant 原文的最小 provider。"""

    name = "echo-provider"

    async def complete(self, session, tools, prompt=None):
        _ = (session, tools, prompt)
        return ProviderResponse(
            display_text="这是 assistant 的原文输出，不应该被摘要。",
            content_blocks=[{"type": "text", "text": "这是 assistant 的原文输出，不应该被摘要。"}],
        )


def _rendered_prompt() -> RenderedPrompt:
    return RenderedPrompt(
        bundle=PromptBundle(
            session_id="s1",
            provider_name="demo",
            model="glm-4.5",
            workspace_root="/tmp",
            sections=[],
            context_data=PromptContextData(variables={}),
        ),
        system_text="",
        user_context_text="",
    )


def test_conversation_runtime_writes_dual_session_logs(tmp_path):
    """测试正常对话会生成同名前缀的 `.log` 与 `.jsonl`。"""
    store = SessionStore(root_dir=tmp_path / "sessions")
    session = store.create(cwd=str(tmp_path), model="glm-4.5", provider_name="echo-provider")
    runtime = ConversationRuntime(
        provider=EchoProvider(),
        session_store=store,
    )

    outcome = asyncio.run(runtime.handle(session, "你好，请保留原文输出"))

    assert outcome.message_added is True
    log_dir = tmp_path / ".claude-code-thy" / "session-logs"
    log_files = sorted(log_dir.glob("*.log"))
    jsonl_files = sorted(log_dir.glob("*.jsonl"))
    assert len(log_files) == 1
    assert len(jsonl_files) == 1
    assert log_files[0].stem == jsonl_files[0].stem

    log_text = log_files[0].read_text(encoding="utf-8")
    assert "交互轮 1" in log_text
    assert "LLM 轮 1.1" in log_text
    assert "[LLM 输出]" in log_text
    assert "工具调用数: 0" in log_text
    assert "这是 assistant 的原文输出，不应该被摘要。" in log_text

    jsonl_records = [
        json.loads(line)
        for line in jsonl_files[0].read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert any(record["event"] == "session_started" for record in jsonl_records)
    assert any(record["event"] == "turn_started" for record in jsonl_records)
    assert any(record["event"] == "llm_turn_started" for record in jsonl_records)
    assert any(record["event"] == "llm_turn_finished" for record in jsonl_records)
    assert any(
        record["event"] == "message_added"
        and record["data"]["role"] == "assistant"
        and record["data"]["text"] == "这是 assistant 的原文输出，不应该被摘要。"
        for record in jsonl_records
    )


def test_session_log_manager_truncates_long_tool_output_only_in_human_log(tmp_path):
    """测试 `.log` 会裁剪超长工具输出，但 `.jsonl` 保留完整原文。"""
    settings = SessionLogSettings(
        output_dir="session-logs",
        tool_output_inline_max_chars=80,
        tool_output_head_chars=18,
        tool_output_tail_chars=18,
    )
    manager = SessionLogManager(tmp_path, settings)
    session = SessionTranscript(session_id="s1", cwd=str(tmp_path), model="glm-4.5", provider_name="demo")

    manager.record_session_started(session, provider_name="demo", model="glm-4.5")
    manager.start_turn(session, prompt="测试长工具输出", input_kind="chat", stream=False)
    manager.start_llm_turn(
        session,
        provider_name="demo",
        request_preview={
            "provider": "demo",
            "endpoint": "https://example.com",
            "json_body": {"model": "glm-4.5", "tools": []},
        },
        rendered_prompt=_rendered_prompt(),
    )
    context = manager.begin_tool_call(
        session,
        tool_name="demo_tool",
        tool_use_id="toolu_demo",
        surface="model",
        input_data={"value": "demo"},
    )
    long_output = "HEAD-1234567890" + ("X" * 160) + "TAIL-0987654321"
    result = ToolResult(
        tool_name="demo_tool",
        ok=True,
        summary="长输出测试",
        display_name="Demo",
        output=long_output,
    )
    manager.finish_tool_call(session, context, result)
    manager.finish_llm_turn(session, status="success")
    manager.finish_turn(session, new_message_count=0, ended_with_error=False, ended_with_pending_permission=False)

    log_path = next((tmp_path / "session-logs").glob("*.log"))
    jsonl_path = next((tmp_path / "session-logs").glob("*.jsonl"))

    log_text = log_path.read_text(encoding="utf-8")
    assert "LLM 轮 1.1" in log_text
    assert "[工具调用]" in log_text
    assert "工具调用数: 1" in log_text
    assert "HEAD-1234567890" in log_text
    assert "TAIL-0987654321" in log_text
    assert "中间已省略" in log_text
    assert long_output not in log_text

    jsonl_records = [
        json.loads(line)
        for line in jsonl_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    tool_finished = next(record for record in jsonl_records if record["event"] == "tool_call_finished")
    assert tool_finished["data"]["output"] == long_output


def test_resume_continues_same_log_bundle_and_writes_resume_marker(tmp_path):
    """测试恢复已有 session 时会继续写同一组日志文件。"""
    store = SessionStore(root_dir=tmp_path / "sessions")
    session = store.create(cwd=str(tmp_path), model="glm-4.5", provider_name="echo-provider")

    runtime_one = ConversationRuntime(
        provider=EchoProvider(),
        session_store=store,
    )
    asyncio.run(runtime_one.handle(session, "第一轮"))

    reloaded = store.load(session.session_id)
    runtime_two = ConversationRuntime(
        provider=EchoProvider(),
        session_store=store,
    )
    asyncio.run(runtime_two.handle(reloaded, "第二轮"))

    log_dir = tmp_path / ".claude-code-thy" / "session-logs"
    log_files = sorted(log_dir.glob("*.log"))
    jsonl_files = sorted(log_dir.glob("*.jsonl"))
    assert len(log_files) == 1
    assert len(jsonl_files) == 1

    log_text = log_files[0].read_text(encoding="utf-8")
    assert "会话恢复" in log_text
    assert "交互轮 1" in log_text
    assert "交互轮 2" in log_text


class FailingProvider(Provider):
    """用于测试 provider 失败时 turn 状态的 provider。"""

    name = "failing-provider"

    async def complete(self, session, tools, prompt=None):
        _ = (session, tools, prompt)
        raise ProviderError("模拟 provider 失败")


def test_turn_finished_marks_error_when_provider_error_is_logged(tmp_path):
    """测试 provider_error 已记录时，turn_finished 不会再误记成 success。"""
    store = SessionStore(root_dir=tmp_path / "sessions")
    session = store.create(cwd=str(tmp_path), model="glm-4.5", provider_name="failing-provider")
    runtime = ConversationRuntime(
        provider=FailingProvider(),
        session_store=store,
    )

    outcome = asyncio.run(runtime.handle(session, "触发一次 provider 错误"))

    assert outcome.message_added is True
    jsonl_path = next((tmp_path / ".claude-code-thy" / "session-logs").glob("*.jsonl"))
    records = [
        json.loads(line)
        for line in jsonl_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    provider_error = next(record for record in records if record["event"] == "provider_error")
    assert provider_error["data"]["error_type"] == "ProviderError"
    turn_finished = next(record for record in records if record["event"] == "turn_finished")
    assert turn_finished["data"]["ended_with_error"] is True
    assert turn_finished["data"]["status"] == "error"


class PermissionProvider(Provider):
    """第一次发起工具调用，第二次输出最终 assistant 文本。"""

    name = "permission-provider"

    async def complete(self, session, tools, prompt=None):
        _ = (tools, prompt)
        has_tool_result = any(message.role == "tool" for message in session.messages)
        if not has_tool_result:
            return ProviderResponse(
                display_text="我先删除这个文件。",
                content_blocks=[
                    {
                        "type": "tool_use",
                        "id": "toolu_rm_1",
                        "name": "bash",
                        "input": {
                            "command": "rm helloworld.py",
                            "description": "删除 helloworld.py",
                        },
                    }
                ],
                tool_calls=[
                    ToolCallRequest(
                        id="toolu_rm_1",
                        name="bash",
                        input={
                            "command": "rm helloworld.py",
                            "description": "删除 helloworld.py",
                        },
                    )
                ],
            )
        return ProviderResponse(
            display_text="文件已删除。",
            content_blocks=[{"type": "text", "text": "文件已删除。"}],
        )


def test_permission_resume_keeps_same_interaction_turn_and_groups_tool_under_same_llm_round(tmp_path):
    """测试权限暂停与恢复后，`.log` 仍按一个交互轮和多个 LLM 轮清晰分组。"""
    settings_dir = tmp_path / ".claude-code-thy"
    settings_dir.mkdir()
    (settings_dir / "settings.local.json").write_text(
        json.dumps(
            {
                "permissions": [
                    {
                        "effect": "ask",
                        "tool": "bash",
                        "target": "command",
                        "pattern": "rm *",
                        "description": "删除文件需要确认",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (tmp_path / "helloworld.py").write_text("print('hello')\n", encoding="utf-8")

    store = SessionStore(root_dir=tmp_path / "sessions")
    session = store.create(cwd=str(tmp_path), model="glm-4.5", provider_name="permission-provider")
    runtime = ConversationRuntime(
        provider=PermissionProvider(),
        session_store=store,
    )

    prompted = asyncio.run(runtime.handle(session, "删除 helloworld.py"))
    assert prompted.session.runtime_state.get("pending_permission") is not None

    resumed = asyncio.run(
        runtime.resolve_pending_permission(prompted.session, approved=True)
    )
    assert resumed.session.runtime_state.get("pending_permission") is None

    log_path = next((tmp_path / ".claude-code-thy" / "session-logs").glob("*.log"))
    log_text = log_path.read_text(encoding="utf-8")

    assert "交互轮 1" in log_text
    assert "交互轮 2" not in log_text
    assert "LLM 轮 1.1" in log_text
    assert "LLM 轮 1.2" in log_text
    assert "交互轮暂停:" in log_text
    assert "权限请求:" in log_text
    assert "权限结果:" in log_text
    assert "工具调用" in log_text
    assert "rm helloworld.py" in log_text
    assert "文件已删除。" in log_text


def test_llm_turn_renders_success_with_tool_error_and_counts(tmp_path):
    """测试 LLM 轮在工具部分失败时，会渲染混合状态和统计信息。"""
    settings = SessionLogSettings(output_dir="session-logs")
    manager = SessionLogManager(tmp_path, settings)
    session = SessionTranscript(session_id="s1", cwd=str(tmp_path), model="glm-4.5", provider_name="demo")

    manager.record_session_started(session, provider_name="demo", model="glm-4.5")
    manager.start_turn(session, prompt="测试混合工具结果", input_kind="chat", stream=False)
    manager.start_llm_turn(
        session,
        provider_name="demo",
        request_preview={
            "provider": "demo",
            "endpoint": "https://example.com",
            "json_body": {"model": "glm-4.5", "tools": []},
        },
        rendered_prompt=_rendered_prompt(),
    )
    first = manager.begin_tool_call(
        session,
        tool_name="bash",
        tool_use_id="toolu_fail",
        surface="model",
        input_data={"command": "rm bad.py"},
    )
    manager.finish_tool_error(
        session,
        first,
        error=RuntimeError("boom"),
        output="工具 `bash` 执行失败：boom",
    )
    second = manager.begin_tool_call(
        session,
        tool_name="write",
        tool_use_id="toolu_ok",
        surface="model",
        input_data={"file_path": "ok.py"},
    )
    manager.finish_tool_call(
        session,
        second,
        ToolResult(
            tool_name="write",
            ok=True,
            summary="创建文件：ok.py",
            display_name="write",
            output="Wrote ok.py",
        ),
    )
    manager.finish_llm_turn(session, status="success")
    manager.finish_turn(session, new_message_count=0, ended_with_error=False, ended_with_pending_permission=False)

    log_path = next((tmp_path / "session-logs").glob("*.log"))
    log_text = log_path.read_text(encoding="utf-8")

    assert "结束状态: success_with_tool_error" in log_text
    assert "工具调用数: 2" in log_text
    assert "工具失败数: 1" in log_text
