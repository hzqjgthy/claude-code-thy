from __future__ import annotations

from pathlib import Path
from typing import Any

from claude_code_thy.settings import AppSettings

from .catalog import McpCatalog
from .config import get_all_mcp_configs
from .errors import McpRuntimeError
from .session_ops import McpSessionOperations
from .transport import McpTransportLayer, _ManagedConnection
from .types import (
    McpPromptDefinition,
    McpResourceDefinition,
    McpServerConfig,
    McpServerConnection,
    McpToolDefinition,
)
from .utils import utc_now


class McpClientManager:
    def __init__(self, workspace_root: Path, settings: AppSettings) -> None:
        self.workspace_root = workspace_root
        self.settings = settings
        self._catalog = McpCatalog()
        self._transport = McpTransportLayer(settings, self._catalog)
        self._session_ops = McpSessionOperations(settings, self._transport.run_session_call)

    @property
    def _handles(self) -> dict[str, _ManagedConnection]:
        return self._transport.handles

    def configs(self) -> dict[str, McpServerConfig]:
        return get_all_mcp_configs(self.workspace_root, self.settings)

    def snapshot(self) -> list[McpServerConnection]:
        return self._catalog.snapshot(self.configs())

    async def refresh_all(self) -> list[McpServerConnection]:
        configs = self.configs()
        async with self._transport.lock:
            stale = [name for name in self._handles if name not in configs]
            for name in stale:
                await self._close_handle(name)
            for name, config in configs.items():
                if not config.enabled:
                    await self._close_handle(name)
                    self._catalog.mark_disabled(name, config)
                    continue
                if config.type == "http":
                    await self._refresh_http_connection(name, config)
                    continue
                handle = await self._ensure_connection(name, config, force_reconnect=False)
                if handle is not None:
                    await self._populate_counts(name, handle)
            return self.snapshot()

    async def get_connection(self, name: str, *, refresh: bool = False) -> McpServerConnection | None:
        config = self.configs().get(name)
        if config is None:
            return None
        self._catalog.ensure_known(name, config)
        if refresh and config.enabled:
            async with self._transport.lock:
                if config.type == "http":
                    await self._refresh_http_connection(name, config)
                else:
                    handle = await self._ensure_connection(name, config, force_reconnect=False)
                    if handle is not None:
                        await self._populate_counts(name, handle)
        return self._catalog.connection(name)

    async def list_tools(self, name: str) -> list[McpToolDefinition]:
        definitions = await self._invoke_with_handle(name, self._session_ops.list_tools)
        self._catalog.set_tools(name, definitions)
        return definitions

    async def list_prompts(self, name: str) -> list[McpPromptDefinition]:
        definitions = await self._invoke_with_handle(name, self._session_ops.list_prompts)
        self._catalog.set_prompts(name, definitions)
        return definitions

    async def list_resources(self, name: str) -> list[McpResourceDefinition]:
        async def _load(handle: _ManagedConnection) -> list[McpResourceDefinition]:
            return await self._session_ops.list_resources(name, handle)

        definitions = await self._invoke_with_handle(name, _load)
        self._catalog.set_resources(name, definitions)
        return definitions

    async def get_prompt(
        self,
        server_name: str,
        prompt_name: str,
        arguments: dict[str, str] | None = None,
    ) -> Any:
        async def _load(handle: _ManagedConnection) -> Any:
            return await self._session_ops.get_prompt(handle, prompt_name, arguments)

        return await self._invoke_with_handle(server_name, _load)

    async def call_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict[str, object] | None = None,
    ) -> Any:
        async def _call(handle: _ManagedConnection) -> Any:
            return await self._session_ops.call_tool(handle, tool_name, arguments)

        return await self._invoke_with_handle(server_name, _call)

    async def read_resource(self, server_name: str, uri: str) -> Any:
        async def _read(handle: _ManagedConnection) -> Any:
            return await self._session_ops.read_resource(handle, uri)

        return await self._invoke_with_handle(server_name, _read)

    async def close_all(self) -> None:
        async with self._transport.lock:
            for name in list(self._handles):
                await self._close_handle(name)

    def cached_tools(self) -> dict[str, list[McpToolDefinition]]:
        return self._catalog.cached_tools()

    def cached_prompts(self) -> dict[str, list[McpPromptDefinition]]:
        return self._catalog.cached_prompts()

    def cached_resources(self) -> dict[str, list[McpResourceDefinition]]:
        return self._catalog.cached_resources()

    async def _get_connected_handle(self, name: str) -> _ManagedConnection:
        config = self.configs().get(name)
        if config is None:
            raise McpRuntimeError(f"MCP server not found: {name}")
        if config.type == "http":
            raise McpRuntimeError("HTTP MCP handles are request-scoped and must not be reused directly")
        async with self._transport.lock:
            handle = await self._ensure_connection(name, config, force_reconnect=False)
        if handle is None:
            connection = self._catalog.connection(name)
            detail = connection.error if connection is not None else ""
            raise McpRuntimeError(detail or f"MCP server is not connected: {name}")
        return handle

    async def _invoke_with_handle(
        self,
        name: str,
        operation,
    ):
        config = self.configs().get(name)
        if config is None:
            raise McpRuntimeError(f"MCP server not found: {name}")
        if config.type == "http":
            handle = await self._open_http_handle(name, config)
            op_error: Exception | None = None
            try:
                result = await operation(handle)
            except Exception as error:
                op_error = error
            finally:
                await self._close_stack_quietly(handle.stack)
            if op_error is not None:
                raise op_error
            return result
        handle = await self._get_connected_handle(name)
        return await operation(handle)

    async def _ensure_connection(
        self,
        name: str,
        config: McpServerConfig,
        *,
        force_reconnect: bool,
    ) -> _ManagedConnection | None:
        return await self._transport.get_persistent_handle(
            name,
            config,
            force_reconnect=force_reconnect,
            open_connection=self._open_connection,
        )

    async def _open_connection(self, config: McpServerConfig) -> _ManagedConnection:
        return await self._transport.open_connection(config)

    async def _open_http_handle(
        self,
        name: str,
        config: McpServerConfig,
    ) -> _ManagedConnection:
        return await self._transport.open_request_scoped_handle(
            name,
            config,
            open_connection=self._open_connection,
        )

    async def _close_handle(self, name: str) -> None:
        await self._transport.close_handle(name)
        self._catalog.clear_definitions(name)

    async def _refresh_http_connection(
        self,
        name: str,
        config: McpServerConfig,
    ) -> None:
        try:
            handle = await self._open_http_handle(name, config)
        except McpRuntimeError:
            self._catalog.set_empty_definitions(name)
            return
        try:
            await self._populate_counts(name, handle)
        finally:
            await self._close_stack_quietly(handle.stack)

    async def _populate_counts(self, name: str, handle: _ManagedConnection) -> None:
        connection = self._catalog.connection(name)
        if connection is None or connection.status != "connected":
            return
        try:
            tools = await self._session_ops.list_tools(handle)
        except McpRuntimeError:
            tools = []
        try:
            prompts = await self._session_ops.list_prompts(handle)
        except McpRuntimeError:
            prompts = []
        try:
            resources = await self._session_ops.list_resources(name, handle)
        except McpRuntimeError:
            resources = []
        self._catalog.set_populated(
            name,
            tools=tools,
            prompts=prompts,
            resources=resources,
        )
        connection.updated_at = utc_now()

    async def _close_stack_quietly(self, stack) -> None:
        await self._transport.close_stack_quietly(stack)
