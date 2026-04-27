from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from claude_code_thy.models import SessionTranscript

from ..deps import get_context, load_session_or_404
from ..presenters import present_chat_turn, present_message, present_tool_event
from ..schemas import (
    ChatRequest,
    ChatTurnDTO,
    SSEAssistantDeltaEventDTO,
    SSEErrorEventDTO,
    SSEDoneEventDTO,
    SSEMessageEventDTO,
)
from ..sse import encode_sse

router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatTurnDTO)
async def chat(
    request: ChatRequest,
    context=Depends(get_context),
):
    """处理一条用户输入；可返回 JSON，也可升级成 SSE 事件流。"""
    if not request.prompt.strip():
        raise HTTPException(status_code=400, detail="prompt must not be empty")

    session = load_session_or_404(context, request.session_id)
    if request.stream:
        return StreamingResponse(
            (
                _stream_chat_turn_live(context.runtime, session, request.prompt)
                if context.config.web_enable_stream_output
                else _stream_chat_turn_buffered(context.runtime, session, request.prompt)
            ),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    start_index = len(session.messages)
    outcome = await context.runtime.handle(session, request.prompt)
    return present_chat_turn(outcome.session, start_index=start_index)


async def _stream_chat_turn_live(runtime, session: SessionTranscript, prompt: str):
    """把一轮对话处理过程转换成带 token 增量的 SSE 事件流。"""
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

    async def run_turn() -> None:
        try:
            outcome = await runtime.handle_stream(
                session,
                prompt,
                tool_event_handler=tool_event_handler,
                text_delta_handler=text_delta_handler,
                message_added_handler=message_added_handler,
            )
            turn = present_chat_turn(outcome.session, start_index=start_index)
            emit("done", SSEDoneEventDTO(turn=turn))
        except Exception as error:
            emit("error", SSEErrorEventDTO(error=str(error)))
        finally:
            emit("_close", {"ok": True})

    task = asyncio.create_task(run_turn())
    try:
        while True:
            event_name, payload = await queue.get()
            if event_name == "_close":
                break
            yield encode_sse(event_name, payload)
    finally:
        await task


async def _stream_chat_turn_buffered(runtime, session: SessionTranscript, prompt: str):
    """保留旧的整轮级 SSE 行为，不发送 token 增量。"""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[tuple[str, object]] = asyncio.Queue()
    start_index = len(session.messages)

    def emit(event_name: str, payload: object) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, (event_name, payload))

    def tool_event_handler(tool_event) -> None:
        emit("tool_event", present_tool_event(tool_event))

    async def run_turn() -> None:
        try:
            outcome = await runtime.handle(
                session,
                prompt,
                tool_event_handler=tool_event_handler,
            )
            turn = present_chat_turn(outcome.session, start_index=start_index)
            for message in turn.new_messages:
                emit("message", SSEMessageEventDTO(message=message))
            emit("done", SSEDoneEventDTO(turn=turn))
        except Exception as error:
            emit("error", SSEErrorEventDTO(error=str(error)))
        finally:
            emit("_close", {"ok": True})

    task = asyncio.create_task(run_turn())
    try:
        while True:
            event_name, payload = await queue.get()
            if event_name == "_close":
                break
            yield encode_sse(event_name, payload)
    finally:
        await task
