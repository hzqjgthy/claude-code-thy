from __future__ import annotations

from pathlib import Path

from .loader import PromptFileLoader
from .types import PromptResource


class PromptResourceRegistry:
    """统一管理 sections / templates / providers 三类 prompt 资源。"""
    def __init__(self, workspace_root: Path) -> None:
        """为当前工作区创建一个文件加载器。"""
        self.loader = PromptFileLoader(workspace_root)

    def list_sections(self) -> list[PromptResource]:
        """返回当前工作区启用的系统级 sections。"""
        return self.loader.load_resources("section")

    def list_templates(self) -> list[PromptResource]:
        """返回当前工作区启用的动态模板。"""
        return self.loader.load_resources("template")

    def list_provider_sections(self, provider_name: str) -> list[PromptResource]:
        """返回适用于指定 provider 的补充 sections。"""
        return self.loader.load_resources("provider", provider_name=provider_name)
