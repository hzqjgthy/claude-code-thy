import time
from pathlib import Path

from claude_code_thy.settings import TaskSettings
from claude_code_thy.tasks import BackgroundTaskManager


def test_local_agent_task_can_be_started_and_recorded(tmp_path, monkeypatch):
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
