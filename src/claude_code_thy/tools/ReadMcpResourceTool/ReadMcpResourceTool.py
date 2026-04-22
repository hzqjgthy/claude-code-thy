from __future__ import annotations

import json

from claude_code_thy.mcp.resources import serialize_resource_read_result
from claude_code_thy.mcp.utils import run_async_sync
from claude_code_thy.tools.base import Tool, ToolContext, ToolError, ToolResult


class ReadMcpResourceTool(Tool):
    """实现 `ReadMcpResource` 工具。"""
    name = "read_mcp_resource"
    description = "读取指定 MCP resource。"
    usage = ""
    input_schema = {
        "type": "object",
        "properties": {
            "server": {"type": "string", "description": "MCP server name."},
            "uri": {"type": "string", "description": "Resource URI."},
        },
        "required": ["server", "uri"],
    }

    def is_read_only(self) -> bool:
        """返回是否满足 `is_read_only` 条件。"""
        return True

    def is_concurrency_safe(self) -> bool:
        """返回是否满足 `is_concurrency_safe` 条件。"""
        return True

    def search_behavior(self) -> dict[str, bool]:
        """搜索 `behavior`。"""
        return {"is_search": False, "is_read": True}

    def parse_raw_input(self, raw_args: str, context: ToolContext) -> dict[str, object]:
        """解析 `raw_input`。"""
        _ = context
        parts = raw_args.strip().split(maxsplit=1)
        if len(parts) != 2:
            raise ToolError("用法：/read_mcp_resource <server> <uri>")
        return {"server": parts[0], "uri": parts[1]}

    def execute(self, raw_args: str, context: ToolContext) -> ToolResult:
        """执行当前流程。"""
        return self.execute_input(self.parse_raw_input(raw_args, context), context)

    def execute_input(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        """执行 `input`。"""
        if context.services is None:
            raise ToolError("MCP manager is unavailable")
        server = str(input_data.get("server", "")).strip()
        uri = str(input_data.get("uri", "")).strip()
        if not server or not uri:
            raise ToolError("tool input 缺少 server/uri")
        timeout_s = max(min(context.services.settings.mcp.tool_call_timeout_ms / 1000, 30.0), 1.0)
        result = run_async_sync(
            context.services.mcp_manager.read_resource(server, uri),
            timeout=timeout_s,
        )
        output, structured = serialize_resource_read_result(result)
        return ToolResult(
            tool_name=self.name,
            ok=True,
            summary=f"MCP resource: {server} {uri}",
            display_name="Read MCP Resource",
            ui_kind="mcp",
            output=output or json.dumps(structured, ensure_ascii=False, indent=2),
            metadata={"server": server, "uri": uri},
            structured_data=structured,
            tool_result_content=output or json.dumps(structured, ensure_ascii=False, indent=2),
        )
