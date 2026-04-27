from __future__ import annotations

from claude_code_thy import APP_DISPLAY_NAME, APP_VERSION
from claude_code_thy.mcp.names import parse_dynamic_mcp_name
from claude_code_thy.models import ChatMessage, SessionTranscript
from claude_code_thy.permissions import PermissionRequest
from claude_code_thy.session.runtime_state import get_pending_permission, pending_request
from claude_code_thy.session.store import SessionSummary
from claude_code_thy.skills.types import PromptCommandSpec
from claude_code_thy.tasks.types import TaskRecord
from claude_code_thy.tools.base import Tool, ToolEvent

from .context import WebAppContext
from .schemas import (
    ChatTurnDTO,
    McpConnectionDTO,
    McpResourceDTO,
    McpSnapshotDTO,
    McpToolDTO,
    MessageDTO,
    PendingPermissionDTO,
    PermissionRequestDTO,
    PromptPreviewDTO,
    PromptSectionDTO,
    RuntimeInfoDTO,
    SSEToolEventDTO,
    SessionDetailDTO,
    SessionSummaryDTO,
    SessionTranscriptDTO,
    SkillDTO,
    SkillsSnapshotDTO,
    TaskDTO,
    TaskNotificationDTO,
    ToolCallDTO,
    ToolDTO,
    ToolResultDTO,
    ToolsSnapshotDTO,
)


def present_permission_request(request: PermissionRequest) -> PermissionRequestDTO:
    """把内部 PermissionRequest 转成前端可直接消费的 DTO。"""
    return PermissionRequestDTO(
        request_id=request.request_id,
        tool_name=request.tool_name,
        target=request.target,
        value=request.value,
        reason=request.reason,
        approval_key=request.approval_key,
        matched_rule_pattern=request.matched_rule_pattern,
        matched_rule_description=request.matched_rule_description,
        prompt_text=request.prompt_text(),
    )


def present_pending_permission(session: SessionTranscript) -> PendingPermissionDTO | None:
    """把会话里的挂起权限状态转成结构化 DTO。"""
    payload = get_pending_permission(session)
    request = pending_request(session)
    if payload is None or request is None:
        return None
    return PendingPermissionDTO(
        request=present_permission_request(request),
        source_type=str(payload.get("source_type", "")),
        tool_name=str(payload.get("tool_name", "")),
        raw_args=(
            str(payload.get("raw_args", ""))
            if payload.get("raw_args") is not None
            else None
        ),
        input_data=payload.get("input_data") if isinstance(payload.get("input_data"), dict) else None,
        original_input=(
            payload.get("original_input")
            if isinstance(payload.get("original_input"), dict)
            else None
        ),
        user_modified=(
            bool(payload.get("user_modified"))
            if payload.get("user_modified") is not None
            else None
        ),
        tool_use_id=(
            str(payload.get("tool_use_id", ""))
            if payload.get("tool_use_id") is not None
            else None
        ),
    )


def present_session_summary(summary: SessionSummary) -> SessionSummaryDTO:
    """把会话摘要映射成 API 返回结构。"""
    return SessionSummaryDTO(
        session_id=summary.session_id,
        title=summary.title,
        cwd=summary.cwd,
        model=summary.model,
        provider_name=summary.provider_name,
        updated_at=summary.updated_at,
    )


def present_session_detail(session: SessionTranscript) -> SessionDetailDTO:
    """把完整会话对象映射成 API 详情结构。"""
    return SessionDetailDTO(
        session_id=session.session_id,
        title=session.title,
        cwd=session.cwd,
        model=session.model,
        provider_name=session.provider_name,
        created_at=session.created_at,
        updated_at=session.updated_at,
        message_count=len(session.messages),
        pending_permission=present_pending_permission(session),
    )


