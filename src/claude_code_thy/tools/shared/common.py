from __future__ import annotations

import argparse
import base64
import difflib
import fnmatch
import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path
from tempfile import mkdtemp

from claude_code_thy.tools.base import (
    FileReadState,
    PermissionRequiredError,
    PermissionResult,
    ToolContext,
    ToolError,
)

MAX_TOOL_OUTPUT_CHARS = 6000
MAX_RESULT_PREVIEW_CHARS = 2000
MAX_GLOB_RESULTS = 100
MAX_GREP_RESULTS = 250
MAX_GREP_FILES = 1000
DEFAULT_GREP_HEAD_LIMIT = 250
PDF_MAX_PAGES_PER_READ = 20
PDF_INLINE_PAGE_THRESHOLD = 20

IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
VCS_DIRECTORIES = {".git", ".svn", ".hg", ".bzr", ".jj", ".sl"}
BLOCKED_DEVICE_PATHS = {
    "/dev/zero",
    "/dev/random",
    "/dev/urandom",
    "/dev/full",
    "/dev/stdin",
    "/dev/tty",
    "/dev/console",
    "/dev/stdout",
    "/dev/stderr",
    "/dev/fd/0",
    "/dev/fd/1",
    "/dev/fd/2",
}


def _truncate(text: str, limit: int = MAX_TOOL_OUTPUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n... [truncated]"


def _optional_stripped(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _format_bytes(size: int) -> str:
    units = ["B", "KB", "MB", "GB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)}{unit}"
            return f"{value:.1f}{unit}"
        value /= 1024
    return f"{int(size)}B"


def _make_parser(prog: str, description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=prog, description=description, add_help=False)
    parser.add_argument("--help", action="store_true")
    return parser


def _parse_args(parser: argparse.ArgumentParser, raw_args: str) -> argparse.Namespace:
    try:
        tokens = shlex.split(raw_args)
    except ValueError as error:
        raise ToolError(f"参数解析失败：{error}") from error
    try:
        namespace = parser.parse_args(tokens)
    except SystemExit as error:
        raise ToolError("参数格式不正确") from error
    if getattr(namespace, "help", False):
        raise ToolError(parser.format_help().strip())
    return namespace


def _is_blocked_device_path(file_path: str) -> bool:
    if file_path in BLOCKED_DEVICE_PATHS:
        return True
    if file_path.startswith("/proc/") and (
        file_path.endswith("/fd/0") or file_path.endswith("/fd/1") or file_path.endswith("/fd/2")
    ):
        return True
    return False


def _normalize_quotes(text: str) -> str:
    return text.translate(
        str.maketrans(
            {
                "‘": "'",
                "’": "'",
                "“": '"',
                "”": '"',
            }
        )
    )


def _quote_variants(text: str) -> list[str]:
    variants = {text}
    single_variants = ["'", "’"]
    double_variants = ['"', "“", "”"]

    if "'" in text:
        for replacement in single_variants:
            variants.add(text.replace("'", replacement))
    if '"' in text:
        for replacement in double_variants:
            variants.add(text.replace('"', replacement))

    normalized = _normalize_quotes(text)
    if normalized != text:
        variants.add(normalized)
    return [variant for variant in variants if variant]


def _find_actual_string(file_content: str, requested: str) -> str | None:
    if requested in file_content:
        return requested
    for variant in _quote_variants(requested):
        if variant in file_content:
            return variant
    normalized_requested = _normalize_quotes(requested)
    if normalized_requested and normalized_requested in _normalize_quotes(file_content):
        for variant in _quote_variants(normalized_requested):
            if variant in file_content:
                return variant
    return None


def _preserve_quote_style(old_string: str, actual_old_string: str, new_string: str) -> str:
    updated = new_string
    if "'" in old_string and "’" in actual_old_string:
        updated = updated.replace("'", "’")
    if '"' in old_string:
        if "“" in actual_old_string and "”" in actual_old_string:
            updated = updated.replace('"', "“", 1)
            updated = updated.replace('"', "”")
        elif "“" in actual_old_string:
            updated = updated.replace('"', "“")
        elif "”" in actual_old_string:
            updated = updated.replace('"', "”")
    return updated


def _decode_text(raw: bytes) -> str:
    if raw.startswith(b"\xff\xfe"):
        return raw[2:].decode("utf-16le", errors="replace").replace("\r\n", "\n")
    if raw.startswith(b"\xfe\xff"):
        return raw[2:].decode("utf-16be", errors="replace").replace("\r\n", "\n")
    return raw.decode("utf-8", errors="replace").replace("\r\n", "\n")


def _is_binary_bytes(raw: bytes) -> bool:
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff") or raw.startswith(b"\xef\xbb\xbf"):
        return False
    if b"\x00" in raw:
        return True
    if not raw:
        return False
    # Follow the upstream-style heuristic: treat UTF-8/high-bit bytes as normal
    # text bytes, and only flag binary when we see NULs or too many control
    # characters. This avoids misclassifying Chinese UTF-8 text files.
    sample = raw[:8192]
    non_printable = 0
    for byte in sample:
        if byte < 32 and byte not in b"\t\n\r":
            non_printable += 1
    return non_printable / len(sample) > 0.1


def _file_timestamp(path: Path) -> int:
    return int(path.stat().st_mtime_ns // 1_000_000)


def _is_inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _display_path(path: Path, cwd: Path) -> str:
    return str(path.relative_to(cwd)) if _is_inside(path, cwd) else str(path)


def _resolve_path(
    context: ToolContext,
    raw_path: str,
    *,
    allow_missing: bool = False,
    tool_name: str = "*",
) -> Path:
    resolved = _candidate_path(context, raw_path, allow_missing=allow_missing)
    context.permission_context.require_path(tool_name, resolved)
    return resolved


def _candidate_path(
    context: ToolContext,
    raw_path: str,
    *,
    allow_missing: bool = False,
) -> Path:
    normalized = os.path.expanduser(raw_path.strip())
    if not normalized:
        raise ToolError("缺少文件路径")

    candidate = Path(normalized)
    path = candidate if candidate.is_absolute() else context.cwd / candidate

    try:
        resolved = path.resolve(strict=not allow_missing)
    except FileNotFoundError:
        resolved = path.resolve(strict=False)
    return resolved


def _path_permission_result(
    tool_name: str,
    raw_path: str,
    context: ToolContext,
    input_data: dict[str, object],
    *,
    allow_missing: bool = True,
) -> PermissionResult:
    path = _candidate_path(context, raw_path, allow_missing=allow_missing)
    try:
        context.permission_context.require_path(tool_name, path)
    except PermissionRequiredError as error:
        return PermissionResult.ask(error.request, updated_input=input_data)
    except ToolError as error:
        return PermissionResult.deny(str(error), updated_input=input_data)
    return PermissionResult.allow(updated_input=input_data)


def _looks_ignored(relative_path: str, ignore_patterns: tuple[str, ...]) -> bool:
    posix_path = relative_path.replace(os.sep, "/")
    parts = set(Path(posix_path).parts)
    if VCS_DIRECTORIES & parts:
        return True
    for pattern in ignore_patterns:
        if pattern in parts:
            return True
        if fnmatch.fnmatch(posix_path, pattern):
            return True
        if fnmatch.fnmatch(posix_path, f"**/{pattern}"):
            return True
    return False


def _suggest_path(context: ToolContext, raw_path: str) -> str | None:
    target = Path(raw_path)
    basename = target.name.lower()
    stem = target.stem.lower()

    candidates: list[str] = []
    if shutil.which("rg"):
        completed = subprocess.run(
            ["rg", "--files", "--hidden"],
            cwd=context.cwd,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if completed.returncode in (0, 1):
            candidates = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    else:
        for path in context.cwd.rglob("*"):
            if path.is_file():
                candidates.append(str(path.relative_to(context.cwd)))

    exact_name = [candidate for candidate in candidates if Path(candidate).name.lower() == basename]
    if exact_name:
        return exact_name[0]

    same_stem = [candidate for candidate in candidates if Path(candidate).stem.lower() == stem]
    if same_stem:
        return same_stem[0]

    return None


def _missing_path_error(context: ToolContext, raw_path: str, kind: str = "File") -> ToolError:
    suggestion = _suggest_path(context, raw_path)
    message = f"{kind} does not exist. Current working directory: {context.cwd}."
    if suggestion:
        message += f" Did you mean {suggestion}?"
    return ToolError(message)


def _remember_read(
    context: ToolContext,
    path: Path,
    content: str,
    *,
    timestamp: int,
    offset: int | None = None,
    limit: int | None = None,
    file_kind: str = "text",
) -> None:
    context.read_file_state[str(path)] = FileReadState(
        content=content,
        timestamp=timestamp,
        offset=offset,
        limit=limit,
        file_kind=file_kind,
    )


def _ensure_full_read_before_write(context: ToolContext, path: Path, current_content: str) -> FileReadState:
    state = context.read_file_state.get(str(path))
    if state is None or state.is_partial_view:
        raise ToolError("File has not been read yet. Read it first before writing to it.")

    last_write_time = _file_timestamp(path)
    if last_write_time > state.timestamp and current_content != state.content:
        raise ToolError(
            "File has been modified since read, either by the user or by a linter. "
            "Read it again before attempting to write it."
        )
    return state


def _build_diff(file_path: str, old: str, new: str) -> dict[str, object]:
    diff_lines = list(
        difflib.unified_diff(
            old.splitlines(),
            new.splitlines(),
            fromfile=f"a/{file_path}",
            tofile=f"b/{file_path}",
            lineterm="",
        )
    )
    added = sum(1 for line in diff_lines if line.startswith("+") and not line.startswith("+++"))
    removed = sum(1 for line in diff_lines if line.startswith("-") and not line.startswith("---"))
    diff_text = "\n".join(diff_lines) if diff_lines else "(no changes)"
    preview = _truncate(diff_text, MAX_RESULT_PREVIEW_CHARS)
    return {
        "diff_text": diff_text,
        "preview": preview,
        "lines_added": added,
        "lines_removed": removed,
        "structured_patch": _structured_patch_from_diff_lines(diff_lines),
    }


def _structured_patch_from_diff_lines(diff_lines: list[str]) -> list[dict[str, object]]:
    hunks: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    hunk_re = re.compile(r"^@@ -(\d+),?(\d*) \+(\d+),?(\d*) @@")

    for line in diff_lines:
        match = hunk_re.match(line)
        if match:
            if current is not None:
                hunks.append(current)
            current = {
                "oldStart": int(match.group(1)),
                "oldLines": int(match.group(2) or "1"),
                "newStart": int(match.group(3)),
                "newLines": int(match.group(4) or "1"),
                "lines": [],
            }
            continue
        if current is not None:
            current["lines"].append(line)

    if current is not None:
        hunks.append(current)
    return hunks


def _apply_head_limit[T](items: list[T], limit: int | None, offset: int = 0) -> tuple[list[T], int | None]:
    if limit == 0:
        return items[offset:], None

    effective_limit = DEFAULT_GREP_HEAD_LIMIT if limit is None else limit
    sliced = items[offset : offset + effective_limit]
    truncated = len(items) - offset > effective_limit
    return sliced, effective_limit if truncated else None


def _format_limit_info(limit: int | None, offset: int | None) -> str:
    parts: list[str] = []
    if limit is not None:
        parts.append(f"limit: {limit}")
    if offset:
        parts.append(f"offset: {offset}")
    return ", ".join(parts)


def _tool_results_dir(context: ToolContext) -> Path:
    directory = context.cwd / ".claude-code-thy" / "tool-results"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _persist_output(context: ToolContext, prefix: str, content: str) -> Path:
    from uuid import uuid4

    path = _tool_results_dir(context) / f"{prefix}-{uuid4().hex[:8]}.txt"
    path.write_text(content, encoding="utf-8")
    return path


def _parse_page_range(pages: str) -> tuple[int, int]:
    text = pages.strip()
    if not text:
        raise ToolError("pages 不能为空")
    if "-" in text:
        first_text, last_text = text.split("-", 1)
        first = int(first_text)
        last = int(last_text)
    else:
        first = last = int(text)
    if first < 1 or last < first:
        raise ToolError(f"Invalid pages parameter: {pages!r}")
    if last - first + 1 > PDF_MAX_PAGES_PER_READ:
        raise ToolError(
            f'Page range "{pages}" exceeds maximum of {PDF_MAX_PAGES_PER_READ} pages per request.'
        )
    return first, last


def _pdf_page_count(path: Path) -> int | None:
    if not shutil.which("pdfinfo"):
        return None
    completed = subprocess.run(
        ["pdfinfo", str(path)],
        capture_output=True,
        text=True,
        timeout=20,
    )
    if completed.returncode != 0:
        return None
    match = re.search(r"^Pages:\s+(\d+)$", completed.stdout, flags=re.MULTILINE)
    if not match:
        return None
    return int(match.group(1))


def _extract_pdf_page_images(path: Path, first_page: int, last_page: int) -> list[dict[str, object]]:
    if not shutil.which("pdftoppm"):
        raise ToolError(
            "读取 PDF pages 需要 `pdftoppm`，请先安装 poppler，例如 macOS 下执行 `brew install poppler`。"
        )

    output_dir = Path(mkdtemp(prefix="claude-code-thy-pdf-"))
    prefix = output_dir / "page"
    completed = subprocess.run(
        [
            "pdftoppm",
            "-jpeg",
            "-f",
            str(first_page),
            "-l",
            str(last_page),
            str(path),
            str(prefix),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if completed.returncode != 0:
        raise ToolError(completed.stderr.strip() or "PDF page extraction failed")

    blocks: list[dict[str, object]] = []
    for image_path in sorted(output_dir.glob("page-*.jpg")):
        blocks.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": base64.b64encode(image_path.read_bytes()).decode("ascii"),
                },
            }
        )
    return blocks
