from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from claude_code_thy.providers import build_provider_for_name

from ..deps import get_context, load_session_or_404
from ..presenters import present_prompt_preview, present_runtime_info
from ..schemas import PromptPreviewDTO, PromptSectionDTO, RuntimeInfoDTO

router = APIRouter(tags=["runtime"])


@router.get("/health")
async def health() -> dict[str, str]:
    """基础健康检查入口。"""
    return {"status": "ok"}


@router.get("/runtime", response_model=RuntimeInfoDTO)
async def runtime_info(context=Depends(get_context)):
    """返回当前 Web 后端绑定的 provider / model / workspace 信息。"""
    return present_runtime_info(context)


@router.get("/runtime/prompt-preview", response_model=PromptPreviewDTO)
async def prompt_preview(
    session_id: str = Query(..., description="Target session ID."),
    provider: str | None = Query(None, description="Optional provider name override."),
    context=Depends(get_context),
):
    """返回当前会话渲染后的完整 prompt 预览。"""
    session = load_session_or_404(context, session_id)
    services = context.runtime.tool_runtime.services_for(session)
    rendered_prompt = services.prompt_runtime.build_rendered_prompt(
        session,
        services,
        provider_name=provider or context.provider.name,
        model=session.model or context.config.model,
    )
    target_provider_name = provider or context.provider.name
    target_provider = build_provider_for_name(target_provider_name, context.config)
    request_preview = target_provider.build_request_preview(
        session,
        context.runtime.tool_runtime.list_tool_specs_for_session(
            session,
            allow_sync_refresh=False,
        ),
        prompt=rendered_prompt,
    )
    return present_prompt_preview(rendered_prompt, request_preview=request_preview)


@router.get("/runtime/prompt-sections", response_model=list[PromptSectionDTO])
async def prompt_sections(
    session_id: str = Query(..., description="Target session ID."),
    provider: str | None = Query(None, description="Optional provider name override."),
    context=Depends(get_context),
):
    """只返回 prompt 中的 section 列表，方便前端单独查看。"""
    preview = await prompt_preview(session_id=session_id, provider=provider, context=context)
    return preview.sections
