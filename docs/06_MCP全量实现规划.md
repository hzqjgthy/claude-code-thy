# MCP 全量实现规划

本文档用于指导在新项目 `claude-code-thy` 中，按原项目 `claude-code-haha` 的逻辑，完整实现 MCP 相关能力。

目标不是做一个“能连上 MCP server 的简化版”，而是尽量把原项目 MCP 子系统的能力边界、运行时逻辑、配置体系、鉴权流程、工具暴露、资源/提示词/技能整合、UI 和 CLI 管理能力整体迁移到新项目。

## 1. 目标定义

### 1.1 总目标

在新项目中建立一个完整的 MCP 子系统，覆盖原项目的两种角色：

- 作为 MCP Client，连接外部 MCP Server，并接入：
  - MCP tools
  - MCP prompts
  - MCP resources
  - MCP skills
  - MCP elicitation
  - MCP OAuth / Auth
- 作为 MCP Server，对外暴露新项目自身的内置工具

### 1.2 对齐原则

实现时遵循以下原则：

- 行为优先对齐原项目，而不是只对齐接口名
- 先补“主链路可用 + 可验证”的能力，再补边角功能
- Python 为主实现
- 如果个别协议细节、IDE transport 或 SDK 兼容性在 Python 中实现成本明显过高，可以引入极小范围的辅助实现，但不能让 MCP 主链路依赖一大套外部脚手架
- 不做 mock 风格替代，不做 demo 版 MCP

### 1.3 非目标

本文档不覆盖：

- plugins 全量实现
- 远程 CCR / Claude.ai 私有后端完整复刻
- analytics 埋点的全量迁移

这些能力会在 MCP 框架稳定后逐步补充。

## 2. 原项目 MCP 能力范围

根据原项目分析，MCP 子系统包括以下能力域：

### 2.1 配置与作用域

- 多作用域配置：
  - `local`
  - `user`
  - `project`
  - `dynamic`
  - `enterprise`
  - `claudeai`
  - `managed`
- 多 transport：
  - `stdio`
  - `sse`
  - `sse-ide`
  - `http`
  - `ws`
  - `sdk`
  - `claudeai-proxy`
- 配置合并、去重、禁用、优先级处理

### 2.2 连接管理

- 连接状态：
  - `connected`
  - `failed`
  - `needs-auth`
  - `pending`
  - `disabled`
- 连接缓存
- reconnect
- list changed 后自动刷新 tools / prompts / resources
- 本地与远程 transport 分批并发连接

### 2.3 运行时能力接入

- `tools/list` -> 包装为 MCPTool
- `prompts/list` -> 包装为内部命令
- `resources/list` -> 挂入资源系统
- `skill://` 等 MCP resource -> 动态技能发现
- 统一进入主循环的权限与工具系统

### 2.4 认证与安全

- OAuth metadata discovery
- token refresh
- callback port
- secure storage
- XAA / IdP
- `needs-auth` 状态与 `McpAuthTool`
- `headersHelper`
- project scope MCP 审批
- channel allowlist / channel permission relay

### 2.5 用户交互与 UI

- `/mcp` 管理界面
- MCP server 状态可视化
- 连接失败 / needs-auth / pending / disabled 展示
- MCP tool progress
- elicitation form / url 流程

### 2.6 CLI

- `claude mcp serve`
- `claude mcp list`
- `claude mcp get`
- `claude mcp add`
- `claude mcp add-json`
- `claude mcp remove`
- `claude mcp reset-choices`
- Desktop 导入流程

### 2.7 作为 MCP Server

- 启动 stdio MCP server
- 暴露内部工具列表
- 支持 `ListTools`
- 支持 `CallTool`

## 3. 新项目当前状态

截至本文档编写时，新项目 MCP 现状基本为：

- `tasks/types.py` 里仅预留了 `mcp` 任务类型
- 没有独立的 `mcp/` 子系统目录
- 没有 MCP client 连接器
- 没有 MCP tool wrapper
- 没有 MCP resources / prompts / skills 接入
- 没有 MCP OAuth / auth
- 没有 `/mcp` 管理面板
- 没有 MCP CLI 子命令
- 没有 MCP server 入口

