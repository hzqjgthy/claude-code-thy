import asyncio

from claude_code_thy.mcp.runtime import McpRuntimeManager
from claude_code_thy.mcp.config import add_project_mcp_server
from claude_code_thy.settings import AppSettings


def test_mcp_runtime_marks_needs_auth_and_exposes_auth_tool(tmp_path):
    add_project_mcp_server(
        tmp_path,
        "demo",
        {
            "type": "http",
            "url": "http://localhost:18060/mcp",
            "oauth": {
                "clientId": "demo-client",
                "authServerMetadataUrl": "https://auth.example.com/.well-known/oauth-authorization-server",
            },
        },
    )
    manager = McpRuntimeManager(tmp_path, AppSettings())

    async def fake_open_connection(config):
        raise RuntimeError("401 Unauthorized")

    manager._client._open_connection = fake_open_connection  # type: ignore[method-assign]

    snapshot = asyncio.run(manager.refresh_all())

    assert snapshot[0].status == "needs-auth"
    assert manager.cached_tools()["demo"][0].name == "authenticate"
    assert manager.cached_tools()["demo"][0].annotations["authTool"] is True
