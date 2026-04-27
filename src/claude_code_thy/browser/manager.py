from __future__ import annotations

import importlib
import queue
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import Lock, Thread
from typing import Any
from uuid import uuid4

from claude_code_thy.settings import BrowserSearchSettings, BrowserSettings

from .search import (
    build_search_url,
    resolve_search_engine_config,
    search_results_script,
)
from .snapshot import SNAPSHOT_SCRIPT, build_snapshot_text


@dataclass(slots=True)
class _WorkerRequest:
    """表示一条发往浏览器 worker 的同步调用请求。"""
    method: str
    args: tuple[object, ...]
    kwargs: dict[str, object]
    response_queue: "queue.Queue[tuple[bool, object]]"


class BrowserManager:
    """对外提供线程安全的浏览器工具调用入口。"""

    def __init__(self, workspace_root: Path, settings: BrowserSettings) -> None:
        """保存工作区路径和浏览器配置，并延迟创建 worker。"""
        self.workspace_root = workspace_root.resolve()
        self.settings = settings
        self._worker: _BrowserWorker | None = None
        self._lock = Lock()

    def status(self) -> dict[str, object]:
        """返回当前浏览器运行状态。"""
        return self._worker_instance().call("status")

    def start(self) -> dict[str, object]:
        """启动隔离浏览器并返回最新状态。"""
        return self._worker_instance().call("start")

    def stop(self) -> dict[str, object]:
        """关闭浏览器实例并返回停止后的状态。"""
        return self._worker_instance().call("stop")

    def list_pages(self) -> list[dict[str, object]]:
        """列出当前浏览器上下文中的所有页面。"""
        return self._worker_instance().call("list_pages")

    def open_page(self, url: str) -> dict[str, object]:
        """新建页面并导航到指定 URL。"""
        return self._worker_instance().call("open_page", url)

    def focus_page(self, page_id: str) -> dict[str, object]:
        """把某个页面切换为当前页面。"""
        return self._worker_instance().call("focus_page", page_id)

    def close_page(self, page_id: str | None = None) -> dict[str, object]:
        """关闭指定页面，未传时关闭当前页面。"""
        if page_id is None:
            return self._worker_instance().call("close_current_page")
        return self._worker_instance().call("close_page", page_id)

    def navigate(self, url: str, *, page_id: str | None = None) -> dict[str, object]:
        """在当前或指定页面里导航到新的 URL。"""
        return self._worker_instance().call("navigate", url, page_id=page_id)

    def snapshot(self, *, page_id: str | None = None, max_chars: int | None = None) -> dict[str, object]:
        """抓取当前页面的文本快照和 ref 列表。"""
        return self._worker_instance().call("snapshot", page_id=page_id, max_chars=max_chars)

    def screenshot(self, *, page_id: str | None = None, full_page: bool = False) -> dict[str, object]:
        """保存当前页面截图到工作区产物目录。"""
        return self._worker_instance().call("screenshot", page_id=page_id, full_page=full_page)

    def click(self, ref: str, *, page_id: str | None = None, timeout_ms: int | None = None) -> dict[str, object]:
        """点击某个 ref 指向的元素。"""
        return self._worker_instance().call("click", ref, page_id=page_id, timeout_ms=timeout_ms)

    def type_text(
        self,
        ref: str,
        text: str,
        *,
        page_id: str | None = None,
        submit: bool = False,
        timeout_ms: int | None = None,
    ) -> dict[str, object]:
        """向某个输入元素写入文本。"""
        return self._worker_instance().call(
            "type_text",
            ref,
            text,
            page_id=page_id,
            submit=submit,
            timeout_ms=timeout_ms,
        )

    def press(self, key: str, *, page_id: str | None = None, timeout_ms: int | None = None) -> dict[str, object]:
        """向当前页面发送一个键盘按键。"""
        return self._worker_instance().call("press", key, page_id=page_id, timeout_ms=timeout_ms)

    def wait(
        self,
        *,
        page_id: str | None = None,
        time_ms: int | None = None,
        text: str | None = None,
        url_contains: str | None = None,
        timeout_ms: int | None = None,
    ) -> dict[str, object]:
        """等待时间、文本出现或 URL 变化。"""
        return self._worker_instance().call(
            "wait",
            page_id=page_id,
            time_ms=time_ms,
            text=text,
            url_contains=url_contains,
            timeout_ms=timeout_ms,
        )

    def search_results(
        self,
        query: str,
        *,
        result_count: int,
        search_settings: BrowserSearchSettings,
        search_engine: str | None = None,
    ) -> dict[str, object]:
        """执行搜索并返回候选结果列表。"""
        return self._worker_instance().call(
            "search_results",
            query,
            result_count=result_count,
            search_settings=search_settings,
            search_engine=search_engine,
        )

    def capture_pages(
        self,
        results: list[dict[str, object]],
        *,
        per_page_max_chars: int,
    ) -> list[dict[str, object]]:
        """顺序打开若干搜索结果页，并抓取各自快照。"""
        return self._worker_instance().call(
            "capture_pages",
            results,
            per_page_max_chars=per_page_max_chars,
        )

    def _worker_instance(self) -> "_BrowserWorker":
        """惰性初始化浏览器 worker，并保证后续复用同一线程。"""
        with self._lock:
            if self._worker is None:
                self._worker = _BrowserWorker(self.workspace_root, self.settings)
            return self._worker


