from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class PermissionRequestDTO(BaseModel):
    request_id: str
    tool_name: str
    target: str
    value: str
    reason: str = ""
    approval_key: str = ""
    matched_rule_pattern: str = ""
    matched_rule_description: str = ""
    prompt_text: str = ""


class PendingPermissionDTO(BaseModel):
    request: PermissionRequestDTO
    source_type: str
    tool_name: str
    raw_args: str | None = None
    input_data: dict[str, Any] | None = None
    original_input: dict[str, Any] | None = None
    user_modified: bool | None = None
    tool_use_id: str | None = None


class ToolCallDTO(BaseModel):
    call_id: str
    name: str
    input: dict[str, Any] = Field(default_factory=dict)


class ToolResultDTO(BaseModel):
    tool_name: str
    display_name: str
    ui_kind: str
    ok: bool
    summary: str
    output: str = ""
    preview: str = ""
    structured_data: Any = None
    tool_use_id: str | None = None
    raw_metadata: dict[str, Any] = Field(default_factory=dict)


class TaskNotificationDTO(BaseModel):
    task_id: str
    task_status: str
    task_type: str


class MessageDTO(BaseModel):
    message_id: str
    index: int
    role: str
    kind: str
    text: str
    created_at: str
    content_blocks: list[dict[str, Any]] = Field(default_factory=list)
    raw_metadata: dict[str, Any] = Field(default_factory=dict)
    tool_calls: list[ToolCallDTO] = Field(default_factory=list)
    tool_result: ToolResultDTO | None = None
    permission_request: PermissionRequestDTO | None = None
    task_notification: TaskNotificationDTO | None = None


class SessionSummaryDTO(BaseModel):
    session_id: str
    title: str | None = None
    cwd: str
    model: str | None = None
    provider_name: str | None = None
    updated_at: str


class SessionDetailDTO(SessionSummaryDTO):
    created_at: str
    message_count: int
    pending_permission: PendingPermissionDTO | None = None


class SessionTranscriptDTO(BaseModel):
    session: SessionDetailDTO
    messages: list[MessageDTO]


class TaskDTO(BaseModel):
    task_id: str
    task_type: str
    task_kind: str = ""
    description: str
    command: str = ""
    cwd: str
    status: str
    started_at: str
    finished_at: str | None = None
    return_code: int | None = None
    output_path: str
    tool_use_id: str | None = None
    agent_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolDTO(BaseModel):
    name: str
    description: str
    usage: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)
    read_only: bool = False
    concurrency_safe: bool = False
    search_behavior: dict[str, bool] = Field(default_factory=dict)
    execution_available: bool = False
    model_visible: bool = False
    dynamic: bool = False
    source: str = "builtin"
    server_name: str | None = None


class ToolsSnapshotDTO(BaseModel):
    execution_tools: list[ToolDTO]
    model_tools: list[ToolDTO]


class SkillDTO(BaseModel):
    name: str
    description: str
    kind: str
    loaded_from: str
    source: str
    arg_names: list[str] = Field(default_factory=list)
    model: str | None = None
    disable_model_invocation: bool = False
    user_invocable: bool = True
    model_invocable: bool = False
    server_name: str | None = None
    original_name: str | None = None
    resource_uri: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SkillsSnapshotDTO(BaseModel):
    user_commands: list[SkillDTO]
    model_commands: list[SkillDTO]


class McpConnectionDTO(BaseModel):
    name: str
    status: str
    scope: str
    transport: str
    description: str = ""
    command: str = ""
    url: str = ""
    error: str = ""
    updated_at: str = ""
    capabilities: list[str] = Field(default_factory=list)
    tool_count: int = 0
    prompt_count: int = 0
    resource_count: int = 0
    instructions: str = ""
    server_label: str = ""


class McpToolDTO(BaseModel):
    server_name: str
    resolved_name: str
    original_name: str
    description: str
    input_schema: dict[str, Any] = Field(default_factory=dict)
    annotations: dict[str, Any] = Field(default_factory=dict)
    auth_tool: bool = False


class McpResourceDTO(BaseModel):
    server_name: str
    uri: str
    name: str
    description: str = ""
    mime_type: str = ""


class McpSnapshotDTO(BaseModel):
    connections: list[McpConnectionDTO]
    tools: list[McpToolDTO]
    prompt_commands: list[SkillDTO]
    skill_commands: list[SkillDTO]
    resources: list[McpResourceDTO]


class RuntimeInfoDTO(BaseModel):
    app_name: str
    app_version: str
    workspace_root: str
    provider_name: str
    model: str
    api_timeout_ms: int
    max_tokens: int
    query_max_iterations: int


class PromptSectionDTO(BaseModel):
    id: str
    kind: str
    target: str
    order: int
    text: str
    source_path: str
    source_type: str
    relative_name: str
    cacheable: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class PromptPreviewDTO(BaseModel):
    session_id: str
    provider_name: str
    model: str
    workspace_root: str
    system_text: str
    user_context_text: str
    sections: list[PromptSectionDTO]
    context_values: dict[str, str] = Field(default_factory=dict)
    debug_meta: dict[str, Any] = Field(default_factory=dict)
    request_preview: dict[str, Any] = Field(default_factory=dict)


class ChatTurnDTO(BaseModel):
    session: SessionDetailDTO
    new_messages: list[MessageDTO]
    pending_permission: PendingPermissionDTO | None = None


class SessionCreateRequest(BaseModel):
    cwd: str | None = None
    model: str | None = None


class ChatRequest(BaseModel):
    session_id: str
    prompt: str
    stream: bool = True


class PermissionResolveRequest(BaseModel):
    approved: bool


class SSEToolEventDTO(BaseModel):
    type: Literal["tool_event"] = "tool_event"
    tool_name: str
    phase: str
    summary: str
    detail: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class SSEAssistantDeltaEventDTO(BaseModel):
    type: Literal["assistant_delta"] = "assistant_delta"
    text: str


class SSEMessageEventDTO(BaseModel):
    type: Literal["message"] = "message"
    message: MessageDTO


class SSEDoneEventDTO(BaseModel):
    type: Literal["done"] = "done"
    turn: ChatTurnDTO


class SSEErrorEventDTO(BaseModel):
    type: Literal["error"] = "error"
    error: str
