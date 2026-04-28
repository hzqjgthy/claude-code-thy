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


def test_load_for_workspace_supports_browser_settings(tmp_path):
    """测试浏览器配置会被正确加载。"""
    settings_dir = tmp_path / ".claude-code-thy"
    settings_dir.mkdir()
    (settings_dir / "settings.json").write_text(
        json.dumps(
            {
                "browser": {
                    "enabled": True,
                    "headless": False,
                    "launch_timeout_ms": 22222,
                    "snapshot_max_chars": 4321
                },
                "browser_search": {
                    "enabled": True,
                    "default_search_engine": "searxng",
                    "search_engines": {
                        "duckduckgo": {
                            "url_template": "https://html.duckduckgo.com/html/?q={query}",
                            "parser": "duckduckgo_html",
                            "enabled": True
                        },
                        "searxng": {
                            "url_template": "http://127.0.0.1:8080/search?q={query}",
                            "parser": "generic_links",
                            "enabled": True
                        }
                    },
                    "max_same_domain": 2,
                    "dedupe_domains": False
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    settings = AppSettings.load_for_workspace(tmp_path)

    assert settings.browser.enabled is True
    assert settings.browser.headless is False
    assert settings.browser.launch_timeout_ms == 22222
    assert settings.browser.snapshot_max_chars == 4321
    assert settings.browser_search.enabled is True
    assert settings.browser_search.default_search_engine == "searxng"
    assert "searxng" in settings.browser_search.search_engines
    assert settings.browser_search.search_engines["searxng"]["parser"] == "generic_links"
    assert settings.browser_search.max_same_domain == 2
    assert settings.browser_search.dedupe_domains is False


def test_load_for_workspace_supports_session_log_settings(tmp_path):
    """测试 session 双轨日志配置会被正确加载。"""
    settings_dir = tmp_path / ".claude-code-thy"
    settings_dir.mkdir()
    (settings_dir / "settings.json").write_text(
        json.dumps(
            {
                "session_logs": {
                    "enabled": True,
                    "output_dir": ".claude-code-thy/custom-session-logs",
                    "write_human_log": True,
                    "write_jsonl_log": False,
                    "tool_output_inline_max_chars": 222,
                    "tool_output_head_chars": 33,
                    "tool_output_tail_chars": 44,
                    "include_text_deltas": True,
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    settings = AppSettings.load_for_workspace(tmp_path)

    assert settings.session_logs.enabled is True
    assert settings.session_logs.output_dir == ".claude-code-thy/custom-session-logs"
    assert settings.session_logs.write_human_log is True
    assert settings.session_logs.write_jsonl_log is False
    assert settings.session_logs.tool_output_inline_max_chars == 222
    assert settings.session_logs.tool_output_head_chars == 33
    assert settings.session_logs.tool_output_tail_chars == 44
    assert settings.session_logs.include_text_deltas is True
