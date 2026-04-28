from __future__ import annotations

import json

from claude_code_thy.settings import SessionLogSettings

from .records import SessionLogRecord
from .serializers import format_local_time


EQ_LINE = "=" * 80
DASH_LINE = "-" * 80
ERROR_LINE = "!" * 80


def render_record(record: SessionLogRecord, settings: SessionLogSettings) -> str:
    """把统一日志事件渲染成人类可读文本。"""
    event = record.event
    data = record.data

    if event == "session_started":
        return _render_session_started(data)
    if event == "session_resumed":
        return _render_session_resumed(data)
    if event == "turn_started":
        return _render_turn_started(record.turn_index, data)
    if event == "command_parsed":
        return _render_command_parsed(data)
    if event == "provider_request":
        return _render_provider_request(data)
    if event == "provider_error":
        return _render_provider_error(record.turn_index, data)
    if event == "runtime_error":
        return _render_runtime_error(record.turn_index, data)
    if event == "message_added":
        return _render_message_added(data)
    if event == "tool_event":
        return _render_tool_event(data)
    if event == "tool_call_started":
        return _render_tool_call_started(data)
    if event == "tool_call_finished":
        return _render_tool_call_finished(data, settings)
    if event == "permission_requested":
        return _render_permission_requested(data)
    if event == "permission_resolved":
        return _render_permission_resolved(data)
    if event == "turn_finished":
        return _render_turn_finished(data)
    return ""


def _render_session_started(data: dict[str, object]) -> str:
    lines = [
        EQ_LINE,
        "会话日志开始",
        f"本地时间: {str(data.get('started_at_local_readable', ''))}",
        f"UTC 时间: {str(data.get('started_at_utc', ''))}",
        f"会话ID: {str(data.get('session_id', ''))}",
        f"标题: {str(data.get('title', '')) or '(empty)'}",
        f"Provider: {str(data.get('provider_name', '')) or 'unknown'}",
        f"Model: {str(data.get('model', '')) or '(unset)'}",
        f"工作目录: {str(data.get('cwd', ''))}",
        f"人类日志: {str(data.get('log_path', ''))}",
        f"结构化日志: {str(data.get('jsonl_path', ''))}",
        EQ_LINE,
        "",
    ]
    return "\n".join(lines)


def _render_session_resumed(data: dict[str, object]) -> str:
    lines = [
        DASH_LINE,
        "会话恢复",
        f"时间: {str(data.get('resumed_at_local_readable', ''))}",
        f"会话ID: {str(data.get('session_id', ''))}",
        "说明: 继续向同一组日志文件追加",
        DASH_LINE,
        "",
    ]
    return "\n".join(lines)


def _render_turn_started(turn_index: int, data: dict[str, object]) -> str:
    lines = [
        EQ_LINE,
        f"第 {turn_index} 轮",
        f"开始时间: {str(data.get('started_at_local_readable', ''))}",
        f"输入类型: {str(data.get('input_kind', 'chat'))}",
        f"流式输出: {'开启' if bool(data.get('stream')) else '关闭'}",
        "",
        "[用户输入]",
        str(data.get("prompt", "")),
        "",
    ]
    return "\n".join(lines)


def _render_command_parsed(data: dict[str, object]) -> str:
    lines = [
        "[Slash 命令]",
        f"- 原始命令: {str(data.get('raw_prompt', ''))}",
        f"- command: {str(data.get('command', ''))}",
    ]
    raw_args = str(data.get("raw_args", ""))
    if raw_args:
        lines.append(f"- raw_args: {raw_args}")
    submit_prompt = str(data.get("submit_prompt", ""))
    if submit_prompt:
        lines.append("- submit_prompt: 已生成")
    model_override = str(data.get("model_override", ""))
    if model_override:
        lines.append(f"- model_override: {model_override}")
    lines.append("")
    return "\n".join(lines)


def _render_provider_request(data: dict[str, object]) -> str:
    summary = data.get("request_preview_summary")
    if not isinstance(summary, dict):
        return ""
    lines = [
        "[Provider 请求]",
        f"- Provider: {str(summary.get('provider', ''))}",
        f"- Model: {str(summary.get('model', ''))}",
        f"- Endpoint: {str(summary.get('endpoint', ''))}",
    ]
    if "tools_count" in summary:
        lines.append(f"- Tools Count: {summary['tools_count']}")
    lines.append("- Request Preview: 已记录")
    lines.append("")
    return "\n".join(lines)


def _render_provider_error(turn_index: int, data: dict[str, object]) -> str:
    lines = [
        ERROR_LINE,
        "错误",
        f"时间: {str(data.get('occurred_at_local_readable', ''))}",
        f"第几轮: {turn_index}",
        f"阶段: {str(data.get('stage', 'provider'))}",
        f"错误类型: {str(data.get('error_type', 'Error'))}",
        f"错误信息: {str(data.get('message', ''))}",
    ]
    provider_name = str(data.get("provider_name", ""))
    if provider_name:
        lines.append(f"Provider: {provider_name}")
    tool_name = str(data.get("tool_name", ""))
    if tool_name:
        lines.append(f"相关工具: {tool_name}")
    tool_use_id = str(data.get("tool_use_id", ""))
    if tool_use_id:
        lines.append(f"tool_use_id: {tool_use_id}")
    input_data = data.get("input_data")
    if input_data not in (None, "", {}):
        lines.extend(["", "相关输入:", _pretty_json(input_data)])
    summary = data.get("request_preview_summary")
    if isinstance(summary, dict) and summary:
        lines.extend(["", "最近一次请求摘要:"])
        for key in ("model", "endpoint", "tools_count", "message_count", "input_count"):
            if key in summary and str(summary[key]).strip():
                lines.append(f"- {key}: {summary[key]}")
    lines.extend([ERROR_LINE, ""])
    return "\n".join(lines)


