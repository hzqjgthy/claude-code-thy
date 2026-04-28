from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from claude_code_thy.mcp import (
    McpClientManager,
    McpRuntimeError,
    add_project_mcp_server,
    get_project_mcp_config_path,
    remove_project_mcp_server,
)
from claude_code_thy.settings import AppSettings


mcp_app = typer.Typer(help="MCP management")
console = Console(stderr=True)


def _is_unsupported_capability_error(error: McpRuntimeError) -> bool:
    """判断错误是否只是服务端不支持某项可选 MCP 能力。"""
    return "method not found" in str(error).lower()


async def _load_optional_capability_async(loader):
    """在同一个事件循环内尝试加载一项可选能力。"""
    try:
        return await loader(), False
    except McpRuntimeError as error:
        if _is_unsupported_capability_error(error):
            return None, True
        raise


def _format_named_items(items, *, unsupported: bool) -> str:
    """把 tools/prompts/resources 列表格式化成命令行可读文本。"""
    if unsupported:
        return "(unsupported)"
    if not items:
        return "(none)"
    return ", ".join(str(getattr(item, "name", "")) for item in items if str(getattr(item, "name", "")).strip()) or "(none)"


def _manager_for_cwd() -> tuple[Path, McpClientManager]:
    """为当前工作目录创建一个临时 MCP manager。"""
    workspace_root = Path(os.getcwd()).resolve()
    settings = AppSettings.load_for_workspace(workspace_root)
    return workspace_root, McpClientManager(workspace_root, settings)


async def _close_manager_quietly(manager) -> None:
    """在命令退出前尽量关闭临时 manager 持有的连接。"""
    close_all = getattr(manager, "close_all", None)
    if close_all is None:
        return
    try:
        await close_all()
    except Exception:
        return


async def _list_mcp_async(manager, *, refresh: bool):
    """在单个事件循环中拉取 MCP 列表快照。"""
    try:
        if refresh:
            return await manager.refresh_all()
        return manager.snapshot()
    finally:
        await _close_manager_quietly(manager)


async def _get_mcp_async(manager, name: str, *, refresh: bool):
    """在单个事件循环中拉取单个 MCP server 的详情及可选能力。"""
    try:
        connection = await manager.get_connection(name, refresh=refresh)
        if connection is None:
            return None
        tools = prompts = resources = None
        tools_unsupported = prompts_unsupported = resources_unsupported = False
        if connection.status == "connected":
            tools, tools_unsupported = await _load_optional_capability_async(
                lambda: manager.list_tools(name)
            )
            prompts, prompts_unsupported = await _load_optional_capability_async(
                lambda: manager.list_prompts(name)
            )
            resources, resources_unsupported = await _load_optional_capability_async(
                lambda: manager.list_resources(name)
            )
        return {
            "connection": connection,
            "tools": tools,
            "tools_unsupported": tools_unsupported,
            "prompts": prompts,
            "prompts_unsupported": prompts_unsupported,
            "resources": resources,
            "resources_unsupported": resources_unsupported,
        }
    finally:
        await _close_manager_quietly(manager)


@mcp_app.command("list")
def list_mcp(refresh: bool = typer.Option(True, "--refresh/--no-refresh", help="Try to connect before listing.")) -> None:
    """列出当前工作区可见的所有 MCP server。"""
    workspace_root, manager = _manager_for_cwd()
    connections = asyncio.run(_list_mcp_async(manager, refresh=refresh))
    table = Table(title=f"MCP Servers · {workspace_root}")
    table.add_column("Name", style="cyan")
    table.add_column("Scope")
    table.add_column("Transport")
    table.add_column("Status")
    table.add_column("Counts")
    table.add_column("Detail")
    for connection in connections:
        counts = f"t:{connection.tool_count} p:{connection.prompt_count} r:{connection.resource_count}"
        detail = connection.error or connection.config.url or connection.config.command
        table.add_row(
            connection.name,
            connection.config.scope,
            connection.config.type,
            connection.status,
            counts,
            detail,
        )
    console.print(table)


