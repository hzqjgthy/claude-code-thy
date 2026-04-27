# Web API 接口设计

本文档描述 `claude-code-thy` 在删除 Textual 终端交互界面后，前后端分离模式下的后端接口和 DTO 设计。

## 1. 设计目标

- 保留现有核心链路：
  - `ConversationRuntime`
  - `QueryEngine`
  - `CommandProcessor`
  - `ToolRuntime`
  - `SessionStore`
- 交互界面全部由前端接管
- 前端不直接消费历史终端渲染约定
- 后端输出稳定 DTO，让前端全面接管界面逻辑

## 2. 当前新增的 Web API

### 基础

- `GET /api/health`
- `GET /api/runtime`

### 会话

- `GET /api/sessions`
- `POST /api/sessions`
- `GET /api/sessions/{session_id}`
- `DELETE /api/sessions/{session_id}`
- `GET /api/sessions/{session_id}/messages`

### 聊天

- `POST /api/chat`
  - `stream=false` 返回 JSON
  - `stream=true` 返回 SSE

### 权限确认

- `GET /api/sessions/{session_id}/pending-permission`
- `POST /api/sessions/{session_id}/pending-permission/resolve`

### 结构化侧边面板

- `GET /api/sessions/{session_id}/tasks`
- `GET /api/sessions/{session_id}/tools`
- `GET /api/sessions/{session_id}/skills`
- `GET /api/sessions/{session_id}/mcp`

## 3. DTO 分层

当前 DTO 集中定义在：

- `src/claude_code_thy/server/schemas.py`

主要分成 5 组：

### 会话类

- `SessionSummaryDTO`
- `SessionDetailDTO`
- `SessionTranscriptDTO`
- `ChatTurnDTO`

### 消息类

- `MessageDTO`
- `ToolCallDTO`
- `ToolResultDTO`
- `TaskNotificationDTO`

### 权限类

- `PermissionRequestDTO`
- `PendingPermissionDTO`

### 面板类

- `TaskDTO`
- `ToolDTO`
- `ToolsSnapshotDTO`
- `SkillDTO`
- `SkillsSnapshotDTO`
- `McpConnectionDTO`
- `McpToolDTO`
- `McpResourceDTO`
- `McpSnapshotDTO`

### 流式事件类

- `SSEToolEventDTO`
- `SSEMessageEventDTO`
- `SSEDoneEventDTO`
- `SSEErrorEventDTO`

## 4. 新增的重构点

### `ConversationRuntime.resolve_pending_permission()`

之前权限恢复只能通过：

- 用户继续输入 `yes/no`

现在抽成了显式方法，Web API 可以直接调用：

- `resolve_pending_permission(session, approved=True/False)`

这样前端可以直接弹窗确认，不需要再模拟文本输入。

### `SessionStore.delete()`

之前会话只有：

- 创建
- 保存
- 加载

现在补了：

- 删除

这样 Web 前端的会话列表可以做真正的删除操作。

## 5. Presenter 层

当前新增：

- `src/claude_code_thy/server/presenters.py`

它的职责是把现有 transcript / metadata / task / MCP 缓存转换成前端稳定 DTO。

这层的意义是：

- 前端不再直接理解 Textual 时代的 `ui_kind / preview / summary / structured_data` 约定
- 后端统一把这些字段组织成更稳定的 API 结构

## 6. 聊天流式事件设计

当前 `POST /api/chat` 在 `stream=true` 下会输出以下 SSE 事件：

- `tool_event`
- `message`
- `done`
- `error`

第一版不做 token 级流式。

原因：

- 现有 provider 不是流式聚合实现
- 但现有 `ToolEvent` 已经能提供足够好的事件级流式

所以当前策略是：

- 先流工具阶段事件
- 最终再流新消息和 turn 结果

## 7. 当前仍保留但后续建议继续重构的点

### 仍然存在的旧消息协议痕迹

当前 transcript 的消息 metadata 里还保留了这些字段：

- `ui_kind`
- `display_name`
- `summary`
- `preview`
- `structured_data`

这在当前 Web API 阶段是可接受的，因为 presenter 会统一封装。

但下一阶段更理想的方向是：

- 逐步让“工具输出协议”独立于 Textual/Rich
- 让 `ToolResult` 的结构本身就更适合前后端分离

### Textual UI 已删除，但消息协议仍然沿用一部分旧字段

当前已经删除：

- `src/claude_code_thy/ui/`
- Textual 入口

但消息里的 `ui_kind / summary / preview / structured_data` 仍然保留，作为过渡期协议供 Web presenter 消费。

## 8. 当前运行方式

CLI 新增：

- `claude-code-thy serve-web --host 127.0.0.1 --port 8002`

前提：

- 安装包含 FastAPI 依赖的新版项目

## 9. 下一步建议

下一阶段最值得做的是：

1. 前端消息模型按 `MessageDTO` 落地
2. 做一个 Web 聊天面板，先接：
   - `/api/chat`
   - `/api/sessions`
   - `/api/sessions/{id}/messages`
   - `/api/sessions/{id}/pending-permission`
3. 再补：
   - `/api/sessions/{id}/tools`
   - `/api/sessions/{id}/skills`
   - `/api/sessions/{id}/mcp`
   - `/api/sessions/{id}/tasks`
