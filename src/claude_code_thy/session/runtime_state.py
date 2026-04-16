from __future__ import annotations

from typing import Any

from claude_code_thy.models import SessionTranscript
from claude_code_thy.permissions import PermissionRequest


def approved_permissions(session: SessionTranscript) -> list[str]:
    raw = session.runtime_state.get("approved_permissions", [])
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw if str(item).strip()]


def add_approved_permission(session: SessionTranscript, approval_key: str) -> None:
    existing = approved_permissions(session)
    if approval_key not in existing:
        existing.append(approval_key)
    session.runtime_state["approved_permissions"] = existing


def get_pending_permission(session: SessionTranscript) -> dict[str, Any] | None:
    raw = session.runtime_state.get("pending_permission")
    if not isinstance(raw, dict):
        return None
    return raw


def set_pending_permission(
    session: SessionTranscript,
    request: PermissionRequest,
    *,
    source_type: str,
    tool_name: str,
    raw_args: str | None = None,
    input_data: dict[str, object] | None = None,
    original_input: dict[str, object] | None = None,
    user_modified: bool | None = None,
    tool_use_id: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "request": request.to_dict(),
        "source_type": source_type,
        "tool_name": tool_name,
    }
    if raw_args is not None:
        payload["raw_args"] = raw_args
    if input_data is not None:
        payload["input_data"] = input_data
    if original_input is not None:
        payload["original_input"] = original_input
    if user_modified is not None:
        payload["user_modified"] = bool(user_modified)
    if tool_use_id is not None:
        payload["tool_use_id"] = tool_use_id
    session.runtime_state["pending_permission"] = payload
    return payload


def clear_pending_permission(session: SessionTranscript) -> None:
    session.runtime_state.pop("pending_permission", None)


def pending_request(session: SessionTranscript) -> PermissionRequest | None:
    pending = get_pending_permission(session)
    if pending is None:
        return None
    request = pending.get("request")
    if not isinstance(request, dict):
        return None
    return PermissionRequest.from_dict(request)
