from __future__ import annotations

import re
from urllib.parse import quote_plus, urlparse

from claude_code_thy.settings import BrowserSearchSettings


DEFAULT_SEARCH_ENGINE = "duckduckgo"


SEARCH_RESULT_SCRIPTS = {
    "duckduckgo_html": r"""
(limit) => {
  const normalize = (value) => String(value || "").replace(/\s+/g, " ").trim();
  const decodeResultUrl = (rawHref) => {
    const raw = String(rawHref || "").trim();
    if (!raw) return "";
    try {
      const parsed = new URL(raw, window.location.href);
      const redirected = parsed.searchParams.get("uddg") || parsed.searchParams.get("rut");
      if (redirected) return decodeURIComponent(redirected);
      return parsed.toString();
    } catch {
      return raw;
    }
  };
  const isHttpUrl = (value) => /^https?:\/\//i.test(String(value || ""));
  const looksLikeSearchHost = (value) => {
    try {
      const host = new URL(String(value)).hostname.toLowerCase();
      return host.includes("duckduckgo.com");
    } catch {
      return false;
    }
  };
  const snippetTextFor = (anchor) => {
    const block = anchor.closest(".result, .results_links, .web-result, tr, .links_main") || anchor.parentElement;
    if (!block) return "";
    const snippet =
      block.querySelector(".result__snippet, .result-snippet, .snippet, .result-snippet__body, td.result-snippet") ||
      null;
    return normalize(snippet ? snippet.textContent : "");
  };

  const results = [];
  const seen = new Set();
  const pushAnchor = (anchor) => {
    if (!(anchor instanceof HTMLAnchorElement)) return;
    const title = normalize(anchor.textContent || anchor.innerText || anchor.getAttribute("title"));
    const url = decodeResultUrl(anchor.getAttribute("href"));
    if (!title || !isHttpUrl(url)) return;
    if (looksLikeSearchHost(url) && !String(anchor.getAttribute("href") || "").includes("uddg=")) return;
    if (seen.has(url)) return;
    seen.add(url);
    results.push({
      rank: results.length + 1,
      title: title.slice(0, 300),
      url,
      snippet: snippetTextFor(anchor).slice(0, 500),
    });
  };

  const selectors = [
    "a[data-testid='result-title-a']",
    ".result__title a",
    "a.result-link",
    ".links_main a",
    "tr td a[href]",
  ];
  for (const selector of selectors) {
    for (const anchor of Array.from(document.querySelectorAll(selector))) {
      if (results.length >= limit) break;
      pushAnchor(anchor);
    }
    if (results.length >= limit) break;
  }

  if (results.length < limit) {
    for (const anchor of Array.from(document.querySelectorAll("a[href]"))) {
      if (results.length >= limit) break;
      pushAnchor(anchor);
    }
  }

  return results.slice(0, limit);
}
""",
    "generic_links": r"""
(limit) => {
  const normalize = (value) => String(value || "").replace(/\s+/g, " ").trim();
  const isHttpUrl = (value) => /^https?:\/\//i.test(String(value || ""));
  const results = [];
  const seen = new Set();

  const scoreAnchor = (anchor) => {
    const href = String(anchor.getAttribute("href") || "").trim();
    const title = normalize(anchor.textContent || anchor.innerText || anchor.getAttribute("title"));
    if (!title || !isHttpUrl(href)) return;
    if (seen.has(href)) return;
    seen.add(href);
    const block = anchor.closest("article, li, div, section, tr") || anchor.parentElement;
    const snippet = normalize(block ? block.textContent : "").replace(title, "").slice(0, 500);
    results.push({
      rank: results.length + 1,
      title: title.slice(0, 300),
      url: href,
      snippet,
    });
  };

  const selectors = [
    "main a[href]",
    "article a[href]",
    "ol a[href]",
    "ul a[href]",
    "a[href]",
  ];
  for (const selector of selectors) {
    for (const anchor of Array.from(document.querySelectorAll(selector))) {
      if (results.length >= limit) break;
      if (!(anchor instanceof HTMLAnchorElement)) continue;
      scoreAnchor(anchor);
    }
    if (results.length >= limit) break;
  }

  return results.slice(0, limit);
}
""",
}

GENERIC_QUERY_STOPWORDS = {
    "的",
    "了",
    "和",
    "与",
    "及",
    "并",
    "帮我",
    "搜索",
    "查询",
    "相关",
    "信息",
    "资料",
    "the",
    "a",
    "an",
    "and",
    "or",
    "for",
    "to",
    "of",
    "in",
    "on",
    "about",
}

SEARCH_HOST_KEYWORDS = ("duckduckgo.", "google.", "bing.", "baidu.", "yahoo.", "search.")
UNHELPFUL_PATH_KEYWORDS = ("/search", "/tag/", "/tags/", "/category/", "/login", "/signup", "/register")
DOC_HOST_KEYWORDS = ("docs.", "developer.", "developers.", "readthedocs.", "api.")
DOC_PATH_KEYWORDS = ("/docs", "/api", "/reference", "/manual", "/guide", "/learn")
TRUSTED_HOST_KEYWORDS = ("github.com", "gitlab.com", "openai.com", "anthropic.com")


def normalize_search_engine(settings: BrowserSearchSettings | None, value: str | None = None) -> str:
    """把搜索引擎名解析为 settings 中当前可用的配置项。"""
    resolved_settings = settings or BrowserSearchSettings()
    configured = value or resolved_settings.default_search_engine or DEFAULT_SEARCH_ENGINE
    normalized = configured.strip().lower() or DEFAULT_SEARCH_ENGINE
    engines = _enabled_search_engines(resolved_settings)
    if normalized not in engines:
        supported = ", ".join(sorted(engines)) or "(none)"
        raise ValueError(f"不支持的搜索引擎：{value or normalized}。当前支持：{supported}")
    return normalized


def resolve_search_engine_config(
    settings: BrowserSearchSettings | None,
    value: str | None = None,
) -> tuple[str, dict[str, object]]:
    """返回当前搜索引擎名和它对应的配置。"""
    resolved_settings = settings or BrowserSearchSettings()
    name = normalize_search_engine(resolved_settings, value)
    config = _enabled_search_engines(resolved_settings)[name]
    return name, dict(config)


def build_search_url(
    query: str,
    *,
    settings: BrowserSearchSettings | None,
    search_engine: str | None = None,
) -> str:
    """根据 settings 中的搜索引擎模板构造搜索 URL。"""
    normalized_query = query.strip()
    if not normalized_query:
        raise ValueError("搜索词不能为空")
    _name, config = resolve_search_engine_config(settings, search_engine)
    template = str(config.get("url_template", "")).strip()
    if not template:
        raise ValueError("搜索引擎缺少 url_template 配置")
    return template.format(query=quote_plus(normalized_query))


def search_results_script(parser: str) -> str:
    """根据 parser 名返回对应的页面结果提取脚本。"""
    normalized = (parser or "generic_links").strip().lower()
    return SEARCH_RESULT_SCRIPTS.get(normalized, SEARCH_RESULT_SCRIPTS["generic_links"])


