from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from claude_code_thy.models import SessionTranscript
from claude_code_thy.tools import ToolRuntime, build_builtin_tools


async def serve_mcp_stdio(cwd: str) -> None:
    """处理 `serve_mcp_stdio`。"""
    try:
        from mcp.server.lowlevel import NotificationOptions, Server
        from mcp.server.stdio import stdio_server
        from mcp.types import CallToolResult, TextContent, Tool
        from mcp.server.models import InitializationOptions
    except Exception as error:
        raise RuntimeError(
            "MCP Python SDK 未安装或不可用，请先重新安装依赖：pip install --no-cache-dir --force-reinstall ."
        ) from error

    runtime = ToolRuntime(build_builtin_tools())
    session = SessionTranscript(
        session_id="mcp-server",
        cwd=str(Path(cwd).resolve()),
        model="mcp-server",
        provider_name="mcp-server",
    )
    server = Server("claude-code-thy")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        """列出 `tools`。"""
        tools: list[Tool] = []
        for spec in runtime.list_tool_specs():
            tools.append(
                Tool(
                    name=spec.name,
                    description=spec.description,
                    inputSchema=spec.input_schema,
                )
            )
        return tools

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> CallToolResult:
        """处理 `call_tool`。"""
        result = runtime.execute_input(
            name,
            arguments or {},
            session,
        )
        content = result.content_for_model()
        if isinstance(content, str):
            payload = content
        else:
            payload = json.dumps(content, ensure_ascii=False)
        return CallToolResult(
            content=[TextContent(type="text", text=payload)],
            isError=not result.ok,
        )

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="claude-code-thy",
                server_version="0.1.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )
