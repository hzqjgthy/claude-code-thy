from claude_code_thy.browser.search import (
    build_search_url,
    resolve_search_engine_config,
    select_search_results,
)
from claude_code_thy.settings import BrowserSearchSettings


def test_build_search_url_uses_browser_settings_default_engine() -> None:
    """测试未显式传参时会使用 settings 里的默认搜索引擎。"""
    settings = BrowserSearchSettings(
        default_search_engine="searxng",
        search_engines={
            "duckduckgo": {
                "url_template": "https://html.duckduckgo.com/html/?q={query}",
                "parser": "duckduckgo_html",
                "enabled": True,
            },
            "searxng": {
                "url_template": "http://127.0.0.1:8080/search?q={query}&language=zh-CN",
                "parser": "generic_links",
                "enabled": True,
            },
        },
    )

    engine_name, engine_config = resolve_search_engine_config(settings, None)
    url = build_search_url("gpt 5.4", settings=settings)

    assert engine_name == "searxng"
    assert engine_config["parser"] == "generic_links"
    assert url == "http://127.0.0.1:8080/search?q=gpt+5.4&language=zh-CN"


def test_select_search_results_prefers_docs_and_dedupes_domains() -> None:
    """测试智能筛选会优先文档页，并限制同域名重复。"""
    settings = BrowserSearchSettings(
        max_same_domain=1,
        dedupe_domains=True,
    )
    results = [
        {
            "rank": 1,
            "title": "OpenAI blog update",
            "url": "https://openai.com/blog/update",
            "snippet": "A general update page.",
        },
        {
            "rank": 2,
            "title": "GPT-5.4 API reference",
            "url": "https://platform.openai.com/docs/api-reference",
            "snippet": "Official API reference for GPT-5.4.",
        },
        {
            "rank": 3,
            "title": "GPT-5.4 overview",
            "url": "https://platform.openai.com/docs/overview",
            "snippet": "Official docs overview.",
        },
        {
            "rank": 4,
            "title": "Random forum discussion",
            "url": "https://forum.example.com/topic",
            "snippet": "People are guessing about GPT-5.4.",
        },
    ]

    scored, selected = select_search_results(
        results,
        query="gpt5.4 api 文档",
        open_count=2,
        settings=settings,
    )

    assert len(scored) == 4
    assert len(selected) == 2
    assert selected[0]["url"] == "https://platform.openai.com/docs/api-reference"
    assert selected[1]["url"] != "https://platform.openai.com/docs/overview"
    assert selected[1]["url"] in {
        "https://openai.com/blog/update",
        "https://forum.example.com/topic",
    }
