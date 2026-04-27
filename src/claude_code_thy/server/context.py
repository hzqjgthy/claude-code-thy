from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from claude_code_thy.config import AppConfig
from claude_code_thy.providers import Provider, build_provider
from claude_code_thy.runtime import ConversationRuntime
from claude_code_thy.session.store import SessionStore


@dataclass(slots=True)
class WebAppContext:
    """保存 Web API 运行时需要共享的 provider、runtime 和 session store。"""
    workspace_root: Path
    config: AppConfig
    provider: Provider
    session_store: SessionStore
    runtime: ConversationRuntime


def default_workspace_root() -> Path:
    """解析当前 Web 服务面向的工作区根目录。"""
    return Path.cwd().resolve()


def default_session_root(workspace_root: Path) -> Path:
    """按 CLI 的同一规则解析 sessions 根目录，但允许显式工作区注入。"""
    configured = os.environ.get("CLAUDE_CODE_THY_HOME")
    if configured:
        return Path(configured).expanduser().resolve() / "sessions"
    return workspace_root / ".claude-code-thy" / "sessions"


def build_web_app_context(workspace_root: Path | None = None) -> WebAppContext:
    """构造默认 Web 上下文，复用现有 provider 和 ConversationRuntime。"""
    resolved_root = (workspace_root or default_workspace_root()).resolve()
    config = AppConfig.from_env()
    provider = build_provider(config)
    session_store = SessionStore(root_dir=default_session_root(resolved_root))
    runtime = ConversationRuntime(
        provider=provider,
        session_store=session_store,
    )
    return WebAppContext(
        workspace_root=resolved_root,
        config=config,
        provider=provider,
        session_store=session_store,
        runtime=runtime,
    )
