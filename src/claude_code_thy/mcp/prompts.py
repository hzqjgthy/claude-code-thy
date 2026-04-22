from __future__ import annotations

from claude_code_thy.mcp.names import build_prompt_command_name
from claude_code_thy.mcp.serializers import render_prompt_result
from claude_code_thy.mcp.types import McpPromptDefinition


def parse_prompt_arguments(
    prompt: McpPromptDefinition,
    raw_args: str,
) -> dict[str, str]:
    """解析 `prompt_arguments`。"""
    names = list(prompt.arguments)
    text = raw_args.strip()
    if not names:
        return {}
    if len(names) == 1:
        return {names[0]: text}

    result: dict[str, str] = {}
    if text:
        for token in text.split():
            if "=" not in token:
                continue
            key, value = token.split("=", 1)
            key = key.strip()
            value = value.strip()
            if key and key in names:
                result[key] = value
    return result
