import json

from claude_code_thy.settings import AppSettings


def test_load_for_workspace_merges_settings_json_and_local(tmp_path):
    """测试 `load_for_workspace_merges_settings_json_and_local` 场景。"""
    settings_dir = tmp_path / ".claude-code-thy"
    settings_dir.mkdir()
    (settings_dir / "settings.json").write_text(
        json.dumps(
            {
                "permissions": [
                    {
                        "effect": "ask",
                        "tool": "bash",
                        "target": "command",
                        "pattern": "rm *",
                    }
                ],
                "skills": {
                    "enabled": True,
                    "search_roots": ["skills-base"],
                },
                "mcp": {
                    "servers": {
                        "base": {"type": "http", "url": "http://base.example/mcp"}
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (settings_dir / "settings.local.json").write_text(
        json.dumps(
            {
                "permissions": [
                    {
                        "effect": "ask",
                        "tool": "bash",
                        "target": "command",
                        "pattern": "echo permission-test",
                    }
                ],
                "skills": {
                    "search_roots": ["skills-local"]
                },
                "mcp": {
                    "servers": {
                        "local": {"type": "stdio", "command": "local-mcp"}
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    settings = AppSettings.load_for_workspace(tmp_path)

    assert [rule.pattern for rule in settings.permission_rules] == ["rm *", "echo permission-test"]
    assert settings.skills.search_roots == ("skills-base", "skills-local")
    assert set(settings.mcp.servers) == {"base", "local"}


def test_load_for_workspace_local_overrides_scalar_values(tmp_path):
    """测试 `load_for_workspace_local_overrides_scalar_values` 场景。"""
    settings_dir = tmp_path / ".claude-code-thy"
    settings_dir.mkdir()
    (settings_dir / "settings.json").write_text(
        json.dumps(
            {
                "sandbox": {"mode": "workspace-write", "allow_network": False},
                "mcp": {"connect_timeout_ms": 1000},
            }
        ),
        encoding="utf-8",
    )
    (settings_dir / "settings.local.json").write_text(
        json.dumps(
            {
                "sandbox": {"allow_network": True},
                "mcp": {"connect_timeout_ms": 5000},
            }
        ),
        encoding="utf-8",
    )

    settings = AppSettings.load_for_workspace(tmp_path)

    assert settings.sandbox.mode == "workspace-write"
    assert settings.sandbox.allow_network is True
    assert settings.mcp.connect_timeout_ms == 5000


def test_load_for_workspace_ignores_invalid_base_and_uses_valid_local(tmp_path):
    """测试 `load_for_workspace_ignores_invalid_base_and_uses_valid_local` 场景。"""
    settings_dir = tmp_path / ".claude-code-thy"
    settings_dir.mkdir()
    (settings_dir / "settings.json").write_text("{invalid json", encoding="utf-8")
    (settings_dir / "settings.local.json").write_text(
        json.dumps(
            {
                "permissions": [
                    {
                        "effect": "ask",
                        "tool": "read",
                        "target": "path",
                        "pattern": "secret/*",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    settings = AppSettings.load_for_workspace(tmp_path)

    assert len(settings.permission_rules) == 1
    assert settings.permission_rules[0].pattern == "secret/*"
