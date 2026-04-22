from __future__ import annotations

from pathlib import Path

from claude_code_thy.settings import AppSettings, McpSettings

from .env_expansion import expand_env_vars
from .types import McpServerConfig
from .utils import read_json_file, write_json_file


MCP_JSON_FILENAME = ".mcp.json"


def get_project_mcp_config_path(workspace_root: Path) -> Path:
    """返回 `project_mcp_config_path`。"""
    return workspace_root / MCP_JSON_FILENAME


def get_all_mcp_configs(
    workspace_root: Path,
    settings: AppSettings,
) -> dict[str, McpServerConfig]:
    """返回 `all_mcp_configs`。"""
    configs: dict[str, McpServerConfig] = {}
    if settings.mcp.enabled:
        configs.update(_configs_from_settings(settings.mcp))
    configs.update(_configs_from_project_file(workspace_root))
    return configs


def add_project_mcp_server(
    workspace_root: Path,
    name: str,
    raw_config: dict[str, object],
) -> Path:
    """添加 `project_mcp_server`。"""
    path = get_project_mcp_config_path(workspace_root)
    current = read_json_file(path) or {}
    servers = current.get("mcpServers")
    if not isinstance(servers, dict):
        servers = {}
    servers[name] = raw_config
    current["mcpServers"] = servers
    write_json_file(path, current)
    return path


def remove_project_mcp_server(workspace_root: Path, name: str) -> Path:
    """移除 `project_mcp_server`。"""
    path = get_project_mcp_config_path(workspace_root)
    current = read_json_file(path) or {}
    servers = current.get("mcpServers")
    if not isinstance(servers, dict):
        servers = {}
    servers.pop(name, None)
    current["mcpServers"] = servers
    write_json_file(path, current)
    return path


def _configs_from_settings(settings: McpSettings) -> dict[str, McpServerConfig]:
    """处理 `configs_from_settings`。"""
    configs: dict[str, McpServerConfig] = {}
    for name, raw in settings.servers.items():
        try:
            configs[name] = parse_server_config(name, raw, scope="local")
        except ValueError:
            continue
    return configs


def _configs_from_project_file(workspace_root: Path) -> dict[str, McpServerConfig]:
    """处理 `configs_from_project_file`。"""
    path = get_project_mcp_config_path(workspace_root)
    data = read_json_file(path)
    if not data:
        return {}
    raw_servers = data.get("mcpServers")
    if not isinstance(raw_servers, dict):
        return {}
    configs: dict[str, McpServerConfig] = {}
    for name, raw in raw_servers.items():
        if not isinstance(raw, dict):
            continue
        try:
            configs[str(name)] = parse_server_config(str(name), raw, scope="project")
        except ValueError:
            continue
    return configs


def parse_server_config(
    name: str,
    raw: dict[str, object],
    *,
    scope: str,
) -> McpServerConfig:
    """解析 `server_config`。"""
    transport = str(raw.get("type", "stdio")).strip() or "stdio"
    if transport not in {"stdio", "sse", "http", "ws", "sdk", "sse-ide", "claudeai-proxy"}:
        raise ValueError(f"unsupported MCP transport: {transport}")

    command = str(raw.get("command", "")).strip()
    url = str(raw.get("url", "")).strip()
    if transport == "stdio" and not command:
        raise ValueError("stdio MCP server requires command")
    if transport in {"sse", "http", "ws", "claudeai-proxy"} and not url:
        raise ValueError(f"{transport} MCP server requires url")

    args_raw = raw.get("args", [])
    args = tuple(str(item) for item in args_raw) if isinstance(args_raw, list) else ()
    env_raw = raw.get("env", {})
    env = (
        {str(key): expand_env_vars(str(value)) for key, value in env_raw.items()}
        if isinstance(env_raw, dict)
        else {}
    )
    headers_raw = raw.get("headers", {})
    headers = (
        {str(key): str(value) for key, value in headers_raw.items()}
        if isinstance(headers_raw, dict)
        else {}
    )
    oauth_raw = raw.get("oauth", {})
    oauth = (
        {str(key): value for key, value in oauth_raw.items()}
        if isinstance(oauth_raw, dict)
        else {}
    )
    return McpServerConfig(
        name=name,
        scope=scope,  # type: ignore[arg-type]
        type=transport,  # type: ignore[arg-type]
        description=str(raw.get("description", "")).strip(),
        command=expand_env_vars(command),
        args=args,
        env=env,
        url=expand_env_vars(url),
        headers=headers,
        headers_helper=str(raw.get("headersHelper", "")).strip(),
        oauth=oauth,
        enabled=bool(raw.get("enabled", True)),
        raw_config={str(key): value for key, value in raw.items()},
    )
