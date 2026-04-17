import json
import asyncio
import time

from claude_code_thy.mcp.client import McpClientManager, McpRuntimeError, _ManagedConnection
from claude_code_thy.mcp.config import (
    add_project_mcp_server,
    get_all_mcp_configs,
    get_project_mcp_config_path,
    remove_project_mcp_server,
)
from claude_code_thy.settings import AppSettings
from claude_code_thy.mcp.utils import run_async_sync


def test_add_and_remove_project_mcp_server(tmp_path):
    add_project_mcp_server(
        tmp_path,
        "demo",
        {"type": "http", "url": "http://localhost:18060/mcp"},
    )
    path = get_project_mcp_config_path(tmp_path)
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["mcpServers"]["demo"]["url"] == "http://localhost:18060/mcp"

    remove_project_mcp_server(tmp_path, "demo")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["mcpServers"] == {}


def test_get_all_mcp_configs_reads_project_file(tmp_path):
    add_project_mcp_server(
        tmp_path,
        "xiaohongshu-mcp",
        {"type": "http", "url": "http://localhost:18060/mcp", "description": "小红书 MCP"},
    )
    settings = AppSettings()
    configs = get_all_mcp_configs(tmp_path, settings)
    assert "xiaohongshu-mcp" in configs
    assert configs["xiaohongshu-mcp"].type == "http"
    assert configs["xiaohongshu-mcp"].scope == "project"


def test_mcp_manager_snapshot_returns_pending_for_enabled_configs(tmp_path):
    add_project_mcp_server(
        tmp_path,
        "demo",
        {"type": "http", "url": "http://localhost:18060/mcp"},
    )
    manager = McpClientManager(tmp_path, AppSettings())
    snapshot = manager.snapshot()
    assert len(snapshot) == 1
    assert snapshot[0].name == "demo"
    assert snapshot[0].status == "pending"


def test_mcp_manager_get_connection_without_refresh_returns_pending_config(tmp_path):
    add_project_mcp_server(
        tmp_path,
        "demo",
        {"type": "http", "url": "http://localhost:18060/mcp"},
    )
    manager = McpClientManager(tmp_path, AppSettings())
    connection = asyncio.run(manager.get_connection("demo", refresh=False))
    assert connection is not None
    assert connection.name == "demo"
    assert connection.status == "pending"


def test_run_async_sync_reuses_same_background_loop_inside_async_context():
    async def current_loop_id() -> int:
        return id(asyncio.get_running_loop())

    async def run() -> tuple[int, int]:
        first = run_async_sync(current_loop_id())
        second = run_async_sync(current_loop_id())
        return first, second

    first, second = asyncio.run(run())
    assert first == second


def test_run_async_sync_timeout_returns_promptly():
    async def slow():
        await asyncio.sleep(0.2)
        return "done"

    started = time.monotonic()
    try:
        run_async_sync(slow(), timeout=0.05)
    except TimeoutError:
        elapsed = time.monotonic() - started
        assert elapsed < 1
    else:
        raise AssertionError("Expected TimeoutError")


def test_mcp_call_tool_times_out(tmp_path):
    add_project_mcp_server(
        tmp_path,
        "demo",
        {"type": "http", "url": "http://localhost:18060/mcp"},
    )
    settings = AppSettings()
    settings.mcp.tool_call_timeout_ms = 50
    manager = McpClientManager(tmp_path, settings)

    class DummyStack:
        async def aclose(self) -> None:
            return None

    class DummySession:
        async def call_tool(self, tool_name, arguments=None):
            await asyncio.sleep(0.2)
            return {"tool_name": tool_name, "arguments": arguments or {}}

    async def fake_open_connection(config):
        return _ManagedConnection(
            config=config,
            stack=DummyStack(),
            session=DummySession(),
        )

    manager._open_connection = fake_open_connection  # type: ignore[method-assign]

    started = time.monotonic()
    try:
        asyncio.run(manager.call_tool("demo", "slow_tool", {}))
    except McpRuntimeError as error:
        elapsed = time.monotonic() - started
        assert "timed out" in str(error)
        assert elapsed < 1
    else:
        raise AssertionError("Expected McpRuntimeError timeout")


def test_http_refresh_all_does_not_persist_handles(tmp_path):
    add_project_mcp_server(
        tmp_path,
        "demo",
        {"type": "http", "url": "http://localhost:18060/mcp"},
    )
    manager = McpClientManager(tmp_path, AppSettings())
    closed = {"value": 0}

    class DummyStack:
        async def aclose(self) -> None:
            closed["value"] += 1

    class DummyTool:
        def __init__(self, name: str) -> None:
            self.name = name
            self.description = f"tool:{name}"
            self.inputSchema = {"type": "object", "properties": {}}
            self.annotations = {}

    class DummyToolListResult:
        def __init__(self) -> None:
            self.tools = [DummyTool("check_login_status")]

    class DummyPromptListResult:
        def __init__(self) -> None:
            self.prompts = []

    class DummyResourceListResult:
        def __init__(self) -> None:
            self.resources = []

    class DummySession:
        async def list_tools(self):
            return DummyToolListResult()

        async def list_prompts(self):
            return DummyPromptListResult()

        async def list_resources(self):
            return DummyResourceListResult()

    async def fake_open_connection(config):
        return _ManagedConnection(config=config, stack=DummyStack(), session=DummySession())

    manager._open_connection = fake_open_connection  # type: ignore[method-assign]

    asyncio.run(manager.refresh_all())

    assert manager._handles == {}
    assert closed["value"] == 1
    assert manager.cached_tools()["demo"][0].name == "check_login_status"


def test_http_call_tool_uses_request_scoped_handle(tmp_path):
    add_project_mcp_server(
        tmp_path,
        "demo",
        {"type": "http", "url": "http://localhost:18060/mcp"},
    )
    manager = McpClientManager(tmp_path, AppSettings())
    closed = {"value": 0}

    class DummyStack:
        async def aclose(self) -> None:
            closed["value"] += 1

    class DummySession:
        async def call_tool(self, tool_name, arguments=None):
            return {"tool_name": tool_name, "arguments": arguments or {}}

    async def fake_open_connection(config):
        return _ManagedConnection(config=config, stack=DummyStack(), session=DummySession())

    manager._open_connection = fake_open_connection  # type: ignore[method-assign]

    result = asyncio.run(manager.call_tool("demo", "check_login_status", {}))

    assert result["tool_name"] == "check_login_status"
    assert manager._handles == {}
    assert closed["value"] == 1


def test_http_call_tool_ignores_close_error_after_success(tmp_path):
    add_project_mcp_server(
        tmp_path,
        "demo",
        {"type": "http", "url": "http://localhost:18060/mcp"},
    )
    manager = McpClientManager(tmp_path, AppSettings())

    class DummyStack:
        async def aclose(self) -> None:
            raise RuntimeError("close failed")

    class DummySession:
        async def call_tool(self, tool_name, arguments=None):
            return {"tool_name": tool_name}

    async def fake_open_connection(config):
        return _ManagedConnection(config=config, stack=DummyStack(), session=DummySession())

    manager._open_connection = fake_open_connection  # type: ignore[method-assign]

    result = asyncio.run(manager.call_tool("demo", "check_login_status", {}))

    assert result["tool_name"] == "check_login_status"
