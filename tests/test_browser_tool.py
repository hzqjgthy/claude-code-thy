import json

import pytest

from claude_code_thy.commands import CommandProcessor
from claude_code_thy.session.store import SessionStore
from claude_code_thy.tools import PermissionRequiredError, ToolRuntime, build_builtin_tools


def build_runtime() -> ToolRuntime:
    """构建包含浏览器工具的运行时。"""
    return ToolRuntime(build_builtin_tools())


def test_browser_status_tool_reports_not_running_by_default(tmp_path):
    """测试浏览器工具在未启动时返回静态状态。"""
    runtime = build_runtime()
    session = SessionStore(root_dir=tmp_path / "sessions").create(cwd=str(tmp_path))

    result = runtime.execute_input("browser", {"action": "status"}, session)

    assert result.ok is True
    assert result.structured_data["type"] == "browser_status"
    assert result.structured_data["running"] is False
    assert "running: False" in result.output


def test_browser_open_requires_url_confirmation_when_rule_matches(tmp_path):
    """测试浏览器访问 URL 时会命中 url 权限规则。"""
    settings_dir = tmp_path / ".claude-code-thy"
    settings_dir.mkdir()
    (settings_dir / "settings.local.json").write_text(
        json.dumps(
            {
                "permissions": [
                    {
                        "effect": "ask",
                        "tool": "browser",
                        "target": "url",
                        "pattern": "https://*",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    runtime = build_runtime()
    session = SessionStore(root_dir=tmp_path / "sessions").create(cwd=str(tmp_path))

    with pytest.raises(PermissionRequiredError) as error_info:
        runtime.execute_input(
            "browser",
            {"action": "open", "url": "https://example.com"},
            session,
        )

    assert error_info.value.request.target == "url"
    assert error_info.value.request.value == "https://example.com"


def test_browser_command_status_executes_tool(tmp_path):
    """测试 `/browser status` 会通过标准工具链执行。"""
    store = SessionStore(root_dir=tmp_path / "sessions")
    processor = CommandProcessor(store, build_runtime())
    session = store.create(cwd=str(tmp_path))
    store.save(session)

    outcome = processor.process(session, "/browser status")

    assert outcome.message_added is True
    assert outcome.session.messages[-1].role == "tool"
    assert outcome.session.messages[-1].metadata["ui_kind"] == "browser"
    assert "running:" in outcome.session.messages[-1].text
