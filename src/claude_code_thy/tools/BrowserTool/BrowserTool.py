from __future__ import annotations

from fnmatch import fnmatch

from claude_code_thy.tools.base import (
    PermissionResult,
    Tool,
    ToolContext,
    ToolError,
    ToolResult,
)
from claude_code_thy.tools.shared.common import _make_parser, _parse_args

from .prompt import DESCRIPTION, USAGE


class BrowserTool(Tool):
    """实现内置浏览器工具。"""

    name = "browser"
    description = DESCRIPTION
    usage = USAGE
    input_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "Browser action: status/start/stop/tabs/open/focus/close/navigate/snapshot/screenshot/click/type/press/wait.",
            },
            "url": {"type": "string", "description": "Target URL for open/navigate."},
            "page_id": {"type": "string", "description": "Optional page id such as p1."},
            "ref": {"type": "string", "description": "Snapshot ref such as e1."},
            "text": {"type": "string", "description": "Text for type or wait."},
            "key": {"type": "string", "description": "Keyboard key for press."},
            "timeout_ms": {"type": "integer", "description": "Optional action timeout."},
            "time_ms": {"type": "integer", "description": "Wait duration in milliseconds."},
            "url_contains": {"type": "string", "description": "Substring expected in current URL."},
            "max_chars": {"type": "integer", "description": "Maximum snapshot characters."},
            "full_page": {"type": "boolean", "description": "Take a full-page screenshot."},
            "submit": {"type": "boolean", "description": "Press Enter after typing."},
        },
        "required": ["action"],
    }

    def parse_raw_input(self, raw_args: str, context: ToolContext) -> dict[str, object]:
        """把 `/browser ...` 文本命令解析成结构化输入。"""
        _ = context
        text = raw_args.strip()
        if not text:
            raise ToolError(
                "用法：/browser <status|start|stop|tabs|open|focus|close|navigate|snapshot|screenshot|click|type|press|wait> ..."
            )

        action, _, remainder = text.partition(" ")
        action = action.strip().lower()
        remainder = remainder.strip()

        if action in {"status", "start", "stop", "tabs"}:
            return {"action": action}

        if action == "open":
            parser = _make_parser("browser open", self.description)
            parser.add_argument("url")
            args = _parse_args(parser, remainder)
            return {"action": action, "url": args.url}

        if action == "focus":
            parser = _make_parser("browser focus", self.description)
            parser.add_argument("page_id")
            args = _parse_args(parser, remainder)
            return {"action": action, "page_id": args.page_id}

        if action == "close":
            parser = _make_parser("browser close", self.description)
            parser.add_argument("page_id", nargs="?")
            args = _parse_args(parser, remainder)
            return {
                "action": action,
                **({"page_id": args.page_id} if args.page_id else {}),
            }

        if action == "navigate":
            parser = _make_parser("browser navigate", self.description)
            parser.add_argument("url")
            parser.add_argument("--page-id")
            args = _parse_args(parser, remainder)
            return {
                "action": action,
                "url": args.url,
                **({"page_id": args.page_id} if args.page_id else {}),
            }

        if action == "snapshot":
            parser = _make_parser("browser snapshot", self.description)
            parser.add_argument("page_id", nargs="?")
            parser.add_argument("--max-chars", type=int)
            args = _parse_args(parser, remainder)
            return {
                "action": action,
                **({"page_id": args.page_id} if args.page_id else {}),
                **({"max_chars": args.max_chars} if args.max_chars is not None else {}),
            }

        if action == "screenshot":
            parser = _make_parser("browser screenshot", self.description)
            parser.add_argument("page_id", nargs="?")
            parser.add_argument("--full-page", action="store_true")
            args = _parse_args(parser, remainder)
            return {
                "action": action,
                **({"page_id": args.page_id} if args.page_id else {}),
                "full_page": bool(args.full_page),
            }

        if action == "click":
            parser = _make_parser("browser click", self.description)
            parser.add_argument("ref")
            parser.add_argument("--page-id")
            parser.add_argument("--timeout-ms", type=int)
            args = _parse_args(parser, remainder)
            return {
                "action": action,
                "ref": args.ref,
                **({"page_id": args.page_id} if args.page_id else {}),
                **({"timeout_ms": args.timeout_ms} if args.timeout_ms is not None else {}),
            }

        if action == "type":
            if " -- " not in remainder:
                raise ToolError("用法：/browser type <ref> [--page-id p1] [--submit] -- <text>")
            arg_part, typed_text = remainder.split(" -- ", 1)
            parser = _make_parser("browser type", self.description)
            parser.add_argument("ref")
            parser.add_argument("--page-id")
            parser.add_argument("--submit", action="store_true")
            parser.add_argument("--timeout-ms", type=int)
            args = _parse_args(parser, arg_part.strip())
            if not typed_text.strip():
                raise ToolError("输入文本不能为空")
            return {
                "action": action,
                "ref": args.ref,
                "text": typed_text,
                "submit": bool(args.submit),
                **({"page_id": args.page_id} if args.page_id else {}),
                **({"timeout_ms": args.timeout_ms} if args.timeout_ms is not None else {}),
            }

        if action == "press":
            parser = _make_parser("browser press", self.description)
            parser.add_argument("key")
            parser.add_argument("--page-id")
            parser.add_argument("--timeout-ms", type=int)
            args = _parse_args(parser, remainder)
            return {
                "action": action,
                "key": args.key,
                **({"page_id": args.page_id} if args.page_id else {}),
                **({"timeout_ms": args.timeout_ms} if args.timeout_ms is not None else {}),
            }

        if action == "wait":
            parser = _make_parser("browser wait", self.description)
            parser.add_argument("--page-id")
            parser.add_argument("--time-ms", type=int)
            parser.add_argument("--text")
            parser.add_argument("--url-contains")
            parser.add_argument("--timeout-ms", type=int)
            args = _parse_args(parser, remainder)
            if args.time_ms is None and not args.text and not args.url_contains:
                raise ToolError("wait 至少需要一个条件：--time-ms / --text / --url-contains")
            payload = {"action": action}
            if args.page_id:
                payload["page_id"] = args.page_id
            if args.time_ms is not None:
                payload["time_ms"] = args.time_ms
            if args.text:
                payload["text"] = args.text
            if args.url_contains:
                payload["url_contains"] = args.url_contains
            if args.timeout_ms is not None:
                payload["timeout_ms"] = args.timeout_ms
            return payload

        raise ToolError(f"不支持的浏览器动作：{action}")

    def execute(self, raw_args: str, context: ToolContext) -> ToolResult:
        """兼容 slash 字符串参数调用。"""
        args = self.parse_raw_input(raw_args, context)
        return self.execute_input(args, context)

    def validate_input(self, input_data: dict[str, object], context: ToolContext):
        """执行浏览器工具自己的业务校验。"""
        _ = context
        action = str(input_data.get("action", "")).strip().lower()
        if not action:
            raise ToolError("tool input 缺少 action")
        if action in {"open", "navigate"} and not str(input_data.get("url", "")).strip():
            raise ToolError(f"浏览器动作 `{action}` 缺少 url")
        if action in {"click", "type"} and not str(input_data.get("ref", "")).strip():
            raise ToolError(f"浏览器动作 `{action}` 缺少 ref")
        if action == "type" and not isinstance(input_data.get("text"), str):
            raise ToolError("浏览器动作 `type` 缺少 text")
        if action == "press" and not str(input_data.get("key", "")).strip():
            raise ToolError("浏览器动作 `press` 缺少 key")
        return super().validate_input(input_data, context)

    def check_permissions(
        self,
        input_data: dict[str, object],
        context: ToolContext,
    ) -> PermissionResult:
        """对 open/navigate 这类会访问外部 URL 的动作做权限检查。"""
        action = str(input_data.get("action", "")).strip().lower()
        url = self._primary_url_for_action(action, input_data)
        if not url:
            return PermissionResult.allow(updated_input=input_data)

        decision = context.permission_context.check_url(self.name, url)
        if decision is None or (decision.allowed and not decision.requires_confirmation):
            return PermissionResult.allow(updated_input=input_data)

        request = context.permission_context.build_request_for_url(
            self.name,
            url,
            reason=decision.reason or f"浏览器工具需要访问 URL：{url}",
        )
        if request.approval_key and request.approval_key in context.permission_context.approved_permissions:
            return PermissionResult.allow(updated_input=input_data)
        if decision.requires_confirmation:
            return PermissionResult.ask(request, updated_input=input_data)
        return PermissionResult.deny(
            decision.reason or f"浏览器工具被拒绝访问 URL：{url}",
            updated_input=input_data,
        )

    def prepare_permission_matcher(self, input_data: dict[str, object], context: ToolContext):
        """为 URL 权限确认阶段提供简单的 glob 匹配器。"""
        action = str(input_data.get("action", "")).strip().lower()
        url = self._primary_url_for_action(action, input_data)
        if not url:
            return None
        return lambda pattern: fnmatch(url, pattern)

    def execute_input(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        """执行结构化浏览器动作。"""
        if context.services is None:
            raise ToolError("Browser manager is unavailable")
        manager = context.services.browser_manager
        action = str(input_data.get("action", "")).strip().lower()

        try:
            if action == "status":
                payload = manager.status()
                return self._result_from_status(payload)
            if action == "start":
                payload = manager.start()
                return self._result_from_status(payload, action="start")
            if action == "stop":
                payload = manager.stop()
                return self._result_from_status(payload, action="stop")
            if action == "tabs":
                payload = manager.list_pages()
                return self._result_from_tabs(payload)
            if action == "open":
                payload = manager.open_page(str(input_data.get("url", "")).strip())
                return self._result_from_page_info("open", payload)
            if action == "focus":
                payload = manager.focus_page(str(input_data.get("page_id", "")).strip())
                return self._result_from_page_info("focus", payload)
            if action == "close":
                page_id = str(input_data.get("page_id", "")).strip() or None
                payload = manager.close_page(page_id)
                return self._result_from_simple_payload("close", payload, "浏览器页面已关闭。")
            if action == "navigate":
                payload = manager.navigate(
                    str(input_data.get("url", "")).strip(),
                    page_id=_optional_page_id(input_data),
                )
                return self._result_from_page_info("navigate", payload)
            if action == "snapshot":
                payload = manager.snapshot(
                    page_id=_optional_page_id(input_data),
                    max_chars=_optional_int(input_data, "max_chars"),
                )
                return ToolResult(
                    tool_name=self.name,
                    ok=True,
                    summary=f"浏览器快照：{payload.get('page_id', '')}",
                    display_name="Browser",
                    ui_kind="browser",
                    output=str(payload.get("snapshot", "")),
                    metadata={},
                    structured_data={"type": "browser_snapshot", "action": action, **payload},
                    tool_result_content=str(payload.get("snapshot", "")),
                )
            if action == "screenshot":
                payload = manager.screenshot(
                    page_id=_optional_page_id(input_data),
                    full_page=bool(input_data.get("full_page", False)),
                )
                output = f"截图已保存：{payload.get('path', '')}"
                return ToolResult(
                    tool_name=self.name,
                    ok=True,
                    summary=f"浏览器截图：{payload.get('page_id', '')}",
                    display_name="Browser",
                    ui_kind="browser",
                    output=output,
                    metadata={"path": payload.get("path", "")},
                    structured_data={"type": "browser_screenshot", "action": action, **payload},
                    tool_result_content=output,
                )
            if action == "click":
                payload = manager.click(
                    str(input_data.get("ref", "")).strip(),
                    page_id=_optional_page_id(input_data),
                    timeout_ms=_optional_int(input_data, "timeout_ms"),
                )
                return self._result_from_page_info("click", payload)
            if action == "type":
                payload = manager.type_text(
                    str(input_data.get("ref", "")).strip(),
                    str(input_data.get("text", "")),
                    page_id=_optional_page_id(input_data),
                    submit=bool(input_data.get("submit", False)),
                    timeout_ms=_optional_int(input_data, "timeout_ms"),
                )
                return self._result_from_page_info("type", payload)
            if action == "press":
                payload = manager.press(
                    str(input_data.get("key", "")).strip(),
                    page_id=_optional_page_id(input_data),
                    timeout_ms=_optional_int(input_data, "timeout_ms"),
                )
                return self._result_from_page_info("press", payload)
            if action == "wait":
                payload = manager.wait(
                    page_id=_optional_page_id(input_data),
                    time_ms=_optional_int(input_data, "time_ms"),
                    text=_optional_str(input_data, "text"),
                    url_contains=_optional_str(input_data, "url_contains"),
                    timeout_ms=_optional_int(input_data, "timeout_ms"),
                )
                return self._result_from_page_info("wait", payload)
        except PermissionRequiredError:
            raise
        except ToolError:
            raise
        except Exception as error:
            raise ToolError(str(error)) from error

        raise ToolError(f"不支持的浏览器动作：{action}")

    def _result_from_status(self, payload: dict[str, object], *, action: str = "status") -> ToolResult:
        """把状态结果转换成统一 ToolResult。"""
        running = bool(payload.get("running", False))
        lines = [
            f"enabled: {payload.get('enabled', False)}",
            f"running: {running}",
            f"headless: {payload.get('headless', False)}",
            f"page_count: {payload.get('page_count', 0)}",
            f"current_page_id: {payload.get('current_page_id') or ''}",
            f"profile_dir: {payload.get('profile_dir', '')}",
            f"artifacts_dir: {payload.get('artifacts_dir', '')}",
        ]
        return ToolResult(
            tool_name=self.name,
            ok=True,
            summary=f"浏览器状态：{'运行中' if running else '未运行'}",
            display_name="Browser",
            ui_kind="browser",
            output="\n".join(lines),
            metadata={},
            structured_data={"type": "browser_status", "action": action, **payload},
            tool_result_content="\n".join(lines),
        )

    def _result_from_tabs(self, pages: list[dict[str, object]]) -> ToolResult:
        """把页面列表转换成统一 ToolResult。"""
        if not pages:
            output = "当前没有页面。"
        else:
            output = "\n".join(
                f"- {page.get('page_id', '')} | {page.get('title', '') or '(untitled)'} | {page.get('url', '')}"
                for page in pages
            )
        return ToolResult(
            tool_name=self.name,
            ok=True,
            summary=f"浏览器页面：{len(pages)} 个",
            display_name="Browser",
            ui_kind="browser",
            output=output,
            metadata={},
            structured_data={"type": "browser_tabs", "action": "tabs", "pages": pages},
            tool_result_content=output,
        )

    def _result_from_page_info(self, action: str, payload: dict[str, object]) -> ToolResult:
        """把单页面动作结果转换成统一 ToolResult。"""
        title = str(payload.get("title", "")).strip() or "(untitled)"
        url = str(payload.get("url", "")).strip()
        page_id = str(payload.get("page_id", "")).strip()
        lines = [
            f"page_id: {page_id}",
            f"title: {title}",
            f"url: {url}",
        ]
        if payload.get("submitted") is not None:
            lines.append(f"submitted: {payload.get('submitted')}")
        if payload.get("key"):
            lines.append(f"key: {payload.get('key')}")
        if payload.get("text"):
            lines.append(f"text: {payload.get('text')}")
        if payload.get("url_contains"):
            lines.append(f"url_contains: {payload.get('url_contains')}")
        if payload.get("time_ms") is not None:
            lines.append(f"time_ms: {payload.get('time_ms')}")
        output = "\n".join(lines)
        return ToolResult(
            tool_name=self.name,
            ok=True,
            summary=f"浏览器动作：{action} {page_id}".strip(),
            display_name="Browser",
            ui_kind="browser",
            output=output,
            metadata={},
            structured_data={"type": "browser_action", "action": action, **payload},
            tool_result_content=output,
        )

    def _result_from_simple_payload(
        self,
        action: str,
        payload: dict[str, object],
        message: str,
    ) -> ToolResult:
        """把没有复杂正文的动作结果包装成统一 ToolResult。"""
        lines = [message]
        for key, value in payload.items():
            lines.append(f"{key}: {value}")
        output = "\n".join(lines)
        return ToolResult(
            tool_name=self.name,
            ok=True,
            summary=f"浏览器动作：{action}",
            display_name="Browser",
            ui_kind="browser",
            output=output,
            metadata={},
            structured_data={"type": "browser_action", "action": action, **payload},
            tool_result_content=output,
        )

    def _primary_url_for_action(
        self,
        action: str,
        input_data: dict[str, object],
    ) -> str:
        """返回当前动作最主要的目标 URL，用于首轮权限判断。"""
        if action in {"open", "navigate"}:
            return str(input_data.get("url", "")).strip()
        return ""


def _optional_page_id(input_data: dict[str, object]) -> str | None:
    """把 page_id 字段安全地转换成可选字符串。"""
    value = str(input_data.get("page_id", "")).strip()
    return value or None


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
