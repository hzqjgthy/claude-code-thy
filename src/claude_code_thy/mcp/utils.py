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
    return datetime.now(timezone.utc).isoformat()


def read_json_file(path: Path) -> dict[str, object] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def write_json_file(path: Path, data: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


class _BackgroundAsyncRunner:
    def __init__(self) -> None:
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
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
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
        if self._closed:
            raise RuntimeError("background async runner has been closed")
        loop = self._loop
        if loop is None:
            raise RuntimeError("background async runner is not ready")

        async def _await_any() -> Any:
            return await awaitable

        future = asyncio.run_coroutine_threadsafe(_await_any(), loop)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError as error:
            future.cancel()
            raise TimeoutError("shared async runner timed out") from error

    def close(self) -> None:
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


def _shared_runner() -> _BackgroundAsyncRunner:
    global _runner
    with _runner_lock:
        if _runner is None or _runner._closed:
            _runner = _BackgroundAsyncRunner()
        return _runner


def _shutdown_runner() -> None:
    global _runner
    with _runner_lock:
        runner = _runner
        _runner = None
    if runner is not None:
        runner.close()


atexit.register(_shutdown_runner)


def run_async_sync(awaitable: Awaitable[Any], *, timeout: float | None = None) -> Any:
    runner = _shared_runner()
    if threading.current_thread() is runner._thread:
        raise RuntimeError("run_async_sync cannot be called from the shared MCP runner thread")
    return runner.run(awaitable, timeout=timeout)
