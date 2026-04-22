from __future__ import annotations

from typing import Any, Awaitable, Callable

from claude_code_thy.settings import AppSettings

from .errors import McpRuntimeError
from .transport import _ManagedConnection
from .types import McpPromptDefinition, McpResourceDefinition, McpToolDefinition


RunSessionCall = Callable[..., Awaitable[Any]]


class McpSessionOperations:
    """表示 `McpSessionOperations`。"""
    def __init__(self, settings: AppSettings, run_session_call: RunSessionCall) -> None:
        """初始化实例状态。"""
        self.settings = settings
        self._run_session_call = run_session_call

    async def list_tools(self, handle: _ManagedConnection) -> list[McpToolDefinition]:
        """列出 `tools`。"""
        result = await self._run_session_call(handle.session.list_tools)
        tools = getattr(result, "tools", []) or []
        definitions: list[McpToolDefinition] = []
        for tool in tools:
            input_schema = getattr(tool, "inputSchema", {}) or {}
            annotations = getattr(tool, "annotations", {}) or {}
            if not isinstance(annotations, dict):
                annotations = {}
            annotations = {
                **annotations,
                "original_name": str(getattr(tool, "name", "")),
            }
            definitions.append(
                McpToolDefinition(
                    name=str(getattr(tool, "name", "")),
                    description=str(getattr(tool, "description", "") or ""),
                    input_schema=input_schema if isinstance(input_schema, dict) else {},
                    annotations=annotations,
                )
            )
        return definitions

    async def list_prompts(self, handle: _ManagedConnection) -> list[McpPromptDefinition]:
        """列出 `prompts`。"""
        result = await self._run_session_call(handle.session.list_prompts)
        prompts = getattr(result, "prompts", []) or []
        definitions: list[McpPromptDefinition] = []
        for prompt in prompts:
            args = getattr(prompt, "arguments", []) or []
            definitions.append(
                McpPromptDefinition(
                    name=str(getattr(prompt, "name", "")),
                    description=str(getattr(prompt, "description", "") or ""),
                    arguments=tuple(
                        str(getattr(arg, "name", ""))
                        for arg in args
                        if str(getattr(arg, "name", "")).strip()
                    ),
                )
            )
        return definitions

    async def list_resources(
        self,
        server_name: str,
        handle: _ManagedConnection,
    ) -> list[McpResourceDefinition]:
        """列出 `resources`。"""
        result = await self._run_session_call(handle.session.list_resources)
        resources = getattr(result, "resources", []) or []
        definitions: list[McpResourceDefinition] = []
        for resource in resources:
            definitions.append(
                McpResourceDefinition(
                    uri=str(getattr(resource, "uri", "")),
                    name=str(getattr(resource, "name", "")),
                    server=server_name,
                    description=str(getattr(resource, "description", "") or ""),
                    mime_type=str(getattr(resource, "mimeType", "") or ""),
                )
            )
        return definitions

    async def get_prompt(
        self,
        handle: _ManagedConnection,
        prompt_name: str,
        arguments: dict[str, str] | None = None,
    ) -> Any:
        """返回 `prompt`。"""
        session = handle.session
        timeout_message = f"MCP prompt timed out after {self.settings.mcp.tool_call_timeout_ms} ms"
        if hasattr(session, "get_prompt"):
            return await self._run_session_call(
                lambda: session.get_prompt(prompt_name, arguments or {}),
                timeout_message=timeout_message,
            )
        if hasattr(session, "request"):
            return await self._run_session_call(
                lambda: session.request(
                    {
                        "method": "prompts/get",
                        "params": {"name": prompt_name, "arguments": arguments or {}},
                    }
                ),
                timeout_message=timeout_message,
            )
        raise McpRuntimeError("当前 MCP SDK 不支持 prompts/get")

    async def call_tool(
        self,
        handle: _ManagedConnection,
        tool_name: str,
        arguments: dict[str, object] | None = None,
    ) -> Any:
        """处理 `call_tool`。"""
        return await self._run_session_call(
            lambda: handle.session.call_tool(tool_name, arguments or {}),
            timeout_message=(
                f"MCP tool `{tool_name}` timed out after {self.settings.mcp.tool_call_timeout_ms} ms"
            ),
        )

    async def read_resource(
        self,
        handle: _ManagedConnection,
        uri: str,
    ) -> Any:
        """读取 `resource`。"""
        return await self._run_session_call(
            lambda: handle.session.read_resource(uri),
            timeout_message=(
                f"MCP resource `{uri}` timed out after {self.settings.mcp.tool_call_timeout_ms} ms"
            ),
        )
