from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from .context import PromptContextBuilder
from .registry import PromptResourceRegistry
from .renderers import render_prompt_bundle
from .types import PromptBundle, PromptResource, RenderedPrompt, RenderedPromptSection

if TYPE_CHECKING:
    from claude_code_thy.models import SessionTranscript
    from claude_code_thy.services import ToolServices


class PromptBuilder:
    """负责把 markdown 资源和动态上下文组装成最终 prompt。"""
    def __init__(self, workspace_root: Path) -> None:
        """准备资源注册器和动态上下文构建器。"""
        self.workspace_root = workspace_root.resolve()
        self.registry = PromptResourceRegistry(self.workspace_root)
        self.context_builder = PromptContextBuilder()

    def build_bundle(
        self,
        session: "SessionTranscript",
        services: "ToolServices",
        *,
        provider_name: str,
        model: str,
    ) -> PromptBundle:
        """构建当前会话一次请求应使用的完整 prompt bundle。"""
        context_data = self.context_builder.build(
            session,
            services,
            provider_name=provider_name,
            model=model,
        )
        resources = (
            self.registry.list_sections()
            + self.registry.list_templates()
            + self.registry.list_provider_sections(provider_name)
        )
        sections: list[RenderedPromptSection] = []
        for resource in resources:
            if not self._should_include(resource, context_data.variables):
                continue
            text = self._render_text(resource.content, context_data.variables).strip()
            if not text:
                continue
            sections.append(
                RenderedPromptSection(
                    id=resource.id,
                    kind=resource.kind,
                    target=resource.target,
                    order=resource.order,
                    text=text,
                    source_path=resource.source_path,
                    source_type=resource.source_type,
                    relative_name=resource.relative_name,
                    cacheable=resource.cacheable,
                    metadata=dict(resource.metadata),
                )
            )

        sections.sort(key=lambda item: (item.order, item.id, item.relative_name))
        return PromptBundle(
            session_id=session.session_id,
            provider_name=provider_name,
            model=model,
            workspace_root=str(self.workspace_root),
            sections=sections,
            context_data=context_data,
        )

    def build_rendered_prompt(
        self,
        session: "SessionTranscript",
        services: "ToolServices",
        *,
        provider_name: str,
        model: str,
    ) -> RenderedPrompt:
        """直接构建最终渲染后的 prompt。"""
        bundle = self.build_bundle(
            session,
            services,
            provider_name=provider_name,
            model=model,
        )
        return render_prompt_bundle(bundle)

    def _should_include(self, resource: PromptResource, variables: dict[str, str]) -> bool:
        """根据 required variables 决定是否保留该资源。"""
        if not resource.required_variables:
            return True
        for key in resource.required_variables:
            if variables.get(key, "").strip():
                continue
            return False
        return True

    def _render_text(self, content: str, variables: dict[str, str]) -> str:
        """执行一轮简单占位符替换，不支持复杂模板语法。"""
        rendered = content
        for key, value in variables.items():
            rendered = rendered.replace(f"{{{{ {key} }}}}", value)
            rendered = rendered.replace(f"{{{{{key}}}}}", value)
        return rendered
