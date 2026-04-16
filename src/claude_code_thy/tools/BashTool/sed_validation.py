from __future__ import annotations

from .utils import shell_split, strip_leading_env_assignments


def extract_sed_expressions(command: str) -> list[str]:
    tokens = shell_split(command)
    if not tokens:
        return []
    tokens = strip_leading_env_assignments(tokens)
    if not tokens or tokens[0] != "sed":
        return []

    expressions: list[str] = []
    index = 1
    while index < len(tokens):
        token = tokens[index]
        if token in {"-e", "--expression"}:
            if index + 1 < len(tokens):
                expressions.append(tokens[index + 1])
                index += 2
                continue
            return []
        if token.startswith("--expression="):
            expressions.append(token.split("=", 1)[1])
            index += 1
            continue
        if token.startswith("-"):
            index += 1
            continue
        if not expressions:
            expressions.append(token)
        index += 1
    return expressions


def is_print_command(command: str) -> bool:
    return bool(command) and bool(__import__("re").match(r"^(?:\d+|\d+,\d+)?p$", command))


def is_line_printing_command(command: str, expressions: list[str]) -> bool:
    tokens = shell_split(command)
    if not tokens:
        return False
    tokens = strip_leading_env_assignments(tokens)
    if not tokens or tokens[0] != "sed":
        return False
    if not expressions:
        return False

    flags = [token for token in tokens[1:] if token.startswith("-") and token != "--"]
    has_n = any(token in {"-n", "--quiet", "--silent"} or ("n" in token[1:] and not token.startswith("--")) for token in flags)
    if not has_n:
        return False

    for expression in expressions:
        for part in expression.split(";"):
            if not is_print_command(part.strip()):
                return False
    return True


def is_substitution_command(
    command: str,
    expressions: list[str],
    *,
    allow_file_writes: bool = False,
) -> bool:
    tokens = shell_split(command)
    if not tokens:
        return False
    tokens = strip_leading_env_assignments(tokens)
    if not tokens or tokens[0] != "sed":
        return False
    if len(expressions) != 1:
        return False

    flags = [token for token in tokens[1:] if token.startswith("-") and token != "--"]
    allowed_flags = {"-E", "-r", "--regexp-extended", "--posix"}
    if allow_file_writes:
        allowed_flags.update({"-i", "--in-place"})
        allowed_flags.update({token for token in flags if token.startswith("-i")})

    for flag in flags:
        if flag.startswith("-i") and allow_file_writes:
            continue
        if flag not in allowed_flags:
            return False

    expression = expressions[0].strip()
    if not expression.startswith("s/"):
        return False
    body = expression[2:]
    delimiter_count = 0
    index = 0
    last_delimiter = -1
    while index < len(body):
        char = body[index]
        if char == "\\":
            index += 2
            continue
        if char == "/":
            delimiter_count += 1
            last_delimiter = index
        index += 1
    if delimiter_count != 2:
        return False
    flags_text = body[last_delimiter + 1 :]
    return bool(__import__("re").match(r"^[gpimIM1-9]*$", flags_text))


def sed_command_is_allowed_by_allowlist(
    command: str,
    *,
    allow_file_writes: bool = False,
) -> bool:
    expressions = extract_sed_expressions(command)
    return is_line_printing_command(command, expressions) or is_substitution_command(
        command,
        expressions,
        allow_file_writes=allow_file_writes,
    )
