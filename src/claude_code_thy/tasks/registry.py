from __future__ import annotations

import json
from pathlib import Path
from typing import TypeVar

from claude_code_thy.tasks.types import TaskRecord

TaskRecordT = TypeVar("TaskRecordT", bound=TaskRecord)


class TaskRegistry:
    def __init__(self, root_dir: Path, *, max_tasks: int) -> None:
        self.root_dir = root_dir.resolve()
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.max_tasks = max_tasks

    def save(self, task: TaskRecord) -> None:
        Path(task.status_path).write_text(
            json.dumps(task.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def load(self, task_id: str, task_cls: type[TaskRecordT]) -> TaskRecordT | None:
        path = self.path_for(task_id)
        if not path.exists():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return task_cls.from_dict(raw)

    def list_ids(self) -> list[str]:
        return sorted(path.stem for path in self.root_dir.glob("*.json"))

    def trim(self) -> None:
        entries = sorted(
            (path for path in self.root_dir.glob("*.json") if path.is_file()),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for stale in entries[self.max_tasks :]:
            stale.unlink(missing_ok=True)

    def read_output(self, output_path: str, *, tail_lines: int = 120) -> str:
        path = Path(output_path)
        if not path.exists():
            return ""
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        if tail_lines <= 0 or len(lines) <= tail_lines:
            return text
        return "\n".join(lines[-tail_lines:])

    def path_for(self, task_id: str) -> Path:
        return self.root_dir / f"{task_id}.json"
