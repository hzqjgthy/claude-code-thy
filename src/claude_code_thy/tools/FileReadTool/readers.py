from __future__ import annotations

import base64
import json
import mimetypes
from pathlib import Path

from claude_code_thy.tools.base import ToolContext, ToolError, ToolResult
from claude_code_thy.tools.shared.text_files import read_text_snapshot
from claude_code_thy.tools.shared.common import (
    _decode_text,
    _display_path,
    _extract_pdf_page_images,
    _file_timestamp,
    _format_bytes,
    _parse_page_range,
    _pdf_page_count,
    _remember_read,
)


def read_image(*, tool_name: str, context: ToolContext, path: Path) -> ToolResult:
    raw = path.read_bytes()
    mime_type = mimetypes.guess_type(path.name)[0] or "image/png"
    base64_data = base64.b64encode(raw).decode("ascii")
    return ToolResult(
        tool_name=tool_name,
        ok=True,
        summary=f"读取图片：{_display_path(path, context.cwd)}",
        display_name="Read",
        ui_kind="read",
        output=f"Read image ({_format_bytes(len(raw))})",
        metadata={"original_size": len(raw), "media_type": mime_type},
        structured_data={
            "type": "image",
            "file_path": _display_path(path, context.cwd),
            "original_size": len(raw),
            "media_type": mime_type,
        },
        tool_result_content=[
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": mime_type,
                    "data": base64_data,
                },
            }
        ],
    )


def read_notebook(*, tool_name: str, context: ToolContext, path: Path) -> ToolResult:
    raw = path.read_bytes()
    content = _decode_text(raw)
    try:
        notebook = json.loads(content)
    except json.JSONDecodeError as error:
        raise ToolError(f"Notebook 解析失败：{error}") from error

    cells = notebook.get("cells", [])
    cells_json = json.dumps(cells, ensure_ascii=False)
    _remember_read(
        context,
        path,
        cells_json,
        timestamp=_file_timestamp(path),
        file_kind="notebook",
    )
    return ToolResult(
        tool_name=tool_name,
        ok=True,
        summary=f"读取 Notebook：{_display_path(path, context.cwd)}",
        display_name="Read",
        ui_kind="read",
        output=f"Read {len(cells)} cells",
        metadata={"cell_count": len(cells), "bytes": len(raw)},
        structured_data={
            "type": "notebook",
            "file_path": _display_path(path, context.cwd),
            "cell_count": len(cells),
        },
        tool_result_content=cells_json,
    )


def read_pdf(
    *,
    tool_name: str,
    context: ToolContext,
    path: Path,
    pages: str | None,
    inline_page_threshold: int,
) -> ToolResult:
    page_count = _pdf_page_count(path)
    raw = path.read_bytes()
    if pages:
        first_page, last_page = _parse_page_range(pages)
        image_blocks = _extract_pdf_page_images(path, first_page, last_page)
        return ToolResult(
            tool_name=tool_name,
            ok=True,
            summary=f"读取 PDF 页面：{_display_path(path, context.cwd)} · pages {pages}",
            display_name="Read",
            ui_kind="read",
            output=f"Read {len(image_blocks)} pages ({_format_bytes(len(raw))})",
            metadata={"page_count": len(image_blocks), "original_size": len(raw), "pages": pages},
            structured_data={
                "type": "parts",
                "file_path": _display_path(path, context.cwd),
                "count": len(image_blocks),
                "original_size": len(raw),
                "pages": pages,
            },
            tool_result_content=image_blocks,
        )

    if page_count is not None and page_count > inline_page_threshold:
        raise ToolError(
            f"This PDF has {page_count} pages, which is too many to read at once. "
            'Use the pages parameter to read specific page ranges (e.g., pages: "1-5").'
        )

    return ToolResult(
        tool_name=tool_name,
        ok=True,
        summary=f"读取 PDF：{_display_path(path, context.cwd)}",
        display_name="Read",
        ui_kind="read",
        output=f"Read PDF ({_format_bytes(len(raw))})",
        metadata={"original_size": len(raw), **({"page_count": page_count} if page_count is not None else {})},
        structured_data={
            "type": "pdf",
            "file_path": _display_path(path, context.cwd),
            "original_size": len(raw),
            "page_count": page_count,
        },
        tool_result_content=[
            {
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": "application/pdf",
                    "data": base64.b64encode(raw).decode("ascii"),
                },
            }
        ],
    )


def read_text_window(
    path: Path,
    *,
    offset: int,
    limit: int | None,
) -> dict[str, object]:
    with path.open("rb") as handle:
        sample = handle.read(8192)
    if sample.startswith(b"\xff\xfe") or sample.startswith(b"\xfe\xff"):
        encoding = "utf-16"
    else:
        encoding = "utf-8"

    selected: list[str] = []
    total_lines = 0
    with path.open("r", encoding=encoding, errors="replace", newline=None) as handle:
        for line_number, line in enumerate(handle, start=1):
            total_lines = line_number
            if line_number < offset:
                continue
            if limit is not None and len(selected) >= limit:
                continue
            selected.append(line.rstrip("\r\n"))

    return {
        "selected_lines": selected,
        "total_lines": total_lines,
        "content": "\n".join(selected),
    }


def read_full_text(path: Path) -> dict[str, object]:
    snapshot = read_text_snapshot(path)
    return {
        "content": snapshot.content,
        "encoding": snapshot.encoding,
        "newline": snapshot.newline,
        "had_bom": snapshot.had_bom,
    }
