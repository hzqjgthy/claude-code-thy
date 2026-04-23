from __future__ import annotations

from claude_code_thy.tools.base import PermissionResult, Tool, ToolContext, ToolError, ToolResult
from claude_code_thy.tools.shared.common import (
    IMAGE_EXTENSIONS,
    PDF_INLINE_PAGE_THRESHOLD,
    _candidate_path,
    _decode_text,
    _display_path,
    _file_timestamp,
    _is_binary_bytes,
    _is_blocked_device_path,
    _make_parser,
    _missing_path_error,
    _optional_stripped,
    _parse_args,
    _path_permission_result,
    _remember_read,
    _resolve_path,
    _truncate,
)
from .limits import MAX_FULL_TEXT_READ_BYTES, MAX_WINDOW_TEXT_READ_BYTES
from .prompt import DESCRIPTION, USAGE
from .readers import read_image, read_notebook, read_pdf, read_text_window


class ReadTool(Tool):
    """实现 `Read` 工具。"""
    name = "read"
    description = DESCRIPTION
    usage = USAGE
    input_schema = {
        "type": "object",
        "properties": {
            "file_path": {"type": "string", "description": "Absolute or relative file path."},
            "offset": {"type": "integer", "description": "1-based start line.", "minimum": 1},
            "limit": {"type": "integer", "description": "Maximum lines to read.", "minimum": 1},
            "pages": {"type": "string", "description": "PDF page range such as 1-5."},
        },
        "required": ["file_path"],
    }

    def is_read_only(self) -> bool:
        """返回是否满足 `is_read_only` 条件。"""
        return True

    def is_concurrency_safe(self) -> bool:
        """返回是否满足 `is_concurrency_safe` 条件。"""
        return True

    def search_behavior(self) -> dict[str, bool]:
        """搜索 `behavior`。"""
        return {"is_search": False, "is_read": True}

    def parse_raw_input(self, raw_args: str, context: ToolContext) -> dict[str, object]:
        """解析 `raw_input`。"""
        _ = context
        parser = _make_parser("read", self.description)
        parser.add_argument("path", nargs="?")
        parser.add_argument("--offset", type=int, default=1)
        parser.add_argument("--limit", type=int)
        parser.add_argument("--pages")
        args = _parse_args(parser, raw_args)

        if not args.path:
            raise ToolError("请提供文件路径，例如：/read README.md --offset 1 --limit 80")
        if args.offset < 1:
            raise ToolError("--offset 必须 >= 1")
        if args.limit is not None and args.limit < 1:
            raise ToolError("--limit 必须 >= 1")
        return {
            "file_path": args.path,
            "offset": args.offset,
            "limit": args.limit,
            "pages": args.pages,
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

    def execute(self, raw_args: str, context: ToolContext) -> ToolResult:
        """执行当前流程。"""
        args = self.parse_raw_input(raw_args, context)
        return self._read(
            context,
            file_path=str(args["file_path"]),
            offset=int(args.get("offset", 1) or 1),
            limit=args.get("limit") if isinstance(args.get("limit"), int) else None,
            pages=str(args.get("pages", "")).strip() or None,
        )

    def execute_input(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        """执行 `input`。"""
        file_path = str(input_data.get("file_path", "")).strip()
        if not file_path:
            raise ToolError("tool input 缺少 file_path")

        offset = int(input_data.get("offset", 1) or 1)
        limit_raw = input_data.get("limit")
        limit = None if limit_raw in (None, "") else int(limit_raw)
        pages = _optional_stripped(input_data.get("pages"))
        return self._read(
            context,
            file_path=file_path,
            offset=offset,
            limit=limit,
            pages=pages,
        )

    def _read(
        self,
        context: ToolContext,
        *,
        file_path: str,
        offset: int,
        limit: int | None,
        pages: str | None,
    ) -> ToolResult:
        """读取 当前流程。"""
        path = _resolve_path(context, file_path, tool_name=self.name)
        if not path.exists():
            raise _missing_path_error(context, file_path)
        if path.is_dir():
            raise ToolError(f"目标是目录，不是文件：{file_path}")
        if _is_blocked_device_path(str(path)):
            raise ToolError(f"Cannot read '{file_path}': this device file would block or produce infinite output.")

        ext = path.suffix.lower().lstrip(".")
        if ext in IMAGE_EXTENSIONS:
            return read_image(tool_name=self.name, context=context, path=path)
        if ext == "ipynb":
            return read_notebook(tool_name=self.name, context=context, path=path)
        if ext == "pdf":
            return read_pdf(
                tool_name=self.name,
                context=context,
                path=path,
                pages=pages,
                inline_page_threshold=PDF_INLINE_PAGE_THRESHOLD,
            )

        timestamp = _file_timestamp(path)
        state = context.read_file_state.get(str(path))
        is_full_request = offset == 1 and limit is None
        if is_full_request:
            raw = path.read_bytes()
            if _is_binary_bytes(raw):
                raise ToolError(f"文件看起来是二进制文件，不支持直接读取：{file_path}")
            if len(raw) > MAX_FULL_TEXT_READ_BYTES:
                raise ToolError(
                    f"文件过大（{len(raw)} bytes），请使用 offset/limit 分段读取。"
                )

            content = _decode_text(raw)
            if (
                state
                and state.file_kind == "text"
                and state.offset == offset
                and state.limit == limit
                and state.timestamp == timestamp
            ):
                return ToolResult(
                    tool_name=self.name,
                    ok=True,
                    summary=f"文件未变化：{_display_path(path, context.cwd)}",
                    display_name="Read",
                    ui_kind="read",
                    output="Unchanged since last read",
                    structured_data={
                        "type": "file_unchanged",
                        "file_path": _display_path(path, context.cwd),
                    },
                    tool_result_content="Unchanged since last read.",
                )
            lines = content.splitlines()
            selected = lines
            state_content = content
            total_bytes = len(raw)
            total_lines = len(lines)
        else:
            with path.open("rb") as handle:
                sample = handle.read(8192)
            if _is_binary_bytes(sample):
                raise ToolError(f"文件看起来是二进制文件，不支持直接读取：{file_path}")
            if path.stat().st_size > MAX_WINDOW_TEXT_READ_BYTES:
                raise ToolError("文件过大，不支持继续按文本窗口读取。请先缩小读取范围。")

            window = read_text_window(path, offset=offset, limit=limit)
            selected = window["selected_lines"] if isinstance(window["selected_lines"], list) else []
            total_lines = int(window["total_lines"])
            state_content = str(window["content"])
            total_bytes = path.stat().st_size

        if selected:
            numbered = "\n".join(
                f"{line_number:>6}\t{line}"
                for line_number, line in enumerate(selected, start=offset)
            )
        elif total_lines == 0:
            numbered = "<system-reminder>Warning: the file exists but the contents are empty.</system-reminder>"
        else:
            numbered = (
                "<system-reminder>"
                f"Warning: the file exists but is shorter than the provided offset ({offset}). "
                f"The file has {total_lines} lines."
                "</system-reminder>"
            )

        _remember_read(
            context,
            path,
            state_content,
            timestamp=timestamp,
            offset=offset,
            limit=limit,
            file_kind="text",
        )
        context.emit(self.name, "result", f"读取文件：{_display_path(path, context.cwd)}")
        return ToolResult(
            tool_name=self.name,
            ok=True,
            summary=f"读取文件：{_display_path(path, context.cwd)}",
            display_name="Read",
            ui_kind="read",
            output=_truncate(numbered),
            metadata={
                "bytes": total_bytes,
                "offset": offset,
                "limit": limit if limit is not None else "all",
                "total_lines": total_lines,
            },
            structured_data={
                "type": "text",
                "file_path": _display_path(path, context.cwd),
                "num_lines": len(selected),
                "start_line": offset,
                "total_lines": total_lines,
                "total_bytes": total_bytes,
            },
            tool_result_content=numbered,
        )
