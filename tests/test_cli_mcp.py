import os
from pathlib import Path
import sys

from typer.testing import CliRunner

import claude_code_thy.cli as cli_module
import claude_code_thy.cli_mcp as cli_mcp_module
from claude_code_thy.cli import app
from claude_code_thy.mcp.errors import McpRuntimeError
from claude_code_thy.mcp.types import McpServerConfig, McpServerConnection, McpToolDefinition


runner = CliRunner()


def test_mcp_show_config_subcommand_is_not_swallowed(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / ".mcp.json").write_text(
        '{"mcpServers":{"demo":{"type":"http","url":"http://localhost:18060/mcp"}}}',
        encoding="utf-8",
    )
    previous_cwd = Path.cwd()
    try:
        os.chdir(root)
        result = runner.invoke(app, ["mcp", "show-config"], catch_exceptions=False, env={})
    finally:
        os.chdir(previous_cwd)

    assert result.exit_code == 0
    assert "mcpServers" in result.stderr


def test_print_mode_uses_extra_args_as_prompt(monkeypatch):
    captured: dict[str, object] = {}

    monkeypatch.setattr(sys, "argv", ["claude-code-thy", "--print", "你好", "世界"])

    def fake_run_root_command(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(cli_module, "_run_root_command", fake_run_root_command)

    cli_module.run()

    assert captured["print_mode"] is True
    assert captured["prompt_tokens"] == ["你好", "世界"]


def test_preprocess_root_invocation_does_not_swallow_mcp_command():
    result = cli_module._preprocess_root_invocation(["mcp", "show-config"])

    assert result is None


def test_preprocess_root_invocation_treats_mcp_as_prompt_in_print_mode():
    result = cli_module._preprocess_root_invocation(["--print", "mcp", "show-config"])

    assert result is not None
    assert result.prompt_tokens == ["mcp", "show-config"]


def test_mcp_get_treats_unsupported_capabilities_as_optional(monkeypatch, tmp_path):
    server_name = "xiaohongshu-mcp"

    class FakeManager:
        async def get_connection(self, name: str, *, refresh: bool = False):
            assert name == server_name
            return McpServerConnection(
                name=server_name,
                status="connected",
                config=McpServerConfig(
                    name=server_name,
                    scope="project",
                    type="http",
                    url="http://localhost:18060/mcp",
                    description="小红书 MCP",
                ),
                tool_count=1,
                prompt_count=0,
                resource_count=0,
            )

        async def list_tools(self, name: str):
            assert name == server_name
            return [
                McpToolDefinition(
                    name="mcp__xiaohongshu_mcp__check_login_status",
                    description="check login status",
                    input_schema={},
                )
            ]

        async def list_prompts(self, name: str):
            assert name == server_name
            raise McpRuntimeError("Method not found")

        async def list_resources(self, name: str):
            assert name == server_name
            raise McpRuntimeError("Method not found")

    monkeypatch.setattr(cli_mcp_module, "_manager_for_cwd", lambda: (tmp_path, FakeManager()))

    result = runner.invoke(app, ["mcp", "get", server_name], catch_exceptions=False, env={})

    assert result.exit_code == 0
    assert "Name: xiaohongshu-mcp" in result.stderr
    assert "Tools: mcp__xiaohongshu_mcp__check_login_status" in result.stderr
    assert "Prompts: (unsupported)" in result.stderr
    assert "Resources: (unsupported)" in result.stderr
