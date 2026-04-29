from __future__ import annotations

import os
import shutil
from pathlib import Path


def _is_windows() -> bool:
    """Return whether the current platform uses Windows process semantics."""
    return os.name == "nt"


def _configured_bash_path() -> str | None:
    """Allow callers to override bash discovery with an explicit executable path."""
    configured = os.environ.get("CLAUDE_CODE_THY_BASH_PATH", "").strip().strip('"')
    if not configured:
        return None

    expanded = os.path.expandvars(os.path.expanduser(configured))
    candidate = Path(expanded)
    if candidate.exists():
        return str(candidate.resolve())

    found = shutil.which(expanded)
    if found:
        return found
    return expanded


def _windows_bash_candidates() -> tuple[Path, ...]:
    """List common Git Bash installation paths used on Windows machines."""
    raw_candidates = (
        r"%ProgramW6432%\Git\bin\bash.exe",
        r"%ProgramW6432%\Git\usr\bin\bash.exe",
        r"%ProgramFiles%\Git\bin\bash.exe",
        r"%ProgramFiles%\Git\usr\bin\bash.exe",
        r"%ProgramFiles(x86)%\Git\bin\bash.exe",
        r"%ProgramFiles(x86)%\Git\usr\bin\bash.exe",
        r"%LocalAppData%\Programs\Git\bin\bash.exe",
        r"%LocalAppData%\Programs\Git\usr\bin\bash.exe",
    )
    candidates: list[Path] = []
    for raw in raw_candidates:
        expanded = os.path.expandvars(raw)
        if "%" in expanded:
            continue
        candidates.append(Path(expanded))
    return tuple(candidates)


def resolve_bash_executable() -> str:
    """Resolve the bash executable while keeping Git Bash as the Windows default."""
    configured = _configured_bash_path()
    if configured:
        return configured

    if not _is_windows():
        if Path("/bin/bash").exists():
            return "/bin/bash"
        found = shutil.which("bash")
        return found or "/bin/bash"

    found = shutil.which("bash")
    if found:
        return found
    for candidate in _windows_bash_candidates():
        if candidate.exists():
            return str(candidate.resolve())
    return "bash"


def build_bash_command(command: str) -> list[str]:
    """Wrap a shell command in the resolved bash launcher."""
    return [resolve_bash_executable(), "-lc", command]
