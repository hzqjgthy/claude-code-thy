from __future__ import annotations

from claude_code_thy.mcp.resources import summarize_resources
from claude_code_thy.mcp.utils import run_async_sync
from claude_code_thy.tools.base import Tool, ToolContext, ToolError, ToolResult


class ListMcpResourcesTool(Tool):
    name = "list_mcp_resources"
    description = "列出已连接 MCP servers 的 resources。"
    usage = ""
    input_schema = {
        "type": "object",
        "properties": {
            "server": {"type": "string", "description": "Optional MCP server name."},
        },
    }

    def is_read_only(self) -> bool:
        return True

    def is_concurrency_safe(self) -> bool:
        return True

    def search_behavior(self) -> dict[str, bool]:
        return {"is_search": True, "is_read": True}

    def parse_raw_input(self, raw_args: str, context: ToolContext) -> dict[str, object]:
        _ = context
        raw = raw_args.strip()
        return {"server": raw} if raw else {}

    def execute(self, raw_args: str, context: ToolContext) -> ToolResult:
        return self.execute_input(self.parse_raw_input(raw_args, context), context)

    def execute_input(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        if context.services is None:
            raise ToolError("MCP manager is unavailable")
        server = str(input_data.get("server", "")).strip() or None
        timeout_s = max(min(context.services.settings.mcp.connect_timeout_ms / 1000, 15.0), 1.0)
        run_async_sync(context.services.mcp_manager.refresh_all(), timeout=timeout_s)
        cached = context.services.mcp_manager.cached_resources()
        resources = []
        if server:
            resources = cached.get(server, [])
        else:
            for items in cached.values():
                resources.extend(items)
        summary = summarize_resources(resources)
        return ToolResult(
            tool_name=self.name,
            ok=True,
            summary="MCP resources",
            display_name="MCP Resources",
            ui_kind="mcp",
            output=summary,
            metadata={"count": len(resources)},
            structured_data={
                "resources": [
                    {
                        "server": resource.server,
                        "uri": resource.uri,
                        "name": resource.name,
                        "description": resource.description,
                        "mime_type": resource.mime_type,
                    }
                    for resource in resources
                ]
            },
            tool_result_content=summary,
        )
