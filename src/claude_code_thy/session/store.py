from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from claude_code_thy.models import SessionTranscript


SESSION_INDEX_FILENAME = ".index.json"
SESSION_INDEX_VERSION = 1


@dataclass(slots=True)
class SessionSummary:
    """保存会话列表页需要的轻量摘要信息。"""
    session_id: str
    title: str | None
    cwd: str
    model: str | None
    provider_name: str | None
    updated_at: str

    def to_dict(self) -> dict[str, object]:
        """序列化为适合写入索引文件的字典。"""
        return {
            "session_id": self.session_id,
            "title": self.title,
            "cwd": self.cwd,
            "model": self.model,
            "provider_name": self.provider_name,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "SessionSummary":
        """从索引文件中的字典恢复会话摘要。"""
        return cls(
            session_id=str(data.get("session_id", "")),
            title=data.get("title") and str(data.get("title")),
            cwd=str(data.get("cwd", "")),
            model=data.get("model") and str(data.get("model")),
            provider_name=data.get("provider_name") and str(data.get("provider_name")),
            updated_at=str(data.get("updated_at", "")),
        )


class SessionStore:
    """负责把会话转录保存到本地 JSON 文件并按需恢复。"""

    def __init__(self, root_dir: Path | None = None) -> None:
        """初始化会话目录、索引文件路径和进程内摘要缓存。"""
        self.root_dir = root_dir or self._default_root_dir()
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.root_dir / SESSION_INDEX_FILENAME
        self._recent_cache: list[SessionSummary] | None = None
        self._index_mtime_ns: int | None = None

    def _default_root_dir(self) -> Path:
        """解析会话存储目录，优先使用环境变量指定的位置。"""
        configured = os.environ.get("CLAUDE_CODE_THY_HOME")
        if configured:
            return Path(configured).expanduser().resolve() / "sessions"
        return Path.cwd() / ".claude-code-thy" / "sessions"

    def create(
        self,
        cwd: str,
        *,
        model: str | None = None,
        provider_name: str | None = None,
    ) -> SessionTranscript:
        """创建一个新的空会话，并记录当前工作目录和默认模型。"""
        return SessionTranscript(
            session_id=str(uuid4()),
            cwd=cwd,
            model=model,
            provider_name=provider_name,
        )

    def save(self, session: SessionTranscript) -> Path:
        """把会话完整写入磁盘，并同步更新摘要索引。"""
        path = self.path_for(session.session_id)
        path.write_text(
            json.dumps(session.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._upsert_summary(self._summary_from_session(session))
        self._write_index()
        return path

    def load(self, session_id: str) -> SessionTranscript:
        """按会话 ID 读取转录文件并恢复对象。"""
        path = self.path_for(session_id)
        if not path.exists():
            raise FileNotFoundError(f"Session not found: {session_id}")

        data = json.loads(path.read_text(encoding="utf-8"))
        return SessionTranscript.from_dict(data)

    def path_for(self, session_id: str) -> Path:
        """返回某个会话在磁盘上的 JSON 文件路径。"""
        return self.root_dir / f"{session_id}.json"

    def list_recent(self, limit: int = 20) -> list[SessionSummary]:
        """优先从索引读取最近会话摘要，索引缺失时才退回全量扫描。"""
        summaries = self._load_or_rebuild_index()
        return list(summaries[:limit])

    def load_latest(self, exclude_session_id: str | None = None) -> SessionTranscript | None:
        """加载最近一次会话，可选跳过当前会话自身。"""
        summaries = self.list_recent(limit=50)
        for summary in summaries:
            if summary.session_id == exclude_session_id:
                continue
            try:
                return self.load(summary.session_id)
            except FileNotFoundError:
                self._remove_summary(summary.session_id)
                self._write_index()
        return None

    def _summary_from_session(self, session: SessionTranscript) -> SessionSummary:
        """从完整会话对象提取索引所需的摘要字段。"""
        return SessionSummary(
            session_id=session.session_id,
            title=session.title,
            cwd=session.cwd,
            model=session.model,
            provider_name=session.provider_name,
            updated_at=session.updated_at,
        )

    def _read_summary(self, path: Path) -> SessionSummary | None:
        """从单个会话文件中读取摘要，不反序列化完整消息对象。"""
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        if not isinstance(data, dict):
            return None
        summary = SessionSummary.from_dict(data)
        return summary if summary.session_id else None

    def _session_files(self) -> list[Path]:
        """列出会话目录中的真实 transcript 文件，排除索引文件。"""
        return [
            path
            for path in self.root_dir.glob("*.json")
            if path != self.index_path and path.name != SESSION_INDEX_FILENAME
        ]

    def _load_or_rebuild_index(self) -> list[SessionSummary]:
        """加载进程内缓存或磁盘索引，必要时回退到全量重建。"""
        current_mtime_ns = self._safe_mtime_ns(self.index_path)
        if self._recent_cache is not None and self._index_mtime_ns == current_mtime_ns:
            return list(self._recent_cache)

        summaries = self._read_index()
        if summaries is None:
            return self._rebuild_index()

        normalized = self._normalize_summaries(summaries)
        self._recent_cache = normalized
        self._index_mtime_ns = current_mtime_ns
        if normalized != summaries:
            self._write_index()
        return list(normalized)

    def _read_index(self) -> list[SessionSummary] | None:
        """读取索引文件；格式非法时返回 `None` 触发重建。"""
        if not self.index_path.exists():
            return None
        try:
            payload = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        if not isinstance(payload, dict):
            return None
        if int(payload.get("version", 0) or 0) != SESSION_INDEX_VERSION:
            return None
        raw_sessions = payload.get("sessions")
        if not isinstance(raw_sessions, list):
            return None

        summaries: list[SessionSummary] = []
        for item in raw_sessions:
            if not isinstance(item, dict):
                return None
            summary = SessionSummary.from_dict(item)
            if not summary.session_id:
                return None
            summaries.append(summary)
        return summaries

    def _rebuild_index(self) -> list[SessionSummary]:
        """全量扫描 transcript 文件，重新生成索引缓存。"""
        summaries: list[SessionSummary] = []
        for path in self._session_files():
            summary = self._read_summary(path)
            if summary is None:
                continue
            summaries.append(summary)
        self._recent_cache = self._normalize_summaries(summaries)
        self._write_index()
        return list(self._recent_cache)

    def _normalize_summaries(self, summaries: list[SessionSummary]) -> list[SessionSummary]:
        """按更新时间排序、去重，并剔除索引里已经失效的会话条目。"""
        ordered = sorted(
            summaries,
            key=lambda item: item.updated_at,
            reverse=True,
        )
        normalized: list[SessionSummary] = []
        seen: set[str] = set()
        for summary in ordered:
            if not summary.session_id or summary.session_id in seen:
                continue
            if not self.path_for(summary.session_id).exists():
                continue
            seen.add(summary.session_id)
            normalized.append(summary)
        return normalized

    def _upsert_summary(self, summary: SessionSummary) -> None:
        """把一条摘要写入进程内缓存，并保持按更新时间倒序排列。"""
        summaries = self._load_or_rebuild_index()
        updated = [item for item in summaries if item.session_id != summary.session_id]
        updated.append(summary)
        self._recent_cache = self._normalize_summaries(updated)

    def _remove_summary(self, session_id: str) -> None:
        """从缓存索引里移除一条已经失效的会话摘要。"""
        summaries = self._load_or_rebuild_index()
        self._recent_cache = [item for item in summaries if item.session_id != session_id]

    def _write_index(self) -> None:
        """把当前摘要缓存原子写回索引文件。"""
        payload = {
            "version": SESSION_INDEX_VERSION,
            "sessions": [summary.to_dict() for summary in (self._recent_cache or [])],
        }
        temp_path = self.index_path.with_suffix(f"{self.index_path.suffix}.tmp")
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp_path.replace(self.index_path)
        self._index_mtime_ns = self._safe_mtime_ns(self.index_path)

    def _safe_mtime_ns(self, path: Path) -> int | None:
        """安全读取文件 mtime，文件不存在时返回 `None`。"""
        try:
            return path.stat().st_mtime_ns
        except OSError:
            return None
