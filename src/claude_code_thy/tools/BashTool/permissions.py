from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from claude_code_thy.permissions import PermissionRequest
from claude_code_thy.tools.base import PermissionRequiredError, ToolContext

from .path_validation import validate_command_paths
from .read_only_validation import is_read_only_command
from .sed_parser import SedEditInfo, parse_sed_edit_command
from .utils import is_cd_command, is_git_command, iter_shell_commands


@dataclass(slots=True)
class BashAssessment:
    command_segments: tuple[str, ...]
    checked_paths: tuple[str, ...]
    is_read_only: bool
    sed_edit: SedEditInfo | None = None


def enforce_bash_permissions(context: ToolContext, command: str) -> BashAssessment:
    segments = tuple(iter_shell_commands(command))
    _check_compound_command_requirements(command, segments)

    checked_paths: list[str] = []
    for segment in segments:
        context.permission_context.require_command("bash", segment)
        checked_paths.extend(validate_command_paths(segment, context))

    return BashAssessment(
        command_segments=segments,
        checked_paths=tuple(checked_paths),
        is_read_only=is_read_only_command(command),
        sed_edit=parse_sed_edit_command(command),
    )


def _check_compound_command_requirements(command: str, segments: tuple[str, ...]) -> None:
    cd_segments = [segment for segment in segments if is_cd_command(segment)]
    if len(cd_segments) > 1:
        raise PermissionRequiredError(
            PermissionRequest.create(
                tool_name="bash",
                target="command",
                value=command,
                reason="Multiple directory changes in one command require approval.",
                approval_key=f"bash:command:{command}",
            )
        )

    has_cd = any(is_cd_command(segment) for segment in segments)
    has_git = any(is_git_command(segment) for segment in segments)
    if has_cd and has_git:
        raise PermissionRequiredError(
            PermissionRequest.create(
                tool_name="bash",
                target="command",
                value=command,
                reason="Compound commands with both cd and git require approval.",
                approval_key=f"bash:command:{command}",
            )
        )
