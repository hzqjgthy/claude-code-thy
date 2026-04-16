from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from claude_code_thy.tools.base import ToolContext, ToolError
from claude_code_thy.tools.shared.text_files import TextFileSnapshot, read_text_snapshot, write_text_snapshot
from claude_code_thy.tools.shared.common import (
    _display_path,
    _ensure_full_read_before_write,
    _file_timestamp,
    _is_binary_bytes,
    _remember_read,
)


@dataclass(slots=True)
class WriteTargetState:
    previous_content: str | None
    operation: str
    encoding: str = "utf-8"
    newline: str = "\n"
    had_bom: bool = False


def load_existing_text(
    *,
    context: ToolContext,
    path: Path,
    file_path: str,
) -> WriteTargetState:
    previous_content: str | None = None
    operation = "create"
    encoding = "utf-8"
    newline = "\n"
    had_bom = False
    if path.exists():
        raw = path.read_bytes()
        if _is_binary_bytes(raw):
            raise ToolError(f"文件看起来是二进制文件，不支持直接写入：{file_path}")
        snapshot = read_text_snapshot(path)
        previous_content = snapshot.content
        encoding = snapshot.encoding
        newline = snapshot.newline
        had_bom = snapshot.had_bom
        _ensure_full_read_before_write(context, path, previous_content)
        operation = "update"
        if context.services is not None:
            context.services.file_history.snapshot(path, previous_content)
    return WriteTargetState(
        previous_content=previous_content,
        operation=operation,
        encoding=encoding,
        newline=newline,
        had_bom=had_bom,
    )


def persist_text_file(
    *,
    context: ToolContext,
    path: Path,
    content: str,
    target_state: WriteTargetState,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_text_snapshot(
        path,
        content,
        encoding=target_state.encoding,
        newline=target_state.newline,
        had_bom=target_state.had_bom,
    )
    timestamp = _file_timestamp(path)
    _remember_read(context, path, content, timestamp=timestamp)
    if context.services is not None:
        if target_state.operation == "create":
            context.services.lsp_manager.notify_file_opened(path, content)
        context.services.lsp_manager.notify_file_changed(path, content)
        context.services.lsp_manager.notify_file_saved(path)


def success_text(*, file_path: str, operation: str, user_modified: bool = False) -> str:
    modified_note = " The user modified the proposed change before accepting it." if user_modified else ""
    if operation == "update":
        return f"The file {file_path} has been updated successfully.{modified_note}"
    return f"File created successfully at: {file_path}.{modified_note}"


def summary_text(*, context: ToolContext, path: Path, operation: str) -> str:
    summary_prefix = "更新文件" if operation == "update" else "创建文件"
    return f"{summary_prefix}：{_display_path(path, context.cwd)}"
