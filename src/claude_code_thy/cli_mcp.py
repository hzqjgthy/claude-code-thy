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
    add_project_mcp_server,
    get_project_mcp_config_path,
    remove_project_mcp_server,
)
from claude_code_thy.mcp.server import serve_mcp_stdio
from claude_code_thy.settings import AppSettings


mcp_app = typer.Typer(help="MCP management")
console = Console(stderr=True)


def _manager_for_cwd() -> tuple[Path, McpClientManager]:
    workspace_root = Path(os.getcwd()).resolve()
    settings = AppSettings.load_for_workspace(workspace_root)
    return workspace_root, McpClientManager(workspace_root, settings)


@mcp_app.command("list")
def list_mcp(refresh: bool = typer.Option(True, "--refresh/--no-refresh", help="Try to connect before listing.")) -> None:
    workspace_root, manager = _manager_for_cwd()
    connections = asyncio.run(manager.refresh_all() if refresh else _snapshot_async(manager))
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
    _, manager = _manager_for_cwd()
    connection = asyncio.run(manager.get_connection(name, refresh=refresh))
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
        tools = asyncio.run(manager.list_tools(name))
        prompts = asyncio.run(manager.list_prompts(name))
        resources = asyncio.run(manager.list_resources(name))
        console.print(f"[bold]Tools:[/bold] {', '.join(tool.name for tool in tools) or '(none)'}")
        console.print(f"[bold]Prompts:[/bold] {', '.join(prompt.name for prompt in prompts) or '(none)'}")
        console.print(f"[bold]Resources:[/bold] {', '.join(resource.name for resource in resources) or '(none)'}")


@mcp_app.command("add-json")
def add_mcp_json(
    name: str = typer.Argument(..., help="Server name."),
    config_json: str = typer.Argument(..., help="Raw JSON object."),
) -> None:
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
    workspace_root, _ = _manager_for_cwd()
    path = remove_project_mcp_server(workspace_root, name)
    console.print(f"[green]已更新：{path}[/green]")


@mcp_app.command("show-config")
def show_mcp_config() -> None:
    workspace_root, _ = _manager_for_cwd()
    path = get_project_mcp_config_path(workspace_root)
    if not path.exists():
        console.print(f"[yellow]当前没有项目级 MCP 配置：{path}[/yellow]")
        raise typer.Exit(code=0)
    console.print(path.read_text(encoding="utf-8"))


@mcp_app.command("serve")
def serve_mcp() -> None:
    asyncio.run(serve_mcp_stdio(os.getcwd()))


async def _snapshot_async(manager: McpClientManager):
    return manager.snapshot()
