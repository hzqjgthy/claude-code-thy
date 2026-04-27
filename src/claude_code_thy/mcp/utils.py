from __future__ import annotations

import atexit
import asyncio
import concurrent.futures
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable


def utc_now() -> str:
    """返回 ISO 格式的 UTC 时间字符串。"""
    return datetime.now(timezone.utc).isoformat()


def read_json_file(path: Path) -> dict[str, object] | None:
    """安全读取一个 JSON 文件；不是对象时返回 `None`。"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def write_json_file(path: Path, data: dict[str, object]) -> None:
    """把对象写成 UTF-8 JSON 文件，并确保父目录存在。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


class _BackgroundAsyncRunner:
    """在后台线程常驻一个事件循环，供同步代码复用异步调用。"""
    def __init__(self) -> None:
        """启动后台线程并等待事件循环就绪。"""
        self._ready = threading.Event()
        self._thread = threading.Thread(
            target=self._bootstrap,
            name="claude-code-thy-async-runner",
            daemon=True,
        )
        self._loop: asyncio.AbstractEventLoop | None = None
        self._closed = False
        self._thread.start()
        self._ready.wait()

    def _bootstrap(self) -> None:
        """在线程内创建事件循环并在退出时清理未完成任务。"""
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        loop.set_exception_handler(_shared_runner_exception_handler)
        self._ready.set()
        try:
            loop.run_forever()
        finally:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()

    def run(self, awaitable: Awaitable[Any], *, timeout: float | None = None) -> Any:
        """把一个 awaitable 投递到共享事件循环并同步等待结果。"""
        if self._closed:
            raise RuntimeError("background async runner has been closed")
        loop = self._loop
        if loop is None:
            raise RuntimeError("background async runner is not ready")

        async def _await_any() -> Any:
            """简单包装 awaitable，便于交给线程安全接口调度。"""
            return await awaitable

        future = asyncio.run_coroutine_threadsafe(_await_any(), loop)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError as error:
            future.cancel()
            raise TimeoutError("shared async runner timed out") from error

    def close(self) -> None:
        """停止后台事件循环并等待线程退出。"""
        if self._closed:
            return
        self._closed = True
        loop = self._loop
        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(loop.stop)
        if self._thread.is_alive():
            self._thread.join(timeout=1)


_runner_lock = threading.Lock()
_runner: _BackgroundAsyncRunner | None = None


def _shared_runner_exception_handler(
    loop: asyncio.AbstractEventLoop,
    context: dict[str, Any],
) -> None:
    """定向吞掉 MCP HTTP 客户端在 async generator 关闭阶段的已知噪音。"""
    if _should_suppress_mcp_exception_context(context):
        return
    loop.default_exception_handler(context)


def install_mcp_exception_handler(loop: asyncio.AbstractEventLoop) -> None:
    """为当前事件循环安装 MCP 已知清理噪音过滤器。"""
    previous = loop.get_exception_handler()

    def _handler(current_loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
        """优先吞掉已知 MCP 清理异常，其余交还原处理器。"""
        if _should_suppress_mcp_exception_context(context):
            return
        if previous is not None:
            previous(current_loop, context)
            return
        current_loop.default_exception_handler(context)

    loop.set_exception_handler(_handler)


def _should_suppress_mcp_exception_context(context: dict[str, Any]) -> bool:
    """判断一个事件循环异常上下文是否属于已知 MCP 清理噪音。"""
    message = str(context.get("message", ""))
    asyncgen = context.get("asyncgen")
    if (
        "an error occurred during closing of asynchronous generator" in message
        and asyncgen is not None
        and _asyncgen_name(asyncgen) in {"streamable_http_client", "stdio_client"}
    ):
        return True
    handle = context.get("handle")
    exception = context.get("exception")
    if (
        message.startswith("Exception in callback TaskGroup._spawn")
        and isinstance(exception, RuntimeError)
        and "Event loop is closed" in str(exception)
        and handle is not None
    ):
        return True
    return False


def _asyncgen_name(asyncgen: object) -> str:
    """尽量从 async generator 对象上提取底层函数名。"""
    code = getattr(asyncgen, "ag_code", None)
    if code is not None:
        return str(getattr(code, "co_name", "") or "")
    return str(getattr(asyncgen, "__name__", "") or "")


def _shared_runner() -> _BackgroundAsyncRunner:
    """懒加载并返回全局共享的异步运行器。"""
    global _runner
    with _runner_lock:
        if _runner is None or _runner._closed:
            _runner = _BackgroundAsyncRunner()
        return _runner


def _shutdown_runner() -> None:
    """在进程退出时关闭全局共享运行器。"""
    global _runner
    with _runner_lock:
        runner = _runner
        _runner = None
    if runner is not None:
        runner.close()


atexit.register(_shutdown_runner)


def run_async_sync(awaitable: Awaitable[Any], *, timeout: float | None = None) -> Any:
    """让同步代码安全地等待一个异步调用完成。"""
    runner = _shared_runner()
    if threading.current_thread() is runner._thread:
        raise RuntimeError("run_async_sync cannot be called from the shared MCP runner thread")
    return runner.run(awaitable, timeout=timeout)
