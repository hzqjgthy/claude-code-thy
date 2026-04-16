from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_session_title(text: str) -> str:
    collapsed = " ".join(text.strip().split())
    if len(collapsed) <= 48:
        return collapsed
    return f"{collapsed[:47]}…"


@dataclass(slots=True)
class ChatMessage:
    role: str
    text: str
    content_blocks: list[dict[str, object]] | None = None
    metadata: dict[str, object] | None = None
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "ChatMessage":
        return cls(
            role=str(data["role"]),
            text=str(data["text"]),
            content_blocks=(
                data.get("content_blocks")
                if isinstance(data.get("content_blocks"), list)
                else None
            ),
            metadata=data.get("metadata") if isinstance(data.get("metadata"), dict) else None,
            created_at=str(data.get("created_at", utc_now())),
        )


@dataclass(slots=True)
class SessionTranscript:
    session_id: str
    cwd: str
    title: str | None = None
    model: str | None = None
    provider_name: str | None = None
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    runtime_state: dict[str, object] = field(default_factory=dict)
    messages: list[ChatMessage] = field(default_factory=list)

    def add_message(
        self,
        role: str,
        text: str,
        *,
        content_blocks: list[dict[str, object]] | None = None,
        metadata: dict[str, object] | None = None,
    ) -> None:
        self.messages.append(
            ChatMessage(
                role=role,
                text=text,
                content_blocks=content_blocks,
                metadata=metadata,
            )
        )
        if role == "user" and not self.title and text.strip():
            self.title = build_session_title(text)
        self.updated_at = utc_now()

    def clear_messages(self) -> None:
        self.messages = []
        self.updated_at = utc_now()

    def to_dict(self) -> dict[str, object]:
        return {
            "session_id": self.session_id,
            "cwd": self.cwd,
            "title": self.title,
            "model": self.model,
            "provider_name": self.provider_name,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "runtime_state": self.runtime_state,
            "messages": [message.to_dict() for message in self.messages],
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "SessionTranscript":
        raw_messages = data.get("messages", [])
        return cls(
            session_id=str(data["session_id"]),
            cwd=str(data["cwd"]),
            title=data.get("title") and str(data["title"]),
            model=data.get("model") and str(data["model"]),
            provider_name=data.get("provider_name") and str(data["provider_name"]),
            created_at=str(data.get("created_at", utc_now())),
            updated_at=str(data.get("updated_at", utc_now())),
            runtime_state=(
                data.get("runtime_state")
                if isinstance(data.get("runtime_state"), dict)
                else {}
            ),
            messages=[
                ChatMessage.from_dict(message)
                for message in raw_messages
                if isinstance(message, dict)
            ],
        )
