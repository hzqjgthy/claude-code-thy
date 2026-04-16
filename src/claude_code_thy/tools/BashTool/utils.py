from __future__ import annotations

import os
import re
import shlex
from pathlib import Path


COMPOUND_SPLIT_RE = re.compile(r"(\|\||&&|[|;]|>>|>|>&)")
REDIRECT_OPERATORS = {">", ">>", ">&"}
COMMAND_OPERATORS = {"||", "&&", "|", ";"}


def split_shell_segments(command: str) -> list[str]:
    return [segment for segment in COMPOUND_SPLIT_RE.split(command) if segment]


def iter_shell_commands(command: str) -> list[str]:
    commands: list[str] = []
    segments = split_shell_segments(command)
    skip_redirect_target = False
    for segment in segments:
        part = segment.strip()
        if not part:
            continue
        if skip_redirect_target:
            skip_redirect_target = False
            continue
        if part in REDIRECT_OPERATORS:
            skip_redirect_target = True
            continue
        if part in COMMAND_OPERATORS:
            continue
        commands.append(part)
    return commands


def extract_redirection_targets(command: str) -> list[str]:
    targets: list[str] = []
    segments = split_shell_segments(command)
    for index, segment in enumerate(segments):
        if segment.strip() not in REDIRECT_OPERATORS:
            continue
        if index + 1 >= len(segments):
            continue
        target = segments[index + 1].strip()
        if target:
            targets.append(target)
    return targets


def shell_split(command: str) -> list[str] | None:
    try:
        return shlex.split(command)
    except ValueError:
        return None


def strip_leading_env_assignments(tokens: list[str]) -> list[str]:
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if "=" not in token or token.startswith("-"):
            break
        key, _, _value = token.partition("=")
        if not key or not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
            break
        index += 1
    return tokens[index:]


def base_command(command: str) -> str:
    tokens = shell_split(command)
    if not tokens:
        return ""
    stripped = strip_leading_env_assignments(tokens)
    return stripped[0] if stripped else ""


def second_token(command: str) -> str:
    tokens = shell_split(command)
    if not tokens:
        return ""
    stripped = strip_leading_env_assignments(tokens)
    return stripped[1] if len(stripped) > 1 else ""


def is_cd_command(command: str) -> bool:
    return base_command(command) == "cd"


def is_git_command(command: str) -> bool:
    return base_command(command) == "git"


def resolve_shell_path(raw_path: str, *, cwd: Path) -> Path:
    expanded = Path(os.path.expanduser(raw_path))
    return expanded if expanded.is_absolute() else cwd / expanded