def _render_runtime_error(turn_index: int, data: dict[str, object]) -> str:
    lines = [
        ERROR_LINE,
        "运行时错误",
        f"时间: {str(data.get('occurred_at_local_readable', ''))}",
        f"第几轮: {turn_index}",
        f"阶段: {str(data.get('stage', 'runtime'))}",
        f"错误类型: {str(data.get('error_type', 'Error'))}",
        f"错误信息: {str(data.get('message', ''))}",
        ERROR_LINE,
        "",
    ]
    return "\n".join(lines)


def _render_message_added(data: dict[str, object]) -> str:
    role = str(data.get("role", ""))
    text = str(data.get("text", ""))
    if role != "assistant" or not text.strip():
        return ""
    lines = [
        "[Assistant]",
        text,
        "",
    ]
    return "\n".join(lines)


def _render_tool_event(data: dict[str, object]) -> str:
    summary = str(data.get("summary", ""))
    phase = str(data.get("phase", ""))
    tool_name = str(data.get("tool_name", ""))
    if not summary and not phase:
        return ""
    lines = ["[工具事件]"]
    if tool_name:
        lines.append(f"- tool: {tool_name}")
    if phase:
        lines.append(f"- phase: {phase}")
    if summary:
        lines.append(f"- summary: {summary}")
    detail = str(data.get("detail", ""))
    if detail:
        lines.extend(["- detail:", detail])
    lines.append("")
    return "\n".join(lines)


def _render_tool_call_started(data: dict[str, object]) -> str:
    lines = [
        f"[工具调用 {int(data.get('ordinal', 0) or 0)}]",
        f"- 名称: {str(data.get('tool_name', ''))}",
    ]
    tool_use_id = str(data.get("tool_use_id", ""))
    if tool_use_id:
        lines.append(f"- tool_use_id: {tool_use_id}")
    lines.append(f"- surface: {str(data.get('surface', ''))}")
    lines.extend(["- 输入:", _pretty_json(data.get("input_data", {})), ""])
    return "\n".join(lines)


def _render_tool_call_finished(data: dict[str, object], settings: SessionLogSettings) -> str:
    status_text = "成功" if bool(data.get("ok")) else "失败"
    lines = [
        f"[工具结果 {int(data.get('ordinal', 0) or 0)}]",
        f"- 状态: {status_text}",
        f"- 摘要: {str(data.get('summary', ''))}",
    ]
    output = str(data.get("output", ""))
    preview = str(data.get("preview", ""))
    body = output or preview
    if body:
        rendered_output, truncated = _truncate_tool_output(body, settings)
        lines.extend(["- 输出:", rendered_output])
        if truncated:
            lines.append("完整工具输出见同名 .jsonl")
    lines.append("")
    return "\n".join(lines)


def _render_permission_requested(data: dict[str, object]) -> str:
    lines = [
        "[权限请求]",
        f"- 工具: {str(data.get('tool_name', ''))}",
        f"- 原因: {str(data.get('reason', ''))}",
    ]
    tool_use_id = str(data.get("tool_use_id", ""))
    if tool_use_id:
        lines.append(f"- tool_use_id: {tool_use_id}")
    lines.append("")
    return "\n".join(lines)


def _render_permission_resolved(data: dict[str, object]) -> str:
    lines = [
        "[权限结果]",
        f"- 结果: {'已同意' if bool(data.get('approved')) else '已拒绝'}",
        f"- 工具: {str(data.get('tool_name', ''))}",
    ]
    tool_use_id = str(data.get("tool_use_id", ""))
    if tool_use_id:
        lines.append(f"- tool_use_id: {tool_use_id}")
    lines.append("")
    return "\n".join(lines)


def _render_turn_finished(data: dict[str, object]) -> str:
    status = str(data.get("status", "success"))
    lines = [
        f"第 {int(data.get('turn_index', 0) or 0)} 轮结束",
        f"结束状态: {status}",
        f"新增消息数: {int(data.get('new_message_count', 0) or 0)}",
        EQ_LINE,
        "",
    ]
    return "\n".join(lines)


def _pretty_json(value: object) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, indent=2)
    except TypeError:
        return str(value)


def _truncate_tool_output(text: str, settings: SessionLogSettings) -> tuple[str, bool]:
    normalized = text or ""
    if len(normalized) <= settings.tool_output_inline_max_chars:
        return normalized, False
    head_chars = max(settings.tool_output_head_chars, 0)
    tail_chars = max(settings.tool_output_tail_chars, 0)
    if head_chars + tail_chars >= len(normalized):
        return normalized, False
    head = normalized[:head_chars]
    tail = normalized[-tail_chars:] if tail_chars else ""
    omitted_chars = len(normalized) - len(head) - len(tail)
    middle = f"... ... ...（中间已省略，共 {len(normalized)} 字符，省略 {omitted_chars} 字符）... ... ..."
    if head and tail:
        return f"{head}\n\n{middle}\n\n{tail}", True
    if head:
        return f"{head}\n\n{middle}", True
    if tail:
        return f"{middle}\n\n{tail}", True
    return middle, True
