from __future__ import annotations

import json
import os
from pathlib import Path
from dataclasses import dataclass
from uuid import uuid4

from claude_code_thy.models import SessionTranscript


@dataclass(slots=True)
class SessionSummary:
    session_id: str
    title: str | None
    cwd: str
    model: str | None
    provider_name: str | None
    updated_at: str


class SessionStore:
    def __init__(self, root_dir: Path | None = None) -> None:
        self.root_dir = root_dir or self._default_root_dir()
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def _default_root_dir(self) -> Path:
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
        return SessionTranscript(
            session_id=str(uuid4()),
            cwd=cwd,
            model=model,
            provider_name=provider_name,
        )

    def save(self, session: SessionTranscript) -> Path:
        path = self.path_for(session.session_id)
        path.write_text(
            json.dumps(session.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path

    def load(self, session_id: str) -> SessionTranscript:
        path = self.path_for(session_id)
        if not path.exists():
            raise FileNotFoundError(f"Session not found: {session_id}")

        data = json.loads(path.read_text(encoding="utf-8"))
        return SessionTranscript.from_dict(data)

    def path_for(self, session_id: str) -> Path:
        return self.root_dir / f"{session_id}.json"

    def list_recent(self, limit: int = 20) -> list[SessionSummary]:
        summaries: list[SessionSummary] = []

        for path in self.root_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue

            summaries.append(
                SessionSummary(
                    session_id=str(data["session_id"]),
                    title=data.get("title") and str(data["title"]),
                    cwd=str(data.get("cwd", "")),
                    model=data.get("model") and str(data["model"]),
                    provider_name=data.get("provider_name") and str(data["provider_name"]),
                    updated_at=str(data.get("updated_at", "")),
                )
            )

        summaries.sort(key=lambda item: item.updated_at, reverse=True)
        return summaries[:limit]

    def load_latest(self, exclude_session_id: str | None = None) -> SessionTranscript | None:
        summaries = self.list_recent(limit=50)
        for summary in summaries:
            if summary.session_id == exclude_session_id:
                continue
            return self.load(summary.session_id)
        return None
