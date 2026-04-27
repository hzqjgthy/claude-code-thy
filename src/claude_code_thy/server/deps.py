from __future__ import annotations

from fastapi import HTTPException, Request

from claude_code_thy.models import SessionTranscript

from .context import WebAppContext


def get_context(request: Request) -> WebAppContext:
    """从 FastAPI app.state 中取回共享的 Web 上下文。"""
    context = getattr(request.app.state, "context", None)
    if not isinstance(context, WebAppContext):
        raise RuntimeError("WebAppContext is not initialized")
    return context


def load_session_or_404(context: WebAppContext, session_id: str) -> SessionTranscript:
    """加载会话；不存在时统一转成 HTTP 404。"""
    try:
        return context.session_store.load(session_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
