from pathlib import Path

from typer.testing import CliRunner

import claude_code_thy.cli as cli_module
from claude_code_thy.cli import app


runner = CliRunner()


def test_mcp_show_config_subcommand_is_not_swallowed(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / ".mcp.json").write_text(
        '{"mcpServers":{"demo":{"type":"http","url":"http://localhost:18060/mcp"}}}',
        encoding="utf-8",
    )

    result = runner.invoke(app, ["mcp", "show-config"], catch_exceptions=False, env={})

    assert result.exit_code == 0
    assert "mcpServers" in result.stdout


def test_print_mode_uses_extra_args_as_prompt(monkeypatch):
    captured: dict[str, str] = {}

    class DummyProvider:
        name = "dummy"

    monkeypatch.setattr(cli_module, "build_provider", lambda config: DummyProvider())

    async def fake_run_print_mode(runtime, session, prompt: str) -> None:
        captured["prompt"] = prompt

    monkeypatch.setattr(cli_module, "_run_print_mode", fake_run_print_mode)

    result = runner.invoke(
        app,
        ["--print", "你好", "世界"],
        catch_exceptions=False,
        env={},
    )

    assert result.exit_code == 0
    assert captured["prompt"] == "你好 世界"
