from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from claude_code_thy.file_history import FileHistoryStore
from claude_code_thy.lsp import LspManager
from claude_code_thy.permissions import PermissionEngine
from claude_code_thy.sandbox import SandboxManager, SandboxPolicy
from claude_code_thy.settings import AppSettings
from claude_code_thy.skills import SkillManager
from claude_code_thy.tasks import BackgroundTaskManager


@dataclass(slots=True)
class ToolServices:
    settings: AppSettings
    permission_engine: PermissionEngine
    sandbox_policy: SandboxPolicy
    sandbox_manager: SandboxManager
    task_manager: BackgroundTaskManager
    file_history: FileHistoryStore
    skill_manager: SkillManager
    lsp_manager: LspManager


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
        lsp_manager=LspManager(workspace_root, settings.lsp),
    )
