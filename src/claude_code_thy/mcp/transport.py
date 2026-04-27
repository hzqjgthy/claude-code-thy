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
    """保存一次 MCP 连接的配置、资源清理栈和 session 对象。"""
    config: McpServerConfig
    stack: AsyncExitStack
    session: Any


class McpTransportLayer:
    """负责建立、复用和关闭不同 transport 类型的 MCP 连接。"""
    def __init__(self, settings: AppSettings, catalog: McpCatalog) -> None:
        """保存 settings、catalog 和连接缓存。"""
        self.settings = settings
        self.catalog = catalog
        self._handles: dict[str, _ManagedConnection] = {}
        self._lock = asyncio.Lock()

    @property
    def handles(self) -> dict[str, _ManagedConnection]:
        """暴露当前持久连接句柄缓存。"""
        return self._handles

    @property
    def lock(self) -> asyncio.Lock:
        """暴露连接级互斥锁，避免并发刷新打架。"""
        return self._lock

    def connect_timeout_seconds(self) -> float:
        """把设置里的连接超时毫秒值转换成秒。"""
        return max(self.settings.mcp.connect_timeout_ms / 1000, 1.0)

    def tool_timeout_seconds(self) -> float:
        """把设置里的工具调用超时毫秒值转换成秒。"""
        return max(self.settings.mcp.tool_call_timeout_ms / 1000, 1.0)

    def close_timeout_seconds(self) -> float:
        """限制 MCP 清理阶段的最长等待时间，避免关闭卡住整个 CLI。"""
        return max(min(self.connect_timeout_seconds(), 5.0), 3.0)

    async def get_persistent_handle(
        self,
        name: str,
        config: McpServerConfig,
        *,
        force_reconnect: bool,
        open_connection,
    ) -> _ManagedConnection | None:
        """获取或重建一个可复用的持久连接句柄。"""
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
        """为 HTTP 请求打开一次性连接，用后由调用方负责关闭。"""
        self.catalog.mark_pending(name, config)
        try:
            handle = await open_connection(config)
        except Exception as error:
            self.catalog.mark_failed(name, config, str(error))
            raise McpRuntimeError(str(error)) from error
        self.catalog.mark_connected(name, config)
        return handle

    async def close_handle(self, name: str) -> None:
        """关闭并移除一个持久连接句柄。"""
        handle = self._handles.pop(name, None)
        if handle is not None:
            await self.close_stack_quietly(handle.stack)

    async def close_all(self) -> None:
        """关闭所有持久连接。"""
        for name in list(self._handles):
            await self.close_handle(name)

    async def open_connection(self, config: McpServerConfig) -> _ManagedConnection:
        """按 transport 类型建立 MCP 连接，并完成 session.initialize。"""
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
        except asyncio.CancelledError as error:
            await self.close_stack_quietly(stack)
            raise McpRuntimeError("MCP session initialization was cancelled") from error
        except Exception:
            await self.close_stack_quietly(stack)
            raise

    async def run_session_call(
        self,
        operation,
        *,
        timeout_message: str | None = None,
    ) -> Any:
        """给 session 操作统一包一层超时和异常转换。"""
        try:
            if timeout_message is not None:
                return await asyncio.wait_for(
                    operation(),
                    timeout=self.tool_timeout_seconds(),
                )
            return await operation()
        except asyncio.TimeoutError as error:
            raise McpRuntimeError(timeout_message or "MCP request timed out") from error
        except asyncio.CancelledError as error:
            raise McpRuntimeError("MCP request was cancelled") from error
        except Exception as error:
            raise McpRuntimeError(str(error)) from error

    async def close_stack_quietly(self, stack: AsyncExitStack) -> None:
        """静默关闭 AsyncExitStack，不把清理异常继续抛出。"""
        try:
            await asyncio.wait_for(
                stack.aclose(),
                timeout=self.close_timeout_seconds(),
            )
        except asyncio.CancelledError:
            pass
        except asyncio.TimeoutError:
            pass
        except Exception:
            pass


def _import_mcp_client() -> dict[str, Any]:
    """延迟导入 MCP SDK，并兼容不同版本里可选的 SSE 客户端。"""
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