def present_tool_call(call: dict[str, object]) -> ToolCallDTO | None:
    """把 assistant metadata 里的工具调用记录转换成 DTO。"""
    call_id = str(call.get("id") or call.get("call_id") or "").strip()
    name = str(call.get("name", "")).strip()
    raw_input = call.get("input", {})
    if not call_id or not name:
        return None
    return ToolCallDTO(
        call_id=call_id,
        name=name,
        input=raw_input if isinstance(raw_input, dict) else {},
    )


def present_tool_result(message: ChatMessage) -> ToolResultDTO | None:
    """把 tool 消息里的 metadata 映射成结构化工具结果。"""
    metadata = message.metadata or {}
    if not metadata:
        return None
    return ToolResultDTO(
        tool_name=str(metadata.get("tool_name", "")),
        display_name=str(metadata.get("display_name", "") or metadata.get("tool_name", "")),
        ui_kind=str(metadata.get("ui_kind", "")),
        ok=bool(metadata.get("ok", False)),
        summary=str(metadata.get("summary", "")),
        output=str(metadata.get("output", "")),
        preview=str(metadata.get("preview", "")),
        structured_data=metadata.get("structured_data"),
        tool_use_id=(
            str(metadata.get("tool_use_id", ""))
            if metadata.get("tool_use_id") is not None
            else None
        ),
        raw_metadata={str(key): value for key, value in metadata.items()},
    )


def present_task_notification(message: ChatMessage) -> TaskNotificationDTO | None:
    """把 assistant/task_notification 消息里的任务摘要映射成 DTO。"""
    metadata = message.metadata or {}
    if str(metadata.get("ui_kind", "")) != "task_notification":
        return None
    return TaskNotificationDTO(
        task_id=str(metadata.get("task_id", "")),
        task_status=str(metadata.get("task_status", "")),
        task_type=str(metadata.get("task_type", "")),
    )


def message_kind(message: ChatMessage) -> str:
    """统一判断一条 transcript 消息在 Web 层的展示类型。"""
    metadata = message.metadata or {}
    if message.role == "user":
        return "user"
    if message.role == "assistant" and metadata.get("ui_kind") == "permission_prompt":
        return "permission_prompt"
    if message.role == "assistant" and metadata.get("ui_kind") == "task_notification":
        return "task_notification"
    if message.role == "assistant" and isinstance(metadata.get("tool_calls"), list):
        return "assistant_tool_call"
    if message.role == "assistant":
        return "assistant_text"
    if message.role == "tool" and metadata.get("ok") is False:
        return "tool_error"
    if message.role == "tool":
        return "tool_result"
    return "unknown"


def present_message(session_id: str, index: int, message: ChatMessage) -> MessageDTO:
    """把 transcript 里的单条消息转成前端稳定消费的结构化消息。"""
    metadata = message.metadata or {}
    tool_calls: list[ToolCallDTO] = []
    if isinstance(metadata.get("tool_calls"), list):
        for call in metadata["tool_calls"]:
            if isinstance(call, dict):
                dto = present_tool_call(call)
                if dto is not None:
                    tool_calls.append(dto)

    permission_request = None
    if isinstance(metadata.get("pending_permission"), dict):
        permission_request = present_permission_request(
            PermissionRequest.from_dict(metadata["pending_permission"])
        )

    return MessageDTO(
        message_id=f"{session_id}:{index}:{message.created_at}",
        index=index,
        role=message.role,
        kind=message_kind(message),
        text=message.text,
        created_at=message.created_at,
        content_blocks=(
            message.content_blocks if isinstance(message.content_blocks, list) else []
        ),
        raw_metadata={str(key): value for key, value in metadata.items()},
        tool_calls=tool_calls,
        tool_result=present_tool_result(message) if message.role == "tool" else None,
        permission_request=permission_request,
        task_notification=present_task_notification(message),
    )


def present_transcript(session: SessionTranscript) -> SessionTranscriptDTO:
    """把完整 transcript 映射成会话详情加结构化消息列表。"""
    return SessionTranscriptDTO(
        session=present_session_detail(session),
        messages=[
            present_message(session.session_id, index, message)
            for index, message in enumerate(session.messages)
        ],
    )


