import os
from pathlib import Path
import sys
import asyncio

from typer.testing import CliRunner

import claude_code_thy.cli as cli_module
import claude_code_thy.cli_mcp as cli_mcp_module
from claude_code_thy.cli import app
from claude_code_thy.mcp.errors import McpRuntimeError
from claude_code_thy.mcp.types import McpServerConfig, McpServerConnection, McpToolDefinition
from claude_code_thy.models import ChatMessage


runner = CliRunner()


def test_mcp_show_config_subcommand_is_not_swallowed(tmp_path):
    """测试 `mcp_show_config_subcommand_is_not_swallowed` 场景。"""
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
    """测试 `print_mode_uses_extra_args_as_prompt` 场景。"""
    captured: dict[str, object] = {}

    monkeypatch.setattr(sys, "argv", ["claude-code-thy", "--print", "你好", "世界"])

    def fake_run_root_command(**kwargs):
        """处理 `fake_run_root_command`。"""
        captured.update(kwargs)

    monkeypatch.setattr(cli_module, "_run_root_command", fake_run_root_command)

    cli_module.run()

    assert captured["print_mode"] is True
    assert captured["prompt_tokens"] == ["你好", "世界"]


def test_render_print_mode_messages_includes_assistant_and_truncated_tool_output():
    """测试无头模式会按顺序打印 assistant/tool，并截断工具正文。"""
    long_output = "x" * 210
    rendered = cli_module._render_print_mode_messages(
        [
            ChatMessage(role="assistant", text="第一条回答"),
            ChatMessage(
                role="tool",
                text="tool text fallback",
                metadata={
                    "display_name": "Read",
                    "summary": "读取文件成功",
                    "output": long_output,
                },
            ),
            ChatMessage(role="assistant", text="第二条回答"),
        ]
    )

    expected = (
        "第一条回答"
        + cli_module.PRINT_SEPARATOR
        + "工具: Read\n"
        + "摘要: 读取文件成功\n"
        + "输出:\n"
        + ("x" * 200)
        + "..."
        + cli_module.PRINT_SEPARATOR
        + "第二条回答"
    )
    assert rendered == expected


def test_preprocess_root_invocation_does_not_swallow_mcp_command():
    """测试 `preprocess_root_invocation_does_not_swallow_mcp_command` 场景。"""
    result = cli_module._preprocess_root_invocation(["mcp", "show-config"])

    assert result is None


def test_preprocess_root_invocation_treats_mcp_as_prompt_in_print_mode():
    """测试 `preprocess_root_invocation_treats_mcp_as_prompt_in_print_mode` 场景。"""
    result = cli_module._preprocess_root_invocation(["--print", "mcp", "show-config"])

    assert result is not None
    assert result.prompt_tokens == ["mcp", "show-config"]


def test_mcp_get_treats_unsupported_capabilities_as_optional(monkeypatch, tmp_path):
    """测试 `mcp_get_treats_unsupported_capabilities_as_optional` 场景。"""
    server_name = "xiaohongshu-mcp"

    class FakeManager:
        """管理 `Fake` 相关逻辑。"""
        async def get_connection(self, name: str, *, refresh: bool = False):
            """返回 `connection`。"""
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
            """列出 `tools`。"""
            assert name == server_name
            return [
                McpToolDefinition(
                    name="mcp__xiaohongshu_mcp__check_login_status",
                    description="check login status",
                    input_schema={},
                )
            ]

        async def list_prompts(self, name: str):
            """列出 `prompts`。"""
            assert name == server_name
            raise McpRuntimeError("Method not found")

        async def list_resources(self, name: str):
            """列出 `resources`。"""
            assert name == server_name
            raise McpRuntimeError("Method not found")

    monkeypatch.setattr(cli_mcp_module, "_manager_for_cwd", lambda: (tmp_path, FakeManager()))

    result = runner.invoke(app, ["mcp", "get", server_name], catch_exceptions=False, env={})

    assert result.exit_code == 0
    assert "Name: xiaohongshu-mcp" in result.stderr
    assert "Tools: mcp__xiaohongshu_mcp__check_login_status" in result.stderr
    assert "Prompts: (unsupported)" in result.stderr
    assert "Resources: (unsupported)" in result.stderr


def test_mcp_get_reuses_same_event_loop_and_closes_manager(monkeypatch, tmp_path):
    """测试 mcp get 会在单次 asyncio.run 内完成全部操作，并显式关闭 manager。"""
    server_name = "demo-stdio"
    observed: dict[str, object] = {"loop_id": None, "closed": False}

    class FakeManager:
        """模拟只能在同一事件循环内复用的 MCP manager。"""

        async def get_connection(self, name: str, *, refresh: bool = False):
            """记录首次连接所在的事件循环。"""
            assert name == server_name
            observed["loop_id"] = id(asyncio.get_running_loop())
            return McpServerConnection(
                name=server_name,
                status="connected",
                config=McpServerConfig(
                    name=server_name,
                    scope="project",
                    type="stdio",
                    command="demo-mcp",
                    args=("--stdio",),
                    description="demo stdio server",
                ),
                tool_count=1,
                prompt_count=0,
                resource_count=0,
            )

        async def list_tools(self, name: str):
            """要求后续能力读取仍在同一事件循环内发生。"""
            assert name == server_name
            assert observed["loop_id"] == id(asyncio.get_running_loop())
            return [
                McpToolDefinition(
                    name="mcp__demo_stdio__read",
                    description="read tool",
                    input_schema={},
                )
            ]

        async def list_prompts(self, name: str):
            """返回空 prompts。"""
            assert name == server_name
            assert observed["loop_id"] == id(asyncio.get_running_loop())
            return []

        async def list_resources(self, name: str):
            """返回空 resources。"""
            assert name == server_name
            assert observed["loop_id"] == id(asyncio.get_running_loop())
            return []

        async def close_all(self):
            """记录 manager 已在命令退出前关闭。"""
            observed["closed"] = True

    monkeypatch.setattr(cli_mcp_module, "_manager_for_cwd", lambda: (tmp_path, FakeManager()))

    result = runner.invoke(app, ["mcp", "get", server_name], catch_exceptions=False, env={})

    assert result.exit_code == 0
    assert "Name: demo-stdio" in result.stderr
    assert "Tools: mcp__demo_stdio__read" in result.stderr
    assert observed["closed"] is True
