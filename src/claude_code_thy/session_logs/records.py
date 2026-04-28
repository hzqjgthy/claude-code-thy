from __future__ import annotations

from dataclasses import dataclass


SESSION_LOG_RECORD_VERSION = 1


@dataclass(slots=True)
class SessionLogRecord:
    """表示一条可同时落到 `.jsonl` 和 `.log` 的统一日志事件。"""
    version: int
    session_id: str
    turn_index: int
    event_index: int
    timestamp: str
    event: str
    data: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        """转成适合 JSON 序列化的字典。"""
        return {
            "version": self.version,
            "session_id": self.session_id,
            "turn_index": self.turn_index,
            "event_index": self.event_index,
            "timestamp": self.timestamp,
            "event": self.event,
            "data": self.data,
        }


@dataclass(slots=True)
class ToolCallLogContext:
    """记录一次工具调用在日志系统里的局部标识。"""
    call_ref: str
    ordinal: int
    tool_name: str
    tool_use_id: str | None
    surface: str
    input_data: dict[str, object]
