from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable

from claude_code_thy.commands import CommandOutcome
from claude_code_thy.models import SessionTranscript

from .presenters import present_chat_turn, present_message, present_tool_event
from .schemas import (
    SSEAssistantDeltaEventDTO,
    SSEDoneEventDTO,
    SSEErrorEventDTO,
    SSEMessageEventDTO,
)
from .sse import encode_sse

RunTurn = Callable[..., Awaitable[CommandOutcome]]


async def stream_turn_live(
    run_turn: RunTurn,
    session: SessionTranscript,
) -> AsyncIterator[bytes]:
    """把一轮运行时执行过程转换成带增量文本的 SSE 事件流。"""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[tuple[str, object]] = asyncio.Queue()
    start_index = len(session.messages)

    def emit(event_name: str, payload: object) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, (event_name, payload))

    def tool_event_handler(tool_event) -> None:
        emit("tool_event", present_tool_event(tool_event))

    def text_delta_handler(text: str) -> None:
        emit("assistant_delta", SSEAssistantDeltaEventDTO(text=text))

    def message_added_handler(index: int, message) -> None:
        emit(
            "message",
            SSEMessageEventDTO(message=present_message(session.session_id, index, message)),
        )

    async def _run() -> None:
        try:
            outcome = await run_turn(
                tool_event_handler=tool_event_handler,
                text_delta_handler=text_delta_handler,
                message_added_handler=message_added_handler,
            )
            emit("done", SSEDoneEventDTO(turn=present_chat_turn(outcome.session, start_index=start_index)))
        except Exception as error:
            emit("error", SSEErrorEventDTO(error=str(error)))
        finally:
            emit("_close", {"ok": True})

    task = asyncio.create_task(_run())
    try:
        while True:
            event_name, payload = await queue.get()
            if event_name == "_close":
                break
            yield encode_sse(event_name, payload)
    finally:
        await task


async def stream_turn_buffered(
    run_turn: RunTurn,
    session: SessionTranscript,
) -> AsyncIterator[bytes]:
    """保留旧的整轮级行为，但统一通过 SSE 一次性发回消息和 done。"""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[tuple[str, object]] = asyncio.Queue()
    start_index = len(session.messages)

    def emit(event_name: str, payload: object) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, (event_name, payload))

    def tool_event_handler(tool_event) -> None:
        emit("tool_event", present_tool_event(tool_event))

    async def _run() -> None:
        try:
            outcome = await run_turn(tool_event_handler=tool_event_handler)
            turn = present_chat_turn(outcome.session, start_index=start_index)
            for message in turn.new_messages:
                emit("message", SSEMessageEventDTO(message=message))
            emit("done", SSEDoneEventDTO(turn=turn))
        except Exception as error:
            emit("error", SSEErrorEventDTO(error=str(error)))
        finally:
            emit("_close", {"ok": True})

    task = asyncio.create_task(_run())
    try:
        while True:
            event_name, payload = await queue.get()
            if event_name == "_close":
                break
            yield encode_sse(event_name, payload)
    finally:
        await task
