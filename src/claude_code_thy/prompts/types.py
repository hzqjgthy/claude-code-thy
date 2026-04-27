from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


PromptResourceKind = Literal["section", "template", "provider"]
PromptTarget = Literal["system", "user"]


@dataclass(slots=True)
class PromptResource:
    """描述一个来自 markdown 文件的 prompt 资源。"""
    id: str
    kind: PromptResourceKind
    target: PromptTarget
    order: int
    content: str
    source_path: str
    source_type: str
    relative_name: str
    cacheable: bool = True
    provider_name: str | None = None
    required_variables: tuple[str, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        """把资源定义转成调试友好的字典。"""
        return {
            "id": self.id,
            "kind": self.kind,
            "target": self.target,
            "order": self.order,
            "content": self.content,
            "source_path": self.source_path,
            "source_type": self.source_type,
            "relative_name": self.relative_name,
            "cacheable": self.cacheable,
            "provider_name": self.provider_name,
            "required_variables": list(self.required_variables),
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class RenderedPromptSection:
    """描述一个已经完成变量替换的 prompt section。"""
    id: str
    kind: PromptResourceKind
    target: PromptTarget
    order: int
    text: str
    source_path: str
    source_type: str
    relative_name: str
    cacheable: bool = True
    metadata: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        """把渲染后的 section 转成可序列化字典。"""
        return {
            "id": self.id,
            "kind": self.kind,
            "target": self.target,
            "order": self.order,
            "text": self.text,
            "source_path": self.source_path,
            "source_type": self.source_type,
            "relative_name": self.relative_name,
            "cacheable": self.cacheable,
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class PromptContextData:
    """保存渲染 prompt 所需的动态变量和调试元数据。"""
    variables: dict[str, str]
    debug_meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        """转成 Web / CLI 调试输出可用的结构。"""
        return {
            "variables": dict(self.variables),
            "debug_meta": dict(self.debug_meta),
        }


@dataclass(slots=True)
class PromptBundle:
    """保存某次请求的完整 prompt sections 和上下文快照。"""
    session_id: str
    provider_name: str
    model: str
    workspace_root: str
    sections: list[RenderedPromptSection]
    context_data: PromptContextData

    def system_sections(self) -> list[RenderedPromptSection]:
        """返回注入到 system/instructions 的 sections。"""
        return [section for section in self.sections if section.target == "system"]

    def user_sections(self) -> list[RenderedPromptSection]:
        """返回注入到 user meta context 的 sections。"""
        return [section for section in self.sections if section.target == "user"]

    def to_dict(self) -> dict[str, object]:
        """转成调试接口可直接返回的字典。"""
        return {
            "session_id": self.session_id,
            "provider_name": self.provider_name,
            "model": self.model,
            "workspace_root": self.workspace_root,
            "sections": [section.to_dict() for section in self.sections],
            "context_data": self.context_data.to_dict(),
        }


@dataclass(slots=True)
class RenderedPrompt:
    """保存最终面向 provider 的 prompt 结果。"""
    bundle: PromptBundle
    system_text: str
    user_context_text: str

    def to_dict(self) -> dict[str, object]:
        """转成完整调试输出。"""
        data = self.bundle.to_dict()
        data.update(
            {
                "system_text": self.system_text,
                "user_context_text": self.user_context_text,
            }
        )
        return data
