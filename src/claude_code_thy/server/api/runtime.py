from __future__ import annotations

from fastapi import APIRouter, Depends

from ..deps import get_context
from ..presenters import present_runtime_info
from ..schemas import RuntimeInfoDTO

router = APIRouter(tags=["runtime"])


@router.get("/health")
async def health() -> dict[str, str]:
    """基础健康检查入口。"""
    return {"status": "ok"}


@router.get("/runtime", response_model=RuntimeInfoDTO)
async def runtime_info(context=Depends(get_context)):
    """返回当前 Web 后端绑定的 provider / model / workspace 信息。"""
    return present_runtime_info(context)
