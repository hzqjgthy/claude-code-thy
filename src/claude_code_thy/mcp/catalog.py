from __future__ import annotations

from .types import (
    McpPromptDefinition,
    McpResourceDefinition,
    McpServerConfig,
    McpServerConnection,
    McpToolDefinition,
)
from .utils import utc_now


class McpCatalog:
    def __init__(self) -> None:
        self._connections: dict[str, McpServerConnection] = {}
        self._tool_defs: dict[str, list[McpToolDefinition]] = {}
        self._prompt_defs: dict[str, list[McpPromptDefinition]] = {}
        self._resource_defs: dict[str, list[McpResourceDefinition]] = {}

    def snapshot(self, configs: dict[str, McpServerConfig]) -> list[McpServerConnection]:
        known_names = set(configs)
        for name, config in configs.items():
            self.ensure_known(name, config)
        stale = [name for name in self._connections if name not in known_names]
        for name in stale:
            self.remove_server(name)
        return [self._connections[name] for name in sorted(self._connections)]

    def ensure_known(self, name: str, config: McpServerConfig) -> None:
        self._connections.setdefault(
            name,
            self._connection_state(
                name,
                "pending" if config.enabled else "disabled",
                config,
            ),
        )

    def connection(self, name: str) -> McpServerConnection | None:
        return self._connections.get(name)

    def mark_pending(self, name: str, config: McpServerConfig) -> None:
        self._connections[name] = self._connection_state(name, "pending", config)

    def mark_disabled(self, name: str, config: McpServerConfig) -> None:
        self._connections[name] = self._connection_state(name, "disabled", config)

    def mark_failed(self, name: str, config: McpServerConfig, error: str) -> None:
        self._connections[name] = self._connection_state(
            name,
            "failed",
            config,
            error=error,
        )

    def mark_connected(self, name: str, config: McpServerConfig) -> None:
        connection = self._connections.get(name)
        if connection is None:
            self._connections[name] = self._connection_state(name, "connected", config)
            return
        connection.status = "connected"
        connection.config = config
        connection.error = ""
        connection.updated_at = utc_now()

    def remove_server(self, name: str) -> None:
        self._connections.pop(name, None)
        self.clear_definitions(name)

    def clear_definitions(self, name: str) -> None:
        self._tool_defs.pop(name, None)
        self._prompt_defs.pop(name, None)
        self._resource_defs.pop(name, None)

    def set_empty_definitions(self, name: str) -> None:
        self.set_populated(name, tools=[], prompts=[], resources=[])

    def set_tools(self, name: str, definitions: list[McpToolDefinition]) -> None:
        self._tool_defs[name] = list(definitions)
        connection = self._connections.get(name)
        if connection is not None:
            connection.tool_count = len(definitions)
            connection.updated_at = utc_now()

    def set_prompts(self, name: str, definitions: list[McpPromptDefinition]) -> None:
        self._prompt_defs[name] = list(definitions)
        connection = self._connections.get(name)
        if connection is not None:
            connection.prompt_count = len(definitions)
            connection.updated_at = utc_now()

    def set_resources(self, name: str, definitions: list[McpResourceDefinition]) -> None:
        self._resource_defs[name] = list(definitions)
        connection = self._connections.get(name)
        if connection is not None:
            connection.resource_count = len(definitions)
            connection.updated_at = utc_now()

    def set_populated(
        self,
        name: str,
        *,
        tools: list[McpToolDefinition],
        prompts: list[McpPromptDefinition],
        resources: list[McpResourceDefinition],
    ) -> None:
        self._tool_defs[name] = list(tools)
        self._prompt_defs[name] = list(prompts)
        self._resource_defs[name] = list(resources)
        connection = self._connections.get(name)
        if connection is None:
            return
        connection.tool_count = len(tools)
        connection.prompt_count = len(prompts)
        connection.resource_count = len(resources)
        connection.updated_at = utc_now()

    def cached_tools(self) -> dict[str, list[McpToolDefinition]]:
        return {name: list(items) for name, items in self._tool_defs.items()}

    def cached_prompts(self) -> dict[str, list[McpPromptDefinition]]:
        return {name: list(items) for name, items in self._prompt_defs.items()}

    def cached_resources(self) -> dict[str, list[McpResourceDefinition]]:
        return {name: list(items) for name, items in self._resource_defs.items()}

    def _connection_state(
        self,
        name: str,
        status: str,
        config: McpServerConfig,
        *,
        error: str = "",
    ) -> McpServerConnection:
        return McpServerConnection(
            name=name,
            status=status,
            config=config,
            error=error,
            updated_at=utc_now(),
        )
