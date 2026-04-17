import asyncio

from claude_code_thy.mcp.catalog import McpCatalog
from claude_code_thy.mcp.session_ops import McpSessionOperations
from claude_code_thy.mcp.transport import McpTransportLayer, _ManagedConnection
from claude_code_thy.mcp.types import McpServerConfig, McpToolDefinition
from claude_code_thy.settings import AppSettings


def test_mcp_catalog_snapshot_and_cache_lifecycle():
    catalog = McpCatalog()
    config = McpServerConfig(name="demo", scope="project", type="http", url="http://localhost")

    snapshot = catalog.snapshot({"demo": config})
    assert snapshot[0].status == "pending"

    catalog.mark_connected("demo", config)
    catalog.set_tools(
        "demo",
        [
            McpToolDefinition(
                name="check_login_status",
                description="check login",
                input_schema={"type": "object", "properties": {}},
                annotations={},
            )
        ],
    )
    assert catalog.cached_tools()["demo"][0].name == "check_login_status"

    snapshot = catalog.snapshot({})
    assert snapshot == []
    assert catalog.cached_tools() == {}


def test_mcp_transport_layer_reuses_persistent_handle_without_reopening():
    catalog = McpCatalog()
    transport = McpTransportLayer(AppSettings(), catalog)
    config = McpServerConfig(name="demo", scope="project", type="stdio", command="demo")
    opened = {"count": 0}

    class DummyStack:
        async def aclose(self) -> None:
            return None

    async def fake_open_connection(server_config):
        opened["count"] += 1
        return _ManagedConnection(config=server_config, stack=DummyStack(), session=object())

    async def run():
        first = await transport.get_persistent_handle(
            "demo",
            config,
            force_reconnect=False,
            open_connection=fake_open_connection,
        )
        second = await transport.get_persistent_handle(
            "demo",
            config,
            force_reconnect=False,
            open_connection=fake_open_connection,
        )
        assert first is second

    asyncio.run(run())
    assert opened["count"] == 1


def test_mcp_session_operations_convert_sdk_objects_and_prompt_fallback():
    settings = AppSettings()

    async def run_session_call(operation, *, timeout_message=None):
        _ = timeout_message
        return await operation()

    ops = McpSessionOperations(settings, run_session_call)

    class DummyTool:
        def __init__(self) -> None:
            self.name = "check_login_status"
            self.description = "check login"
            self.inputSchema = {"type": "object", "properties": {}}
            self.annotations = {"readOnlyHint": True}

    class DummyPromptArg:
        def __init__(self, name: str) -> None:
            self.name = name

    class DummyPrompt:
        def __init__(self) -> None:
            self.name = "daily_summary"
            self.description = "daily summary"
            self.arguments = [DummyPromptArg("date")]

    class DummyResource:
        def __init__(self) -> None:
            self.uri = "memo://1"
            self.name = "memo"
            self.description = "memo resource"
            self.mimeType = "text/plain"

    class DummyResultTools:
        def __init__(self) -> None:
            self.tools = [DummyTool()]

    class DummyResultPrompts:
        def __init__(self) -> None:
            self.prompts = [DummyPrompt()]

    class DummyResultResources:
        def __init__(self) -> None:
            self.resources = [DummyResource()]

    class DummySession:
        async def list_tools(self):
            return DummyResultTools()

        async def list_prompts(self):
            return DummyResultPrompts()

        async def list_resources(self):
            return DummyResultResources()

        async def request(self, payload):
            return payload

    handle = _ManagedConnection(
        config=McpServerConfig(name="demo", scope="project", type="http", url="http://localhost"),
        stack=object(),  # type: ignore[arg-type]
        session=DummySession(),
    )

    async def run():
        tools = await ops.list_tools(handle)
        prompts = await ops.list_prompts(handle)
        resources = await ops.list_resources("demo", handle)
        prompt_result = await ops.get_prompt(handle, "daily_summary", {"date": "2026-04-17"})
        return tools, prompts, resources, prompt_result

    tools, prompts, resources, prompt_result = asyncio.run(run())

    assert tools[0].annotations["original_name"] == "check_login_status"
    assert prompts[0].arguments == ("date",)
    assert resources[0].server == "demo"
    assert prompt_result["method"] == "prompts/get"
