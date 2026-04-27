from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from claude_code_thy.browser import BrowserManager
from claude_code_thy.lsp import LspManager
from claude_code_thy.mcp import McpRuntimeManager
from claude_code_thy.permissions import PermissionEngine
from claude_code_thy.sandbox import SandboxManager, SandboxPolicy
from claude_code_thy.settings import AppSettings
from claude_code_thy.skills import PromptCommandRegistry
from claude_code_thy.tasks import BackgroundTaskManager

if TYPE_CHECKING:
    from claude_code_thy.models import SessionTranscript


@dataclass(slots=True)
class ToolServices:
    """聚合工具运行时需要共享的设置、权限、任务和 MCP 服务。"""
    settings: AppSettings
    permission_engine: PermissionEngine
    sandbox_policy: SandboxPolicy
    sandbox_manager: SandboxManager
    task_manager: BackgroundTaskManager
    command_registry: PromptCommandRegistry
    browser_manager: BrowserManager
    lsp_manager: LspManager
    mcp_manager: McpRuntimeManager
    _sessions: dict[str, "SessionTranscript"] = field(default_factory=dict, repr=False)

    def register_session(self, session: "SessionTranscript") -> None:
        """把当前会话注册到共享服务容器中。"""
        self._sessions[session.session_id] = session

    def command_session_for(self, session_id: str) -> "SessionTranscript":
        """按会话 ID 取回命令系统正在操作的会话对象。"""
        return self._sessions[session_id]


def build_tool_services(workspace_root: Path) -> ToolServices:
    """基于工作区配置一次性创建所有长生命周期服务。"""
    settings = AppSettings.load_for_workspace(workspace_root)
    return ToolServices(
        settings=settings,
        permission_engine=PermissionEngine(workspace_root, settings),
        sandbox_policy=SandboxPolicy(settings.sandbox),
        sandbox_manager=SandboxManager(workspace_root, settings.sandbox),
        task_manager=BackgroundTaskManager(workspace_root, settings.tasks),
        command_registry=PromptCommandRegistry(workspace_root, settings.skills),
        browser_manager=BrowserManager(workspace_root, settings.browser),
        lsp_manager=LspManager(workspace_root, settings.lsp),
        mcp_manager=McpRuntimeManager(workspace_root, settings),
    )
