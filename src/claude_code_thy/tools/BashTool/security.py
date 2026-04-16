from __future__ import annotations

import re

from claude_code_thy.tools.base import ToolError
from .command_ast import BashStructureAnalysis, analyze_bash_structure

DESTRUCTIVE_BASH_PATTERNS = [
    re.compile(r"(^|[;&|]\s*)rm\s+-[^\n]*r", re.IGNORECASE),
    re.compile(r"\bgit\s+reset\s+--hard\b", re.IGNORECASE),
    re.compile(r"\bgit\s+clean\s+-[^\n]*f", re.IGNORECASE),
    re.compile(r"(^|[;&|]\s*)truncate\s+", re.IGNORECASE),
]


def validate_bash_command(
    command: str,
    *,
    dangerous_disable_sandbox: bool,
) -> BashStructureAnalysis:
    analysis = analyze_bash_structure(command)
    if analysis.warnings:
        raise ToolError("; ".join(analysis.warnings))

    if not dangerous_disable_sandbox:
        for pattern in DESTRUCTIVE_BASH_PATTERNS:
            if pattern.search(command):
                raise ToolError(
                    "该 bash 命令包含高风险 destructive 操作。"
                    "如确需执行，请显式传入 dangerouslyDisableSandbox=true。"
                )

    match = re.match(r"^\s*sleep\s+(\d+)\s*(?:$|&&|;)", command)
    if match and int(match.group(1)) >= 2:
        raise ToolError(
            "Blocked: standalone or leading sleep detected. "
            "请用更直接的命令检查状态，或改用后台任务。"
        )
    return analysis
