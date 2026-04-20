from claude_code_thy.models import SessionTranscript
from claude_code_thy.tasks.types import BackgroundTask
from claude_code_thy.tools import ToolRuntime, build_builtin_tools


def build_runtime() -> ToolRuntime:
    return ToolRuntime(build_builtin_tools())


def test_agent_tool_inherits_session_model_and_default_description(tmp_path, monkeypatch):
    runtime = build_runtime()
    session = SessionTranscript(
        session_id="agent-1",
        cwd=str(tmp_path),
        model="glm-5",
        provider_name="test-provider",
    )
    services = runtime.services_for(session)

    captured: dict[str, object] = {}

    def fake_start_local_agent(*, prompt, cwd, model, env=None, description=None, session_id=None):
        captured.update(
            {
                "prompt": prompt,
                "cwd": str(cwd),
                "model": model,
                "description": description,
                "session_id": session_id,
            }
        )
        return BackgroundTask(
            task_id="task-1",
            task_type="local_agent",
            description=str(description or ""),
            cwd=str(cwd),
            output_path=str(tmp_path / "task-1.output"),
            status_path=str(tmp_path / "task-1.json"),
            status="running",
            command=f"agent-run: {prompt}",
            task_kind="agent",
        )

    def fake_wait_for_task(task_id, *, timeout_seconds=30.0, poll_interval=0.2):
        _ = (task_id, timeout_seconds, poll_interval)
        return BackgroundTask(
            task_id="task-1",
            task_type="local_agent",
            description=str(captured["description"]),
            cwd=str(tmp_path),
            output_path=str(tmp_path / "task-1.output"),
            status_path=str(tmp_path / "task-1.json"),
            status="completed",
            return_code=0,
            command=f"agent-run: {captured['prompt']}",
            task_kind="agent",
        )

    def fake_read_output(task_id, *, tail_lines=120):
        _ = (task_id, tail_lines)
        return "agent ok"

    monkeypatch.setattr(services.task_manager, "start_local_agent", fake_start_local_agent)
    monkeypatch.setattr(services.task_manager, "wait_for_task", fake_wait_for_task)
    monkeypatch.setattr(services.task_manager, "read_output", fake_read_output)

    result = runtime.execute("agent", "-- 请总结 README.md 的主要内容", session)

    assert captured["prompt"] == "请总结 README.md 的主要内容"
    assert captured["model"] == "glm-5"
    assert captured["description"] == "Agent: 请总结 README.md 的主要内容"
    assert result.ok is True
    assert result.summary == "Agent completed: Agent: 请总结 README.md 的主要内容"
