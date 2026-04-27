export interface PermissionRequestDTO {
  request_id: string;
  tool_name: string;
  target: string;
  value: string;
  reason: string;
  approval_key: string;
  matched_rule_pattern: string;
  matched_rule_description: string;
  prompt_text: string;
}

export interface PendingPermissionDTO {
  request: PermissionRequestDTO;
  source_type: string;
  tool_name: string;
  raw_args?: string | null;
  input_data?: Record<string, unknown> | null;
  original_input?: Record<string, unknown> | null;
  user_modified?: boolean | null;
  tool_use_id?: string | null;
}

export interface ToolCallDTO {
  call_id: string;
  name: string;
  input: Record<string, unknown>;
}

export interface ToolResultDTO {
  tool_name: string;
  display_name: string;
  ui_kind: string;
  ok: boolean;
  summary: string;
  output: string;
  preview: string;
  structured_data: unknown;
  tool_use_id?: string | null;
  raw_metadata: Record<string, unknown>;
}

export interface TaskNotificationDTO {
  task_id: string;
  task_status: string;
  task_type: string;
}

export interface MessageDTO {
  message_id: string;
  index: number;
  role: string;
  kind: string;
  text: string;
  created_at: string;
  content_blocks: Array<Record<string, unknown>>;
  raw_metadata: Record<string, unknown>;
  tool_calls: ToolCallDTO[];
  tool_result?: ToolResultDTO | null;
  permission_request?: PermissionRequestDTO | null;
  task_notification?: TaskNotificationDTO | null;
}

export interface SessionSummaryDTO {
  session_id: string;
  title?: string | null;
  cwd: string;
  model?: string | null;
  provider_name?: string | null;
  updated_at: string;
}

export interface SessionDetailDTO extends SessionSummaryDTO {
  created_at: string;
  message_count: number;
  pending_permission?: PendingPermissionDTO | null;
}

export interface SessionTranscriptDTO {
  session: SessionDetailDTO;
  messages: MessageDTO[];
}

export interface TaskDTO {
  task_id: string;
  task_type: string;
  task_kind: string;
  description: string;
  command: string;
  cwd: string;
  status: string;
  started_at: string;
  finished_at?: string | null;
  return_code?: number | null;
  output_path: string;
  tool_use_id?: string | null;
  agent_id?: string | null;
  metadata: Record<string, unknown>;
}

export interface ToolDTO {
  name: string;
  description: string;
  usage: string;
  input_schema: Record<string, unknown>;
  read_only: boolean;
  concurrency_safe: boolean;
  search_behavior: Record<string, boolean>;
  execution_available: boolean;
  model_visible: boolean;
  dynamic: boolean;
  source: string;
  server_name?: string | null;
}

export interface ToolsSnapshotDTO {
  execution_tools: ToolDTO[];
  model_tools: ToolDTO[];
}

export interface SkillDTO {
  name: string;
  description: string;
  kind: string;
  loaded_from: string;
  source: string;
  arg_names: string[];
  model?: string | null;
  disable_model_invocation: boolean;
  user_invocable: boolean;
  model_invocable: boolean;
  server_name?: string | null;
  original_name?: string | null;
  resource_uri?: string | null;
  metadata: Record<string, unknown>;
}

export interface SkillsSnapshotDTO {
  user_commands: SkillDTO[];
  model_commands: SkillDTO[];
}

export interface McpConnectionDTO {
  name: string;
  status: string;
  scope: string;
  transport: string;
  description: string;
  command: string;
  url: string;
  error: string;
  updated_at: string;
  capabilities: string[];
  tool_count: number;
  prompt_count: number;
  resource_count: number;
  instructions: string;
  server_label: string;
}

export interface McpToolDTO {
  server_name: string;
  resolved_name: string;
  original_name: string;
  description: string;
  input_schema: Record<string, unknown>;
  annotations: Record<string, unknown>;
  auth_tool: boolean;
}

export interface McpResourceDTO {
  server_name: string;
  uri: string;
  name: string;
  description: string;
  mime_type: string;
}

export interface McpSnapshotDTO {
  connections: McpConnectionDTO[];
  tools: McpToolDTO[];
  prompt_commands: SkillDTO[];
  skill_commands: SkillDTO[];
  resources: McpResourceDTO[];
}

export interface RuntimeInfoDTO {
  app_name: string;
  app_version: string;
  workspace_root: string;
  provider_name: string;
  model: string;
  api_timeout_ms: number;
  max_tokens: number;
  query_max_iterations: number;
}

export interface ChatTurnDTO {
  session: SessionDetailDTO;
  new_messages: MessageDTO[];
  pending_permission?: PendingPermissionDTO | null;
}

export interface ChatRequest {
  session_id: string;
  prompt: string;
  stream: boolean;
}

export interface PermissionResolveRequest {
  approved: boolean;
}

export interface SSEToolEventDTO {
  type: "tool_event";
  tool_name: string;
  phase: string;
  summary: string;
  detail: string;
  metadata: Record<string, unknown>;
}

export interface SSEAssistantDeltaEventDTO {
  type: "assistant_delta";
  text: string;
}

export interface SSEMessageEventDTO {
  type: "message";
  message: MessageDTO;
}

export interface SSEDoneEventDTO {
  type: "done";
  turn: ChatTurnDTO;
}

export interface SSEErrorEventDTO {
  type: "error";
  error: string;
}
