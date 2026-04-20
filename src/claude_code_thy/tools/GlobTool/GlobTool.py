from __future__ import annotations

import subprocess
import time
from pathlib import Path

from claude_code_thy.tools.base import PermissionResult, Tool, ToolContext, ToolError, ToolResult
from claude_code_thy.tools.shared.common import (
    _candidate_path,
    _make_parser,
    _missing_path_error,
    _optional_stripped,
    _parse_args,
    _path_permission_result,
    _resolve_path,
)
from .prompt import DESCRIPTION, USAGE
from .search import glob_with_python, glob_with_rg


class GlobTool(Tool):
    name = "glob"
    description = DESCRIPTION
    usage = USAGE
    input_schema = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Glob pattern to match."},
            "path": {"type": "string", "description": "Directory to search in."},
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
        parser = _make_parser("glob", self.description)
        parser.add_argument("pattern", nargs="?")
        parser.add_argument("--path")
        args = _parse_args(parser, raw_args)
        pattern = args.pattern
        if not pattern:
            raise ToolError("请提供 glob pattern，例如：/glob **/*.py --path src")
        return {
            "pattern": pattern,
            "path": args.path,
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
        return self._glob(
            context,
            pattern=str(args["pattern"]),
            path=str(args.get("path", "")).strip() or None,
        )

    def execute_input(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        pattern = str(input_data.get("pattern", "")).strip()
        if not pattern:
            raise ToolError("tool input 缺少 pattern")
        path = _optional_stripped(input_data.get("path"))
        return self._glob(context, pattern=pattern, path=path)

    def _glob(self, context: ToolContext, *, pattern: str, path: str | None) -> ToolResult:
        search_root = context.cwd if not path else _resolve_path(context, path, tool_name=self.name)
        if not search_root.exists():
            raise _missing_path_error(context, path or str(search_root), kind="Directory")
        if not search_root.is_dir():
            raise ToolError("glob 的搜索路径必须是目录")

        started = time.time()
        results, truncated = glob_with_rg(context, pattern, search_root)
        if results is None:
            results, truncated = glob_with_python(context, pattern, search_root)

        output = "\n".join(results) if results else "No files found"
        if truncated:
            output += "\n(Results are truncated. Consider using a more specific path or pattern.)"
        duration_ms = int((time.time() - started) * 1000)
        return ToolResult(
            tool_name=self.name,
            ok=True,
            summary=f"匹配模式：{pattern}",
            display_name="Glob",
            ui_kind="glob",
            output=output,
            metadata={
                "duration_ms": duration_ms,
                "num_files": len(results),
                "truncated": truncated,
            },
            structured_data={
                "filenames": results,
                "duration_ms": duration_ms,
                "num_files": len(results),
                "truncated": truncated,
            },
            tool_result_content=output,
        )
