from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from ..deps import get_context, load_session_or_404
from ..presenters import (
    present_chat_turn,
    present_mcp_snapshot,
    present_pending_permission,
    present_session_detail,
    present_session_summary,
    present_skills_snapshot,
    present_task,
    present_tools_snapshot,
    present_transcript,
)
from ..schemas import (
    ChatTurnDTO,
    McpSnapshotDTO,
    PendingPermissionDTO,
    PermissionResolveRequest,
    SessionCreateRequest,
    SessionDetailDTO,
    SessionSummaryDTO,
    SessionTranscriptDTO,
    SkillsSnapshotDTO,
    TaskDTO,
    ToolsSnapshotDTO,
)

router = APIRouter(tags=["sessions"])


@router.get("/sessions", response_model=list[SessionSummaryDTO])
async def list_sessions(context=Depends(get_context)):
    """列出最近会话摘要，供前端侧边栏直接消费。"""
    return [present_session_summary(item) for item in context.session_store.list_recent(limit=100)]


@router.post("/sessions", response_model=SessionDetailDTO)
async def create_session(
    request: SessionCreateRequest,
    context=Depends(get_context),
):
    """创建一个新会话，并立即落盘。"""
    session = context.session_store.create(
        cwd=request.cwd or str(context.workspace_root),
        model=request.model or context.config.model,
        provider_name=context.provider.name,
    )
    context.session_store.save(session)
    return present_session_detail(session)


@router.get("/sessions/{session_id}", response_model=SessionDetailDTO)
async def get_session(session_id: str, context=Depends(get_context)):
    """返回单个会话的基础信息，不含完整消息列表。"""
    session = load_session_or_404(context, session_id)
    return present_session_detail(session)


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, context=Depends(get_context)):
    """删除一个会话 transcript。"""
    try:
        context.session_store.delete(session_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return {"status": "deleted", "session_id": session_id}


@router.get("/sessions/{session_id}/messages", response_model=SessionTranscriptDTO)
async def get_session_messages(session_id: str, context=Depends(get_context)):
    """返回完整 transcript，供 Web 前端恢复消息流。"""
    session = load_session_or_404(context, session_id)
    return present_transcript(session)


@router.get("/sessions/{session_id}/pending-permission", response_model=PendingPermissionDTO | None)
async def get_pending_permission(session_id: str, context=Depends(get_context)):
    """返回当前会话挂起的权限请求；没有则返回 null。"""
    session = load_session_or_404(context, session_id)
    return present_pending_permission(session)


@router.post("/sessions/{session_id}/pending-permission/resolve", response_model=ChatTurnDTO)
async def resolve_pending_permission(
    session_id: str,
    request: PermissionResolveRequest,
    context=Depends(get_context),
):
    """显式批准或拒绝当前挂起的权限请求，避免 Web 前端走 `yes/no` 文本分支。"""
    session = load_session_or_404(context, session_id)
    start_index = len(session.messages)
    outcome = await context.runtime.resolve_pending_permission(
        session,
        approved=request.approved,
    )
    return present_chat_turn(outcome.session, start_index=start_index)


@router.get("/sessions/{session_id}/tasks", response_model=list[TaskDTO])
async def get_session_tasks(session_id: str, context=Depends(get_context)):
    """返回属于当前会话的后台任务和 agent 任务。"""
    session = load_session_or_404(context, session_id)
    manager = context.runtime.tool_runtime.services_for(session).task_manager
    tasks = []
    for task in manager.list_task_records():
        task_session_id = ""
        if isinstance(task.metadata, dict):
            task_session_id = str(task.metadata.get("session_id", "")).strip()
        if task_session_id != session.session_id:
            continue
        tasks.append(present_task(task))
    return tasks


@router.get("/sessions/{session_id}/tools", response_model=ToolsSnapshotDTO)
async def get_session_tools(session_id: str, context=Depends(get_context)):
    """返回 execution/model 两个面的工具快照。"""
    session = load_session_or_404(context, session_id)
    execution_tools = context.runtime.tool_runtime.list_tools_for_session(session, surface="execution")
    model_tools = context.runtime.tool_runtime.list_tools_for_session(session, surface="model")
    return present_tools_snapshot(execution_tools, model_tools)


@router.get("/sessions/{session_id}/skills", response_model=SkillsSnapshotDTO)
async def get_session_skills(
    session_id: str,
    refresh_mcp: bool = Query(False, description="Whether to refresh MCP caches before listing skills."),
    context=Depends(get_context),
):
    """返回本地 skill、MCP skill 和 MCP prompt 的结构化快照。"""
    session = load_session_or_404(context, session_id)
    services = context.runtime.tool_runtime.services_for(session)
    if refresh_mcp:
        try:
            await services.mcp_manager.refresh_all()
        except Exception:
            pass
    user_commands = services.command_registry.list_user_commands(session, services)
    model_commands = services.command_registry.list_model_commands(session, services)
    return present_skills_snapshot(user_commands, model_commands)


@router.get("/sessions/{session_id}/mcp", response_model=McpSnapshotDTO)
async def get_session_mcp(
    session_id: str,
    refresh: bool = Query(False, description="Whether to refresh all MCP servers before reading caches."),
    context=Depends(get_context),
):
    """返回 MCP 连接和缓存的结构化快照，替代 `/mcp` 文本输出。"""
    session = load_session_or_404(context, session_id)
    services = context.runtime.tool_runtime.services_for(session)
    if refresh:
        try:
            await services.mcp_manager.refresh_all()
        except Exception:
            pass
    return present_mcp_snapshot(
        services.mcp_manager.snapshot(),
        tools_by_server=services.mcp_manager.cached_tools(),
        prompt_commands=services.mcp_manager.cached_prompt_commands(),
        skill_commands=services.mcp_manager.cached_skill_commands(),
        resources_by_server=services.mcp_manager.cached_resources(),
    )
