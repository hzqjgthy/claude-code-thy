from __future__ import annotations

from fnmatch import fnmatch

from claude_code_thy.browser import (
    build_search_url,
    normalize_search_engine,
    select_search_results,
)
from claude_code_thy.tools.base import (
    PermissionRequiredError,
    PermissionResult,
    Tool,
    ToolContext,
    ToolError,
    ToolResult,
    ValidationResult,
)
from claude_code_thy.tools.shared.common import _make_parser, _parse_args

from .prompt import DESCRIPTION, USAGE

DEFAULT_SEARCH_RESULT_COUNT = 8
DEFAULT_SEARCH_OPEN_COUNT = 3
DEFAULT_SEARCH_PER_PAGE_MAX_CHARS = 3000
MAX_SEARCH_RESULT_COUNT = 20
MAX_SEARCH_OPEN_COUNT = 5


class BrowserSearchTool(Tool):
    """实现独立的浏览器搜索工具。"""

    name = "browser_search"
    description = DESCRIPTION
    usage = USAGE
    input_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query."},
            "result_count": {"type": "integer", "description": "How many search results to collect from the results page."},
            "open_count": {"type": "integer", "description": "How many result pages to expand after ranking and dedupe."},
            "per_page_max_chars": {"type": "integer", "description": "Maximum snapshot characters for each expanded page."},
            "search_engine": {"type": "string", "description": "Search engine name from browser_search settings."},
        },
        "required": ["query"],
    }

    def is_read_only(self) -> bool:
        """声明该工具为只读型网页搜索。"""
        return True

    def parse_raw_input(self, raw_args: str, context: ToolContext) -> dict[str, object]:
        """把 `/browser-search ...` 解析成结构化输入。"""
        _ = context
        parser = _make_parser("browser-search", self.description)
        parser.add_argument("--result-count", type=int, default=DEFAULT_SEARCH_RESULT_COUNT)
        parser.add_argument("--open-count", type=int, default=DEFAULT_SEARCH_OPEN_COUNT)
        parser.add_argument("--per-page-max-chars", type=int, default=DEFAULT_SEARCH_PER_PAGE_MAX_CHARS)
        parser.add_argument("--search-engine")

        remainder = raw_args.strip()
        if remainder.startswith("-- "):
            arg_part = ""
            query = remainder[3:]
        elif " -- " in remainder:
            arg_part, query = remainder.split(" -- ", 1)
        else:
            arg_part = ""
            query = remainder

        args = _parse_args(parser, arg_part)
        query = query.strip()
        if not query:
            raise ToolError(
                "用法：/browser-search [--result-count N] [--open-count N] [--per-page-max-chars N] [--search-engine NAME] -- <query>"
            )
        return {
            "query": query,
            "result_count": int(args.result_count or DEFAULT_SEARCH_RESULT_COUNT),
            "open_count": int(args.open_count or DEFAULT_SEARCH_OPEN_COUNT),
            "per_page_max_chars": int(args.per_page_max_chars or DEFAULT_SEARCH_PER_PAGE_MAX_CHARS),
            **({"search_engine": str(args.search_engine).strip()} if args.search_engine else {}),
        }

    def execute(self, raw_args: str, context: ToolContext) -> ToolResult:
        """兼容 slash 文本执行。"""
        args = self.parse_raw_input(raw_args, context)
        return self.execute_input(args, context)

    def validate_input(self, input_data: dict[str, object], context: ToolContext):
        """校验搜索参数并归一成稳定输入。"""
        if context.services is None:
            raise ToolError("Browser search settings are unavailable")
        normalized = dict(input_data)
        query = str(input_data.get("query", "")).strip()
        if not query:
            raise ToolError("browser_search 缺少 query")
        result_count = _optional_int(input_data, "result_count") or DEFAULT_SEARCH_RESULT_COUNT
        open_count = _optional_int(input_data, "open_count")
        if open_count is None:
            open_count = min(DEFAULT_SEARCH_OPEN_COUNT, result_count)
        per_page_max_chars = _optional_int(input_data, "per_page_max_chars") or DEFAULT_SEARCH_PER_PAGE_MAX_CHARS
        if result_count < 1 or result_count > MAX_SEARCH_RESULT_COUNT:
            raise ToolError(f"result_count 必须在 1 到 {MAX_SEARCH_RESULT_COUNT} 之间")
        if open_count < 0 or open_count > MAX_SEARCH_OPEN_COUNT:
            raise ToolError(f"open_count 必须在 0 到 {MAX_SEARCH_OPEN_COUNT} 之间")
        if open_count > result_count:
            raise ToolError("open_count 不能大于 result_count")
        if per_page_max_chars < 1:
            raise ToolError("per_page_max_chars 必须大于 0")
        normalized["query"] = query
        normalized["result_count"] = result_count
        normalized["open_count"] = open_count
        normalized["per_page_max_chars"] = per_page_max_chars
        normalized["search_engine"] = normalize_search_engine(
            context.services.settings.browser_search,
            _optional_str(input_data, "search_engine"),
        )
        return ValidationResult.allow(updated_input=normalized)

    def check_permissions(
        self,
        input_data: dict[str, object],
        context: ToolContext,
    ) -> PermissionResult:
        """先对搜索引擎 URL 做权限检查。"""
        if context.services is None:
            return PermissionResult.allow(updated_input=input_data)
        url = self._primary_search_url(input_data, context)
        decision = context.permission_context.check_url(self.name, url)
        if decision is None or (decision.allowed and not decision.requires_confirmation):
            return PermissionResult.allow(updated_input=input_data)
        request = context.permission_context.build_request_for_url(
            self.name,
            url,
            reason=decision.reason or f"浏览器搜索工具需要访问 URL：{url}",
        )
        if request.approval_key and request.approval_key in context.permission_context.approved_permissions:
            return PermissionResult.allow(updated_input=input_data)
        if decision.requires_confirmation:
            return PermissionResult.ask(request, updated_input=input_data)
        return PermissionResult.deny(
            decision.reason or f"浏览器搜索工具被拒绝访问 URL：{url}",
            updated_input=input_data,
        )

    def prepare_permission_matcher(self, input_data: dict[str, object], context: ToolContext):
        """为权限确认阶段提供搜索 URL 的 glob 匹配器。"""
        if context.services is None:
            return None
        url = self._primary_search_url(input_data, context)
        return lambda pattern: fnmatch(url, pattern)

    def execute_input(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        """执行搜索、打分筛选和展开网页抓取。"""
        if context.services is None:
            raise ToolError("Browser manager is unavailable")

        manager = context.services.browser_manager
        search_settings = context.services.settings.browser_search
        query = str(input_data.get("query", "")).strip()
        result_count = _optional_int(input_data, "result_count") or DEFAULT_SEARCH_RESULT_COUNT
        open_count = _optional_int(input_data, "open_count")
        if open_count is None:
            open_count = min(DEFAULT_SEARCH_OPEN_COUNT, result_count)

        try:
            search_payload = manager.search_results(
                query,
                result_count=result_count,
                search_settings=search_settings,
                search_engine=_optional_str(input_data, "search_engine"),
            )
            results = search_payload.get("results") if isinstance(search_payload.get("results"), list) else []
            scored_results, selected_results = select_search_results(
                [item for item in results if isinstance(item, dict)],
                query=query,
                open_count=open_count,
                settings=search_settings,
            )
            for item in selected_results:
                context.permission_context.require_url(
                    self.name,
                    str(item.get("url", "")).strip(),
                )
            captured_pages = manager.capture_pages(
                selected_results,
                per_page_max_chars=_optional_int(input_data, "per_page_max_chars") or DEFAULT_SEARCH_PER_PAGE_MAX_CHARS,
            )
            return self._result_from_search(
                search_payload,
                scored_results,
                selected_results,
                captured_pages,
                open_count=open_count,
            )
        except PermissionRequiredError:
            raise
        except ToolError:
            raise
        except Exception as error:
            raise ToolError(str(error)) from error

    def _result_from_search(
        self,
        search_payload: dict[str, object],
        scored_results: list[dict[str, object]],
        selected_results: list[dict[str, object]],
        pages: list[dict[str, object]],
        *,
        open_count: int,
    ) -> ToolResult:
        """把搜索结果和展开网页内容汇总成统一 ToolResult。"""
        query = str(search_payload.get("query", "")).strip()
        search_url = str(search_payload.get("search_url", "")).strip()
        search_engine = str(search_payload.get("search_engine", "")).strip()
        parser = str(search_payload.get("parser", "")).strip()

        lines = [
            f"Search Query: {query}",
            f"Search Engine: {search_engine}",
            f"Search Parser: {parser}",
            f"Search URL: {search_url}",
            "",
            "Top Results:",
        ]
        if not scored_results:
            lines.append("(none)")
        else:
            for item in scored_results:
                if not isinstance(item, dict):
                    continue
                rank = item.get("rank", "")
                title = str(item.get("title", "")).strip()
                url = str(item.get("url", "")).strip()
                snippet = str(item.get("snippet", "")).strip()
                score = item.get("selection_score", 0)
                selected = any(
                    str(candidate.get("url", "")).strip() == url
                    for candidate in selected_results
                    if isinstance(candidate, dict)
                )
                lines.append(f"{rank}. {title}")
                lines.append(f"URL: {url}")
                lines.append(f"Score: {score}")
                lines.append(f"Selected: {'yes' if selected else 'no'}")
                if snippet:
                    lines.append(f"Snippet: {snippet}")
                reasons = item.get("selection_reasons")
                if isinstance(reasons, list) and reasons:
                    lines.append("Why: " + ", ".join(str(reason) for reason in reasons[:4]))
                lines.append("")

        lines.append("Expanded Pages:")
        if not pages:
            lines.append("(none)")
        else:
            for item in pages:
                if not isinstance(item, dict):
                    continue
                rank = item.get("rank", "")
                title = str(item.get("title") or item.get("source_title") or "").strip() or "(untitled)"
                url = str(item.get("url") or item.get("source_url") or "").strip()
                lines.append(f"[{rank}] {title}")
                lines.append(f"URL: {url}")
                if item.get("error"):
                    lines.append(f"Error: {item['error']}")
                else:
                    lines.append("Snapshot:")
                    lines.append(str(item.get("snapshot", "")).strip())
                lines.append("")

        output = "\n".join(line for line in lines).strip()
        return ToolResult(
            tool_name=self.name,
            ok=True,
            summary=f"浏览器搜索：{query}",
            display_name="Browser Search",
            ui_kind="browser_search",
            output=output,
            metadata={},
            structured_data={
                "type": "browser_search",
                "query": query,
                "search_url": search_url,
                "search_engine": search_engine,
                "parser": parser,
                "result_count": len(scored_results),
                "open_count": open_count,
                "results": scored_results,
                "selected_results": selected_results,
                "pages": pages,
            },
            tool_result_content=output,
        )

    def _primary_search_url(self, input_data: dict[str, object], context: ToolContext) -> str:
        """返回搜索引擎结果页 URL，用于首轮权限判断。"""
        query = str(input_data.get("query", "")).strip()
        if not query:
            raise ToolError("browser_search 缺少 query")
        try:
            return build_search_url(
                query,
                settings=context.services.settings.browser_search if context.services is not None else None,
                search_engine=_optional_str(input_data, "search_engine"),
            )
        except ValueError as error:
            raise ToolError(str(error)) from error


def _optional_int(input_data: dict[str, object], key: str) -> int | None:
    """把某个整数输入字段安全地转成可选 int。"""
    value = input_data.get(key)
    if value in (None, ""):
        return None
    return int(value)


def _optional_str(input_data: dict[str, object], key: str) -> str | None:
    """把某个字符串输入字段安全地转成可选字符串。"""
    value = str(input_data.get(key, "")).strip()
    return value or None
