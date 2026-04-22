from __future__ import annotations

import re
from collections.abc import Iterable


MCP_DYNAMIC_PREFIX = "mcp__"


def normalize_name_for_mcp(name: str) -> str:
    """把任意 server/tool/prompt 名称标准化为 MCP 动态命名可用的片段。"""
    collapsed = re.sub(r"[^a-zA-Z0-9]+", "_", name.strip())
    collapsed = re.sub(r"_+", "_", collapsed).strip("_")
    return collapsed.lower() or "mcp"


def build_dynamic_mcp_name(server_name: str, item_name: str) -> str:
    """拼出统一的 `mcp__server__item` 动态名称。"""
    return (
        f"{MCP_DYNAMIC_PREFIX}"
        f"{normalize_name_for_mcp(server_name)}"
        f"__{normalize_name_for_mcp(item_name)}"
    )


def build_mcp_tool_name(server_name: str, tool_name: str) -> str:
    """为 MCP tool 生成 slash 命令和工具注册共用的名称。"""
    return build_dynamic_mcp_name(server_name, tool_name)


def build_prompt_command_name(server_name: str, prompt_name: str) -> str:
    """为 MCP prompt 生成统一命令名。"""
    return build_dynamic_mcp_name(server_name, prompt_name)


def parse_dynamic_mcp_name(name: str) -> tuple[str, str]:
    """把 `mcp__server__item` 还原为 server 和 item 两段。"""
    if not name.startswith(MCP_DYNAMIC_PREFIX):
        return "", ""
    suffix = name[len(MCP_DYNAMIC_PREFIX):]
    if "__" not in suffix:
        return "", ""
    server_name, item_name = suffix.split("__", 1)
    return server_name.strip(), item_name.strip()


def is_normalized_mcp_name_match(actual_name: str, normalized_name: str) -> bool:
    """判断原始名称规范化后是否等于给定名称片段。"""
    return normalize_name_for_mcp(actual_name) == normalized_name


def matching_server_names(
    available_names: Iterable[str],
    normalized_server_name: str,
) -> list[str]:
    """在一组实际 server 名中找出与规范化名称匹配的候选。"""
    return [
        actual_name
        for actual_name in available_names
        if is_normalized_mcp_name_match(actual_name, normalized_server_name)
    ]