class _BrowserWorker:
    """把所有 Playwright 对象固定在单独线程里，避免跨线程复用。"""

    def __init__(self, workspace_root: Path, settings: BrowserSettings) -> None:
        """创建请求队列和后台线程，但不立即初始化浏览器实例。"""
        self.workspace_root = workspace_root
        self.settings = settings
        self._requests: "queue.Queue[_WorkerRequest | None]" = queue.Queue()
        self._thread = Thread(
            target=self._run,
            name="claude-code-thy-browser",
            daemon=True,
        )
        self._started = False
        self._lock = Lock()

    def call(self, method: str, *args: object, **kwargs: object) -> object:
        """向 worker 线程同步发起一次方法调用并返回结果。"""
        self._ensure_started()
        response_queue: "queue.Queue[tuple[bool, object]]" = queue.Queue(maxsize=1)
        self._requests.put(
            _WorkerRequest(
                method=method,
                args=args,
                kwargs=kwargs,
                response_queue=response_queue,
            )
        )
        ok, payload = response_queue.get()
        if ok:
            return payload
        if isinstance(payload, Exception):
            raise payload
        raise RuntimeError(str(payload))

    def _ensure_started(self) -> None:
        """确保后台线程已经启动。"""
        with self._lock:
            if self._started:
                return
            self._thread.start()
            self._started = True

    def _run(self) -> None:
        """浏览器 worker 主循环。"""
        runtime = _BrowserRuntime(self.workspace_root, self.settings)
        while True:
            request = self._requests.get()
            if request is None:
                break
            try:
                result = getattr(runtime, request.method)(*request.args, **request.kwargs)
            except Exception as error:  # pragma: no cover - 错误透传给主线程
                request.response_queue.put((False, error))
                continue
            request.response_queue.put((True, result))


