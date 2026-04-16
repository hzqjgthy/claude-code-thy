from __future__ import annotations

from pathlib import Path

from claude_code_thy.tools.base import ToolContext, ToolError

from .sed_parser import parse_sed_edit_command
from .utils import (
    extract_redirection_targets,
    resolve_shell_path,
    shell_split,
    strip_leading_env_assignments,
)


GENERIC_PATH_COMMANDS = {
    "ls",
    "cat",
    "head",
    "tail",
    "sort",
    "uniq",
    "wc",
    "file",
    "stat",
    "diff",
    "awk",
    "strings",
    "hexdump",
    "od",
    "base64",
    "nl",
    "touch",
    "mkdir",
    "rm",
    "rmdir",
}

DOUBLE_PATH_COMMANDS = {"cp", "mv"}


def validate_command_paths(command: str, context: ToolContext) -> list[str]:
    checked: list[str] = []
    for target in extract_command_paths(command):
        if _should_skip_path(target):
            continue
        resolved = resolve_shell_path(target, cwd=context.cwd).resolve(strict=False)
        context.permission_context.require_path("bash", resolved)
        checked.append(str(resolved))

    for target in extract_redirection_targets(command):
        if _should_skip_path(target):
            continue
        resolved = resolve_shell_path(target, cwd=context.cwd).resolve(strict=False)
        context.permission_context.require_path("bash", resolved)
        checked.append(str(resolved))

    return checked


def extract_command_paths(command: str) -> list[str]:
    sed_info = parse_sed_edit_command(command)
    if sed_info is not None:
        return [sed_info.file_path]

    tokens = shell_split(command)
    if not tokens:
        return []
    tokens = strip_leading_env_assignments(tokens)
    if not tokens:
        return []

    name = tokens[0]
    args = tokens[1:]
    if name == "cd":
        return [args[0]] if args else ["~"]
    if name in GENERIC_PATH_COMMANDS:
        return _filter_out_flags(args)
    if name in DOUBLE_PATH_COMMANDS:
        return _filter_out_flags(args)
    if name == "find":
        return _find_paths(args)
    if name in {"grep", "rg"}:
        return _pattern_command_paths(args)
    if name == "sed":
        return _sed_paths(args)
    if name == "git":
        return _git_paths(args)
    return []


def _find_paths(args: list[str]) -> list[str]:
    paths: list[str] = []
    after_double_dash = False
    for arg in args:
        if after_double_dash:
            paths.append(arg)
            continue
        if arg == "--":
            after_double_dash = True
            continue
        if arg.startswith("-"):
            break
        paths.append(arg)
    return paths or ["."]


def _pattern_command_paths(args: list[str]) -> list[str]:
    paths: list[str] = []
    pattern_found = False
    after_double_dash = False
    flags_with_args = {
        "-e",
        "-f",
        "-g",
        "--glob",
        "--type",
        "-t",
        "-A",
        "-B",
        "-C",
        "--max-count",
        "-m",
    }
    index = 0
    while index < len(args):
        arg = args[index]
        if after_double_dash:
            if pattern_found:
                paths.append(arg)
            else:
                pattern_found = True
            index += 1
            continue
        if arg == "--":
            after_double_dash = True
            index += 1
            continue
        if arg.startswith("-"):
            if arg in flags_with_args and index + 1 < len(args):
                index += 2
            else:
                index += 1
            continue
        if not pattern_found:
            pattern_found = True
        else:
            paths.append(arg)
        index += 1
    return paths


def _sed_paths(args: list[str]) -> list[str]:
    expressions_seen = False
    paths: list[str] = []
    index = 0
    while index < len(args):
        arg = args[index]
        if arg in {"-i", "--in-place"} and index + 1 < len(args):
            suffix = args[index + 1]
            if suffix == "" or (suffix and suffix.startswith(".")):
                index += 2
                continue
        if arg in {"-e", "--expression"} and index + 1 < len(args):
            expressions_seen = True
            index += 2
            continue
        if arg.startswith("--expression="):
            expressions_seen = True
            index += 1
            continue
        if arg.startswith("-"):
            index += 1
            continue
        if not expressions_seen:
            expressions_seen = True
            index += 1
            continue
        paths.append(arg)
        index += 1
    return paths


def _git_paths(args: list[str]) -> list[str]:
    if not args:
        return []
    if "--" in args:
        marker = args.index("--")
        return args[marker + 1 :]
    subcommand = args[0]
    rest = args[1:]
    if subcommand in {"add", "rm", "restore", "checkout", "mv"}:
        return _filter_out_flags(rest)
    if subcommand in {"status", "diff"}:
        return _filter_out_flags(rest)
    return []


def _filter_out_flags(args: list[str]) -> list[str]:
    paths: list[str] = []
    after_double_dash = False
    for arg in args:
        if after_double_dash:
            paths.append(arg)
            continue
        if arg == "--":
            after_double_dash = True
            continue
        if arg.startswith("-"):
            continue
        paths.append(arg)
    return paths


def _should_skip_path(path: str) -> bool:
    return (
        not path
        or path in {"-", "/dev/stdin", "/dev/stdout", "/dev/stderr"}
        or "$" in path
        or "*" in path
        or "?" in path
    )
