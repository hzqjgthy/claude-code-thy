from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from .builder import PromptBuilder
from .types import PromptBundle, RenderedPrompt

if TYPE_CHECKING:
    from claude_code_thy.models import SessionTranscript
    from claude_code_thy.services import ToolServices


class PromptRuntime:
    """对外暴露统一的 prompt 构建入口，供服务层和调试入口复用。"""
    def __init__(self, workspace_root: Path) -> None:
        """为当前工作区创建一个 PromptBuilder。"""
        self.builder = PromptBuilder(workspace_root)

    def build_bundle(
        self,
        session: "SessionTranscript",
        services: "ToolServices",
        *,
        provider_name: str,
        model: str,
    ) -> PromptBundle:
        """构建调试友好的 bundle。"""
        return self.builder.build_bundle(
            session,
            services,
            provider_name=provider_name,
            model=model,
        )

    def build_rendered_prompt(
        self,
        session: "SessionTranscript",
        services: "ToolServices",
        *,
        provider_name: str,
        model: str,
    ) -> RenderedPrompt:
        """构建最终渲染后的 provider prompt。"""
        return self.builder.build_rendered_prompt(
            session,
            services,
            provider_name=provider_name,
            model=model,
        )
