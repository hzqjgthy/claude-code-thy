from __future__ import annotations

from claude_code_thy.tools.base import PermissionResult, Tool, ToolContext, ToolError, ToolResult
from claude_code_thy.tools.shared import check_secret_like_content, validate_settings_file_content
from claude_code_thy.tools.shared.git_diff import single_file_git_diff
from claude_code_thy.tools.shared.common import (
    _candidate_path,
    _build_diff,
    _display_path,
    _make_parser,
    _parse_args,
    _path_permission_result,
    _resolve_path,
)
from claude_code_thy.tools.shared.text_files import read_text_snapshot
from .operations import load_existing_text, persist_text_file, success_text, summary_text
from .prompt import DESCRIPTION, USAGE


class WriteTool(Tool):
    """实现 `Write` 工具。"""
    name = "write"
    description = DESCRIPTION
    usage = USAGE
    input_schema = {
        "type": "object",
        "properties": {
            "file_path": {"type": "string", "description": "Absolute or relative file path."},
            "content": {"type": "string", "description": "The full file content to write."},
        },
        "required": ["file_path", "content"],
    }

    def is_concurrency_safe(self) -> bool:
        """返回是否满足 `is_concurrency_safe` 条件。"""
        return False

    def parse_raw_input(self, raw_args: str, context: ToolContext) -> dict[str, object]:
        """解析 `raw_input`。"""
        _ = context
        parser = _make_parser("write", self.description)
        parser.add_argument("path", nargs="?")
        if " -- " in raw_args:
            arg_part, content = raw_args.split(" -- ", 1)
        else:
            arg_part = raw_args
            content = ""
        args = _parse_args(parser, arg_part)
        if not args.path:
            raise ToolError("用法：/write <path> -- <content>")
        return {
            "file_path": args.path,
            "content": content,
        }

    def check_permissions(
        self,
        input_data: dict[str, object],
        context: ToolContext,
    ) -> PermissionResult:
        """检查 `permissions`。"""
        file_path = str(input_data.get("file_path", "")).strip()
        return _path_permission_result(self.name, file_path, context, input_data)

    def prepare_permission_matcher(self, input_data: dict[str, object], context: ToolContext):
        """处理 `prepare_permission_matcher`。"""
        file_path = str(input_data.get("file_path", "")).strip()
        path = _candidate_path(context, file_path, allow_missing=True)
        return lambda pattern: context.permission_context.match_path_pattern(path, pattern)

    def inputs_equivalent(
        self,
        original_input: dict[str, object],
        updated_input: dict[str, object],
    ) -> bool:
        """处理 `inputs_equivalent`。"""
        return (
            str(original_input.get("file_path", "")).strip()
            == str(updated_input.get("file_path", "")).strip()
            and str(original_input.get("content", "")) == str(updated_input.get("content", ""))
        )

    def render_tool_use_rejected_message(
        self,
        input_data: dict[str, object],
        context: ToolContext,
        *,
        reason: str,
        original_input: dict[str, object] | None = None,
        user_modified: bool = False,
    ) -> ToolResult:
        """渲染 `tool_use_rejected_message`。"""
        _ = original_input
        file_path = str(input_data.get("file_path", "")).strip()
        content = str(input_data.get("content", ""))
        path = _candidate_path(context, file_path, allow_missing=True)
        display_path = _display_path(path, context.cwd)
        old_content: str | None = None
        operation = "create"
        if path.exists() and path.is_file():
            try:
                old_content = read_text_snapshot(path).content
                operation = "update"
            except Exception:
                old_content = None
        patch = _build_diff(display_path, old_content or "", content)
        return ToolResult(
            tool_name=self.name,
            ok=False,
            summary=reason or f"写入 `{display_path}` 被拒绝",
            display_name="Write" if operation == "create" else "Update",
            ui_kind="rejected",
            output=reason or "写入被拒绝。",
            metadata={
                "rejected": True,
                "operation": operation,
                "user_modified": user_modified,
            },
            preview=patch["preview"],
            structured_data={
                "type": operation,
                "file_path": display_path,
                "original_file": old_content,
                "diff_text": patch["diff_text"],
                "structured_patch": patch["structured_patch"],
                "lines_added": patch["lines_added"],
                "lines_removed": patch["lines_removed"],
                "user_modified": user_modified,
                "rejected": True,
            },
            tool_result_content=f"Write to {file_path} was rejected. {reason}".strip(),
        )

    def execute(self, raw_args: str, context: ToolContext) -> ToolResult:
        """执行当前流程。"""
        args = self.parse_raw_input(raw_args, context)
        return self._write(
            context,
            file_path=str(args["file_path"]),
            content=str(args.get("content", "")),
        )

    def execute_input(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        """执行 `input`。"""
        file_path = str(input_data.get("file_path", "")).strip()
        if not file_path:
            raise ToolError("tool input 缺少 file_path")
        content = str(input_data.get("content", ""))
        return self._write(context, file_path=file_path, content=content)

    def _write(self, context: ToolContext, *, file_path: str, content: str) -> ToolResult:
        """写入 当前流程。"""
        path = _resolve_path(context, file_path, allow_missing=True, tool_name=self.name)
        if path.exists() and path.is_dir():
            raise ToolError(f"目标是目录，不是文件：{file_path}")
        check_secret_like_content(path, content)
        validate_settings_file_content(path, content)

        target_state = load_existing_text(
            context=context,
            path=path,
            file_path=file_path,
        )
        persist_text_file(
            context=context,
            path=path,
            content=content,
            target_state=target_state,
        )

        display_path = _display_path(path, context.cwd)
        patch = _build_diff(display_path, target_state.previous_content or "", content)
        git_diff = single_file_git_diff(path, status="added" if target_state.operation == "create" else "modified")
        lines_written = len(content.splitlines())
        user_modified = context.user_modified
        return ToolResult(
            tool_name=self.name,
            ok=True,
            summary=summary_text(context=context, path=path, operation=target_state.operation),
            display_name="Write",
            ui_kind="write",
            output=f"Wrote {lines_written} lines to {display_path}",
            metadata={
                "bytes_written": len(content.encode('utf-8')),
                "lines_written": lines_written,
                "operation": target_state.operation,
                "encoding": target_state.encoding,
                "newline": repr(target_state.newline),
                "user_modified": user_modified,
            },
            preview=patch["preview"],
            structured_data={
                "type": target_state.operation,
                "file_path": display_path,
                "original_file": target_state.previous_content,
                "lines_written": lines_written,
                "diff_text": patch["diff_text"],
                "structured_patch": patch["structured_patch"],
                "lines_added": patch["lines_added"],
                "lines_removed": patch["lines_removed"],
                "user_modified": user_modified,
                **({"git_diff": git_diff} if git_diff is not None else {}),
            },
            tool_result_content=success_text(
                file_path=file_path,
                operation=target_state.operation,
                user_modified=user_modified,
            ),
        )
