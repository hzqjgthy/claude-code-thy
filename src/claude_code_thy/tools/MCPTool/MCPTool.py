from __future__ import annotations

import json

from claude_code_thy.mcp.types import McpToolDefinition
from claude_code_thy.mcp.utils import run_async_sync
from claude_code_thy.tools.base import PermissionResult, Tool, ToolContext, ToolError, ToolResult


class MCPTool(Tool):
    def __init__(self, server_name: str, definition: McpToolDefinition) -> None:
        self.server_name = server_name
        self.definition = definition
        self.name = definition.name
        self.description = definition.description or f"MCP tool from {server_name}"
        self.usage = ""
        self.input_schema = definition.input_schema or {"type": "object", "properties": {}}

    def is_read_only(self) -> bool:
        return bool(self.definition.annotations.get("readOnlyHint", False))

    def is_concurrency_safe(self) -> bool:
        return self.is_read_only()

    def search_behavior(self) -> dict[str, bool]:
        return {
            "is_search": bool(self.definition.annotations.get("openWorldHint", False)),
            "is_read": self.is_read_only(),
        }

    def parse_raw_input(self, raw_args: str, context: ToolContext) -> dict[str, object]:
        _ = (raw_args, context)
        raise ToolError("MCP tool 需要结构化输入，不支持 slash 纯文本参数解析")

    def check_permissions(
        self,
        input_data: dict[str, object],
        context: ToolContext,
    ) -> PermissionResult:
        _ = input_data
        if self.is_read_only():
            return PermissionResult.allow(updated_input=input_data)
        request = context.permission_context.build_request_for_command(
            self.name,
            self.name,
            reason=f"MCP tool `{self.name}` 来自 server `{self.server_name}`，需要权限确认。",
        )
        if request.approval_key and request.approval_key in context.permission_context.approved_permissions:
            return PermissionResult.allow(updated_input=input_data)
        return PermissionResult.ask(request, updated_input=input_data)

    def execute(self, raw_args: str, context: ToolContext) -> ToolResult:
        raise ToolError("MCP tool 不支持 slash 文本执行。")

    def execute_input(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        if context.services is None:
            raise ToolError("MCP manager is unavailable")
        timeout_s = _interactive_mcp_timeout_seconds(context)
        try:
            result = run_async_sync(
                context.services.mcp_manager.call_tool(
                    self.server_name,
                    self.definition.annotations.get("original_name", self.name) if isinstance(self.definition.annotations, dict) else self.name,
                    input_data,
                ),
                timeout=timeout_s,
            )
        except Exception as error:
            raise ToolError(str(error)) from error
        output_text, structured = _serialize_mcp_tool_result(result)
        return ToolResult(
            tool_name=self.name,
            ok=True,
            summary=f"MCP tool: {self.server_name}/{self.name}",
            display_name=self.name,
            ui_kind="mcp",
            output=output_text,
            metadata={
                "server_name": self.server_name,
                "is_mcp": True,
                "read_only": self.is_read_only(),
            },
            structured_data={
                "server_name": self.server_name,
                "result": structured,
            },
            tool_result_content=output_text or json.dumps(structured, ensure_ascii=False),
        )


def _serialize_mcp_tool_result(result: object) -> tuple[str, object]:
    if result is None:
        return "", {}
    content = getattr(result, "content", None)
    if isinstance(content, str):
        return content, {"content": content}
    if isinstance(content, list):
        text_parts: list[str] = []
        normalized: list[object] = []
        for item in content:
            entry = _to_jsonable(item)
            normalized.append(entry)
            if isinstance(entry, dict) and isinstance(entry.get("text"), str):
                text_parts.append(str(entry["text"]))
            else:
                text = getattr(item, "text", None)
                if isinstance(text, str):
                    text_parts.append(text)
        return "\n".join(part for part in text_parts if part.strip()), {"content": normalized}
    if isinstance(result, dict):
        normalized = _to_jsonable(result)
        return json.dumps(normalized, ensure_ascii=False, indent=2), normalized
    normalized = _to_jsonable(result)
    if isinstance(normalized, (dict, list)):
        return json.dumps(normalized, ensure_ascii=False, indent=2), normalized
    return str(normalized), {"content": str(normalized)}


def _interactive_mcp_timeout_seconds(context: ToolContext) -> float:
    if context.services is None:
        return 30.0
    timeout_ms = context.services.settings.mcp.tool_call_timeout_ms
    return max(min(timeout_ms / 1000, 30.0), 1.0)


def _to_jsonable(value: object) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_jsonable(item) for item in value]
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            return _to_jsonable(model_dump())
        except Exception:
            pass
    if hasattr(value, "__dict__"):
        data = {
            key: item
            for key, item in vars(value).items()
            if not key.startswith("_")
        }
        if data:
            return _to_jsonable(data)
    return str(value)
