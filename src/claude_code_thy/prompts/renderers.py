from __future__ import annotations

from .types import PromptBundle, RenderedPrompt


def render_prompt_bundle(bundle: PromptBundle) -> RenderedPrompt:
    """把统一 bundle 渲染成 provider 可消费的 system/user 文本。"""
    system_text = "\n\n".join(
        section.text.strip()
        for section in bundle.system_sections()
        if section.text.strip()
    ).strip()
    user_context_text = "\n\n".join(
        section.text.strip()
        for section in bundle.user_sections()
        if section.text.strip()
    ).strip()
    return RenderedPrompt(
        bundle=bundle,
        system_text=system_text,
        user_context_text=user_context_text,
    )
