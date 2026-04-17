from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Any

from claude_code_thy.settings import AppSettings

from .catalog import McpCatalog
from .errors import McpRuntimeError
from .headers import get_server_headers
from .types import McpServerConfig


@dataclass(slots=True)
class _ManagedConnection:
    config: McpServerConfig
    stack: AsyncExitStack
    session: Any


class McpTransportLayer:
    def __init__(self, settings: AppSettings, catalog: McpCatalog) -> None:
        self.settings = settings
        self.catalog = catalog
        self._handles: dict[str, _ManagedConnection] = {}
        self._lock = asyncio.Lock()

    @property
    def handles(self) -> dict[str, _ManagedConnection]:
        return self._handles

    @property
    def lock(self) -> asyncio.Lock:
        return self._lock

    def connect_timeout_seconds(self) -> float:
        return max(self.settings.mcp.connect_timeout_ms / 1000, 1.0)

    def tool_timeout_seconds(self) -> float:
        return max(self.settings.mcp.tool_call_timeout_ms / 1000, 1.0)

    async def get_persistent_handle(
        self,
        name: str,
        config: McpServerConfig,
        *,
        force_reconnect: bool,
        open_connection,
    ) -> _ManagedConnection | None:
        existing = self._handles.get(name)
        if existing is not None and not force_reconnect and existing.config.signature == config.signature:
            self.catalog.mark_connected(name, config)
            return existing

        if force_reconnect or existing is not None:
            await self.close_handle(name)

        self.catalog.mark_pending(name, config)
        try:
            handle = await open_connection(config)
        except Exception as error:
            self.catalog.mark_failed(name, config, str(error))
            return None

        self._handles[name] = handle
        self.catalog.mark_connected(name, config)
        return handle

    async def open_request_scoped_handle(
        self,
        name: str,
        config: McpServerConfig,
        *,
        open_connection,
    ) -> _ManagedConnection:
        self.catalog.mark_pending(name, config)
        try:
            handle = await open_connection(config)
        except Exception as error:
            self.catalog.mark_failed(name, config, str(error))
            raise McpRuntimeError(str(error)) from error
        self.catalog.mark_connected(name, config)
        return handle

    async def close_handle(self, name: str) -> None:
        handle = self._handles.pop(name, None)
        if handle is not None:
            await handle.stack.aclose()

    async def close_all(self) -> None:
        for name in list(self._handles):
            await self.close_handle(name)

    async def open_connection(self, config: McpServerConfig) -> _ManagedConnection:
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
                connect_timeout_s = self.connect_timeout_seconds()
                tool_timeout_s = self.tool_timeout_seconds()
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
            await self.close_stack_quietly(stack)
            raise

    async def run_session_call(
        self,
        operation,
        *,
        timeout_message: str | None = None,
    ) -> Any:
        try:
            if timeout_message is not None:
                return await asyncio.wait_for(
                    operation(),
                    timeout=self.tool_timeout_seconds(),
                )
            return await operation()
        except asyncio.TimeoutError as error:
            raise McpRuntimeError(timeout_message or "MCP request timed out") from error
        except Exception as error:
            raise McpRuntimeError(str(error)) from error

    async def close_stack_quietly(self, stack: AsyncExitStack) -> None:
        try:
            await stack.aclose()
        except Exception:
            pass


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
