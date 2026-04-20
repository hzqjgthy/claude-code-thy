from __future__ import annotations

import time
from pathlib import Path

from claude_code_thy.tools.base import PermissionResult, Tool, ToolContext, ToolError, ToolResult
from claude_code_thy.tools.shared.common import (
    _apply_head_limit,
    _candidate_path,
    _format_limit_info,
    _make_parser,
    _missing_path_error,
    _optional_stripped,
    _parse_args,
    _path_permission_result,
    _resolve_path,
)
from .prompt import DESCRIPTION, USAGE
from .search import grep_with_python, grep_with_rg


class GrepTool(Tool):
    name = "grep"
    description = DESCRIPTION
    usage = USAGE
    input_schema = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "The regular expression pattern to search for."},
            "path": {"type": "string", "description": "File or directory to search in."},
            "glob": {"type": "string", "description": "Glob pattern to filter files."},
            "output_mode": {
                "type": "string",
                "enum": ["content", "files_with_matches", "count"],
            },
            "-B": {"type": "integer"},
            "-A": {"type": "integer"},
            "-C": {"type": "integer"},
            "context": {"type": "integer"},
            "-n": {"type": "boolean"},
            "-i": {"type": "boolean"},
            "type": {"type": "string"},
            "head_limit": {"type": "integer"},
            "offset": {"type": "integer"},
            "multiline": {"type": "boolean"},
        },
        "required": ["pattern"],
    }

    def is_read_only(self) -> bool:
        return True

    def is_concurrency_safe(self) -> bool:
        return True

    def search_behavior(self) -> dict[str, bool]:
        return {"is_search": True, "is_read": False}

    def parse_raw_input(self, raw_args: str, context: ToolContext) -> dict[str, object]:
        _ = context
        parser = _make_parser("grep", self.description)
        parser.add_argument("pattern", nargs="?")
        parser.add_argument("--path")
        parser.add_argument("--glob")
        parser.add_argument("--content", action="store_true")
        parser.add_argument("--files-with-matches", action="store_true")
        parser.add_argument("--count", action="store_true")
        parser.add_argument("--before", type=int)
        parser.add_argument("--after", type=int)
        parser.add_argument("--context", type=int)
        parser.add_argument("--ignore-case", action="store_true")
        parser.add_argument("--type")
        parser.add_argument("--head-limit", type=int)
        parser.add_argument("--offset", type=int, default=0)
        parser.add_argument("--multiline", action="store_true")
        parser.add_argument("--line-numbers", dest="line_numbers", action="store_true")
        parser.add_argument("--no-line-numbers", dest="line_numbers", action="store_false")
        parser.set_defaults(line_numbers=True)
        args = _parse_args(parser, raw_args)
        if not args.pattern:
            raise ToolError("用法：/grep <pattern> [--glob PATTERN] [--path 路径]")
        output_mode = "files_with_matches"
        if args.content:
            output_mode = "content"
        elif args.count:
            output_mode = "count"
        elif args.files_with_matches:
            output_mode = "files_with_matches"
        return {
            "pattern": args.pattern,
            "path": args.path,
            "glob": args.glob,
            "output_mode": output_mode,
            "-B": args.before,
            "-A": args.after,
            "context": args.context,
            "-n": args.line_numbers,
            "-i": args.ignore_case,
            "type": args.type,
            "head_limit": args.head_limit,
            "offset": args.offset,
            "multiline": args.multiline,
        }

    def check_permissions(
        self,
        input_data: dict[str, object],
        context: ToolContext,
    ) -> PermissionResult:
        raw_path = str(input_data.get("path", "")).strip()
        if not raw_path:
            return PermissionResult.allow(updated_input=input_data)
        return _path_permission_result(self.name, raw_path, context, input_data)

    def prepare_permission_matcher(self, input_data: dict[str, object], context: ToolContext):
        raw_path = str(input_data.get("path", "")).strip()
        path = _candidate_path(context, raw_path or ".", allow_missing=True)
        return lambda pattern: context.permission_context.match_path_pattern(path, pattern)

    def execute(self, raw_args: str, context: ToolContext) -> ToolResult:
        args = self.parse_raw_input(raw_args, context)
        return self._grep(
            context,
            pattern=str(args["pattern"]),
            path=str(args.get("path", "")).strip() or None,
            glob=str(args.get("glob", "")).strip() or None,
            output_mode=str(args.get("output_mode", "files_with_matches")),
            before=args.get("-B") if isinstance(args.get("-B"), int) else None,
            after=args.get("-A") if isinstance(args.get("-A"), int) else None,
            context_lines=args.get("context") if isinstance(args.get("context"), int) else None,
            line_numbers=bool(args.get("-n", True)),
            ignore_case=bool(args.get("-i", False)),
            file_type=(
                str(args.get("type")).strip()
                if args.get("type") not in (None, "")
                else None
            ),
            head_limit=args.get("head_limit") if isinstance(args.get("head_limit"), int) else None,
            offset=int(args.get("offset", 0) or 0),
            multiline=bool(args.get("multiline", False)),
        )

    def execute_input(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        pattern = str(input_data.get("pattern", "")).strip()
        if not pattern:
            raise ToolError("tool input 缺少 pattern")
        return self._grep(
            context,
            pattern=pattern,
            path=_optional_stripped(input_data.get("path")),
            glob=_optional_stripped(input_data.get("glob")),
            output_mode=str(input_data.get("output_mode", "files_with_matches") or "files_with_matches"),
            before=int(input_data.get("-B", 0) or 0) or None,
            after=int(input_data.get("-A", 0) or 0) or None,
            context_lines=int(input_data.get("context", 0) or input_data.get("-C", 0) or 0) or None,
            line_numbers=bool(input_data.get("-n", True)),
            ignore_case=bool(input_data.get("-i", False)),
            file_type=_optional_stripped(input_data.get("type")),
            head_limit=(
                None
                if input_data.get("head_limit", None) in (None, "")
                else int(input_data.get("head_limit") or 0)
            ),
            offset=int(input_data.get("offset", 0) or 0),
            multiline=bool(input_data.get("multiline", False)),
        )

    def _grep(
        self,
        context: ToolContext,
        *,
        pattern: str,
        path: str | None,
        glob: str | None,
        output_mode: str,
        before: int | None,
        after: int | None,
        context_lines: int | None,
        line_numbers: bool,
        ignore_case: bool,
        file_type: str | None,
        head_limit: int | None,
        offset: int,
        multiline: bool,
    ) -> ToolResult:
        if output_mode not in {"content", "files_with_matches", "count"}:
            raise ToolError(f"不支持的 output_mode：{output_mode}")
        if offset < 0:
            raise ToolError("--offset 必须 >= 0")
        if head_limit is not None and head_limit < 0:
            raise ToolError("--head-limit 必须 >= 0")

        search_path = context.cwd if not path else _resolve_path(context, path, tool_name=self.name)
        if not search_path.exists():
            raise _missing_path_error(context, path or str(search_path))

        started = time.time()
        results = grep_with_rg(
            context,
            pattern=pattern,
            search_path=search_path,
            glob=glob,
            output_mode=output_mode,
            before=before,
            after=after,
            context_lines=context_lines,
            line_numbers=line_numbers,
            ignore_case=ignore_case,
            file_type=file_type,
            multiline=multiline,
        )
        if results is None:
            results = grep_with_python(
                context,
                pattern=pattern,
                search_path=search_path,
                glob=glob,
                output_mode=output_mode,
                ignore_case=ignore_case,
            )

        if output_mode == "content":
            paged, applied_limit = _apply_head_limit(results, head_limit, offset)
            content = "\n".join(paged)
            limit_info = _format_limit_info(applied_limit, offset if offset else None)
            if limit_info:
                model_content = f"{content}\n\n[Showing results with pagination = {limit_info}]"
            else:
                model_content = content or "No matches found"
            num_lines = len(paged)
            structured_data = {
                "mode": "content",
                "content": content,
                "num_lines": num_lines,
                "applied_limit": applied_limit,
                "applied_offset": offset if offset else None,
            }
            output = content or "No matches found"
        elif output_mode == "count":
            paged, applied_limit = _apply_head_limit(results, head_limit, offset)
            content = "\n".join(paged)
            num_matches = 0
            file_count = 0
            for line in paged:
                _, _, count_text = line.rpartition(":")
                count_text = count_text.strip()
                if count_text.isdigit():
                    num_matches += int(count_text)
                    file_count += 1
            limit_info = _format_limit_info(applied_limit, offset if offset else None)
            model_content = content or "No matches found"
            model_content += (
                f"\n\nFound {num_matches} total occurrences across {file_count} files."
                + (f" with pagination = {limit_info}" if limit_info else "")
            )
            structured_data = {
                "mode": "count",
                "content": content,
                "num_matches": num_matches,
                "num_files": file_count,
                "applied_limit": applied_limit,
                "applied_offset": offset if offset else None,
            }
            output = content or "No matches found"
        else:
            paged, applied_limit = _apply_head_limit(results, head_limit, offset)
            num_files = len(paged)
            limit_info = _format_limit_info(applied_limit, offset if offset else None)
            output = "No files found" if not paged else "\n".join(paged)
            model_content = (
                "No files found"
                if not paged
                else f"Found {num_files} files"
                + (f" {limit_info}" if limit_info else "")
                + f"\n{output}"
            )
            structured_data = {
                "mode": "files_with_matches",
                "filenames": paged,
                "num_files": num_files,
                "applied_limit": applied_limit,
                "applied_offset": offset if offset else None,
            }

        return ToolResult(
            tool_name=self.name,
            ok=True,
            summary=f"搜索：{pattern}",
            display_name="Search",
            ui_kind="grep",
            output=output,
            metadata={
                "mode": output_mode,
                "duration_ms": int((time.time() - started) * 1000),
            },
            structured_data=structured_data,
            tool_result_content=model_content,
        )
