from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from .utils import iter_shell_commands


@dataclass(slots=True)
class BashStructureAnalysis:
    backend: str
    commands: tuple[str, ...]
    connectors: tuple[str, ...]
    has_subshell: bool = False
    has_command_substitution: bool = False
    has_process_substitution: bool = False
    has_heredoc: bool = False
    has_function_definition: bool = False
    max_nesting: int = 0
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


CONNECTOR_RE = re.compile(r"(\|\||&&|[|;])")
FUNCTION_RE = re.compile(
    r"(^|[;&\n]\s*)(?:function\s+[A-Za-z_][A-Za-z0-9_]*\s*\(|[A-Za-z_][A-Za-z0-9_]*\s*\(\)\s*\{)",
)


def analyze_bash_structure(command: str) -> BashStructureAnalysis:
    try:
        import bashlex  # type: ignore
    except Exception:
        return _heuristic_analysis(command)
    return _bashlex_analysis(command, bashlex)


def _bashlex_analysis(command: str, bashlex) -> BashStructureAnalysis:
    warnings: list[str] = []
    max_nesting = 0
    current_nesting = 0
    has_subshell = False
    has_command_substitution = False
    has_process_substitution = False
    has_heredoc = "<<" in command
    has_function_definition = bool(FUNCTION_RE.search(command))
    try:
        parts = bashlex.parse(command)
    except Exception as error:
        warnings.append(f"bashlex parse failed: {error}")
        return _heuristic_analysis(command, warnings=warnings)

    def walk(node) -> None:
        nonlocal max_nesting, current_nesting, has_subshell, has_command_substitution, has_process_substitution
        kind = getattr(node, "kind", "")
        if kind in {"commandsubstitution", "processsubstitution", "subshell"}:
            current_nesting += 1
            max_nesting = max(max_nesting, current_nesting)
        if kind == "commandsubstitution":
            has_command_substitution = True
        if kind == "processsubstitution":
            has_process_substitution = True
        if kind == "subshell":
            has_subshell = True
        for child_name in ("parts", "list", "command", "redirects"):
            child = getattr(node, child_name, None)
            if isinstance(child, list):
                for item in child:
                    walk(item)
            elif child is not None and hasattr(child, "kind"):
                walk(child)
        if kind in {"commandsubstitution", "processsubstitution", "subshell"}:
            current_nesting -= 1

    for part in parts:
        walk(part)

    return BashStructureAnalysis(
        backend="bashlex",
        commands=tuple(iter_shell_commands(command)),
        connectors=tuple(CONNECTOR_RE.findall(command)),
        has_subshell=has_subshell,
        has_command_substitution=has_command_substitution,
        has_process_substitution=has_process_substitution,
        has_heredoc=has_heredoc,
        has_function_definition=has_function_definition,
        max_nesting=max_nesting,
        warnings=tuple(warnings),
    )


def _heuristic_analysis(command: str, *, warnings: list[str] | None = None) -> BashStructureAnalysis:
    warnings = list(warnings or [])
    has_subshell = False
    has_command_substitution = False
    has_process_substitution = False
    has_heredoc = False
    has_function_definition = bool(FUNCTION_RE.search(command))
    max_nesting = 0
    nesting = 0
    single = False
    double = False
    escape = False
    index = 0
    while index < len(command):
        char = command[index]
        prev = command[index - 1] if index > 0 else ""
        nxt = command[index + 1] if index + 1 < len(command) else ""
        if escape:
            escape = False
            index += 1
            continue
        if char == "\\" and not single:
            escape = True
            index += 1
            continue
        if char == "'" and not double:
            single = not single
            index += 1
            continue
        if char == '"' and not single:
            double = not double
            index += 1
            continue
        if single or double:
            index += 1
            continue

        if char == "<" and nxt == "<":
            has_heredoc = True
        if char in "<>" and nxt == "(":
            has_process_substitution = True
            nesting += 1
            max_nesting = max(max_nesting, nesting)
        elif char == "$" and nxt == "(":
            if index + 2 < len(command) and command[index + 2] == "(":
                pass
            else:
                has_command_substitution = True
                nesting += 1
                max_nesting = max(max_nesting, nesting)
        elif char == "(" and prev not in {"$", "<", ">", ""}:
            has_subshell = True
            nesting += 1
            max_nesting = max(max_nesting, nesting)
        elif char == ")":
            nesting = max(0, nesting - 1)
        elif char == "`":
            has_command_substitution = True

        index += 1

    if single or double:
        warnings.append("Unterminated shell quote detected")
    if nesting:
        warnings.append("Unbalanced shell grouping detected")

    return BashStructureAnalysis(
        backend="heuristic",
        commands=tuple(iter_shell_commands(command)),
        connectors=tuple(CONNECTOR_RE.findall(command)),
        has_subshell=has_subshell,
        has_command_substitution=has_command_substitution,
        has_process_substitution=has_process_substitution,
        has_heredoc=has_heredoc,
        has_function_definition=has_function_definition,
        max_nesting=max_nesting,
        warnings=tuple(warnings),
    )
