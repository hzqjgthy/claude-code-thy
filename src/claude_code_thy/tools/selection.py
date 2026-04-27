from __future__ import annotations

from fnmatch import fnmatch


MODEL_VISIBLE_TOOLS = [
    "agent",
    "bash",
    "browser",
    "browser_search",
    "read",
    "write",
    "edit",
    "glob",
    "grep",
    "skill",
    "list_mcp_resources",
    "read_mcp_resource",
    "mcp__*",
]


SLASH_AVAILABLE_TOOLS = [
    "agent",
    "bash",
    "browser",
    "browser_search",
    "read",
    "write",
    "edit",
    "glob",
    "grep",
    "mcp__*",
]


def tool_visible_for_model(tool_name: str) -> bool:
    """判断某个工具当前是否暴露给主链模型。"""
    return _matches_any(tool_name, MODEL_VISIBLE_TOOLS)


def tool_available_for_slash(tool_name: str) -> bool:
    """判断某个工具当前是否允许通过 slash 或本地命令执行。"""
    return _matches_any(tool_name, SLASH_AVAILABLE_TOOLS)


def selected_tools(tool_names: list[str], *, surface: str) -> list[str]:
    """按目标面过滤工具名列表。"""
    predicate = tool_visible_for_model if surface == "model" else tool_available_for_slash
    return [name for name in tool_names if predicate(name)]


def _matches_any(tool_name: str, selectors: list[str]) -> bool:
    """支持精确名和 fnmatch 通配符两种选择方式。"""
    return any(fnmatch(tool_name, selector) for selector in selectors)
