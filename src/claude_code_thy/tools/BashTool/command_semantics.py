from __future__ import annotations

from .utils import base_command, iter_shell_commands


def interpret_command_result(
    command: str,
    exit_code: int,
    stdout: str,
    stderr: str,
) -> dict[str, object]:
    """处理 `interpret_command_result`。"""
    _ = (stdout, stderr)
    segments = iter_shell_commands(command)
    inspected = segments[-1] if segments else command
    name = base_command(inspected)

    if name in {"grep", "rg"}:
        return {
            "is_error": exit_code >= 2,
            "message": "No matches found" if exit_code == 1 else None,
        }
    if name == "find":
        return {
            "is_error": exit_code >= 2,
            "message": "Some directories were inaccessible" if exit_code == 1 else None,
        }
    if name == "diff":
        return {
            "is_error": exit_code >= 2,
            "message": "Files differ" if exit_code == 1 else None,
        }
    if name in {"test", "["}:
        return {
            "is_error": exit_code >= 2,
            "message": "Condition is false" if exit_code == 1 else None,
        }

    return {
        "is_error": exit_code != 0,
        "message": f"Command failed with exit code {exit_code}" if exit_code != 0 else None,
    }
