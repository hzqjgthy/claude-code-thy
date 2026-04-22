from __future__ import annotations

import re
from dataclasses import dataclass

from .utils import shell_split, strip_leading_env_assignments


@dataclass(slots=True)
class SedEditInfo:
    """表示 `SedEditInfo`。"""
    file_path: str
    pattern: str
    replacement: str
    flags: str
    extended_regex: bool = False


def parse_sed_edit_command(command: str) -> SedEditInfo | None:
    """解析 `sed_edit_command`。"""
    tokens = shell_split(command)
    if not tokens:
        return None
    tokens = strip_leading_env_assignments(tokens)
    if not tokens or tokens[0] != "sed":
        return None

    has_in_place = False
    extended_regex = False
    expression: str | None = None
    file_path: str | None = None
    index = 1

    while index < len(tokens):
        token = tokens[index]
        if token in {"-i", "--in-place"} or token.startswith("-i"):
            has_in_place = True
            if token in {"-i", "--in-place"} and index + 1 < len(tokens):
                suffix = tokens[index + 1]
                if suffix == "" or (suffix and suffix.startswith(".")):
                    index += 2
                    continue
            index += 1
            continue
        if token in {"-E", "-r", "--regexp-extended"}:
            extended_regex = True
            index += 1
            continue
        if token in {"-e", "--expression"}:
            if index + 1 >= len(tokens):
                return None
            expression = tokens[index + 1]
            index += 2
            continue
        if token.startswith("--expression="):
            expression = token.split("=", 1)[1]
            index += 1
            continue
        if token.startswith("-"):
            index += 1
            continue
        if expression is None:
            expression = token
        elif file_path is None:
            file_path = token
        else:
            return None
        index += 1

    if not has_in_place or not expression or not file_path:
        return None

    match = re.match(r"^s/(.*)$", expression)
    if not match:
        return None
    rest = match.group(1)
    pattern = ""
    replacement = ""
    flags = ""
    state = "pattern"
    index = 0
    while index < len(rest):
        char = rest[index]
        if char == "\\" and index + 1 < len(rest):
            nxt = rest[index + 1]
            if state == "pattern":
                pattern += char + nxt
            elif state == "replacement":
                replacement += char + nxt
            else:
                flags += char + nxt
            index += 2
            continue
        if char == "/":
            if state == "pattern":
                state = "replacement"
            elif state == "replacement":
                state = "flags"
            else:
                return None
            index += 1
            continue
        if state == "pattern":
            pattern += char
        elif state == "replacement":
            replacement += char
        else:
            flags += char
        index += 1

    if state != "flags" or not re.match(r"^[gpimIM1-9]*$", flags):
        return None

    return SedEditInfo(
        file_path=file_path,
        pattern=pattern,
        replacement=replacement,
        flags=flags,
        extended_regex=extended_regex,
    )


def apply_sed_substitution(content: str, info: SedEditInfo) -> str:
    """处理 `apply_sed_substitution`。"""
    pattern = info.pattern
    if not info.extended_regex:
        pattern = (
            pattern.replace(r"\+", "\x00PLUS\x00")
            .replace(r"\?", "\x00QUESTION\x00")
            .replace(r"\|", "\x00PIPE\x00")
            .replace(r"\(", "\x00LPAREN\x00")
            .replace(r"\)", "\x00RPAREN\x00")
        )
        pattern = (
            pattern.replace("+", r"\+")
            .replace("?", r"\?")
            .replace("|", r"\|")
            .replace("(", r"\(")
            .replace(")", r"\)")
            .replace("\x00PLUS\x00", "+")
            .replace("\x00QUESTION\x00", "?")
            .replace("\x00PIPE\x00", "|")
            .replace("\x00LPAREN\x00", "(")
            .replace("\x00RPAREN\x00", ")")
        )

    replacement = _convert_sed_replacement(info.replacement)
    regex_flags = 0
    if "i" in info.flags or "I" in info.flags:
        regex_flags |= re.IGNORECASE
    regex = re.compile(pattern, regex_flags)
    count = 0 if "g" in info.flags else 1
    return regex.sub(replacement, content, count=count)


def _convert_sed_replacement(replacement: str) -> str:
    """处理 `convert_sed_replacement`。"""
    converted = []
    index = 0
    while index < len(replacement):
        char = replacement[index]
        if char == "\\" and index + 1 < len(replacement):
            converted.append(replacement[index : index + 2])
            index += 2
            continue
        if char == "&":
            converted.append(r"\g<0>")
            index += 1
            continue
        converted.append(char)
        index += 1
    return "".join(converted)
