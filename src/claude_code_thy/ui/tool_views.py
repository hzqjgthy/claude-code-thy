from __future__ import annotations

from rich import box
from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.text import Text

from claude_code_thy.tools.AgentTool.UI import (
    extra_result_lines as agent_extra_result_lines,
    summarize_input as agent_summarize_input,
    tool_label as agent_tool_label,
)
from claude_code_thy.tools.BashTool.UI import (
    extra_result_lines as bash_extra_result_lines,
    summarize_input as bash_summarize_input,
    tool_label as bash_tool_label,
)
from claude_code_thy.tools.FileEditTool.UI import (
    extra_result_lines as edit_extra_result_lines,
    summarize_input as edit_summarize_input,
    tool_label as edit_tool_label,
)
from claude_code_thy.tools.FileReadTool.UI import (
    extra_result_lines as read_extra_result_lines,
    summarize_input as read_summarize_input,
    tool_label as read_tool_label,
)
from claude_code_thy.tools.FileWriteTool.UI import (
    extra_result_lines as write_extra_result_lines,
    summarize_input as write_summarize_input,
    tool_label as write_tool_label,
)
from claude_code_thy.tools.GlobTool.UI import (
    extra_result_lines as glob_extra_result_lines,
    summarize_input as glob_summarize_input,
    tool_label as glob_tool_label,
)
from claude_code_thy.tools.GrepTool.UI import (
    extra_result_lines as grep_extra_result_lines,
    summarize_input as grep_summarize_input,
    tool_label as grep_tool_label,
)

TOOL_LABELS = {
    "agent": agent_tool_label,
    "bash": bash_tool_label,
    "read": read_tool_label,
    "write": write_tool_label,
    "edit": edit_tool_label,
    "glob": glob_tool_label,
    "grep": grep_tool_label,
}

TOOL_INPUT_SUMMARIZERS = {
    "agent": agent_summarize_input,
    "bash": bash_summarize_input,
    "read": read_summarize_input,
    "write": write_summarize_input,
    "edit": edit_summarize_input,
    "glob": glob_summarize_input,
    "grep": grep_summarize_input,
}

TOOL_EXTRA_RESULT_LINES = {
    "agent": agent_extra_result_lines,
    "bash": bash_extra_result_lines,
    "read": read_extra_result_lines,
    "write": write_extra_result_lines,
    "edit": edit_extra_result_lines,
    "glob": glob_extra_result_lines,
    "grep": grep_extra_result_lines,
}


def truncate_single_line(text: str, limit: int = 120) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return f"{collapsed[: limit - 1]}…"


def combine_text_lines(lines: list[Text]) -> Text:
    combined = Text()
    for index, line in enumerate(lines):
        if index > 0:
            combined.append("\n")
        combined.append_text(line)
    return combined


def tool_label(tool_name: str) -> str:
    if tool_name.startswith("mcp__"):
        parts = tool_name.split("__", 2)
        if len(parts) == 3:
            return f"MCP {parts[1]}/{parts[2]}"
        return "MCP"
    renderer = TOOL_LABELS.get(tool_name)
    return renderer() if renderer is not None else tool_name


def summarize_tool_input(tool_name: str, raw_input: object) -> str:
    if not isinstance(raw_input, dict):
        return ""
    renderer = TOOL_INPUT_SUMMARIZERS.get(tool_name)
    if renderer is not None:
        return truncate_single_line(renderer(raw_input))
    return truncate_single_line(str(raw_input))


def build_tool_call_message(message_text: str, tool_calls: list[object]) -> RenderableType:
    lines: list[RenderableType] = [Text("")]
    if message_text.strip():
        lines.append(
            Text.assemble(
                Text("⏺ ", style="bold #f5f7fa"),
                Text(message_text, style="#f5f7fa"),
            )
        )

    for call in tool_calls:
        if not isinstance(call, dict):
            continue
        tool_name = str(call.get("name", "tool"))
        detail = summarize_tool_input(tool_name, call.get("input"))
        lines.append(
            Text.assemble(
                Text("⏺ ", style="bold #f5f7fa"),
                Text(tool_label(tool_name), style="bold #f5f7fa"),
                Text(f" {detail}", style="#9aa4b2"),
            )
        )

    return Group(*lines)


def build_permission_prompt_message(message_text: str, metadata: dict[str, object]) -> RenderableType:
    request = metadata.get("pending_permission")
    target = ""
    value = ""
    if isinstance(request, dict):
        target = str(request.get("target", ""))
        value = str(request.get("value", "")).strip()

    title = "Permission Request"
    if target:
        title = f"Permission Request · {target}"

    body = Text(message_text.strip() or "工具请求权限确认。", style="#f5f7fa")
    renderables: list[RenderableType] = [Text("")]
    renderables.append(
        Panel(
            body,
            title=title,
            title_align="left",
            border_style="#d7e3f4",
            box=box.ROUNDED,
            padding=(0, 1),
        )
    )
    if value:
        renderables.append(Text(f"  {truncate_single_line(value, 160)}", style="#9aa4b2"))
    return Group(*renderables)


