from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from claude_code_thy.settings import AppSettings

from .config import get_all_mcp_configs
from .headers import get_server_headers
from .types import (
    McpPromptDefinition,
    McpResourceDefinition,
    McpServerConfig,
    McpServerConnection,
    McpToolDefinition,
)
from .utils import utc_now


class McpRuntimeError(RuntimeError):
    pass


@dataclass(slots=True)
class _ManagedConnection:
    config: McpServerConfig
    stack: AsyncExitStack
    session: Any


class McpClientManager:
    def __init__(self, workspace_root: Path, settings: AppSettings) -> None:
        self.workspace_root = workspace_root
        self.settings = settings
        self._handles: dict[str, _ManagedConnection] = {}
        self._connections: dict[str, McpServerConnection] = {}
        self._tool_defs: dict[str, list[McpToolDefinition]] = {}
        self._prompt_defs: dict[str, list[McpPromptDefinition]] = {}
        self._resource_defs: dict[str, list[McpResourceDefinition]] = {}
        self._lock = asyncio.Lock()

    def configs(self) -> dict[str, McpServerConfig]:
        return get_all_mcp_configs(self.workspace_root, self.settings)

    def snapshot(self) -> list[McpServerConnection]:
        known_names = set(self.configs())
        for name, config in self.configs().items():
            self._connections.setdefault(
                name,
                McpServerConnection(
                    name=name,
                    status="pending" if config.enabled else "disabled",
                    config=config,
                    updated_at=utc_now(),
                ),
            )
        stale = [name for name in self._connections if name not in known_names]
        for name in stale:
            self._connections.pop(name, None)
            self._tool_defs.pop(name, None)
            self._prompt_defs.pop(name, None)
            self._resource_defs.pop(name, None)
        return [self._connections[name] for name in sorted(self._connections)]

    async def refresh_all(self) -> list[McpServerConnection]:
        configs = self.configs()
        async with self._lock:
            stale = [name for name in self._handles if name not in configs]
            for name in stale:
                await self._close_handle(name)
            for name, config in configs.items():
                if not config.enabled:
                    await self._close_handle(name)
                    self._connections[name] = McpServerConnection(
                        name=name,
                        status="disabled",
                        config=config,
                        updated_at=utc_now(),
                    )
                    continue
                if config.type == "http":
                    await self._refresh_http_connection(name, config)
                    continue
                handle = await self._ensure_connection(name, config, force_reconnect=False)
                if handle is not None:
                    await self._populate_counts(name, handle)
            return self.snapshot()

    async def get_connection(self, name: str, *, refresh: bool = False) -> McpServerConnection | None:
        configs = self.configs()
        config = configs.get(name)
        if config is None:
            return None
        self._connections.setdefault(
            name,
            McpServerConnection(
                name=name,
                status="pending" if config.enabled else "disabled",
                config=config,
                updated_at=utc_now(),
            ),
        )
        if refresh and config.enabled:
            async with self._lock:
                if config.type == "http":
                    await self._refresh_http_connection(name, config)
                else:
                    handle = await self._ensure_connection(name, config, force_reconnect=False)
                    if handle is not None:
                        await self._populate_counts(name, handle)
        return self._connections.get(name)

    async def list_tools(self, name: str) -> list[McpToolDefinition]:
        definitions = await self._invoke_with_handle(name, self._fetch_tools_for_handle)
        conn = self._connections.get(name)
        if conn is not None:
            conn.tool_count = len(definitions)
            conn.updated_at = utc_now()
        self._tool_defs[name] = definitions
        return definitions

    async def _fetch_tools_for_handle(
        self,
        handle: _ManagedConnection,
    ) -> list[McpToolDefinition]:
        try:
            result = await handle.session.list_tools()
        except Exception as error:
            raise McpRuntimeError(str(error)) from error
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

    async def list_prompts(self, name: str) -> list[McpPromptDefinition]:
        definitions = await self._invoke_with_handle(name, self._fetch_prompts_for_handle)
        conn = self._connections.get(name)
        if conn is not None:
            conn.prompt_count = len(definitions)
            conn.updated_at = utc_now()
        self._prompt_defs[name] = definitions
        return definitions

    async def _fetch_prompts_for_handle(
        self,
        handle: _ManagedConnection,
    ) -> list[McpPromptDefinition]:
        try:
            result = await handle.session.list_prompts()
        except Exception as error:
            raise McpRuntimeError(str(error)) from error
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

    async def list_resources(self, name: str) -> list[McpResourceDefinition]:
        async def _load(handle: _ManagedConnection) -> list[McpResourceDefinition]:
            return await self._fetch_resources_for_handle(name, handle)

        definitions = await self._invoke_with_handle(name, _load)
        conn = self._connections.get(name)
        if conn is not None:
            conn.resource_count = len(definitions)
            conn.updated_at = utc_now()
        self._resource_defs[name] = definitions
        return definitions

    async def _fetch_resources_for_handle(
        self,
        server_name: str,
        handle: _ManagedConnection,
    ) -> list[McpResourceDefinition]:
        try:
            result = await handle.session.list_resources()
        except Exception as error:
            raise McpRuntimeError(str(error)) from error
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
        server_name: str,
        prompt_name: str,
        arguments: dict[str, str] | None = None,
    ) -> Any:
        async def _load(handle: _ManagedConnection) -> Any:
            session = handle.session
            try:
                if hasattr(session, "get_prompt"):
                    return await asyncio.wait_for(
                        session.get_prompt(prompt_name, arguments or {}),
                        timeout=self.settings.mcp.tool_call_timeout_ms / 1000,
                    )
                if hasattr(session, "request"):
                    return await asyncio.wait_for(
                        session.request(
                            {
                                "method": "prompts/get",
                                "params": {"name": prompt_name, "arguments": arguments or {}},
                            }
                        ),
                        timeout=self.settings.mcp.tool_call_timeout_ms / 1000,
                    )
            except asyncio.TimeoutError as error:
                raise McpRuntimeError(
                    f"MCP prompt timed out after {self.settings.mcp.tool_call_timeout_ms} ms"
                ) from error
            except Exception as error:
                raise McpRuntimeError(str(error)) from error
            raise McpRuntimeError("当前 MCP SDK 不支持 prompts/get")

        return await self._invoke_with_handle(server_name, _load)

    async def call_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict[str, object] | None = None,
    ) -> Any:
        async def _call(handle: _ManagedConnection) -> Any:
            try:
                return await asyncio.wait_for(
                    handle.session.call_tool(tool_name, arguments or {}),
                    timeout=self.settings.mcp.tool_call_timeout_ms / 1000,
                )
            except asyncio.TimeoutError as error:
                raise McpRuntimeError(
                    f"MCP tool `{tool_name}` timed out after {self.settings.mcp.tool_call_timeout_ms} ms"
                ) from error
            except Exception as error:
                raise McpRuntimeError(str(error)) from error

        return await self._invoke_with_handle(server_name, _call)

    async def read_resource(self, server_name: str, uri: str) -> Any:
        async def _read(handle: _ManagedConnection) -> Any:
            try:
                return await asyncio.wait_for(
                    handle.session.read_resource(uri),
                    timeout=self.settings.mcp.tool_call_timeout_ms / 1000,
                )
            except asyncio.TimeoutError as error:
                raise McpRuntimeError(
                    f"MCP resource `{uri}` timed out after {self.settings.mcp.tool_call_timeout_ms} ms"
                ) from error
            except Exception as error:
                raise McpRuntimeError(str(error)) from error

        return await self._invoke_with_handle(server_name, _read)

    async def close_all(self) -> None:
        async with self._lock:
            for name in list(self._handles):
                await self._close_handle(name)

    def cached_tools(self) -> dict[str, list[McpToolDefinition]]:
        return {name: list(items) for name, items in self._tool_defs.items()}

    def cached_prompts(self) -> dict[str, list[McpPromptDefinition]]:
        return {name: list(items) for name, items in self._prompt_defs.items()}

    def cached_resources(self) -> dict[str, list[McpResourceDefinition]]:
        return {name: list(items) for name, items in self._resource_defs.items()}

    async def _get_connected_handle(self, name: str) -> _ManagedConnection:
        configs = self.configs()
        config = configs.get(name)
        if config is None:
            raise McpRuntimeError(f"MCP server not found: {name}")
        if config.type == "http":
            raise McpRuntimeError("HTTP MCP handles are request-scoped and must not be reused directly")
        async with self._lock:
            handle = await self._ensure_connection(name, config, force_reconnect=False)
        if handle is None:
            conn = self._connections.get(name)
            detail = conn.error if conn is not None else ""
            raise McpRuntimeError(detail or f"MCP server is not connected: {name}")
        return handle

    async def _invoke_with_handle(
        self,
        name: str,
        operation,
    ):
        configs = self.configs()
        config = configs.get(name)
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
                try:
                    await handle.stack.aclose()
                except Exception:
                    pass
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
        existing = self._handles.get(name)
        if existing is not None and not force_reconnect and existing.config.signature == config.signature:
            self._connections[name] = self._connections.get(
                name,
                McpServerConnection(name=name, status="connected", config=config, updated_at=utc_now()),
            )
            self._connections[name].status = "connected"
            self._connections[name].config = config
            self._connections[name].updated_at = utc_now()
            return existing

        if force_reconnect or existing is not None:
            await self._close_handle(name)

        self._connections[name] = McpServerConnection(
            name=name,
            status="pending",
            config=config,
            updated_at=utc_now(),
        )
        try:
            handle = await self._open_connection(config)
        except Exception as error:
            self._connections[name] = McpServerConnection(
                name=name,
                status="failed",
                config=config,
                error=str(error),
                updated_at=utc_now(),
            )
            return None

        self._handles[name] = handle
        self._connections[name] = McpServerConnection(
            name=name,
            status="connected",
            config=config,
            updated_at=utc_now(),
        )
        return handle

    async def _open_connection(self, config: McpServerConfig) -> _ManagedConnection:
        stack = AsyncExitStack()
        try:
            client_imports = _import_mcp_client()
            if config.type == "stdio":
                params = client_imports["StdioServerParameters"](
                    command=config.command,
                    args=list(config.args),
                    env=config.env or None,
                )
                read_stream, write_stream = await stack.enter_async_context(
                    client_imports["stdio_client"](params)
                )
            elif config.type == "http":
                try:
                    import httpx
                except Exception as error:
                    raise McpRuntimeError(
                        "当前环境缺少 httpx，无法连接 HTTP MCP server。"
                    ) from error
                connect_timeout_s = max(self.settings.mcp.connect_timeout_ms / 1000, 1.0)
                tool_timeout_s = max(self.settings.mcp.tool_call_timeout_ms / 1000, 1.0)
                http_client = await stack.enter_async_context(
                    httpx.AsyncClient(
                        headers=get_server_headers(config) or None,
                        timeout=httpx.Timeout(
                            connect=connect_timeout_s,
                            read=tool_timeout_s,
                            write=tool_timeout_s,
                            pool=connect_timeout_s,
                        ),
                    )
                )
                transport = await stack.enter_async_context(
                    client_imports["streamable_http_client"](
                        config.url,
                        http_client=http_client,
                    )
                )
                read_stream, write_stream = transport[0], transport[1]
            elif config.type == "sse":
                sse_client = client_imports.get("sse_client")
                if sse_client is None:
                    raise McpRuntimeError("当前安装的 mcp SDK 不支持 SSE transport")
                read_stream, write_stream = await stack.enter_async_context(
                    sse_client(
                        config.url,
                        headers=get_server_headers(config) or None,
                    )
                )
            else:
                raise McpRuntimeError(f"当前阶段尚未支持 transport: {config.type}")

            session = await stack.enter_async_context(
                client_imports["ClientSession"](read_stream, write_stream)
            )
            await session.initialize()
            return _ManagedConnection(config=config, stack=stack, session=session)
        except Exception:
            await stack.aclose()
            raise

    async def _open_http_handle(
        self,
        name: str,
        config: McpServerConfig,
    ) -> _ManagedConnection:
        self._connections[name] = McpServerConnection(
            name=name,
            status="pending",
            config=config,
            updated_at=utc_now(),
        )
        try:
            handle = await self._open_connection(config)
        except Exception as error:
            self._connections[name] = McpServerConnection(
                name=name,
                status="failed",
                config=config,
                error=str(error),
                updated_at=utc_now(),
            )
            raise McpRuntimeError(str(error)) from error
        self._connections[name] = McpServerConnection(
            name=name,
            status="connected",
            config=config,
            updated_at=utc_now(),
        )
        return handle

    async def _close_handle(self, name: str) -> None:
        handle = self._handles.pop(name, None)
        if handle is not None:
            await handle.stack.aclose()
        self._tool_defs.pop(name, None)
        self._prompt_defs.pop(name, None)
        self._resource_defs.pop(name, None)

    async def _refresh_http_connection(
        self,
        name: str,
        config: McpServerConfig,
    ) -> None:
        try:
            handle = await self._open_http_handle(name, config)
        except McpRuntimeError:
            self._tool_defs[name] = []
            self._prompt_defs[name] = []
            self._resource_defs[name] = []
            return
        try:
            await self._populate_counts(name, handle)
        finally:
            try:
                await handle.stack.aclose()
            except Exception:
                pass

    async def _populate_counts(self, name: str, handle: _ManagedConnection) -> None:
        connection = self._connections.get(name)
        if connection is None or connection.status != "connected":
            return
        try:
            tools = await self._fetch_tools_for_handle(handle)
        except McpRuntimeError:
            tools = []
        try:
            prompts = await self._fetch_prompts_for_handle(handle)
        except McpRuntimeError:
            prompts = []
        try:
            resources = await self._fetch_resources_for_handle(name, handle)
        except McpRuntimeError:
            resources = []
        self._tool_defs[name] = list(tools)
        self._prompt_defs[name] = list(prompts)
        self._resource_defs[name] = list(resources)
        connection.tool_count = len(tools)
        connection.prompt_count = len(prompts)
        connection.resource_count = len(resources)
        connection.updated_at = utc_now()


def _import_mcp_client() -> dict[str, Any]:
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        from mcp.client.streamable_http import streamable_http_client
    except Exception as error:
        raise McpRuntimeError(
            "MCP Python SDK 未安装或不可用，请先重新安装依赖：pip install --no-cache-dir --force-reinstall ."
        ) from error

    sse_client = None
    try:
        from mcp.client.sse import sse_client as imported_sse_client  # type: ignore
    except Exception:
        imported_sse_client = None
    if imported_sse_client is not None:
        sse_client = imported_sse_client

    return {
        "ClientSession": ClientSession,
        "StdioServerParameters": StdioServerParameters,
        "stdio_client": stdio_client,
        "streamable_http_client": streamable_http_client,
        "sse_client": sse_client,
    }
