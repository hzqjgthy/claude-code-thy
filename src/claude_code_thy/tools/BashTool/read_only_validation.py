from __future__ import annotations

from .sed_validation import sed_command_is_allowed_by_allowlist
from .utils import base_command, extract_redirection_targets, iter_shell_commands, second_token


READ_ONLY_COMMANDS = {
    "cat",
    "head",
    "tail",
    "less",
    "more",
    "wc",
    "stat",
    "file",
    "strings",
    "jq",
    "awk",
    "cut",
    "sort",
    "uniq",
    "tr",
    "grep",
    "rg",
    "find",
    "ls",
    "tree",
    "du",
    "diff",
    "hexdump",
    "od",
    "base64",
    "nl",
    "md5sum",
    "sha1sum",
    "sha256sum",
}

GIT_READ_ONLY_SUBCOMMANDS = {
    "status",
    "diff",
    "show",
    "log",
    "grep",
    "ls-files",
    "branch",
    "rev-parse",
    "describe",
}


def is_read_only_command(command: str) -> bool:
    if extract_redirection_targets(command):
        return False

    segments = iter_shell_commands(command)
    if not segments:
        return False

    for segment in segments:
        name = base_command(segment)
        if not name:
            return False
        if name in READ_ONLY_COMMANDS:
            continue
        if name == "git" and second_token(segment) in GIT_READ_ONLY_SUBCOMMANDS:
            continue
        if name == "sed" and sed_command_is_allowed_by_allowlist(segment):
            continue
        return False

    return True
