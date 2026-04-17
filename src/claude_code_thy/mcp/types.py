from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


ConfigScope = Literal["local", "user", "project", "dynamic", "enterprise", "claudeai", "managed"]
TransportType = Literal["stdio", "sse", "http", "ws", "sdk", "sse-ide", "claudeai-proxy"]
ConnectionStatus = Literal["connected", "failed", "needs-auth", "pending", "disabled"]


@dataclass(slots=True)
class McpServerConfig:
    name: str
    scope: ConfigScope
    type: TransportType = "stdio"
    description: str = ""
    command: str = ""
    args: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    headers_helper: str = ""
    oauth: dict[str, object] = field(default_factory=dict)
    enabled: bool = True
    raw_config: dict[str, object] = field(default_factory=dict)

    @property
    def signature(self) -> tuple[object, ...]:
        return (
            self.type,
            self.command,
            self.args,
            tuple(sorted(self.env.items())),
            self.url,
            tuple(sorted(self.headers.items())),
            self.headers_helper,
            tuple(sorted(self.oauth.items())),
            self.enabled,
        )


@dataclass(slots=True)
class McpServerConnection:
    name: str
    status: ConnectionStatus
    config: McpServerConfig
    error: str = ""
    updated_at: str = ""
    capabilities: tuple[str, ...] = ()
    tool_count: int = 0
    prompt_count: int = 0
    resource_count: int = 0
    instructions: str = ""
    server_label: str = ""


@dataclass(slots=True)
class McpToolDefinition:
    name: str
    description: str
    input_schema: dict[str, object]
    annotations: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class McpPromptDefinition:
    name: str
    description: str
    arguments: tuple[str, ...] = ()


@dataclass(slots=True)
class McpResourceDefinition:
    uri: str
    name: str
    server: str
    description: str = ""
    mime_type: str = ""
