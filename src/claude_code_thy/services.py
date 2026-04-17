from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from claude_code_thy.file_history import FileHistoryStore
from claude_code_thy.lsp import LspManager
from claude_code_thy.mcp import McpRuntimeManager
from claude_code_thy.permissions import PermissionEngine
from claude_code_thy.sandbox import SandboxManager, SandboxPolicy
from claude_code_thy.settings import AppSettings
from claude_code_thy.skills import PromptCommandRegistry, SkillManager
from claude_code_thy.tasks import BackgroundTaskManager

if TYPE_CHECKING:
    from claude_code_thy.models import SessionTranscript
    from claude_code_thy.tools.base import RuntimeSessionState


@dataclass(slots=True)
class ToolServices:
    settings: AppSettings
    permission_engine: PermissionEngine
    sandbox_policy: SandboxPolicy
    sandbox_manager: SandboxManager
    task_manager: BackgroundTaskManager
    file_history: FileHistoryStore
    skill_manager: SkillManager
    command_registry: PromptCommandRegistry
    lsp_manager: LspManager
    mcp_manager: McpRuntimeManager
    _sessions: dict[str, "SessionTranscript"] = field(default_factory=dict, repr=False)
    _command_states: dict[str, "RuntimeSessionState"] = field(default_factory=dict, repr=False)

    def register_session(
        self,
        session: "SessionTranscript",
        state: "RuntimeSessionState",
    ) -> None:
        self._sessions[session.session_id] = session
        self._command_states[session.session_id] = state

    def command_session_for(self, session_id: str) -> "SessionTranscript":
        return self._sessions[session_id]

    def command_state_for_session(self, session_id: str) -> "RuntimeSessionState":
        return self._command_states[session_id]


def build_tool_services(workspace_root: Path) -> ToolServices:
    settings = AppSettings.load_for_workspace(workspace_root)
    return ToolServices(
        settings=settings,
        permission_engine=PermissionEngine(workspace_root, settings),
        sandbox_policy=SandboxPolicy(settings.sandbox),
        sandbox_manager=SandboxManager(workspace_root, settings.sandbox),
        task_manager=BackgroundTaskManager(workspace_root, settings.tasks),
        file_history=FileHistoryStore(workspace_root, settings.file_history),
        skill_manager=SkillManager(workspace_root, settings.skills),
        command_registry=PromptCommandRegistry(workspace_root, settings.skills),
        lsp_manager=LspManager(workspace_root, settings.lsp),
        mcp_manager=McpRuntimeManager(workspace_root, settings),
    )
