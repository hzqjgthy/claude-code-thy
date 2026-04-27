from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import chat_router, runtime_router, sessions_router
from .context import WebAppContext, build_web_app_context


def create_app(context: WebAppContext | None = None) -> FastAPI:
    """创建 Web API 应用，默认复用项目现有 runtime/provider/tool 栈。"""
    app = FastAPI(
        title="claude-code-thy Web API",
        version="0.1.0",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.context = context or build_web_app_context()
    app.include_router(runtime_router, prefix="/api")
    app.include_router(sessions_router, prefix="/api")
    app.include_router(chat_router, prefix="/api")
    return app
