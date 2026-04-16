from __future__ import annotations

from .constants import (
    BASH_LIST_COMMANDS,
    BASH_READ_COMMANDS,
    BASH_SEARCH_COMMANDS,
    BASH_SEMANTIC_NEUTRAL_COMMANDS,
    BASH_SILENT_COMMANDS,
)
from .utils import split_shell_segments


def classify_shell_command(command: str) -> dict[str, bool]:
    segments = split_shell_segments(command)
    if not segments:
        return {"is_search": False, "is_read": False, "is_list": False}

    has_search = False
    has_read = False
    has_list = False
    has_non_neutral = False
    skip_redirect_target = False

    for segment in segments:
        part = segment.strip()
        if not part:
            continue
        if skip_redirect_target:
            skip_redirect_target = False
            continue
        if part in {">", ">>", ">&"}:
            skip_redirect_target = True
            continue
        if part in {"||", "&&", "|", ";"}:
            continue

        base = part.split()[0]
        if base in BASH_SEMANTIC_NEUTRAL_COMMANDS:
            continue

        has_non_neutral = True
        is_search = base in BASH_SEARCH_COMMANDS
        is_read = base in BASH_READ_COMMANDS
        is_list = base in BASH_LIST_COMMANDS
        if not any((is_search, is_read, is_list)):
            return {"is_search": False, "is_read": False, "is_list": False}
        has_search = has_search or is_search
        has_read = has_read or is_read
        has_list = has_list or is_list

    if not has_non_neutral:
        return {"is_search": False, "is_read": False, "is_list": False}
    return {"is_search": has_search, "is_read": has_read, "is_list": has_list}


def is_silent_shell_command(command: str) -> bool:
    segments = split_shell_segments(command)
    if not segments:
        return False

    has_non_fallback = False
    previous_operator: str | None = None
    skip_redirect_target = False

    for segment in segments:
        part = segment.strip()
        if not part:
            continue
        if skip_redirect_target:
            skip_redirect_target = False
            continue
        if part in {">", ">>", ">&"}:
            skip_redirect_target = True
            continue
        if part in {"||", "&&", "|", ";"}:
            previous_operator = part
            continue

        base = part.split()[0]
        if previous_operator == "||" and base in BASH_SEMANTIC_NEUTRAL_COMMANDS:
            continue
        has_non_fallback = True
        if base not in BASH_SILENT_COMMANDS:
            return False

    return has_non_fallback
