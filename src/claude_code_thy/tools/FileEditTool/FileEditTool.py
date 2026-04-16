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
    _resolve_path,
    _truncate,
)
from claude_code_thy.tools.shared.text_files import read_text_snapshot
from .constants import DESCRIPTION, USAGE
from .operations import apply_edits, load_edit_target, persist_edit
from .types import EditInstruction


class EditTool(Tool):
    name = "edit"
    description = DESCRIPTION
    usage = USAGE
    input_schema = {
        "type": "object",
        "properties": {
            "file_path": {"type": "string", "description": "File to edit."},
            "old_string": {"type": "string", "description": "Exact text to replace."},
            "new_string": {"type": "string", "description": "Replacement text."},
            "replace_all": {"type": "boolean", "description": "Replace every match instead of one."},
            "edits": {
                "type": "array",
                "description": "Optional list of edit instructions.",
            },
        },
        "required": ["file_path"],
    }

    def is_concurrency_safe(self) -> bool:
        return False

    def parse_raw_input(self, raw_args: str, context: ToolContext) -> dict[str, object]:
        _ = context
        parser = _make_parser("edit", self.description)
        parser.add_argument("path", nargs="?")
        parser.add_argument("--old", dest="old_string")
        parser.add_argument("--new", dest="new_string")
        parser.add_argument("--replace-all", action="store_true")
        args = _parse_args(parser, raw_args)
        if not args.path or args.old_string is None or args.new_string is None:
            raise ToolError("用法：/edit <path> --old <old_string> --new <new_string> [--replace-all]")
        return {
            "file_path": args.path,
            "old_string": args.old_string,
            "new_string": args.new_string,
            "replace_all": args.replace_all,
        }

    def validate_input(
        self,
        input_data: dict[str, object],
        context: ToolContext,
    ):
        _ = context
        edits = self._coerce_edits(input_data)
        for edit in edits:
            if edit.old_string == edit.new_string:
                raise ToolError("No changes to make: old_string and new_string are exactly the same.")
        return super().validate_input(input_data, context)

    def check_permissions(
        self,
        input_data: dict[str, object],
        context: ToolContext,
    ) -> PermissionResult:
        file_path = str(input_data.get("file_path", "")).strip()
        path = _candidate_path(context, file_path, allow_missing=True)
        decision = context.permission_context.check_path(self.name, path)
        if decision is None or (decision.allowed and not decision.requires_confirmation):
            return PermissionResult.allow(updated_input=input_data)
        if decision.requires_confirmation:
            return PermissionResult.ask(
                context.permission_context.build_request_for_path(
                    self.name,
                    path,
                    reason=decision.reason,
                ),
                updated_input=input_data,
            )
        return PermissionResult.deny(decision.reason or f"{self.name} 被权限规则拒绝")

    def prepare_permission_matcher(self, input_data: dict[str, object], context: ToolContext):
        file_path = str(input_data.get("file_path", "")).strip()
        path = _candidate_path(context, file_path, allow_missing=True)
        return lambda pattern: context.permission_context.match_path_pattern(path, pattern)

    def inputs_equivalent(
        self,
        original_input: dict[str, object],
        updated_input: dict[str, object],
    ) -> bool:
        return self._normalized_edit_signature(original_input) == self._normalized_edit_signature(
            updated_input
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
        _ = original_input
        file_path = str(input_data.get("file_path", "")).strip()
        edits = self._coerce_edits(input_data)
        path = _candidate_path(context, file_path, allow_missing=True)
        display_path = _display_path(path, context.cwd)
        current_content = ""
        operation = "create"
        if path.exists() and path.is_file():
            try:
                current_content = read_text_snapshot(path).content
                operation = "update"
            except Exception:
                current_content = ""
        preview = ""
        structured_patch: object = []
        diff_text = ""
        lines_added = 0
        lines_removed = 0
        try:
            updated_file, _, operation = apply_edits(
                original_file=current_content,
                edits=edits,
            )
            patch = _build_diff(display_path, current_content, updated_file)
            preview = str(patch["preview"])
            structured_patch = patch["structured_patch"]
            diff_text = str(patch["diff_text"])
            lines_added = int(patch["lines_added"])
            lines_removed = int(patch["lines_removed"])
        except Exception:
            pass
        return ToolResult(
            tool_name=self.name,
            ok=False,
            summary=reason or f"编辑 `{display_path}` 被拒绝",
            display_name="Update" if operation == "update" else "Create",
            ui_kind="rejected",
            output=reason or "编辑被拒绝。",
            metadata={
                "rejected": True,
                "operation": operation,
                "user_modified": user_modified,
            },
            preview=preview,
            structured_data={
                "type": operation,
                "file_path": display_path,
                "original_file": current_content,
                "diff_text": diff_text,
                "structured_patch": structured_patch,
                "lines_added": lines_added,
                "lines_removed": lines_removed,
                "user_modified": user_modified,
                "rejected": True,
                "edits": [
                    {
                        "old_string_preview": _truncate(edit.old_string, 300),
                        "new_string_preview": _truncate(edit.new_string, 300),
                        "replace_all": edit.replace_all,
                    }
                    for edit in edits
                ],
            },
            tool_result_content=f"Edit to {file_path} was rejected. {reason}".strip(),
        )

    def execute(self, raw_args: str, context: ToolContext) -> ToolResult:
        args = self.parse_raw_input(raw_args, context)
        return self._edit(
            context,
            file_path=str(args["file_path"]),
            edits=self._coerce_edits(args),
        )

    def execute_input(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        file_path = str(input_data.get("file_path", "")).strip()
        if not file_path:
            raise ToolError("tool input 缺少 file_path")
        edits = self._coerce_edits(input_data)
        return self._edit(context, file_path=file_path, edits=edits)

    def _edit(
        self,
        context: ToolContext,
        *,
        file_path: str,
        edits: list[EditInstruction],
    ) -> ToolResult:
        path = _resolve_path(context, file_path, allow_missing=True, tool_name=self.name)
        context.discover_skills_for_paths([path])
        for edit in edits:
            check_secret_like_content(path, edit.new_string)
        if path.exists() and path.is_dir():
            raise ToolError(f"目标是目录，不是文件：{file_path}")
        if path.suffix.lower() == ".ipynb":
            raise ToolError("File is a Jupyter Notebook. Use notebook-specific tooling to edit this file.")

        original_file, snapshot = load_edit_target(
            context=context,
            path=path,
            file_path=file_path,
            old_string=edits[0].old_string if edits else "",
        )
        updated_file, edit_details, operation = apply_edits(
            original_file=original_file,
            edits=edits,
        )
        validate_settings_file_content(path, updated_file)
        persist_edit(
            context=context,
            path=path,
            updated_file=updated_file,
            operation=operation,
            snapshot=snapshot,
        )

        patch = _build_diff(_display_path(path, context.cwd), original_file, updated_file)
        git_diff = single_file_git_diff(path, status="added" if operation == "create" else "modified")
        replace_all = any(detail["replace_all"] for detail in edit_details)
        total_occurrences = sum(int(detail["occurrences"]) for detail in edit_details)
        user_modified = context.user_modified
        modified_note = " The user modified the proposed change before accepting it." if user_modified else ""
        if replace_all:
            tool_result_content = (
                "The file "
                f"{file_path} has been updated.{modified_note} All occurrences were successfully replaced."
            )
        else:
            tool_result_content = f"The file {file_path} has been updated successfully.{modified_note}"

        return ToolResult(
            tool_name=self.name,
            ok=True,
            summary=f"编辑文件：{_display_path(path, context.cwd)}",
            display_name="Update" if operation == "update" else "Create",
            ui_kind="edit",
            output="编辑已写入磁盘。",
            metadata={
                "replace_all": replace_all,
                "occurrences": total_occurrences,
                "num_edits": len(edit_details),
                "operation": operation,
                "encoding": snapshot.encoding if snapshot is not None else "utf-8",
                "newline": repr(snapshot.newline) if snapshot is not None else repr("\n"),
                "user_modified": user_modified,
            },
            preview=patch["preview"],
            structured_data={
                "type": operation,
                "file_path": _display_path(path, context.cwd),
                "original_file": original_file,
                "replace_all": replace_all,
                "diff_text": patch["diff_text"],
                "structured_patch": patch["structured_patch"],
                "lines_added": patch["lines_added"],
                "lines_removed": patch["lines_removed"],
                "user_modified": user_modified,
                **({"git_diff": git_diff} if git_diff is not None else {}),
                "edits": [
                    {
                        "old_string_preview": _truncate(str(detail["old_string"]), 300),
                        "new_string_preview": _truncate(str(detail["new_string"]), 300),
                        "replace_all": bool(detail["replace_all"]),
                        "occurrences": int(detail["occurrences"]),
                    }
                    for detail in edit_details
                ],
            },
            tool_result_content=tool_result_content,
        )

    def _coerce_edits(self, input_data: dict[str, object]) -> list[EditInstruction]:
        raw_edits = input_data.get("edits")
        if isinstance(raw_edits, list) and raw_edits:
            edits: list[EditInstruction] = []
            for item in raw_edits:
                if not isinstance(item, dict):
                    continue
                edits.append(
                    EditInstruction(
                        old_string=str(item.get("old_string", "")),
                        new_string=str(item.get("new_string", "")),
                        replace_all=bool(item.get("replace_all", False)),
                    )
                )
            if edits:
                return edits

        old_string = str(input_data.get("old_string", ""))
        new_string = str(input_data.get("new_string", ""))
        replace_all = bool(input_data.get("replace_all", False))
        if old_string == "" and new_string == "" and not raw_edits:
            raise ToolError("tool input 缺少 old_string/new_string 或 edits")
        return [
            EditInstruction(
                old_string=old_string,
                new_string=new_string,
                replace_all=replace_all,
            )
        ]

    def _normalized_edit_signature(self, input_data: dict[str, object]) -> tuple[object, ...]:
        file_path = str(input_data.get("file_path", "")).strip()
        edits = self._coerce_edits(input_data)
        return (
            file_path,
            tuple(
                (edit.old_string, edit.new_string, edit.replace_all)
                for edit in edits
            ),
        )
