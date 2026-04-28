from __future__ import annotations

import traceback
from datetime import datetime
from typing import Any

from claude_code_thy.models import ChatMessage
from claude_code_thy.prompts.types import RenderedPrompt
from claude_code_thy.tools.base import ToolEvent, ToolResult


def serialize_message(message: ChatMessage) -> dict[str, object]:
    """把 ChatMessage 变成稳定的结构化字典。"""
    return {
        "role": message.role,
        "text": message.text,
        "content_blocks": message.content_blocks or [],
        "metadata": message.metadata or {},
        "created_at": message.created_at,
    }


def serialize_tool_event(event: ToolEvent) -> dict[str, object]:
    """把 ToolEvent 变成结构化字典。"""
    return {
        "tool_name": event.tool_name,
        "phase": event.phase,
        "summary": event.summary,
        "detail": event.detail,
        "metadata": dict(event.metadata),
    }


def serialize_tool_result(result: ToolResult) -> dict[str, object]:
    """把 ToolResult 变成结构化字典。"""
    return {
        "tool_name": result.tool_name,
        "ok": result.ok,
        "summary": result.summary,
        "display_name": result.display_name,
        "ui_kind": result.ui_kind,
        "output": result.output,
        "preview": result.preview,
        "metadata": dict(result.metadata),
        "structured_data": result.structured_data,
    }


def serialize_exception(error: BaseException, *, include_traceback: bool = False) -> dict[str, object]:
    """把异常整理成适合落盘的结构。"""
    payload: dict[str, object] = {
        "error_type": error.__class__.__name__,
        "message": str(error),
        "repr": repr(error),
    }
    if include_traceback:
        payload["traceback"] = "".join(traceback.format_exception(type(error), error, error.__traceback__))
    return payload


def summarize_request_preview(preview: dict[str, object]) -> dict[str, object]:
    """提取请求预览里最适合 `.log` 展示的摘要字段。"""
    json_body = preview.get("json_body")
    endpoint = str(preview.get("endpoint", "")).strip()
    provider = str(preview.get("provider", "")).strip()
    summary: dict[str, object] = {
        "provider": provider,
        "endpoint": endpoint,
    }
    if isinstance(json_body, dict):
        summary["model"] = str(json_body.get("model", "")).strip()
        tools = json_body.get("tools")
        if isinstance(tools, list):
            summary["tools_count"] = len(tools)
        messages = json_body.get("messages")
        if isinstance(messages, list):
            summary["message_count"] = len(messages)
        input_items = json_body.get("input")
        if isinstance(input_items, list):
            summary["input_count"] = len(input_items)
    return summary


def summarize_prompt_bundle(rendered_prompt: RenderedPrompt) -> dict[str, object]:
    """提取 prompt bundle 的简要结构，避免正文过度膨胀。"""
    bundle = rendered_prompt.bundle
    return {
        "session_id": bundle.session_id,
        "provider_name": bundle.provider_name,
        "model": bundle.model,
        "workspace_root": bundle.workspace_root,
        "sections": [
            {
                "id": section.id,
                "target": section.target,
                "kind": section.kind,
                "order": section.order,
                "relative_name": section.relative_name,
                "source_type": section.source_type,
            }
            for section in bundle.sections
        ],
    }


def format_local_time(value: str) -> str:
    """把 ISO 时间戳转成本地时区可读格式。"""
    try:
        date = datetime.fromisoformat(value)
    except ValueError:
        return value
    return date.astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