def present_task(task: TaskRecord) -> TaskDTO:
    """把后台任务记录转换成 Web DTO。"""
    return TaskDTO(
        task_id=task.task_id,
        task_type=task.task_type,
        task_kind=str(getattr(task, "task_kind", "")),
        description=task.description,
        command=str(getattr(task, "command", "")),
        cwd=task.cwd,
        status=task.status,
        started_at=task.started_at,
        finished_at=task.finished_at,
        return_code=task.return_code,
        output_path=task.output_path,
        tool_use_id=task.tool_use_id,
        agent_id=task.agent_id,
        metadata={str(key): value for key, value in task.metadata.items()},
    )


def present_tool(
    tool: Tool,
    *,
    execution_available: bool,
    model_visible: bool,
) -> ToolDTO:
    """把 Tool 实例转换成前端结构化展示所需的摘要。"""
    server_name, _ = parse_dynamic_mcp_name(tool.name)
    source = "mcp" if tool.name.startswith("mcp__") else "builtin"
    return ToolDTO(
        name=tool.name,
        description=tool.description,
        usage=getattr(tool, "usage", "") or "",
        input_schema=dict(tool.input_schema),
        read_only=tool.is_read_only(),
        concurrency_safe=tool.is_concurrency_safe(),
        search_behavior=dict(tool.search_behavior()),
        execution_available=execution_available,
        model_visible=model_visible,
        dynamic=tool.name.startswith("mcp__"),
        source=source,
        server_name=server_name or None,
    )


def present_tools_snapshot(
    execution_tools: list[Tool],
    model_tools: list[Tool],
) -> ToolsSnapshotDTO:
    """把 execution/model 两个工具面统一映射成前端可消费结构。"""
    model_names = {tool.name for tool in model_tools}
    execution_names = {tool.name for tool in execution_tools}
    return ToolsSnapshotDTO(
        execution_tools=[
            present_tool(tool, execution_available=True, model_visible=tool.name in model_names)
            for tool in execution_tools
        ],
        model_tools=[
            present_tool(tool, execution_available=tool.name in execution_names, model_visible=True)
            for tool in model_tools
        ],
    )


def present_skill(command: PromptCommandSpec) -> SkillDTO:
    """把 skill / MCP prompt 统一命令对象映射成 DTO。"""
    return SkillDTO(
        name=command.name,
        description=command.description,
        kind=command.kind,
        loaded_from=command.loaded_from,
        source=command.source,
        arg_names=list(command.arg_names),
        model=command.model,
        disable_model_invocation=command.disable_model_invocation,
        user_invocable=command.user_invocable,
        model_invocable=command.model_invocable,
        server_name=command.server_name,
        original_name=command.original_name,
        resource_uri=command.resource_uri,
        metadata={str(key): value for key, value in command.metadata.items()},
    )


def present_skills_snapshot(
    user_commands: list[PromptCommandSpec],
    model_commands: list[PromptCommandSpec],
) -> SkillsSnapshotDTO:
    """把用户可调和模型可调 skills 分两组输出。"""
    return SkillsSnapshotDTO(
        user_commands=[present_skill(command) for command in user_commands],
        model_commands=[present_skill(command) for command in model_commands],
    )


