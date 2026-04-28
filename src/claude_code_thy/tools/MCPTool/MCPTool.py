from __future__ import annotations

import json

from claude_code_thy.mcp.serializers import serialize_mcp_tool_result
from claude_code_thy.mcp.types import McpToolDefinition
from claude_code_thy.mcp.utils import run_async_sync
from claude_code_thy.tools.base import PermissionResult, Tool, ToolContext, ToolError, ToolResult


class MCPTool(Tool):
    """实现 `MCP` 工具。"""
    def __init__(self, server_name: str, definition: McpToolDefinition) -> None:
        """初始化实例状态。"""
        self.server_name = server_name
        self.definition = definition
        self.name = definition.name
        self.description = definition.description or f"MCP tool from {server_name}"
        self.usage = ""
        self.input_schema = definition.input_schema or {"type": "object", "properties": {}}

    def is_read_only(self) -> bool:
        """返回是否满足 `is_read_only` 条件。"""
        return bool(self.definition.annotations.get("readOnlyHint", False))

    def is_concurrency_safe(self) -> bool:
        """返回是否满足 `is_concurrency_safe` 条件。"""
        return self.is_read_only()

    def original_name(self) -> str:
        """处理 `original_name`。"""
        return str(self.definition.annotations.get("original_name", self.name))

    def search_behavior(self) -> dict[str, bool]:
        """搜索 `behavior`。"""
        return {
            "is_search": bool(self.definition.annotations.get("openWorldHint", False)),
            "is_read": self.is_read_only(),
        }

    def parse_raw_input(self, raw_args: str, context: ToolContext) -> dict[str, object]:
        """解析 `raw_input`。"""
        _ = (raw_args, context)
        raise ToolError("MCP tool 需要结构化输入，不支持 slash 纯文本参数解析")

    def check_permissions(
        self,
        input_data: dict[str, object],
        context: ToolContext,
    ) -> PermissionResult:
        """检查 `permissions`。"""
        decision = context.permission_context.check_command(self.name, self.name)
        if decision is None or (decision.allowed and not decision.requires_confirmation):
            return PermissionResult.allow(updated_input=input_data)

        request = context.permission_context.build_request_for_command(
            self.name,
            self.name,
            reason=(
                decision.reason
                if decision is not None and decision.reason
                else f"MCP tool `{self.name}` 来自 server `{self.server_name}`，需要权限确认。"
            ),
        )
        if request.approval_key and request.approval_key in context.permission_context.approved_permissions:
            return PermissionResult.allow(updated_input=input_data)
        if decision is not None and decision.requires_confirmation:
            return PermissionResult.ask(request, updated_input=input_data)
        return PermissionResult.deny(
            (
                decision.reason
                if decision is not None and decision.reason
                else f"MCP tool `{self.name}` 来自 server `{self.server_name}`，被权限规则拒绝。"
            ),
            updated_input=input_data,
        )

    def execute(self, raw_args: str, context: ToolContext) -> ToolResult:
        """执行当前流程。"""
        raise ToolError("MCP tool 不支持 slash 文本执行。")

    def execute_input(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        """执行 `input`。"""
        if context.services is None:
            raise ToolError("MCP manager is unavailable")
        timeout_s = _interactive_mcp_timeout_seconds(context)
        try:
            result = run_async_sync(
                context.services.mcp_manager.call_tool(
                    self.server_name,
                    self.original_name(),
                    input_data,
                ),
                timeout=timeout_s,
            )
        except Exception as error:
            raise ToolError(str(error)) from error
        output_text, structured = serialize_mcp_tool_result(result)
        is_error = bool(getattr(result, "isError", False) or getattr(result, "is_error", False))
        return ToolResult(
            tool_name=self.name,
            ok=not is_error,
            summary=(
                f"MCP tool: {self.server_name}/{self.name}"
                if not is_error
                else f"MCP tool `{self.server_name}/{self.name}` 执行失败"
            ),
            display_name=self.name,
            ui_kind="mcp",
            output=output_text,
            metadata={
                "server_name": self.server_name,
                "is_mcp": True,
                "read_only": self.is_read_only(),
                "is_error": is_error,
            },
            structured_data={
                "server_name": self.server_name,
                "result": structured,
            },
            tool_result_content=output_text or json.dumps(structured, ensure_ascii=False),
        )


def _interactive_mcp_timeout_seconds(context: ToolContext) -> float:
    """处理 `interactive_mcp_timeout_seconds`。"""
    if context.services is None:
        return 30.0
    timeout_ms = context.services.settings.mcp.tool_call_timeout_ms
    return max(min(timeout_ms / 1000, 30.0), 1.0)
