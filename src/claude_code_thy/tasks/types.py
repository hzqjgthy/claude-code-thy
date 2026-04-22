from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Literal


TaskType = Literal["local_bash", "local_agent", "mcp", "workflow"]
TaskStatus = Literal["pending", "running", "completed", "failed", "killed", "exited"]


def utc_now() -> str:
    """返回 ISO 格式的 UTC 时间字符串。"""
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class TaskRecord:
    """保存一个后台任务最核心的状态与元数据。"""
    task_id: str
    task_type: TaskType
    description: str
    cwd: str
    output_path: str
    status_path: str
    status: TaskStatus = "pending"
    started_at: str = field(default_factory=utc_now)
    finished_at: str | None = None
    pid: int | None = None
    return_code: int | None = None
    tool_use_id: str | None = None
    agent_id: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)

    @property
    def is_terminal(self) -> bool:
        """判断任务是否已经进入终态。"""
        return self.status in {"completed", "failed", "killed", "exited"}

    def to_dict(self) -> dict[str, object]:
        """序列化成适合落盘的字典。"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "TaskRecord":
        """从持久化字典恢复基础任务记录。"""
        return cls(
            task_id=str(data.get("task_id", "")),
            task_type=str(data.get("task_type", "local_bash")),  # type: ignore[arg-type]
            description=str(data.get("description", "")),
            cwd=str(data.get("cwd", "")),
            output_path=str(data.get("output_path", "")),
            status_path=str(data.get("status_path", "")),
            status=str(data.get("status", "pending")),  # type: ignore[arg-type]
            started_at=str(data.get("started_at", utc_now())),
            finished_at=str(data["finished_at"]) if data.get("finished_at") is not None else None,
            pid=int(data["pid"]) if data.get("pid") is not None else None,
            return_code=(
                int(data["return_code"]) if data.get("return_code") is not None else None
            ),
            tool_use_id=(
                str(data["tool_use_id"]) if data.get("tool_use_id") is not None else None
            ),
            agent_id=str(data["agent_id"]) if data.get("agent_id") is not None else None,
            metadata=data.get("metadata", {}) if isinstance(data.get("metadata"), dict) else {},
        )


@dataclass(slots=True)
class BackgroundTask(TaskRecord):
    """在基础任务记录上补充本地命令执行相关字段。"""
    command: str = ""
    task_kind: str = "bash"
    sandbox_mode: str | None = None
    sandbox_applied: bool | None = None
    sandbox_reason: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "BackgroundTask":
        """从持久化字典恢复完整后台任务对象。"""
        base = TaskRecord.from_dict(data)
        return cls(
            task_id=base.task_id,
            task_type=base.task_type,
            description=base.description,
            cwd=base.cwd,
            output_path=base.output_path,
            status_path=base.status_path,
            status=base.status,
            started_at=base.started_at,
            finished_at=base.finished_at,
            pid=base.pid,
            return_code=base.return_code,
            tool_use_id=base.tool_use_id,
            agent_id=base.agent_id,
            metadata=base.metadata,
            command=str(data.get("command", "")),
            task_kind=str(data.get("task_kind", "bash")),
            sandbox_mode=(
                str(data["sandbox_mode"]) if data.get("sandbox_mode") is not None else None
            ),
            sandbox_applied=(
                bool(data["sandbox_applied"])
                if data.get("sandbox_applied") is not None
                else None
            ),
            sandbox_reason=str(data.get("sandbox_reason", "")),
        )
