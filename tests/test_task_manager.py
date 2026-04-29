import time
from pathlib import Path

import claude_code_thy.tasks.manager as task_manager_module
from claude_code_thy.settings import TaskSettings
from claude_code_thy.tasks import BackgroundTaskManager
from claude_code_thy.tasks.types import BackgroundTask


def test_local_agent_task_can_be_started_and_recorded(tmp_path, monkeypatch):
    """测试 `local_agent_task_can_be_started_and_recorded` 场景。"""
    src_dir = Path(__file__).resolve().parents[1] / "src"
    monkeypatch.setenv("PYTHONPATH", str(src_dir))

    manager = BackgroundTaskManager(tmp_path, TaskSettings())
    task = manager.start_local_agent(
        prompt="say hello from agent",
        cwd=tmp_path,
        model="glm-4.5",
        env=None,
    )

    assert task.task_type == "local_agent"
    assert task.task_kind == "agent"

    for _ in range(40):
        current = manager.get(task.task_id)
        if current is not None and current.status != "running":
            break
        time.sleep(0.1)

    current = manager.get(task.task_id)
    assert current is not None
    assert current.task_type == "local_agent"
    assert current.status in {"completed", "failed", "exited"}


def test_task_manager_lists_non_bash_task_records(tmp_path):
    """测试 `task_manager_lists_non_bash_task_records` 场景。"""
    manager = BackgroundTaskManager(tmp_path, TaskSettings())
    record = manager.create_task(
        task_type="workflow",
        description="workflow test",
        cwd=tmp_path,
        metadata={"kind": "workflow"},
    )
    manager.update_task(record.task_id, status="completed", finished=True)

    tasks = manager.list_task_records()

    assert any(task.task_id == record.task_id for task in tasks)


def test_task_manager_marks_stale_windows_tasks_as_exited(tmp_path, monkeypatch):
    """Windows task refresh should tolerate stale PIDs instead of raising 500s."""
    manager = BackgroundTaskManager(tmp_path, TaskSettings())
    task = BackgroundTask(
        task_id="win-task",
        task_type="local_bash",
        description="stale windows task",
        cwd=str(tmp_path),
        output_path=str(tmp_path / "win-task.output"),
        status_path=str(manager.registry.path_for("win-task")),
        status="running",
        pid=27307,
        command="echo hi",
        task_kind="bash",
        metadata={"session_id": "session-1"},
    )
    manager.registry.save(task)

    monkeypatch.setattr(task_manager_module, "_is_windows", lambda: True)
    monkeypatch.setattr(manager, "_pid_exists_windows", lambda pid: False)

    tasks = manager.list_task_records()
    refreshed = next(item for item in tasks if item.task_id == "win-task")

    assert refreshed.status == "exited"
    assert refreshed.finished_at is not None


def test_stop_task_uses_taskkill_on_windows(tmp_path, monkeypatch):
    """Stopping background tasks on Windows should terminate the full process tree."""
    manager = BackgroundTaskManager(tmp_path, TaskSettings())
    task = BackgroundTask(
        task_id="kill-task",
        task_type="local_bash",
        description="kill task",
        cwd=str(tmp_path),
        output_path=str(tmp_path / "kill-task.output"),
        status_path=str(manager.registry.path_for("kill-task")),
        status="running",
        pid=4321,
        command="sleep 10",
        task_kind="bash",
    )
    manager.registry.save(task)

    calls: list[list[str]] = []

    def fake_run(argv, **kwargs):
        calls.append(list(argv))

        class Result:
            returncode = 0

        return Result()

    monkeypatch.setattr(task_manager_module, "_is_windows", lambda: True)
    monkeypatch.setattr(task_manager_module.subprocess, "run", fake_run)

    result = manager.stop_task(task.task_id)

    assert result is not None
    assert result.status == "killed"
    assert calls == [["taskkill", "/PID", "4321", "/T", "/F"]]
