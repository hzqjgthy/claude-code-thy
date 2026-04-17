from __future__ import annotations

import re
from collections.abc import Iterable


MCP_DYNAMIC_PREFIX = "mcp__"


def normalize_name_for_mcp(name: str) -> str:
    collapsed = re.sub(r"[^a-zA-Z0-9]+", "_", name.strip())
    collapsed = re.sub(r"_+", "_", collapsed).strip("_")
    return collapsed.lower() or "mcp"


def build_dynamic_mcp_name(server_name: str, item_name: str) -> str:
    return (
        f"{MCP_DYNAMIC_PREFIX}"
        f"{normalize_name_for_mcp(server_name)}"
        f"__{normalize_name_for_mcp(item_name)}"
    )


def build_mcp_tool_name(server_name: str, tool_name: str) -> str:
    return build_dynamic_mcp_name(server_name, tool_name)


def build_prompt_command_name(server_name: str, prompt_name: str) -> str:
    return build_dynamic_mcp_name(server_name, prompt_name)


def parse_dynamic_mcp_name(name: str) -> tuple[str, str]:
    if not name.startswith(MCP_DYNAMIC_PREFIX):
        return "", ""
    suffix = name[len(MCP_DYNAMIC_PREFIX):]
    if "__" not in suffix:
        return "", ""
    server_name, item_name = suffix.split("__", 1)
    return server_name.strip(), item_name.strip()


def is_normalized_mcp_name_match(actual_name: str, normalized_name: str) -> bool:
    return normalize_name_for_mcp(actual_name) == normalized_name


def matching_server_names(
    available_names: Iterable[str],
    normalized_server_name: str,
) -> list[str]:
    return [
        actual_name
        for actual_name in available_names
        if is_normalized_mcp_name_match(actual_name, normalized_server_name)
    ]
