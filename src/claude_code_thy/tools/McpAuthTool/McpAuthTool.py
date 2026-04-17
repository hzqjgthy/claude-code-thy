from __future__ import annotations

from claude_code_thy.mcp.auth import start_oauth_flow
from claude_code_thy.mcp.names import build_mcp_tool_name
from claude_code_thy.tools.base import PermissionResult, Tool, ToolContext, ToolError, ToolResult


class McpAuthTool(Tool):
    def __init__(self, server_name: str) -> None:
        self.server_name = server_name
        self.name = build_mcp_tool_name(server_name, "authenticate")
        self.description = f"启动 MCP server `{server_name}` 的 OAuth 认证流程。"
        self.usage = ""
        self.input_schema = {"type": "object", "properties": {}}

    def parse_raw_input(self, raw_args: str, context: ToolContext) -> dict[str, object]:
        _ = (raw_args, context)
        return {}

    def check_permissions(
        self,
        input_data: dict[str, object],
        context: ToolContext,
    ) -> PermissionResult:
        _ = context
        return PermissionResult.allow(updated_input=input_data)

    def execute(self, raw_args: str, context: ToolContext) -> ToolResult:
        return self.execute_input({}, context)

    def execute_input(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        _ = input_data
        if context.services is None:
            raise ToolError("MCP manager is unavailable")
        config = context.services.mcp_manager.configs().get(self.server_name)
        if config is None:
            raise ToolError(f"未找到 MCP server：{self.server_name}")

        def _on_complete(ok: bool, message: str | None) -> None:
            if not ok:
                return
            context.services.mcp_manager.refresh_server_sync(self.server_name)

        try:
            auth_url = start_oauth_flow(self.server_name, config, on_complete=_on_complete)
        except Exception as error:
            raise ToolError(str(error)) from error

        output = (
            f"MCP server `{self.server_name}` 需要认证。\n\n"
            f"请在浏览器中打开下面的地址完成授权：\n{auth_url}\n\n"
            "授权完成后，工具会自动刷新。"
        )
        return ToolResult(
            tool_name=self.name,
            ok=True,
            summary=f"MCP auth started: {self.server_name}",
            display_name=self.name,
            ui_kind="mcp_auth",
            output=output,
            metadata={"server_name": self.server_name, "auth_url": auth_url},
            structured_data={
                "server_name": self.server_name,
                "auth_url": auth_url,
                "status": "auth_url",
            },
            tool_result_content=output,
        )