@mcp_app.command("get")
def get_mcp(
    name: str = typer.Argument(..., help="Server name."),
    refresh: bool = typer.Option(True, "--refresh/--no-refresh", help="Try to connect before reading details."),
) -> None:
    """显示单个 MCP server 的详细信息。"""
    _, manager = _manager_for_cwd()
    result = asyncio.run(_get_mcp_async(manager, name, refresh=refresh))
    if result is None:
        console.print(f"[red]未找到 MCP server：{name}[/red]")
        raise typer.Exit(code=1)
    connection = result["connection"]
    if connection is None:
        console.print(f"[red]未找到 MCP server：{name}[/red]")
        raise typer.Exit(code=1)

    console.print(f"[bold]Name:[/bold] {connection.name}")
    console.print(f"[bold]Scope:[/bold] {connection.config.scope}")
    console.print(f"[bold]Transport:[/bold] {connection.config.type}")
    console.print(f"[bold]Status:[/bold] {connection.status}")
    if connection.config.url:
        console.print(f"[bold]URL:[/bold] {connection.config.url}")
    if connection.config.command:
        argv = " ".join([connection.config.command, *connection.config.args]).strip()
        console.print(f"[bold]Command:[/bold] {argv}")
    if connection.config.description:
        console.print(f"[bold]Description:[/bold] {connection.config.description}")
    console.print(
        f"[bold]Counts:[/bold] tools={connection.tool_count} prompts={connection.prompt_count} resources={connection.resource_count}"
    )
    if connection.error:
        console.print(f"[bold red]Error:[/bold red] {connection.error}")
        return

    if connection.status == "connected":
        tools = result["tools"]
        tools_unsupported = result["tools_unsupported"]
        prompts = result["prompts"]
        prompts_unsupported = result["prompts_unsupported"]
        resources = result["resources"]
        resources_unsupported = result["resources_unsupported"]
        console.print(f"[bold]Tools:[/bold] {_format_named_items(tools, unsupported=tools_unsupported)}")
        console.print(f"[bold]Prompts:[/bold] {_format_named_items(prompts, unsupported=prompts_unsupported)}")
        console.print(f"[bold]Resources:[/bold] {_format_named_items(resources, unsupported=resources_unsupported)}")


@mcp_app.command("add-json")
def add_mcp_json(
    name: str = typer.Argument(..., help="Server name."),
    config_json: str = typer.Argument(..., help="Raw JSON object."),
) -> None:
    """直接以 JSON 对象形式向项目配置里添加一个 MCP server。"""
    workspace_root, _ = _manager_for_cwd()
    try:
        raw = json.loads(config_json)
    except json.JSONDecodeError as error:
        console.print(f"[red]JSON 解析失败：{error}[/red]")
        raise typer.Exit(code=1) from error
    if not isinstance(raw, dict):
        console.print("[red]config_json 必须是 JSON object。[/red]")
        raise typer.Exit(code=1)
    path = add_project_mcp_server(workspace_root, name, raw)
    console.print(f"[green]已写入：{path}[/green]")


@mcp_app.command("add")
def add_mcp(
    name: str = typer.Argument(..., help="Server name."),
    target: str = typer.Argument(..., help="URL or command."),
    transport: str = typer.Option("stdio", "--transport", "-t", help="stdio/http/sse/ws"),
    description: str = typer.Option("", "--description", help="Optional description."),
    args: list[str] = typer.Option(None, "--arg", help="stdio args, can be repeated."),
) -> None:
    """用更友好的参数形式向项目配置里添加一个 MCP server。"""
    workspace_root, _ = _manager_for_cwd()
    raw: dict[str, object] = {"type": transport}
    if description.strip():
        raw["description"] = description.strip()
    if transport == "stdio":
        raw["command"] = target
        if args:
            raw["args"] = args
    else:
        raw["url"] = target
    path = add_project_mcp_server(workspace_root, name, raw)
    console.print(f"[green]已写入：{path}[/green]")


@mcp_app.command("remove")
def remove_mcp(
    name: str = typer.Argument(..., help="Server name."),
) -> None:
    """从项目级 MCP 配置中删除一个 server。"""
    workspace_root, _ = _manager_for_cwd()
    path = remove_project_mcp_server(workspace_root, name)
    console.print(f"[green]已更新：{path}[/green]")


@mcp_app.command("show-config")
def show_mcp_config() -> None:
    """直接打印当前项目的 MCP 配置文件内容。"""
    workspace_root, _ = _manager_for_cwd()
    path = get_project_mcp_config_path(workspace_root)
    if not path.exists():
        console.print(f"[yellow]当前没有项目级 MCP 配置：{path}[/yellow]")
        raise typer.Exit(code=0)
    console.print(path.read_text(encoding="utf-8"))
