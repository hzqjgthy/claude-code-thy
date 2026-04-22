from __future__ import annotations

from claude_code_thy.mcp.serializers import serialize_resource_read_result
from claude_code_thy.mcp.types import McpResourceDefinition


def summarize_resources(resources: list[McpResourceDefinition]) -> str:
    """汇总 `resources`。"""
    if not resources:
        return "No resources found"
    return "\n".join(f"{resource.server}: {resource.name} <{resource.uri}>" for resource in resources)