结论：

- 这是一个“从 0 到 1”建立完整 MCP 子系统的工作
- 不能只在现有 `tools/` 下补几个文件，需要先建立基础架构

## 4. 目标架构

建议在新项目中新增独立的顶层 MCP 模块：

```text
src/claude_code_thy/mcp/
  __init__.py
  types.py
  state.py
  config.py
  utils.py
  normalization.py
  string_utils.py
  headers.py
  env_expansion.py
  auth.py
  oauth_port.py
  xaa.py
  xaa_idp.py
  client.py
  cache.py
  connection_manager.py
  resources.py
  prompts.py
  skills.py
  elicitation.py
  approvals.py
  channel_allowlist.py
  channel_permissions.py
  channel_notifications.py
  official_registry.py
  managed.py
  server.py
```

对应工具目录：

```text
src/claude_code_thy/tools/MCPTool/
src/claude_code_thy/tools/McpAuthTool/
src/claude_code_thy/tools/ListMcpResourcesTool/
src/claude_code_thy/tools/ReadMcpResourceTool/
```

对应 UI 与 CLI：

```text
src/claude_code_thy/ui/mcp/
src/claude_code_thy/cli_mcp.py
```

说明：

- MCP 不建议塞进现有 `services.py` 的单层聚合里直接硬堆
- 应先有独立 `mcp/` 目录，再通过 `services.py` 暴露统一入口
- 这样结构最清晰，也方便后续扩展 plugins / remote / skills / IDE 特化

## 5. 模块设计

### 5.1 配置层

目标模块：

- `mcp/types.py`
- `mcp/config.py`
- `mcp/env_expansion.py`
- `mcp/utils.py`

职责：

- 定义 MCP server config schema
- 支持多 scope 配置合并
- 支持 `.mcp.json`
- 支持 settings 内的 MCP 配置
- 支持 disabled 状态
- 支持 config hash / dedup signature
- 支持 plugin / claudeai / enterprise / managed 扩展入口

第一阶段必须支持：

- `stdio`
- `http`
- `sse`
- `ws`

后续阶段补：

- `sdk`
- `sse-ide`
- `claudeai-proxy`

### 5.2 连接层

目标模块：

- `mcp/client.py`
- `mcp/cache.py`
- `mcp/connection_manager.py`

职责：

- 连接 MCP server
- 维护连接状态
- 支持 reconnect
- 提供：
  - `connect_to_server(...)`
  - `ensure_connected_client(...)`
  - `reconnect_mcp_server(...)`
  - `clear_server_cache(...)`
- 支持拉取：
  - `fetch_tools_for_client(...)`
  - `fetch_prompts_for_client(...)`
  - `fetch_resources_for_client(...)`
  - `fetch_skills_for_client(...)`

要求：

- 按 server name 做缓存
- transport 分流并发
- 支持 list changed 触发刷新

### 5.3 MCP 工具包装层

目标模块：

- `tools/MCPTool/`
- `tools/McpAuthTool/`
- `tools/ListMcpResourcesTool/`
- `tools/ReadMcpResourceTool/`

职责：

- 把 MCP tools 包装进现有 `ToolRuntime`
- 把资源读取接入统一生命周期
- 把未认证 server 暴露为 `McpAuthTool`

要求：

- 保留原项目语义：
  - MCP tool 可声明只读 / destructive / openWorld
  - MCP tool progress 可视化
  - MCP tool result 支持 `_meta` 和 `structuredContent`
- 资源工具支持二进制落盘而不是把 blob 直接灌进上下文

### 5.4 提示词与技能整合层

目标模块：

- `mcp/prompts.py`
- `mcp/skills.py`

职责：

- `prompts/list` -> 内部 command
- MCP skills 发现与加载
- 资源到 skill 的映射

要求：

- MCP prompt 不只是列出来，必须可以进入主命令系统
- MCP skill 必须进入现有 skills 管理体系，而不是作为普通文件资源停留在连接层

### 5.5 认证层

目标模块：

