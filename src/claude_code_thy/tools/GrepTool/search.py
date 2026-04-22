from __future__ import annotations

import fnmatch
import re
import subprocess
from pathlib import Path

from claude_code_thy.tools.base import ToolContext, ToolError
from claude_code_thy.tools.shared.common import (
    MAX_GREP_FILES,
    VCS_DIRECTORIES,
    _decode_text,
    _display_path,
    _is_binary_bytes,
    _looks_ignored,
)


def grep_with_rg(
    context: ToolContext,
    *,
    pattern: str,
    search_path: Path,
    glob: str | None,
    output_mode: str,
    before: int | None,
    after: int | None,
    context_lines: int | None,
    line_numbers: bool,
    ignore_case: bool,
    file_type: str | None,
    multiline: bool,
) -> list[str] | None:
    """处理 `grep_with_rg`。"""
    import shutil

    if not shutil.which("rg"):
        return None

    args = ["rg", "--hidden", "--max-columns", "500"]
    for directory in sorted(VCS_DIRECTORIES):
        args.extend(["--glob", f"!{directory}"])
    for ignore_pattern in context.permission_context.read_ignore_patterns:
        args.extend(["--glob", f"!**/{ignore_pattern}"])

    if multiline:
        args.extend(["-U", "--multiline-dotall"])
    if ignore_case:
        args.append("-i")
    if output_mode == "files_with_matches":
        args.append("-l")
    elif output_mode == "count":
        args.append("-c")
    elif line_numbers:
        args.append("-n")

    if output_mode == "content":
        if context_lines is not None:
            args.extend(["-C", str(context_lines)])
        else:
            if before is not None:
                args.extend(["-B", str(before)])
            if after is not None:
                args.extend(["-A", str(after)])

    if pattern.startswith("-"):
        args.extend(["-e", pattern])
    else:
        args.append(pattern)

    if file_type:
        args.extend(["--type", file_type])
    if glob:
        for token in split_glob_patterns(glob):
            args.extend(["--glob", token])

    args.append(str(search_path))
    completed = subprocess.run(args, capture_output=True, text=True, timeout=30)
    if completed.returncode not in (0, 1):
        stderr = completed.stderr.strip()
        raise ToolError(stderr or "grep 执行失败")

    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if output_mode == "content":
        return [relativize_grep_content_line(context, line) for line in lines]
    if output_mode == "count":
        return [relativize_count_line(context, line) for line in lines]
    return [relativize_plain_path(context, line) for line in lines]


def grep_with_python(
    context: ToolContext,
    *,
    pattern: str,
    search_path: Path,
    glob: str | None,
    output_mode: str,
    ignore_case: bool,
) -> list[str]:
    """处理 `grep_with_python`。"""
    flags = re.IGNORECASE if ignore_case else 0
    try:
        regex = re.compile(pattern, flags)
    except re.error:
        regex = re.compile(re.escape(pattern), flags)

    content_matches: list[str] = []
    file_hits: dict[str, int] = {}
    candidate_iter = [search_path] if search_path.is_file() else search_path.rglob("*")
    scanned = 0
    for file_candidate in candidate_iter:
        if scanned >= MAX_GREP_FILES:
            break
        if not file_candidate.is_file():
            continue
        relative = _display_path(file_candidate.resolve(), context.cwd)
        if _looks_ignored(relative, context.permission_context.read_ignore_patterns):
            continue
        if glob and not (
            fnmatch.fnmatch(relative, glob) or fnmatch.fnmatch(file_candidate.name, glob)
        ):
            continue
        raw = file_candidate.read_bytes()
        if _is_binary_bytes(raw):
            continue
        scanned += 1
        text = _decode_text(raw)
        for line_number, line in enumerate(text.splitlines(), start=1):
            if regex.search(line):
                file_hits.setdefault(relative, 0)
                file_hits[relative] += 1
                if output_mode == "content":
                    content_matches.append(f"{relative}:{line_number}:{line}")
    if output_mode == "content":
        return content_matches
    if output_mode == "count":
        return [f"{path}: {count}" for path, count in file_hits.items()]
    return list(file_hits.keys())


def split_glob_patterns(raw_patterns: str) -> list[str]:
    """处理 `split_glob_patterns`。"""
    patterns: list[str] = []
    for raw_pattern in raw_patterns.split():
        if "{" in raw_pattern and "}" in raw_pattern:
            patterns.append(raw_pattern)
            continue
        patterns.extend(part for part in raw_pattern.split(",") if part)
    return patterns


def relativize_plain_path(context: ToolContext, line: str) -> str:
    """处理 `relativize_plain_path`。"""
    candidate = Path(line)
    if candidate.is_absolute():
        return _display_path(candidate, context.cwd)
    return _display_path((context.cwd / candidate).resolve(), context.cwd)


def relativize_count_line(context: ToolContext, line: str) -> str:
    """处理 `relativize_count_line`。"""
    file_part, _, count_text = line.rpartition(":")
    file_path = relativize_plain_path(context, file_part)
    return f"{file_path}: {count_text.strip()}"


def relativize_grep_content_line(context: ToolContext, line: str) -> str:
    """处理 `relativize_grep_content_line`。"""
    colon_index = line.find(":")
    if colon_index <= 0:
        return line
    file_path = line[:colon_index]
    remainder = line[colon_index:]
    return relativize_plain_path(context, file_path) + remainder