def build_task_notification_message(message_text: str, metadata: dict[str, object]) -> RenderableType:
    task_id = str(metadata.get("task_id", "")).strip()
    task_status = str(metadata.get("task_status", "")).strip() or "updated"
    task_type = str(metadata.get("task_type", "")).strip() or "task"
    title = f"{task_type} · {task_status}"
    if task_id:
        title = f"{title} · {task_id}"
    return Group(
        Text(""),
        Panel(
            Text(message_text.strip(), style="#f5f7fa"),
            title=title,
            title_align="left",
            border_style="#4b5563",
            box=box.ROUNDED,
            padding=(0, 1),
        ),
    )


def build_tool_result_message(metadata: dict[str, object]) -> RenderableType:
    label = str(metadata.get("display_name") or tool_label(str(metadata.get("tool_name", "tool"))))
    summary = str(metadata.get("summary", "")).strip()
    output = str(metadata.get("output", "")).strip()
    preview = str(metadata.get("preview", "")).strip()
    structured_data = metadata.get("structured_data")
    ui_kind = str(metadata.get("ui_kind", ""))
    label_style = "bold #f5f7fa" if ui_kind != "rejected" else "bold #f59e0b"

    body = Text.assemble(
        Text("⏺ ", style="bold #f5f7fa"),
        Text(label, style=label_style),
        Text(f" {truncate_single_line(summary)}", style="#9aa4b2"),
    )
    text_lines: list[Text] = [body]

    summary_text = tool_result_summary(structured_data, output, summary=summary)
    if summary_text:
        text_lines.append(Text(f"  {summary_text}", style="#d7e3f4"))

    tool_name = str(metadata.get("tool_name", ""))
    extra_renderer = TOOL_EXTRA_RESULT_LINES.get(tool_name)
    if extra_renderer is not None:
        for line in extra_renderer(metadata):
            text_lines.append(Text(f"  {truncate_single_line(line)}", style="#d7e3f4"))

    renderables: list[RenderableType] = [Text("")]
    if text_lines:
        renderables.append(combine_text_lines(text_lines))

    if preview:
        renderables.append(
            Panel(
                Text(preview, style="#d7e3f4"),
                border_style="#7c5c12" if ui_kind == "rejected" else "#344054",
                box=box.ROUNDED,
                padding=(0, 1),
            )
        )
    elif output and metadata.get("ui_kind") in {"bash", "rejected"}:
        renderables.append(
            Panel(
                Text(truncate_single_line(output, 400), style="#d7e3f4"),
                border_style="#7c5c12" if ui_kind == "rejected" else "#344054",
                box=box.ROUNDED,
                padding=(0, 1),
            )
        )

    return Group(*renderables)


def tool_result_summary(structured_data: object, fallback_output: str, *, summary: str = "") -> str:
    if not isinstance(structured_data, dict):
        return truncate_single_line(fallback_output) if fallback_output else ""

    result_type = structured_data.get("type")
    if result_type == "text":
        count = structured_data.get("num_lines", 0)
        return f"Read {count} line{'s' if count != 1 else ''}"
    if result_type == "image":
        size = structured_data.get("original_size")
        return f"Read image ({format_size(size)})"
    if result_type == "pdf":
        size = structured_data.get("original_size")
        return f"Read PDF ({format_size(size)})"
    if result_type == "parts":
        count = structured_data.get("count", 0)
        size = structured_data.get("original_size")
        return f"Read {count} page{'s' if count != 1 else ''} ({format_size(size)})"
    if result_type == "notebook":
        count = structured_data.get("cell_count", 0)
        return f"Read {count} cell{'s' if count != 1 else ''}"
    if result_type == "file_unchanged":
        return "Unchanged since last read"
    if result_type in {"create", "update"}:
        file_path = structured_data.get("file_path", "")
        if "lines_written" in structured_data:
            lines_written = structured_data.get("lines_written", 0)
            return f"Wrote {lines_written} lines to {file_path}"
        return f"Updated {file_path}"
    if structured_data.get("mode") == "content":
        count = structured_data.get("num_lines", 0)
        return f"Found {count} matching line{'s' if count != 1 else ''}"
    if structured_data.get("mode") == "count":
        matches = structured_data.get("num_matches", 0)
        files = structured_data.get("num_files", 0)
        return f"Found {matches} matches across {files} files"
    if structured_data.get("mode") == "files_with_matches":
        files = structured_data.get("num_files", 0)
        return f"Found {files} file{'s' if files != 1 else ''}"
    if structured_data.get("num_files") is not None:
        files = structured_data.get("num_files", 0)
        return f"Found {files} file{'s' if files != 1 else ''}"
    if structured_data.get("background_task_id"):
        task_id = structured_data.get("background_task_id")
        return f"Running in background: {task_id}"
    if structured_data.get("task_id"):
        task_id = structured_data.get("task_id")
        status = structured_data.get("status", "running")
        return f"Agent {status}: {task_id}"
    if structured_data.get("description"):
        description = truncate_single_line(str(structured_data["description"]))
        command = truncate_single_line(str(structured_data.get("command", "")).strip())
        summary_single_line = truncate_single_line(summary) if summary else ""
        if command and description == command:
            return ""
        if summary_single_line and description and description in summary_single_line:
            return ""
        return description
    return truncate_single_line(fallback_output) if fallback_output else ""


def format_size(value: object) -> str:
    if not isinstance(value, int):
        return "?"
    units = ["B", "KB", "MB", "GB"]
    size = float(value)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(size)}{unit}"
            return f"{size:.1f}{unit}"
        size /= 1024
    return f"{value}B"
