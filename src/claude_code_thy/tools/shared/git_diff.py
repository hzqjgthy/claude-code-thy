from __future__ import annotations

import subprocess
from pathlib import Path


def single_file_git_diff(path: Path, *, status: str = "modified") -> dict[str, object] | None:
    """处理 `single_file_git_diff`。"""
    repo_root = _git_root(path.parent)
    if repo_root is None:
        return None

    relative = str(path.resolve().relative_to(repo_root))
    completed = subprocess.run(
        ["git", "-C", str(repo_root), "diff", "--no-ext-diff", "--", relative],
        capture_output=True,
        text=True,
        timeout=20,
    )
    if completed.returncode not in (0, 1):
        return None
    patch = completed.stdout
    if not patch.strip():
        return None

    additions = sum(1 for line in patch.splitlines() if line.startswith("+") and not line.startswith("+++"))
    deletions = sum(1 for line in patch.splitlines() if line.startswith("-") and not line.startswith("---"))
    return {
        "filename": relative,
        "status": status,
        "additions": additions,
        "deletions": deletions,
        "changes": additions + deletions,
        "patch": patch,
        "repository": None,
    }


def _git_root(cwd: Path) -> Path | None:
    """处理 `git_root`。"""
    completed = subprocess.run(
        ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if completed.returncode != 0:
        return None
    root = completed.stdout.strip()
    return Path(root).resolve() if root else None
