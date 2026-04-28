from __future__ import annotations

import json

from claude_code_thy.settings import SessionLogSettings


EQ_LINE = "=" * 80
DASH_LINE = "-" * 76
ERROR_LINE = "!" * 80


def render_session_started_block(data: dict[str, object]) -> str:
    """渲染一条会话日志启动头。"""
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


def render_session_resumed_block(data: dict[str, object]) -> str:
    """渲染一条会话恢复头。"""
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


def render_turn_started_block(turn_index: int, data: dict[str, object]) -> str:
    """渲染交互轮开始块。"""
    lines = [
        EQ_LINE,
        f"交互轮 {turn_index}",
        f"开始时间: {str(data.get('started_at_local_readable', ''))}",
        f"输入类型: {str(data.get('input_kind', 'chat'))}",
        f"流式输出: {'开启' if bool(data.get('stream')) else '关闭'}",
        "",
        "[用户输入]",
        str(data.get("prompt", "")),
        "",
    ]
    return "\n".join(lines)


def render_command_parsed_block(data: dict[str, object]) -> str:
    """渲染 slash 命令解析块。"""
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


def render_turn_finished_block(turn_index: int, data: dict[str, object]) -> str:
    """渲染交互轮结束块。"""
    lines = [
        f"交互轮 {turn_index} 结束",
        f"结束状态: {str(data.get('status', 'success'))}",
        f"新增 transcript 消息数: {int(data.get('new_message_count', 0) or 0)}",
        f"LLM 轮数: {int(data.get('llm_turn_count', 0) or 0)}",
        f"工具调用数: {int(data.get('tool_call_count', 0) or 0)}",
        EQ_LINE,
        "",
    ]
    return "\n".join(lines)


def render_assistant_message_block(text: str) -> str:
    """渲染一条不属于 LLM 轮块的 assistant 直接输出。"""
    return "\n".join(
        [
            "[Assistant]",
            text,
            "",
        ]
    )


def render_llm_turn_block(llm_turn: dict[str, object], settings: SessionLogSettings) -> str:
    """按“交互轮 -> LLM 轮 -> 工具调用”的层级渲染一个完整 LLM 块。"""
    interaction_turn_index = int(llm_turn.get("interaction_turn_index", 0) or 0)
    llm_turn_index = int(llm_turn.get("llm_turn_index", 0) or 0)
    status = _resolved_llm_status(llm_turn)
    request_summary = llm_turn.get("request_preview_summary")
    assistant_text = str(llm_turn.get("assistant_text", "")).strip()
    tool_calls = llm_turn.get("tool_calls")
    error = llm_turn.get("error")
    tool_call_count = int(llm_turn.get("tool_call_count", 0) or 0)
    tool_error_count = int(llm_turn.get("tool_error_count", 0) or 0)
    permission_request_count = int(llm_turn.get("permission_request_count", 0) or 0)

    lines = [
        DASH_LINE,
        f"LLM 轮 {interaction_turn_index}.{llm_turn_index}",
        f"开始时间: {str(llm_turn.get('started_at_local_readable', ''))}",
        f"结束状态: {status}",
        f"工具调用数: {tool_call_count}",
        f"工具失败数: {tool_error_count}",
        f"权限请求数: {permission_request_count}",
    ]

    if isinstance(request_summary, dict):
        lines.extend(
            [
                "",
                "[请求摘要]",
                f"- Provider: {str(llm_turn.get('provider_name', ''))}",
            ]
        )
        for key in ("model", "endpoint", "tools_count", "message_count", "input_count"):
            value = request_summary.get(key)
            if value in (None, "", []):
                continue
            lines.append(f"- {key}: {value}")

    if assistant_text:
        lines.extend(["", "[LLM 输出]", assistant_text])
    else:
        lines.extend(["", "[LLM 输出]", "(无直接文本输出，仅工具调用或控制块)"])

    if isinstance(tool_calls, list) and tool_calls:
        lines.append("")
        lines.append("[工具调用]")
        for tool in tool_calls:
            if not isinstance(tool, dict):
                continue
            lines.extend(_render_tool_call_block(tool, settings))

    if isinstance(error, dict) and error:
        lines.extend(
            [
                "",
                "[LLM 错误]",
                f"- 类型: {str(error.get('error_type', 'Error'))}",
                f"- 信息: {str(error.get('message', ''))}",
            ]
        )

    lines.extend([DASH_LINE, ""])
    return "\n".join(lines)


def _render_tool_call_block(tool: dict[str, object], settings: SessionLogSettings) -> list[str]:
    ordinal = int(tool.get("ordinal", 0) or 0)
    lines = [
        f"{ordinal}. {str(tool.get('tool_name', ''))}",
    ]
    tool_use_id = str(tool.get("tool_use_id", "")).strip()
    if tool_use_id:
        lines.append(f"   tool_use_id: {tool_use_id}")
    surface = str(tool.get("surface", "")).strip()
    if surface:
        lines.append(f"   surface: {surface}")
    lines.extend(
        [
            "   输入:",
            _indent_block(_pretty_json(tool.get("input_data", {})), "   "),
        ]
    )

    permission_requested = tool.get("permission_requested")
    if isinstance(permission_requested, dict):
        lines.extend(
            [
                "   权限请求:",
                f"   - 原因: {str(permission_requested.get('reason', ''))}",
            ]
        )
        if bool(permission_requested.get("paused")):
            lines.extend(
                [
                    "   交互轮暂停:",
                    f"   - 原因: {str(permission_requested.get('pause_reason', 'pending_permission'))}",
                ]
            )

    permission_resolved = tool.get("permission_resolved")
    if isinstance(permission_resolved, dict):
        lines.extend(
            [
                "   权限结果:",
                f"   - 结果: {'已同意' if bool(permission_resolved.get('approved')) else '已拒绝'}",
            ]
        )

    result = tool.get("result")
    if isinstance(result, dict):
        lines.extend(
            [
                f"   状态: {'成功' if bool(result.get('ok')) else '失败'}",
            ]
        )
        summary = str(result.get("summary", "")).strip()
        if summary:
            lines.append(f"   摘要: {summary}")
        output = str(result.get("output", "") or result.get("preview", "")).strip()
        if output:
            rendered_output, truncated = _truncate_tool_output(output, settings)
            lines.extend(["   输出:", _indent_block(rendered_output, "   ")])
            if truncated:
                lines.append("   完整工具输出见同名 .jsonl")
    return lines


def _pretty_json(value: object) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, indent=2)
    except TypeError:
        return str(value)


def _indent_block(text: str, prefix: str) -> str:
    stripped = text.rstrip()
    if not stripped:
        return prefix
    return "\n".join(f"{prefix}{line}" for line in stripped.splitlines())


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


def _resolved_llm_status(llm_turn: dict[str, object]) -> str:
    """根据聚合统计给 LLM 轮渲染更贴近真实过程的状态。"""
    base_status = str(llm_turn.get("status", "success") or "success")
    if base_status == "error":
        return "error"
    tool_error_count = int(llm_turn.get("tool_error_count", 0) or 0)
    if tool_error_count > 0:
        return "success_with_tool_error"
    return base_status
