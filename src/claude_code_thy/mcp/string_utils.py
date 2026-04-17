from __future__ import annotations

from .normalization import normalize_name_for_mcp


def build_mcp_tool_name(server_name: str, tool_name: str) -> str:
    return f"mcp__{normalize_name_for_mcp(server_name)}__{normalize_name_for_mcp(tool_name)}"