- `mcp/auth.py`
- `mcp/oauth_port.py`
- `mcp/xaa.py`
- `mcp/xaa_idp.py`

职责：

- OAuth discovery
- callback port
- secure token storage
- refresh token
- needs-auth 状态判定
- `McpAuthTool` 支持

最低阶段先支持：

- 普通 OAuth HTTP/SSE MCP server

后续阶段补：

- XAA
- IdP
- 更复杂的 Claude.ai / 私有代理链路

### 5.6 审批与安全层

目标模块：

- `mcp/approvals.py`
- `mcp/headers.py`
- `mcp/channel_allowlist.py`
- `mcp/channel_permissions.py`
- `mcp/channel_notifications.py`

职责：

- project scope MCP server 首次审批
- headersHelper 执行与安全防护
- channel 相关 permission relay
- server 启用 / 禁用

最低阶段必须支持：

- project scope server approval
- headersHelper

### 5.7 UI 层

目标模块：

- `ui/mcp/`
- `mcp/connection_manager.py`

职责：

- `/mcp` 管理面板
- server 列表与状态展示
- reconnect / toggle enabled
- needs-auth 入口
- pending approvals
- MCP progress / errors / notifications
- elicitation UI

要求：

- 不要只做一页文本列表
- 要能融入现有 TUI 和会话流

### 5.8 CLI 层

目标模块：

- `cli_mcp.py`
- `cli.py`

职责：

- 增加 `claude-code-thy mcp ...`
- 至少实现：
  - `serve`
  - `list`
  - `get`
  - `add`
  - `add-json`
  - `remove`
  - `reset-choices`

### 5.9 MCP Server 层

目标模块：

- `mcp/server.py`
- `__main__.py` / `cli.py`

职责：

- 作为 MCP server 对外暴露新项目内部工具
- 支持：
  - `ListTools`
  - `CallTool`

要求：

- 使用新项目现有 `ToolRuntime`
- 保持工具权限与结果映射风格一致

## 6. 分阶段开发计划

## Phase 0：冻结协议与模块边界

目标：

- 在开始编码前冻结 MCP 架构边界，避免后面返工

任务：

- 确认 Python 侧 MCP SDK 选择
- 确认 transport 支持策略
- 确认 token storage 方案
- 确认 `mcp/` 目录结构
- 确认与现有 `ToolRuntime`、`ConversationRuntime`、`tasks`、`skills`、`ui` 的集成边界

产出：

- MCP 模块目录落地
- 基础类型文件

验收：

- 新项目代码树中出现稳定的 `mcp/` 子系统目录

## Phase 1：先做 MCP Client 核心闭环

目标：

- 先让新项目能真正连接 MCP server，并拿到 tools / prompts / resources

任务：

- 实现 server config schema
- 实现 `.mcp.json` 读取
- 实现 `stdio/http/sse/ws` 连接器
- 实现 server 状态机
- 实现 `fetch_tools / fetch_prompts / fetch_resources`
- 实现缓存与 reconnect

验收：

- 能连接本地 `stdio` MCP server
- 能连接本地 `http` MCP server
- 能列出 tools / prompts / resources
- server 断开后可重连

## Phase 2：把 MCP 接进主循环

目标：

- MCP server 暴露的工具、提示词、资源真正进入新项目主链路

任务：

- 实现 `MCPTool`
- 实现 `ListMcpResourcesTool`
- 实现 `ReadMcpResourceTool`
- MCP prompts -> 内部 commands
- 接入 `ToolRuntime`
- 接入 `CommandProcessor`

验收：

- 模型可自动调用 MCP tool
- 用户可通过资源工具读取 MCP resources
- MCP prompts 能进入命令系统

## Phase 3：认证与 needs-auth 链路

目标：

- 让远程 MCP server 的 OAuth 不再是“手工搞”，而是进入系统主链路

任务：

- 实现 OAuth metadata discovery
- 实现 callback port
- 实现 token storage
- 实现 refresh
- 实现 `needs-auth` 状态
- 实现 `McpAuthTool`

验收：

- 一个需要 OAuth 的 MCP server 能被标记为 `needs-auth`
- `McpAuthTool` 可发起认证
- 认证完成后 server 自动切回 `connected`