class _BrowserRuntime:
    """真正持有 Playwright 对象并执行浏览器动作的线程内运行时。"""

    def __init__(self, workspace_root: Path, settings: BrowserSettings) -> None:
        """初始化运行时状态，但暂不启动 Playwright。"""
        self.workspace_root = workspace_root
        self.settings = settings
        self._playwright: object | None = None
        self._context: object | None = None
        self._pages_by_id: dict[str, object] = {}
        self._page_ids_by_object_id: dict[int, str] = {}
        self._current_page_id: str | None = None
        self._next_page_number = 1

    def status(self) -> dict[str, object]:
        """返回浏览器启用状态、运行状态和页面数量。"""
        self._sync_pages()
        return {
            "enabled": self.settings.enabled,
            "running": self._context is not None,
            "headless": self.settings.headless,
            "current_page_id": self._current_page_id,
            "page_count": len(self._pages_by_id),
            "profile_dir": str(self._profile_dir()),
            "artifacts_dir": str(self._artifacts_dir()),
        }

    def start(self) -> dict[str, object]:
        """启动浏览器上下文，并确保至少有一个空白页可用。"""
        self._ensure_running()
        self._ensure_current_page()
        return self.status()

    def stop(self) -> dict[str, object]:
        """关闭浏览器上下文并清空线程内缓存。"""
        if self._context is not None:
            self._context.close()
        if self._playwright is not None:
            self._playwright.stop()
        self._playwright = None
        self._context = None
        self._pages_by_id.clear()
        self._page_ids_by_object_id.clear()
        self._current_page_id = None
        return self.status()

    def list_pages(self) -> list[dict[str, object]]:
        """列出所有页面的 page_id、标题、URL 和是否当前页。"""
        self._sync_pages()
        pages: list[dict[str, object]] = []
        for page_id, page in self._pages_by_id.items():
            pages.append(self._page_info(page_id, page))
        return pages

    def open_page(self, url: str) -> dict[str, object]:
        """创建新页面并导航到指定 URL。"""
        self._ensure_running()
        page = self._context.new_page()
        self._set_page_timeout(page)
        page.goto(url, wait_until="domcontentloaded", timeout=self.settings.action_timeout_ms)
        page_id = self._register_page(page)
        self._current_page_id = page_id
        return self._page_info(page_id, page)

    def focus_page(self, page_id: str) -> dict[str, object]:
        """把指定页面切换为当前页，并尝试 bring_to_front。"""
        page = self._require_page(page_id)
        page.bring_to_front()
        self._current_page_id = page_id
        return self._page_info(page_id, page)

    def close_current_page(self) -> dict[str, object]:
        """关闭当前页面。"""
        page_id, _page = self._require_current_page()
        return self.close_page(page_id)

    def close_page(self, page_id: str) -> dict[str, object]:
        """关闭指定页面，并自动切换到剩余页面中的一个。"""
        page = self._require_page(page_id)
        page.close()
        self._sync_pages()
        return {
            "closed_page_id": page_id,
            "current_page_id": self._current_page_id,
            "page_count": len(self._pages_by_id),
        }

    def navigate(self, url: str, *, page_id: str | None = None) -> dict[str, object]:
        """在当前或指定页面里导航到新地址。"""
        resolved_page_id, page = self._page_or_current(page_id)
        page.goto(url, wait_until="domcontentloaded", timeout=self.settings.action_timeout_ms)
        self._current_page_id = resolved_page_id
        return self._page_info(resolved_page_id, page)

    def snapshot(self, *, page_id: str | None = None, max_chars: int | None = None) -> dict[str, object]:
        """抓取页面文本快照，并给交互元素分配稳定的 ref。"""
        resolved_page_id, page = self._page_or_current(page_id)
        raw = page.evaluate(SNAPSHOT_SCRIPT)
        if not isinstance(raw, dict):
            raise RuntimeError("浏览器快照结果格式无效")
        rendered = build_snapshot_text(
            raw,
            max_chars=max(1, int(max_chars or self.settings.snapshot_max_chars)),
        )
        refs = raw.get("refs") if isinstance(raw.get("refs"), list) else []
        return {
            "page_id": resolved_page_id,
            "title": str(raw.get("title", "")).strip(),
            "url": str(raw.get("url", "")).strip(),
            "ref_count": len(refs),
            "snapshot": rendered,
        }

    def screenshot(self, *, page_id: str | None = None, full_page: bool = False) -> dict[str, object]:
        """保存截图到浏览器产物目录。"""
        resolved_page_id, page = self._page_or_current(page_id)
        path = self._artifacts_dir() / f"screenshot-{resolved_page_id}-{uuid4().hex[:8]}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(
            path=str(path),
            full_page=full_page,
            timeout=self.settings.action_timeout_ms,
        )
        info = self._page_info(resolved_page_id, page)
        return {
            "page_id": resolved_page_id,
            "url": info["url"],
            "title": info["title"],
            "path": str(path),
            "full_page": full_page,
        }

    def click(self, ref: str, *, page_id: str | None = None, timeout_ms: int | None = None) -> dict[str, object]:
        """点击由 snapshot 生成的 ref。"""
        resolved_page_id, page = self._page_or_current(page_id)
        locator = self._locator_for_ref(page, ref)
        locator.click(timeout=timeout_ms or self.settings.action_timeout_ms)
        return self._page_info(resolved_page_id, page)

    def type_text(
        self,
        ref: str,
        text: str,
        *,
        page_id: str | None = None,
        submit: bool = False,
        timeout_ms: int | None = None,
    ) -> dict[str, object]:
        """向 ref 指向的输入元素填充文本，可选回车提交。"""
        resolved_page_id, page = self._page_or_current(page_id)
        locator = self._locator_for_ref(page, ref)
        locator.fill(text, timeout=timeout_ms or self.settings.action_timeout_ms)
        if submit:
            locator.press("Enter", timeout=timeout_ms or self.settings.action_timeout_ms)
        info = self._page_info(resolved_page_id, page)
        info["submitted"] = submit
        return info

    def press(self, key: str, *, page_id: str | None = None, timeout_ms: int | None = None) -> dict[str, object]:
        """向页面发送一个键盘按键。"""
        resolved_page_id, page = self._page_or_current(page_id)
        page.keyboard.press(key, timeout=timeout_ms or self.settings.action_timeout_ms)
        info = self._page_info(resolved_page_id, page)
        info["key"] = key
        return info

    def wait(
        self,
        *,
        page_id: str | None = None,
        time_ms: int | None = None,
        text: str | None = None,
        url_contains: str | None = None,
        timeout_ms: int | None = None,
    ) -> dict[str, object]:
        """等待指定时间、文本出现或 URL 包含某个片段。"""
        resolved_page_id, page = self._page_or_current(page_id)
        resolved_timeout = timeout_ms or self.settings.action_timeout_ms
        if time_ms is not None:
            page.wait_for_timeout(time_ms)
        if text:
            page.get_by_text(text).first.wait_for(state="visible", timeout=resolved_timeout)
        if url_contains:
            page.wait_for_function(
                "(value) => window.location.href.includes(value)",
                arg=url_contains,
                timeout=resolved_timeout,
            )
        info = self._page_info(resolved_page_id, page)
        if time_ms is not None:
            info["time_ms"] = time_ms
        if text:
            info["text"] = text
        if url_contains:
            info["url_contains"] = url_contains
        return info

    def search_results(
        self,
        query: str,
        *,
        result_count: int,
        search_settings: BrowserSearchSettings,
        search_engine: str | None = None,
    ) -> dict[str, object]:
        """打开搜索结果页，并提取前若干条候选结果。"""
        normalized_engine, engine_config = resolve_search_engine_config(search_settings, search_engine)
        parser_name = str(engine_config.get("parser", "generic_links") or "generic_links").strip().lower()
        search_url = build_search_url(
            query,
            settings=search_settings,
            search_engine=normalized_engine,
        )

        search_page = self._open_fresh_page(search_url)
        search_page_id = self._register_page(search_page)
        self._current_page_id = search_page_id

        raw_results = search_page.evaluate(
            search_results_script(parser_name),
            max(1, int(result_count)),
        )
        if not isinstance(raw_results, list):
            raw_results = []

        results: list[dict[str, object]] = []
        for index, item in enumerate(raw_results, start=1):
            if not isinstance(item, dict):
                continue
            title = str(item.get("title", "")).strip()
            url = str(item.get("url", "")).strip()
            snippet = str(item.get("snippet", "")).strip()
            if not title or not url:
                continue
            results.append(
                {
                    "rank": int(item.get("rank", index) or index),
                    "title": title,
                    "url": url,
                    "snippet": snippet,
                }
            )

        return {
            "query": query.strip(),
            "search_engine": normalized_engine,
            "parser": parser_name,
            "search_url": search_url,
            "page_id": search_page_id,
            "result_count": len(results),
            "results": results,
        }

    def capture_pages(
        self,
        results: list[dict[str, object]],
        *,
        per_page_max_chars: int,
    ) -> list[dict[str, object]]:
        """顺序打开若干网页并返回每个网页的快照结果。"""
        self._ensure_running()
        captured: list[dict[str, object]] = []
        max_chars = max(1, int(per_page_max_chars))

        for item in results:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url", "")).strip()
            if not url:
                continue

            page = self._context.new_page()
            self._set_page_timeout(page)
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=self.settings.action_timeout_ms)
                raw_snapshot = page.evaluate(SNAPSHOT_SCRIPT)
                if not isinstance(raw_snapshot, dict):
                    raise RuntimeError("网页快照结果格式无效")
                captured.append(
                    {
                        "rank": int(item.get("rank", 0) or 0),
                        "source_title": str(item.get("title", "")).strip(),
                        "source_url": url,
                        "title": str(raw_snapshot.get("title", "")).strip(),
                        "url": str(raw_snapshot.get("url", "")).strip() or url,
                        "ref_count": len(raw_snapshot.get("refs") or []),
                        "snapshot": build_snapshot_text(raw_snapshot, max_chars=max_chars),
                    }
                )
            except Exception as error:
                captured.append(
                    {
                        "rank": int(item.get("rank", 0) or 0),
                        "source_title": str(item.get("title", "")).strip(),
                        "source_url": url,
                        "error": str(error),
                    }
                )
            finally:
                try:
                    page.close()
                except Exception:
                    pass

        self._sync_pages()
        return captured

    def _ensure_running(self) -> None:
        """惰性启动 Playwright 和持久浏览器上下文。"""
        if not self.settings.enabled:
            raise RuntimeError("浏览器工具已在 settings 中被禁用。")
        if self._context is not None:
            return

        sync_api = self._load_playwright_sync_api()
        self._profile_dir().mkdir(parents=True, exist_ok=True)
        self._artifacts_dir().mkdir(parents=True, exist_ok=True)
        self._playwright = sync_api.sync_playwright().start()
        launch_options: dict[str, object] = {
            "user_data_dir": str(self._profile_dir()),
            "headless": self.settings.headless,
            "timeout": self.settings.launch_timeout_ms,
            "viewport": {
                "width": self.settings.viewport_width,
                "height": self.settings.viewport_height,
            },
        }
        executable_path = self.settings.executable_path.strip()
        if executable_path:
            launch_options["executable_path"] = executable_path
        self._context = self._playwright.chromium.launch_persistent_context(**launch_options)
        self._sync_pages()

    def _open_fresh_page(self, url: str) -> object:
        """创建一个新页面并导航到目标 URL。"""
        self._ensure_running()
        page = self._context.new_page()
        self._set_page_timeout(page)
        page.goto(url, wait_until="domcontentloaded", timeout=self.settings.action_timeout_ms)
        return page

    def _ensure_current_page(self) -> tuple[str, object]:
        """确保当前上下文里至少存在一个页面。"""
        self._sync_pages()
        if self._current_page_id and self._current_page_id in self._pages_by_id:
            return self._current_page_id, self._pages_by_id[self._current_page_id]
        if self._context is None:
            raise RuntimeError("浏览器尚未启动。")
        page = self._context.new_page()
        self._set_page_timeout(page)
        page_id = self._register_page(page)
        self._current_page_id = page_id
        return page_id, page

    def _require_current_page(self) -> tuple[str, object]:
        """返回当前页面，不存在时自动创建一个空白页。"""
        self._ensure_running()
        return self._ensure_current_page()

    def _page_or_current(self, page_id: str | None) -> tuple[str, object]:
        """在显式 page_id 和当前页之间解析最终目标页面。"""
        self._ensure_running()
        if page_id:
            return page_id, self._require_page(page_id)
        return self._require_current_page()

    def _require_page(self, page_id: str) -> object:
        """按 page_id 取回页面对象。"""
        self._sync_pages()
        page = self._pages_by_id.get(page_id)
        if page is None:
            raise RuntimeError(f"未找到页面：{page_id}")
        return page

    def _sync_pages(self) -> None:
        """把上下文里的真实页面列表同步到 page_id 映射。"""
        if self._context is None:
            self._pages_by_id = {}
            self._page_ids_by_object_id = {}
            self._current_page_id = None
            return

        live_pages = list(self._context.pages)
        live_object_ids = {id(page) for page in live_pages}
        self._page_ids_by_object_id = {
            object_id: page_id
            for object_id, page_id in self._page_ids_by_object_id.items()
            if object_id in live_object_ids
        }

        pages_by_id: dict[str, object] = {}
        for page in live_pages:
            page_id = self._page_ids_by_object_id.get(id(page))
            if not page_id:
                page_id = f"p{self._next_page_number}"
                self._next_page_number += 1
                self._page_ids_by_object_id[id(page)] = page_id
            self._set_page_timeout(page)
            pages_by_id[page_id] = page
        self._pages_by_id = pages_by_id

        if self._current_page_id not in self._pages_by_id:
            self._current_page_id = next(iter(self._pages_by_id), None)

    def _register_page(self, page: object) -> str:
        """为新页面分配 page_id，并更新当前页游标。"""
        self._sync_pages()
        page_id = self._page_ids_by_object_id.get(id(page))
        if not page_id:
            page_id = f"p{self._next_page_number}"
            self._next_page_number += 1
            self._page_ids_by_object_id[id(page)] = page_id
        self._pages_by_id[page_id] = page
        self._current_page_id = page_id
        return page_id

    def _page_info(self, page_id: str, page: object) -> dict[str, object]:
        """提取单个页面的可展示信息。"""
        title = ""
        url = ""
        try:
            title = page.title()
        except Exception:
            title = ""
        try:
            url = str(page.url or "")
        except Exception:
            url = ""
        return {
            "page_id": page_id,
            "title": title.strip(),
            "url": url.strip(),
            "is_current": page_id == self._current_page_id,
        }

    def _locator_for_ref(self, page: object, ref: str) -> object:
        """按 snapshot 分配的 ref 找到对应 DOM 元素。"""
        locator = page.locator(f'[data-cct-ref="{ref}"]').first
        if locator.count() == 0:
            raise RuntimeError(f"未找到 ref `{ref}`，请先重新执行 snapshot。")
        return locator

    def _set_page_timeout(self, page: object) -> None:
        """为页面设置统一默认动作超时。"""
        page.set_default_timeout(self.settings.action_timeout_ms)

    def _load_playwright_sync_api(self) -> Any:
        """延迟导入 Playwright，同步错误文案里带上安装提示。"""
        try:
            return importlib.import_module("playwright.sync_api")
        except ModuleNotFoundError as error:
            raise RuntimeError(
                "浏览器工具依赖 Playwright，请先安装项目依赖并执行 `playwright install chromium`。"
            ) from error

    def _profile_dir(self) -> Path:
        """返回浏览器持久 profile 目录。"""
        return self._resolve_relative_path(self.settings.profile_dir)

    def _artifacts_dir(self) -> Path:
        """返回截图等浏览器产物的落盘目录。"""
        return self._resolve_relative_path(self.settings.artifacts_dir)

    def _resolve_relative_path(self, raw_path: str) -> Path:
        """把相对路径解析到当前工作区下，绝对路径则原样保留。"""
        path = Path(raw_path).expanduser()
        if path.is_absolute():
            return path.resolve()
        return (self.workspace_root / path).resolve()

    def _timestamp(self) -> str:
        """返回用于文件命名的短时间戳。"""
        return datetime.now().strftime("%Y%m%d-%H%M%S")
