from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from claude_code_thy.models import SessionTranscript

from ..deps import get_context, load_session_or_404
from ..presenters import present_chat_turn
from ..schemas import ChatRequest, ChatTurnDTO
from ..turn_stream import stream_turn_buffered, stream_turn_live

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
    async for chunk in stream_turn_live(
        lambda **handlers: runtime.handle_stream(session, prompt, **handlers),
        session,
    ):
        yield chunk


async def _stream_chat_turn_buffered(runtime, session: SessionTranscript, prompt: str):
    """保留旧的整轮级 SSE 行为，不发送 token 增量。"""
    async for chunk in stream_turn_buffered(
        lambda **handlers: runtime.handle(session, prompt, **handlers),
        session,
    ):
        yield chunk