## Phase 4：UI 与交互面板

目标：

- MCP 不只存在于底层逻辑，要成为用户可见、可管理的能力域

任务：

- 实现 `/mcp` 面板
- 实现 server 状态展示
- 实现 reconnect / enable / disable
- 实现 pending approval 展示
- 实现 MCP tool progress UI
- 实现基础 error / auth 状态 UI

验收：

- 用户在 TUI 中能看到所有 MCP servers 的状态
- 可以直接在界面中触发 reconnect / auth / enable / disable

## Phase 5：审批、安全与 headersHelper

目标：

- 补上原项目里 MCP 安全体系的核心能力

任务：

- project scope MCP 审批
- headersHelper
- workspace trust 检查
- 本地/项目配置安全边界

验收：

- 项目级 `.mcp.json` 新 server 首次接入需要审批
- headersHelper 可返回动态 headers，并通过安全检查

## Phase 6：MCP skills 与 elicitation

目标：

- 补上原项目里最有特色但最容易漏掉的两块能力

任务：

- MCP resource -> skill 发现
- skill 进入现有 skills 管理体系
- `form` / `url` elicitation
- waiting state 与用户响应回传

验收：

- MCP skill 可被系统发现并加载
- MCP server 发起 elicitation 时，用户能完成交互

## Phase 7：CLI MCP 管理命令

目标：

- 把运行时能力产品化成完整命令行管理能力

任务：

- `claude-code-thy mcp list`
- `claude-code-thy mcp get`
- `claude-code-thy mcp add`
- `claude-code-thy mcp add-json`
- `claude-code-thy mcp remove`
- `claude-code-thy mcp reset-choices`
- `claude-code-thy mcp serve`

验收：

- 不进 TUI 也能完整管理 MCP server

## Phase 8：作为 MCP Server 对外暴露

目标：

- 让新项目也能像原项目一样，作为 MCP server 给外部使用

任务：

- 建立 MCP server 入口
- 暴露 `ListTools`
- 暴露 `CallTool`
- 使用现有 `ToolRuntime` 作为内部执行器

验收：

- 外部 MCP client 可以调用新项目暴露出的内置工具

## Phase 9：高级 transport 与企业特性补齐

目标：

- 把原项目剩余 MCP 特性逐步补完

任务：

- `sdk`
- `sse-ide`
- `claudeai-proxy`
- enterprise / managed config
- official registry
- channel allowlist / relay

验收：

- 这些高级 transport 和配置源能被识别并进入统一管理流程

## 7. 原项目文件映射建议

建议按下面思路做文件映射：


| 原项目                                         | 新项目建议                                                                           |
| ------------------------------------------- | ------------------------------------------------------------------------------- |
| `src/services/mcp/types.ts`                 | `src/claude_code_thy/mcp/types.py`                                              |
| `src/services/mcp/config.ts`                | `src/claude_code_thy/mcp/config.py`                                             |
| `src/services/mcp/client.ts`                | `src/claude_code_thy/mcp/client.py`                                             |
| `src/services/mcp/auth.ts`                  | `src/claude_code_thy/mcp/auth.py`                                               |
| `src/services/mcp/headersHelper.ts`         | `src/claude_code_thy/mcp/headers.py`                                            |
| `src/services/mcp/elicitationHandler.ts`    | `src/claude_code_thy/mcp/elicitation.py`                                        |
| `src/services/mcp/MCPConnectionManager.tsx` | `src/claude_code_thy/mcp/connection_manager.py` + `src/claude_code_thy/ui/mcp/` |
| `src/tools/MCPTool/`                        | `src/claude_code_thy/tools/MCPTool/`                                            |
| `src/tools/McpAuthTool/`                    | `src/claude_code_thy/tools/McpAuthTool/`                                        |
| `src/tools/ListMcpResourcesTool/`           | `src/claude_code_thy/tools/ListMcpResourcesTool/`                               |
| `src/tools/ReadMcpResourceTool/`            | `src/claude_code_thy/tools/ReadMcpResourceTool/`                                |
| `src/entrypoints/mcp.ts`                    | `src/claude_code_thy/mcp/server.py`                                             |
| `src/cli/handlers/mcp.tsx`                  | `src/claude_code_thy/cli_mcp.py`                                                |


