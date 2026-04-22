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
    """集中保存 MCP 连接状态以及工具、prompt、资源三类定义缓存。"""
    def __init__(self) -> None:
        """初始化连接快照和定义缓存。"""
        self._connections: dict[str, McpServerConnection] = {}
        self._tool_defs: dict[str, list[McpToolDefinition]] = {}
        self._prompt_defs: dict[str, list[McpPromptDefinition]] = {}
        self._resource_defs: dict[str, list[McpResourceDefinition]] = {}

    def snapshot(self, configs: dict[str, McpServerConfig]) -> list[McpServerConnection]:
        """根据最新配置补齐、删除 server，并返回排序后的连接快照。"""
        known_names = set(configs)
        for name, config in configs.items():
            self.ensure_known(name, config)
        stale = [name for name in self._connections if name not in known_names]
        for name in stale:
            self.remove_server(name)
        return [self._connections[name] for name in sorted(self._connections)]

    def ensure_known(self, name: str, config: McpServerConfig) -> None:
        """确保 catalog 至少有一条该 server 的基础连接记录。"""
        self._connections.setdefault(
            name,
            self._connection_state(
                name,
                "pending" if config.enabled else "disabled",
                config,
            ),
        )

    def connection(self, name: str) -> McpServerConnection | None:
        """按名称读取单个 server 的连接记录。"""
        return self._connections.get(name)

    def mark_pending(self, name: str, config: McpServerConfig) -> None:
        """把 server 状态更新为等待连接。"""
        self._connections[name] = self._connection_state(name, "pending", config)

    def mark_disabled(self, name: str, config: McpServerConfig) -> None:
        """把 server 状态更新为已禁用。"""
        self._connections[name] = self._connection_state(name, "disabled", config)

    def mark_failed(self, name: str, config: McpServerConfig, error: str) -> None:
        """把 server 状态更新为失败，并记录错误文本。"""
        self._connections[name] = self._connection_state(
            name,
            "failed",
            config,
            error=error,
        )

    def mark_connected(self, name: str, config: McpServerConfig) -> None:
        """把 server 标记为已连接，并刷新时间戳。"""
        connection = self._connections.get(name)
        if connection is None:
            self._connections[name] = self._connection_state(name, "connected", config)
            return
        connection.status = "connected"
        connection.config = config
        connection.error = ""
        connection.updated_at = utc_now()

    def remove_server(self, name: str) -> None:
        """移除一个已不再存在的 server 及其全部缓存。"""
        self._connections.pop(name, None)
        self.clear_definitions(name)

    def clear_definitions(self, name: str) -> None:
        """清空某个 server 的工具、prompt 和资源定义缓存。"""
        self._tool_defs.pop(name, None)
        self._prompt_defs.pop(name, None)
        self._resource_defs.pop(name, None)

    def set_empty_definitions(self, name: str) -> None:
        """把某个 server 的三类定义统一设置为空列表。"""
        self.set_populated(name, tools=[], prompts=[], resources=[])

    def set_tools(self, name: str, definitions: list[McpToolDefinition]) -> None:
        """写入工具定义缓存，并同步更新连接统计。"""
        self._tool_defs[name] = list(definitions)
        connection = self._connections.get(name)
        if connection is not None:
            connection.tool_count = len(definitions)
            connection.updated_at = utc_now()

    def set_prompts(self, name: str, definitions: list[McpPromptDefinition]) -> None:
        """写入 prompt 定义缓存，并同步更新连接统计。"""
        self._prompt_defs[name] = list(definitions)
        connection = self._connections.get(name)
        if connection is not None:
            connection.prompt_count = len(definitions)
            connection.updated_at = utc_now()

    def set_resources(self, name: str, definitions: list[McpResourceDefinition]) -> None:
        """写入资源定义缓存，并同步更新连接统计。"""
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
        """一次性写入三类定义缓存，并更新连接统计。"""
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
        """返回工具缓存的浅拷贝，避免外部直接修改内部状态。"""
        return {name: list(items) for name, items in self._tool_defs.items()}

    def cached_prompts(self) -> dict[str, list[McpPromptDefinition]]:
        """返回 prompt 缓存的浅拷贝。"""
        return {name: list(items) for name, items in self._prompt_defs.items()}

    def cached_resources(self) -> dict[str, list[McpResourceDefinition]]:
        """返回资源缓存的浅拷贝。"""
        return {name: list(items) for name, items in self._resource_defs.items()}

    def _connection_state(
        self,
        name: str,
        status: str,
        config: McpServerConfig,
        *,
        error: str = "",
    ) -> McpServerConnection:
        """构造一条带当前时间戳的标准连接记录。"""
        return McpServerConnection(
            name=name,
            status=status,
            config=config,
            error=error,
            updated_at=utc_now(),
        )
