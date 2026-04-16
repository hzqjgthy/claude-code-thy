from __future__ import annotations

from pathlib import Path

from claude_code_thy.tools.base import ToolContext, ToolError
from claude_code_thy.tools.shared.text_files import TextFileSnapshot, read_text_snapshot, write_text_snapshot
from claude_code_thy.tools.shared.common import (
    _ensure_full_read_before_write,
    _file_timestamp,
    _find_actual_string,
    _is_binary_bytes,
    _missing_path_error,
    _preserve_quote_style,
    _remember_read,
)
from .types import EditInstruction

MAX_EDIT_FILE_SIZE = 1024 * 1024 * 1024


def load_edit_target(
    *,
    context: ToolContext,
    path: Path,
    file_path: str,
    old_string: str,
) -> tuple[str, TextFileSnapshot | None]:
    if path.exists():
        if path.stat().st_size > MAX_EDIT_FILE_SIZE:
            raise ToolError("File is too large to edit safely.")
        raw = path.read_bytes()
        if _is_binary_bytes(raw):
            raise ToolError(f"文件看起来是二进制文件，不支持直接编辑：{file_path}")
        snapshot = read_text_snapshot(path)
        original_file = snapshot.content
        _ensure_full_read_before_write(context, path, original_file)
        if context.services is not None:
            context.services.file_history.snapshot(path, original_file)
        return original_file, snapshot

    if old_string != "":
        raise _missing_path_error(context, file_path)
    return "", None


def apply_edit(
    *,
    original_file: str,
    old_string: str,
    new_string: str,
    replace_all: bool,
) -> tuple[str, str, str, str, int]:
    if old_string == "":
        if original_file.strip():
            raise ToolError("Cannot create new file - file already exists.")
        return new_string, "", new_string, "create", 0

    actual_old_string = _find_actual_string(original_file, old_string)
    if not actual_old_string:
        raise ToolError(f"String to replace not found in file.\nString: {old_string}")
    occurrences = original_file.count(actual_old_string)
    if occurrences > 1 and not replace_all:
        raise ToolError(
            "Found multiple matches of the string to replace, but replace_all is false. "
            "Provide more context or set replace_all=true."
        )
    actual_new_string = _preserve_quote_style(old_string, actual_old_string, new_string)
    updated_file = (
        original_file.replace(actual_old_string, actual_new_string)
        if replace_all
        else original_file.replace(actual_old_string, actual_new_string, 1)
    )
    return updated_file, actual_old_string, actual_new_string, "update", occurrences


def apply_edits(
    *,
    original_file: str,
    edits: list[EditInstruction],
) -> tuple[str, list[dict[str, object]], str]:
    updated_file = original_file
    details: list[dict[str, object]] = []
    operation = "update"

    if len(edits) == 1 and edits[0].old_string == "" and original_file.strip() == "":
        updated_file = edits[0].new_string
        details.append(
            {
                "old_string": "",
                "new_string": edits[0].new_string,
                "replace_all": edits[0].replace_all,
                "occurrences": 0,
            }
        )
        return updated_file, details, "create"

    for edit in edits:
        if edit.old_string == edit.new_string:
            raise ToolError("No changes to make: old_string and new_string are exactly the same.")
        updated_file, actual_old, actual_new, operation, occurrences = apply_edit(
            original_file=updated_file,
            old_string=edit.old_string,
            new_string=edit.new_string,
            replace_all=edit.replace_all,
        )
        details.append(
            {
                "old_string": actual_old,
                "new_string": actual_new,
                "replace_all": edit.replace_all,
                "occurrences": occurrences,
            }
        )
    return updated_file, details, operation


def persist_edit(
    *,
    context: ToolContext,
    path: Path,
    updated_file: str,
    operation: str,
    snapshot: TextFileSnapshot | None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_text_snapshot(
        path,
        updated_file,
        encoding=snapshot.encoding if snapshot is not None else "utf-8",
        newline=snapshot.newline if snapshot is not None else "\n",
        had_bom=snapshot.had_bom if snapshot is not None else False,
    )
    timestamp = _file_timestamp(path)
    _remember_read(context, path, updated_file, timestamp=timestamp)
    if context.services is not None:
        if operation == "create":
            context.services.lsp_manager.notify_file_opened(path, updated_file)
        context.services.lsp_manager.notify_file_changed(path, updated_file)
        context.services.lsp_manager.notify_file_saved(path)