## 8. 测试与验证矩阵

必须建立以下验证矩阵：

### 8.1 transport 维度

- `stdio`
- `http`
- `sse`
- `ws`

### 8.2 状态维度

- `connected`
- `failed`
- `needs-auth`
- `pending`
- `disabled`

### 8.3 能力维度

- tools 拉取
- prompts 拉取
- resources 拉取
- skills 发现
- tool 调用
- resource 读取
- auth 启动
- auth 完成后恢复
- reconnect
- list changed 刷新

### 8.4 UI 维度

- `/mcp` server 列表
- needs-auth 状态显示
- progress 展示
- approval 对话框
- elicitation 交互

### 8.5 CLI 维度

- `mcp list`
- `mcp get`
- `mcp add-json`
- `mcp remove`
- `mcp serve`

## 9. 风险与处理策略

### 风险 1：Python MCP SDK transport 覆盖不足

处理：

- Phase 0 先验证 SDK 能力
- 若某 transport 缺失，优先写 adapter
- 仅在必要时引入最小 sidecar

### 风险 2：OAuth / XAA 复杂度过高

处理：

- 先落普通 OAuth
- XAA / IdP 放后置 phase
- `McpAuthTool` 先支持最常见的 HTTP/SSE auth

### 风险 3：MCP skills 与现有 skills 体系耦合高

处理：

- 先把 skill 发现与 skill 执行分层
- 不要直接把 MCP skills 混进文件技能逻辑里

### 风险 4：UI 与底层连接状态不同步

处理：

- 引入显式 `MCPState`
- 所有 UI 从统一状态读，不直接读 client 对象

### 风险 5：把 MCP 实现成“只有工具调用”的缩水版

处理：

- 每阶段验收必须覆盖：
  - tools
  - prompts
  - resources
  - auth
  - UI
  - CLI
- 任一项长期缺失都不能宣称“已实现 MCP”

## 10. 推荐开发顺序

按执行性排序，推荐下面顺序：

1. 建立 `mcp/` 模块骨架与类型系统
2. 打通 `stdio/http/sse/ws` MCP client 连接
3. 拉取并接入 tools / prompts / resources
4. 建立 `MCPTool` / 资源工具
5. 打通 OAuth / `McpAuthTool`
6. 做 `/mcp` 面板与连接状态 UI
7. 做 project scope approval / headersHelper
8. 做 MCP skills / elicitation
9. 做 `claude-code-thy mcp ...` CLI
10. 做 MCP server 入口
11. 补高级 transport / 企业特性

## 11. 里程碑定义

### M1

- 能连接 `stdio/http` MCP server
- 能列出并调用 MCP tools

### M2

- prompts / resources 可用
- 资源读取工具可用

### M3

- OAuth / needs-auth / `McpAuthTool` 可用

### M4

- `/mcp` UI 可用
- reconnect / enable / disable / approval 可用

### M5

- MCP skills / elicitation 可用

### M6

- `claude-code-thy mcp ...` CLI 完整可用
- 新项目自身可作为 MCP server 对外服务

## 12. 最终验收标准

只有满足下面条件，才能认为“新项目 MCP 子系统已经基本对齐原项目”：

- 新项目可以稳定连接多类 MCP server
- MCP tools / prompts / resources / skills 全部能进入主链路
- 需要认证的 server 有 `needs-auth` 和认证工具链
- 用户可以通过 TUI 和 CLI 管理 MCP server
- 项目级 MCP 有审批机制
- 新项目可作为 MCP server 对外暴露自身工具
- 基础 transport、状态机、UI、CLI、认证、资源、技能、交互，都有验证用例

---

建议执行策略：

- 先按 Phase 1 到 Phase 4 把“核心可用 MCP client”做完
- 再补 Phase 5 到 Phase 8 的原项目高级能力
- 最后进入 Phase 9 做高阶 transport 和企业能力收尾

