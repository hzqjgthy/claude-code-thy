from __future__ import annotations

import subprocess
from pathlib import Path

from claude_code_thy.tools.base import ToolContext
from claude_code_thy.tools.shared.common import (
    MAX_GLOB_RESULTS,
    VCS_DIRECTORIES,
    _display_path,
    _looks_ignored,
)


def glob_with_rg(
    context: ToolContext,
    pattern: str,
    search_root: Path,
) -> tuple[list[str], bool] | tuple[None, bool]:
    """处理 `glob_with_rg`。"""
    import shutil

    if not shutil.which("rg"):
        return None, False
    args = ["rg", "--files", "--hidden"]
    for directory in sorted(VCS_DIRECTORIES):
        args.extend(["--glob", f"!{directory}"])
    for ignore_pattern in context.permission_context.read_ignore_patterns:
        args.extend(["--glob", f"!**/{ignore_pattern}"])
    args.extend(["-g", pattern])
    completed = subprocess.run(
        args,
        cwd=search_root,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if completed.returncode not in (0, 1):
        return None, False
    matches = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    normalized = [
        _display_path((search_root / match).resolve(), context.cwd)
        for match in matches
        if not _looks_ignored(match, context.permission_context.read_ignore_patterns)
    ]
    truncated = len(normalized) > MAX_GLOB_RESULTS
    return normalized[:MAX_GLOB_RESULTS], truncated


def glob_with_python(
    context: ToolContext,
    pattern: str,
    search_root: Path,
) -> tuple[list[str], bool]:
    """处理 `glob_with_python`。"""
    results: list[str] = []
    for candidate in search_root.glob(pattern):
        if not candidate.is_file():
            continue
        relative = str(candidate.resolve().relative_to(context.cwd))
        if _looks_ignored(relative, context.permission_context.read_ignore_patterns):
            continue
        results.append(relative)
    truncated = len(results) > MAX_GLOB_RESULTS
    return results[:MAX_GLOB_RESULTS], truncated
