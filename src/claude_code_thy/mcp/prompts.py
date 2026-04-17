from __future__ import annotations

import json

from claude_code_thy.mcp.normalization import normalize_name_for_mcp
from claude_code_thy.mcp.types import McpPromptDefinition


def build_prompt_command_name(server_name: str, prompt_name: str) -> str:
    return f"mcp__{normalize_name_for_mcp(server_name)}__{normalize_name_for_mcp(prompt_name)}"


def parse_prompt_arguments(
    prompt: McpPromptDefinition,
    raw_args: str,
) -> dict[str, str]:
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


def render_prompt_result(result: object) -> str:
    if result is None:
        return ""
    messages = getattr(result, "messages", None)
    if isinstance(messages, list):
        chunks: list[str] = []
        for message in messages:
            content = getattr(message, "content", None)
            if isinstance(content, str):
                chunks.append(content)
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and isinstance(block.get("text"), str):
                        chunks.append(str(block["text"]))
                    else:
                        text = getattr(block, "text", None)
                        if isinstance(text, str):
                            chunks.append(text)
        return "\n".join(chunk for chunk in chunks if chunk.strip())
    if isinstance(result, dict):
        return json.dumps(result, ensure_ascii=False, indent=2)
    return str(result)