def select_search_results(
    results: list[dict[str, object]],
    *,
    query: str,
    open_count: int,
    settings: BrowserSearchSettings,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """对搜索结果做打分、去重和筛选，返回已打分结果与最终选中结果。"""
    normalized_query = query.strip()
    if open_count <= 0:
        return [_annotate_result(result, normalized_query) for result in results], []

    scored: list[dict[str, object]] = []
    for result in results:
        if not isinstance(result, dict):
            continue
        scored.append(_annotate_result(result, normalized_query))

    scored.sort(
        key=lambda item: (
            float(item.get("selection_score", 0)),
            -int(item.get("rank", 0) or 0),
        ),
        reverse=True,
    )

    selected: list[dict[str, object]] = []
    domain_counts: dict[str, int] = {}
    max_same_domain = max(1, int(settings.max_same_domain or 1))
    dedupe = bool(settings.dedupe_domains)

    for item in scored:
        if len(selected) >= open_count:
            break
        domain = str(item.get("domain", "")).strip()
        if dedupe and domain:
            if domain_counts.get(domain, 0) >= max_same_domain:
                continue
        selected.append(item)
        if dedupe and domain:
            domain_counts[domain] = domain_counts.get(domain, 0) + 1

    return scored, selected


def _enabled_search_engines(settings: BrowserSettings) -> dict[str, dict[str, object]]:
    """过滤出 settings 中被启用的搜索引擎配置。"""
    engines: dict[str, dict[str, object]] = {}
    for name, config in settings.search_engines.items():
        if not isinstance(config, dict):
            continue
        if config.get("enabled", True) is False:
            continue
        engines[str(name).strip().lower()] = config
    return engines


def _annotate_result(result: dict[str, object], query: str) -> dict[str, object]:
    """为单条结果补充域名、打分和筛选原因。"""
    annotated = dict(result)
    title = str(result.get("title", "")).strip()
    snippet = str(result.get("snippet", "")).strip()
    url = str(result.get("url", "")).strip()
    domain = _domain_for_url(url)
    tokens = _query_tokens(query)
    score = 0.0
    reasons: list[str] = []

    title_lower = title.lower()
    snippet_lower = snippet.lower()
    url_lower = url.lower()
    query_lower = query.lower()

    if query_lower and query_lower in title_lower:
        score += 28
        reasons.append("title contains full query")
    if query_lower and query_lower in snippet_lower:
        score += 16
        reasons.append("snippet contains full query")

    if _contains_any(domain, SEARCH_HOST_KEYWORDS):
        score -= 80
        reasons.append("search host")
    if _contains_any(url_lower, UNHELPFUL_PATH_KEYWORDS):
        score -= 12
        reasons.append("unhelpful path")

    if _contains_any(domain, DOC_HOST_KEYWORDS):
        score += 12
        reasons.append("docs-like host")
    if _contains_any(url_lower, DOC_PATH_KEYWORDS):
        score += 10
        reasons.append("docs-like path")
    if _contains_any(domain, TRUSTED_HOST_KEYWORDS):
        score += 8
        reasons.append("trusted host")

    unique_tokens = []
    for token in tokens:
        if token not in unique_tokens:
            unique_tokens.append(token)
    for token in unique_tokens:
        if token in title_lower:
            score += 10
            reasons.append(f'title token "{token}"')
        elif token in snippet_lower:
            score += 6
            reasons.append(f'snippet token "{token}"')
        elif token in url_lower:
            score += 4
            reasons.append(f'url token "{token}"')

    if domain:
        brand_overlap = [token for token in unique_tokens if token in domain]
        if brand_overlap:
            score += 10
            reasons.append("domain matches query terms")

    annotated["domain"] = domain
    annotated["selection_score"] = round(score, 2)
    annotated["selection_reasons"] = reasons
    return annotated


def _query_tokens(query: str) -> list[str]:
    """把搜索词切分成更适合匹配的 token 列表。"""
    raw_tokens = re.findall(r"[a-z0-9._-]+|[\u4e00-\u9fff]+", query.lower())
    tokens: list[str] = []
    for token in raw_tokens:
        cleaned = token.strip()
        if len(cleaned) < 2:
            continue
        if cleaned in GENERIC_QUERY_STOPWORDS:
            continue
        tokens.append(cleaned)
    if not tokens and query.strip():
        tokens.append(query.strip().lower())
    return tokens


def _domain_for_url(url: str) -> str:
    """从 URL 中提取域名。"""
    try:
        return urlparse(url).hostname.lower() if urlparse(url).hostname else ""
    except Exception:
        return ""


def _contains_any(value: str, keywords: tuple[str, ...]) -> bool:
    """判断某个字符串是否包含给定关键字集合中的任意一项。"""
    lowered = value.lower()
    return any(keyword in lowered for keyword in keywords)
