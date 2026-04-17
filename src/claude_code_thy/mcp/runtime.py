from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from typing import Any

from claude_code_thy.settings import AppSettings
from claude_code_thy.skills import PromptCommandSpec, build_mcp_prompt_specs, build_mcp_skill_spec, discover_mcp_skill_resources

from .auth import supports_oauth
from .client import McpClientManager, McpRuntimeError
from .names import build_mcp_tool_name
from .transport import _ManagedConnection
from .types import McpServerConfig, McpServerConnection, McpToolDefinition
from .utils import run_async_sync


class McpRuntimeManager:
    def __init__(self, workspace_root: Path, settings: AppSettings) -> None:
        self.workspace_root = workspace_root
        self.settings = settings
        self._client = McpClientManager(workspace_root, settings)
        self._tool_defs: dict[str, list[McpToolDefinition]] = {}
        self._prompt_command_specs: dict[str, list[PromptCommandSpec]] = {}
        self._skill_command_specs: dict[str, list[PromptCommandSpec]] = {}
        self._needs_auth: dict[str, McpServerConfig] = {}
        self._notification_registered: set[str] = set()

    @property
    def _handles(self) -> dict[str, _ManagedConnection]:
        return self._client._handles

    def configs(self) -> dict[str, McpServerConfig]:
        return self._client.configs()

    def snapshot(self) -> list[McpServerConnection]:
        connections: list[McpServerConnection] = []
        for connection in self._client.snapshot():
            if connection.name in self._needs_auth:
                connections.append(
                    replace(
                        connection,
                        status="needs-auth",
                        error="",
                        tool_count=1,
                    )
                )
                continue
            if connection.status != "connected":
                connections.append(connection)
                continue
            connections.append(
                replace(
                    connection,
                    tool_count=len(self._tool_defs.get(connection.name, [])),
                    prompt_count=len(self._prompt_command_specs.get(connection.name, [])),
                    resource_count=len(self.cached_resources().get(connection.name, [])),
                )
            )
        return connections

    async def refresh_all(self) -> list[McpServerConnection]:
        connections = await self._client.refresh_all()
        await self._sync_after_refresh(connections)
        return self.snapshot()

    async def refresh_server(self, server_name: str) -> McpServerConnection | None:
        connection = await self._client.get_connection(server_name, refresh=True)
        await self._sync_after_refresh(self._client.snapshot())
        for item in self.snapshot():
            if item.name == server_name:
                return item
        return connection

    def refresh_server_sync(self, server_name: str) -> McpServerConnection | None:
        return run_async_sync(self.refresh_server(server_name), timeout=60)

    async def get_connection(self, name: str, *, refresh: bool = False) -> McpServerConnection | None:
        connection = await self._client.get_connection(name, refresh=refresh)
        if refresh:
            await self._sync_after_refresh(self._client.snapshot())
        if connection is None:
            return None
        for item in self.snapshot():
            if item.name == name:
                return item
        return connection

    async def list_tools(self, name: str) -> list[McpToolDefinition]:
        if name in self._needs_auth:
            return [self._auth_tool_definition(name)]
        try:
            definitions = await self._client.list_tools(name)
        except McpRuntimeError as error:
            self._handle_auth_error(name, error)
            raise
        self._tool_defs[name] = list(definitions)
        await self._register_notification_handlers()
        return definitions

    async def list_prompts(self, name: str):
        try:
            prompts = await self._client.list_prompts(name)
        except McpRuntimeError as error:
            self._handle_auth_error(name, error)
            raise
        self._prompt_command_specs[name] = build_mcp_prompt_specs(name, prompts)
        await self._register_notification_handlers()
        return prompts

    async def list_resources(self, name: str):
        try:
            resources = await self._client.list_resources(name)
        except McpRuntimeError as error:
            self._handle_auth_error(name, error)
            raise
        await self._rebuild_skill_commands_for_server(name, resources)
        await self._register_notification_handlers()
        return resources

    async def get_prompt(
        self,
        server_name: str,
        prompt_name: str,
        arguments: dict[str, str] | None = None,
    ) -> Any:
        try:
            return await self._client.get_prompt(server_name, prompt_name, arguments)
        except McpRuntimeError as error:
            self._handle_auth_error(server_name, error)
            raise

    def get_prompt_sync(
        self,
        server_name: str,
        prompt_name: str,
        arguments: dict[str, str] | None = None,
    ) -> Any:
        return run_async_sync(self.get_prompt(server_name, prompt_name, arguments), timeout=30)

    async def call_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict[str, object] | None = None,
    ) -> Any:
        try:
            return await self._client.call_tool(server_name, tool_name, arguments)
        except McpRuntimeError as error:
            self._handle_auth_error(server_name, error)
            raise

    async def read_resource(self, server_name: str, uri: str) -> Any:
        try:
            return await self._client.read_resource(server_name, uri)
        except McpRuntimeError as error:
            self._handle_auth_error(server_name, error)
            raise

    def cached_tools(self) -> dict[str, list[McpToolDefinition]]:
        result = {name: list(defs) for name, defs in self._tool_defs.items()}
        for name in self._needs_auth:
            result[name] = [self._auth_tool_definition(name)]
        return result

    def cached_prompts(self):
        if hasattr(self._client, "cached_prompts"):
            return self._client.cached_prompts()
        return {}

    def cached_resources(self):
        if hasattr(self._client, "cached_resources"):
            return self._client.cached_resources()
        return {}

    def cached_prompt_commands(self) -> list[PromptCommandSpec]:
        commands: list[PromptCommandSpec] = []
        for items in self._prompt_command_specs.values():
            commands.extend(items)
        return sorted(commands, key=lambda item: item.name)

    def cached_skill_commands(self) -> list[PromptCommandSpec]:
        commands: list[PromptCommandSpec] = []
        for items in self._skill_command_specs.values():
            commands.extend(items)
        return sorted(commands, key=lambda item: item.name)

    async def _sync_after_refresh(self, connections: list[McpServerConnection]) -> None:
        self._tool_defs = self._client.cached_tools()
        prompt_defs = self._client.cached_prompts()
        resource_defs = self._client.cached_resources()

        active_servers = {connection.name for connection in connections if connection.status == "connected"}
        self._tool_defs = {
            name: defs
            for name, defs in self._tool_defs.items()
            if name in active_servers and name not in self._needs_auth
        }
        self._prompt_command_specs = {
            name: build_mcp_prompt_specs(name, defs)
            for name, defs in prompt_defs.items()
            if name in active_servers
        }
        for connection in connections:
            if connection.name in active_servers:
                self._clear_auth_required(connection.name)
        for connection in connections:
            if connection.status == "failed":
                self._handle_failed_connection(connection)

        for server_name, resources in resource_defs.items():
            if server_name not in active_servers or server_name in self._needs_auth:
                self._skill_command_specs.pop(server_name, None)
                continue
            await self._rebuild_skill_commands_for_server(server_name, resources)

        stale = {
            name
            for name in set(self._skill_command_specs) | set(self._prompt_command_specs) | set(self._tool_defs)
            if name not in active_servers and name not in self._needs_auth
        }
        for name in stale:
            self._tool_defs.pop(name, None)
            self._prompt_command_specs.pop(name, None)
            self._skill_command_specs.pop(name, None)

        await self._register_notification_handlers()

    async def _rebuild_skill_commands_for_server(
        self,
        server_name: str,
        resources,
    ) -> None:
        commands: list[PromptCommandSpec] = []
        for resource in discover_mcp_skill_resources(list(resources)):
            try:
                result = await self._client.read_resource(server_name, resource.uri)
            except McpRuntimeError as error:
                self._handle_auth_error(server_name, error)
                continue
            command = build_mcp_skill_spec(server_name, resource, result)
            if command is not None:
                commands.append(command)
        self._skill_command_specs[server_name] = commands

    async def _register_notification_handlers(self) -> None:
        for server_name, handle in self._handles.items():
            if server_name in self._notification_registered:
                continue
            session = handle.session
            setter = getattr(session, "set_notification_handler", None)
            if not callable(setter):
                continue
            registered = False
            registered = self._register_notification_handler(setter, "tools", server_name) or registered
            registered = self._register_notification_handler(setter, "prompts", server_name) or registered
            registered = self._register_notification_handler(setter, "resources", server_name) or registered
            if registered:
                self._notification_registered.add(server_name)

    def _register_notification_handler(
        self,
        setter,
        kind: str,
        server_name: str,
    ) -> bool:
        def _handler(*_args, **_kwargs) -> None:
            self._schedule_refresh(server_name)

        schema = _notification_schema(kind)
        method = f"notifications/{kind}/list_changed"
        for target in [schema, method]:
            if target is None:
                continue
            try:
                setter(target, _handler)
                return True
            except Exception:
                continue
        return False

    def _schedule_refresh(self, server_name: str) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            run_async_sync(self.refresh_server(server_name), timeout=60)
            return
        loop.create_task(self.refresh_server(server_name))

    def _handle_failed_connection(self, connection: McpServerConnection) -> None:
        if self._is_auth_error(connection.config, connection.error):
            self._mark_auth_required(connection.name, connection.config)
            return
        self._tool_defs.pop(connection.name, None)
        self._prompt_command_specs.pop(connection.name, None)
        self._skill_command_specs.pop(connection.name, None)

    def _handle_auth_error(self, server_name: str, error: Exception) -> None:
        config = self.configs().get(server_name)
        if config is None:
            return
        if self._is_auth_error(config, str(error)):
            self._mark_auth_required(server_name, config)

    def _is_auth_error(self, config: McpServerConfig, error_text: str) -> bool:
        if not supports_oauth(config):
            return False
        normalized = error_text.lower()
        return any(
            token in normalized
            for token in ("401", "unauthorized", "authorization", "oauth", "auth required")
        )

    def _mark_auth_required(self, server_name: str, config: McpServerConfig) -> None:
        self._needs_auth[server_name] = config
        self._tool_defs.pop(server_name, None)
        self._prompt_command_specs.pop(server_name, None)
        self._skill_command_specs.pop(server_name, None)

    def _clear_auth_required(self, server_name: str) -> None:
        self._needs_auth.pop(server_name, None)

    def _auth_tool_definition(self, server_name: str) -> McpToolDefinition:
        return McpToolDefinition(
            name="authenticate",
            description=f"Authenticate MCP server `{server_name}`.",
            input_schema={"type": "object", "properties": {}},
            annotations={
                "authTool": True,
                "original_name": "authenticate",
                "readOnlyHint": False,
            },
        )


def _notification_schema(kind: str):
    try:
        import importlib

        module = importlib.import_module("mcp.types")
    except Exception:
        return None
    names = {
        "tools": "ToolListChangedNotificationSchema",
        "prompts": "PromptListChangedNotificationSchema",
        "resources": "ResourceListChangedNotificationSchema",
    }
    return getattr(module, names[kind], None)
