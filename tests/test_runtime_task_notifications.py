import asyncio

from claude_code_thy.providers.base import Provider, ProviderResponse
from claude_code_thy.runtime import ConversationRuntime
from claude_code_thy.session.store import SessionStore


class DummyProvider(Provider):
    """实现 `Dummy` 提供方。"""
    name = "dummy"

    async def complete(self, session, tools):
        """完成当前流程。"""
        _ = (session, tools)
        return ProviderResponse(
            display_text="ok",
            content_blocks=[{"type": "text", "text": "ok"}],
            tool_calls=[],
        )


def _create_completed_task(runtime: ConversationRuntime, session, *, task_type: str, description: str, output: str):
    """创建 `completed_task`。"""
    manager = runtime.tool_runtime.services_for(session).task_manager
    record = manager.create_task(
        task_type=task_type,  # type: ignore[arg-type]
        description=description,
        cwd=runtime.tool_runtime.services_for(session).task_manager.workspace_root,
        metadata={"session_id": session.session_id, "prompt": description},
    )
    output_path = manager.tasks_dir / f"{record.task_id}.output"
    output_path.write_text(output, encoding="utf-8")
    manager.update_task(record.task_id, status="completed", return_code=0, finished=True)
    return record.task_id


def test_tasks_command_does_not_append_task_notification(tmp_path):
    """测试 `tasks_command_does_not_append_task_notification` 场景。"""
    store = SessionStore(root_dir=tmp_path / "sessions")
    runtime = ConversationRuntime(provider=DummyProvider(), session_store=store)
    session = store.create(cwd=str(tmp_path), model="dummy", provider_name="dummy")
    store.save(session)

    _create_completed_task(
        runtime,
        session,
        task_type="workflow",
        description="workflow test",
        output="workflow output",
    )

    outcome = asyncio.run(runtime.handle(session, "/tasks"))
    texts = [message.text for message in outcome.session.messages]

    assert any(text.startswith("后台任务：") for text in texts)
    assert not any("workflow output" in text for text in texts)
    assert not any((message.metadata or {}).get("ui_kind") == "task_notification" for message in outcome.session.messages)


def test_status_command_still_appends_task_notification(tmp_path):
    """测试 `status_command_still_appends_task_notification` 场景。"""
    store = SessionStore(root_dir=tmp_path / "sessions")
    runtime = ConversationRuntime(provider=DummyProvider(), session_store=store)
    session = store.create(cwd=str(tmp_path), model="dummy", provider_name="dummy")
    store.save(session)

    _create_completed_task(
        runtime,
        session,
        task_type="workflow",
        description="workflow test",
        output="workflow output",
    )

    outcome = asyncio.run(runtime.handle(session, "/status"))
    texts = [message.text for message in outcome.session.messages]

    assert any("当前会话状态：" in text for text in texts)
    assert any("workflow output" in text for text in texts)
    assert any((message.metadata or {}).get("ui_kind") == "task_notification" for message in outcome.session.messages)
