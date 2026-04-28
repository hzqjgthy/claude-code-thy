from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(slots=True)
class SessionLogBundle:
    """描述某个 session 对应的一组日志文件路径。"""
    prefix: str
    root_dir: Path
    log_path: Path
    jsonl_path: Path
    started_at_utc: str
    started_at_local: str


def resolve_output_dir(workspace_root: Path, output_dir: str) -> Path:
    """把配置里的输出目录解析成绝对路径。"""
    base = Path(output_dir).expanduser()
    if not base.is_absolute():
        base = workspace_root / base
    return base.resolve()


def build_log_prefix(session_id: str, now_local: datetime) -> str:
    """按本地时间戳和 session id 生成固定日志前缀。"""
    return f"{now_local.strftime('%Y%m%d_%H%M%S')}__{session_id}"


def build_session_log_bundle(root_dir: Path, prefix: str, *, now_local: datetime | None = None) -> SessionLogBundle:
    """根据输出目录和前缀构造日志文件路径。"""
    current_local = now_local or datetime.now().astimezone()
    started_at_local = current_local.isoformat()
    started_at_utc = current_local.astimezone(timezone.utc).isoformat()
    return SessionLogBundle(
        prefix=prefix,
        root_dir=root_dir,
        log_path=root_dir / f"{prefix}.log",
        jsonl_path=root_dir / f"{prefix}.jsonl",
        started_at_utc=started_at_utc,
        started_at_local=started_at_local,
    )
