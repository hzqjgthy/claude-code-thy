import json

import pytest

from claude_code_thy.commands import CommandProcessor
from claude_code_thy.session.store import SessionStore
from claude_code_thy.tools import PermissionRequiredError, ToolRuntime, build_builtin_tools


def build_runtime() -> ToolRuntime:
    """构建包含浏览器搜索工具的运行时。"""
    return ToolRuntime(build_builtin_tools())


def test_browser_search_returns_results_and_expanded_pages(tmp_path):
    """测试 browser_search 会汇总搜索结果和展开网页快照。"""
    runtime = build_runtime()
    store = SessionStore(root_dir=tmp_path / "sessions")
    session = store.create(cwd=str(tmp_path))
    services = runtime.services_for(session)

    class DummyBrowserManager:
        """模拟浏览器搜索和网页抓取结果。"""

        def search_results(self, query, *, result_count, search_settings, search_engine=None):
            assert query == "gpt5.4 相关的信息"
            assert result_count == 4
            assert search_settings.default_search_engine == "duckduckgo"
            return {
                "query": query,
                "search_engine": search_engine or "duckduckgo",
                "parser": "duckduckgo_html",
                "search_url": "https://html.duckduckgo.com/html/?q=gpt5.4",
                "page_id": "p2",
                "result_count": 2,
                "results": [
                    {
                        "rank": 1,
                        "title": "Result One",
                        "url": "https://docs.example.com/one",
                        "snippet": "snippet one",
                    },
                    {
                        "rank": 2,
                        "title": "Result Two",
                        "url": "https://docs.example.com/two",
                        "snippet": "snippet two",
                    },
                ],
            }

        def capture_pages(self, results, *, per_page_max_chars):
            assert len(results) == 1
            assert per_page_max_chars == 2000
            return [
                {
                    "rank": 1,
                    "title": "Opened One",
                    "url": "https://docs.example.com/one",
                    "snapshot": "Page Title: Opened One\nPage URL: https://docs.example.com/one",
                    "ref_count": 2,
                }
            ]

    services.browser_manager = DummyBrowserManager()

    result = runtime.execute_input(
        "browser_search",
        {
            "query": "gpt5.4 相关的信息",
            "result_count": 4,
            "open_count": 1,
            "per_page_max_chars": 2000,
        },
        session,
    )

    assert result.ok is True
    assert result.structured_data["type"] == "browser_search"
    assert "Top Results:" in result.output
    assert "Expanded Pages:" in result.output
    assert "Opened One" in result.output


def test_browser_search_requires_permission_for_expanded_result_urls(tmp_path):
    """测试 browser_search 在展开结果页前也会检查 URL 权限。"""
    settings_dir = tmp_path / ".claude-code-thy"
    settings_dir.mkdir()
    (settings_dir / "settings.local.json").write_text(
        json.dumps(
            {
                "permissions": [
                    {
                        "effect": "ask",
                        "tool": "browser_search",
                        "target": "url",
                        "pattern": "https://docs.example.com/*",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    runtime = build_runtime()
    session = SessionStore(root_dir=tmp_path / "sessions").create(cwd=str(tmp_path))
    services = runtime.services_for(session)

    class DummyBrowserManager:
        """模拟 search_results 已经找到了外部链接。"""

        def search_results(self, query, *, result_count, search_settings, search_engine=None):
            return {
                "query": query,
                "search_engine": search_engine or "duckduckgo",
                "parser": "duckduckgo_html",
                "search_url": "https://html.duckduckgo.com/html/?q=test",
                "page_id": "p3",
                "result_count": 1,
                "results": [
                    {
                        "rank": 1,
                        "title": "Docs Page",
                        "url": "https://docs.example.com/page",
                        "snippet": "doc snippet",
                    }
                ],
            }

        def capture_pages(self, results, *, per_page_max_chars):
            raise AssertionError("capture_pages 不应该在权限确认前被调用")

    services.browser_manager = DummyBrowserManager()

    with pytest.raises(PermissionRequiredError) as error_info:
        runtime.execute_input(
            "browser_search",
            {
                "query": "test",
                "result_count": 3,
                "open_count": 1,
            },
            session,
        )

    assert error_info.value.request.target == "url"
    assert error_info.value.request.value == "https://docs.example.com/page"


def test_browser_search_command_executes_tool(tmp_path):
    """测试 `/browser-search ...` 会通过 slash 正常执行。"""
    store = SessionStore(root_dir=tmp_path / "sessions")
    runtime = build_runtime()
    processor = CommandProcessor(store, runtime)
    session = store.create(cwd=str(tmp_path))
    store.save(session)
    services = runtime.services_for(session)

    class DummyBrowserManager:
        """模拟浏览器搜索命令的底层实现。"""

        def search_results(self, query, *, result_count, search_settings, search_engine=None):
            assert query == "gpt5.4 相关的信息"
            return {
                "query": query,
                "search_engine": search_engine or "duckduckgo",
                "parser": "duckduckgo_html",
                "search_url": "https://html.duckduckgo.com/html/?q=gpt5.4",
                "page_id": "p4",
                "result_count": 1,
                "results": [
                    {
                        "rank": 1,
                        "title": "Result One",
                        "url": "https://example.com/one",
                        "snippet": "snippet one",
                    }
                ],
            }

        def capture_pages(self, results, *, per_page_max_chars):
            return [
                {
                    "rank": 1,
                    "title": "Example One",
                    "url": "https://example.com/one",
                    "snapshot": "Page Title: Example One",
                    "ref_count": 1,
                }
            ]

    services.browser_manager = DummyBrowserManager()

    outcome = processor.process(
        session,
        "/browser-search --result-count 4 --open-count 1 --per-page-max-chars 2000 -- gpt5.4 相关的信息",
    )

    assert outcome.message_added is True
    assert outcome.session.messages[-1].metadata["ui_kind"] == "browser_search"
    assert "Top Results:" in outcome.session.messages[-1].text