def present_mcp_snapshot(
    connections,
    *,
    tools_by_server: dict[str, list[object]],
    prompt_commands: list[PromptCommandSpec],
    skill_commands: list[PromptCommandSpec],
    resources_by_server: dict[str, list[object]],
) -> McpSnapshotDTO:
    """把 MCP runtime 的连接和缓存统一映射成结构化快照。"""
    tool_items: list[McpToolDTO] = []
    for server_name, definitions in tools_by_server.items():
        for definition in definitions:
            resolved_name = getattr(definition, "name", "")
            annotations = getattr(definition, "annotations", {}) or {}
            tool_items.append(
                McpToolDTO(
                    server_name=server_name,
                    resolved_name=str(resolved_name),
                    original_name=str(annotations.get("original_name", resolved_name)),
                    description=str(getattr(definition, "description", "") or ""),
                    input_schema=dict(getattr(definition, "input_schema", {}) or {}),
                    annotations=dict(annotations) if isinstance(annotations, dict) else {},
                    auth_tool=bool(isinstance(annotations, dict) and annotations.get("authTool")),
                )
            )

    resource_items: list[McpResourceDTO] = []
    for server_name, resources in resources_by_server.items():
        for resource in resources:
            resource_items.append(
                McpResourceDTO(
                    server_name=server_name,
                    uri=str(getattr(resource, "uri", "")),
                    name=str(getattr(resource, "name", "")),
                    description=str(getattr(resource, "description", "") or ""),
                    mime_type=str(getattr(resource, "mime_type", "") or ""),
                )
            )

    return McpSnapshotDTO(
        connections=[
            McpConnectionDTO(
                name=connection.name,
                status=connection.status,
                scope=connection.config.scope,
                transport=connection.config.type,
                description=connection.config.description,
                command=connection.config.command,
                url=connection.config.url,
                error=connection.error,
                updated_at=connection.updated_at,
                capabilities=list(connection.capabilities),
                tool_count=connection.tool_count,
                prompt_count=connection.prompt_count,
                resource_count=connection.resource_count,
                instructions=connection.instructions,
                server_label=connection.server_label,
            )
            for connection in connections
        ],
        tools=tool_items,
        prompt_commands=[present_skill(command) for command in prompt_commands],
        skill_commands=[present_skill(command) for command in skill_commands],
        resources=resource_items,
    )


def present_runtime_info(context: WebAppContext) -> RuntimeInfoDTO:
    """输出当前 Web 后端的 provider 和工作区配置摘要。"""
    return RuntimeInfoDTO(
        app_name=APP_DISPLAY_NAME,
        app_version=APP_VERSION,
        workspace_root=str(context.workspace_root),
        provider_name=context.provider.name,
        model=context.config.model,
        api_timeout_ms=context.config.api_timeout_ms,
        max_tokens=context.config.max_tokens,
        query_max_iterations=context.config.query_max_iterations,
    )


def present_tool_event(event: ToolEvent) -> SSEToolEventDTO:
    """把内部 ToolEvent 转成 SSE 事件载荷。"""
    return SSEToolEventDTO(
        tool_name=event.tool_name,
        phase=event.phase,
        summary=event.summary,
        detail=event.detail,
        metadata={str(key): value for key, value in event.metadata.items()},
    )


def present_chat_turn(session: SessionTranscript, *, start_index: int) -> ChatTurnDTO:
    """把一轮调用新增的消息片段和最新会话摘要一起输出。"""
    return ChatTurnDTO(
        session=present_session_detail(session),
        new_messages=[
            present_message(session.session_id, index, message)
            for index, message in enumerate(session.messages[start_index:], start=start_index)
        ],
        pending_permission=present_pending_permission(session),
    )


def present_prompt_preview(rendered_prompt, *, request_preview: dict[str, object] | None = None) -> PromptPreviewDTO:
    """把内部 RenderedPrompt 映射成调试和 Web 展示可用的 DTO。"""
    bundle = rendered_prompt.bundle
    return PromptPreviewDTO(
        session_id=bundle.session_id,
        provider_name=bundle.provider_name,
        model=bundle.model,
        workspace_root=bundle.workspace_root,
        system_text=rendered_prompt.system_text,
        user_context_text=rendered_prompt.user_context_text,
        sections=[
            PromptSectionDTO(
                id=section.id,
                kind=section.kind,
                target=section.target,
                order=section.order,
                text=section.text,
                source_path=section.source_path,
                source_type=section.source_type,
                relative_name=section.relative_name,
                cacheable=section.cacheable,
                metadata=dict(section.metadata),
            )
            for section in bundle.sections
        ],
        context_values=dict(bundle.context_data.variables),
        debug_meta=dict(bundle.context_data.debug_meta),
        request_preview=dict(request_preview or {}),
    )
