# claude-code-thy

`claude-code-thy` 是一个以 Python 为主实现、持续向原项目能力边界靠拢的 Claude Code 风格终端工程。

它不是一个只会调用模型的简单聊天壳，也不是一个只接了几个工具的 demo。当前项目已经具备比较完整的会话、工具、后台任务、skills、MCP、TUI/CLI 主链路，并且仍在继续补齐和原项目之间的差距。

## 项目定位

当前版本重点覆盖这些能力域：

- Claude Code 风格的终端交互和会话恢复
- 工具驱动的多轮推理主链路
- 本地文件 / shell / agent / 后台任务能力
- 本地 skills 与 MCP skills 的统一命令模型
- MCP client、MCP server、MCP prompt / resource / skill 接入
- 会话级权限确认、sandbox、文件历史、基础 LSP 通知

项目目标不是完全复刻原项目内部所有约束组件，而是在保留核心能力强度的前提下，用更清晰的 Python 结构把主链路做完整。

## 当前功能总览

### 1. 运行模式

- 交互式 TUI：
  - `claude-code-thy`
- 无头单次执行：
  - `claude-code-thy --print "你好"`
  - `echo "你好" | claude-code-thy --print`
- 会话恢复：
  - `claude-code-thy --resume <session-id>`
- 最近会话列表：
  - `claude-code-thy --list-sessions`

### 2. 会话与运行时

- 会话持久化到本地 JSON transcript
- 自动标题生成
- `--resume` 恢复历史上下文
- slash 命令、模型对话、工具调用统一进入同一运行时
- 工具权限确认支持 pending/resume
- 后台任务完成后会自动回写会话通知

### 3. 工具体系

当前内置并可实际使用的工具包括：

- `agent`
- `bash`
- `read`
- `write`
- `edit`
- `glob`
- `grep`
- `skill`
- `list_mcp_resources`
- `read_mcp_resource`

这些工具已经接入统一生命周期：

- 字符串参数解析
- 结构化输入执行
- 输入校验
- 权限检查
- 拒绝态结果
- tool result 到模型消息的映射
- tool metadata / structured_data 持久化

### 4. Bash / 文件能力

#### `bash`

- 支持前台执行和后台执行
- 支持 sandbox 决策和适配
- 支持权限校验
- 支持基础进度事件
- 支持部分 shell 结构分析

#### `read`

- 普通文本读取
- `offset/limit` 窗口读取
- UTF-16 / BOM 文本读取
- 图片读取
- PDF 读取
- notebook 读取

#### `write`

- 完整文件覆盖写入
- read-before-write 保护
- 文件历史快照
- 结构化 diff
- git 仓库内单文件 `git_diff`

#### `edit`

- `old_string/new_string` 编辑
- `edits` 批量编辑
- read-before-edit 保护
- 编码 / BOM / 换行保留
- 结构化 diff
- rejected diff 结果

### 5. Agent 与后台任务

- `AgentTool` 可直接发起本地 agent
- `/agent-run` 启动后台 agent
- `/agent-wait` 等待 agent 完成
- `/task-output` 查看输出尾部
- `/task-stop` 停止后台任务
- 后台任务 registry 与状态恢复
- TUI 中可看到任务相关状态更新

### 6. Skills 系统

当前项目已经不是“只发现目录”的状态，而是具备一套真正可执行的 skills 子系统：

- 本地 `SKILL.md` 会解析成统一的 prompt command 模型
- 本地 skill 与 MCP prompt / MCP skill 共用同一套 registry
- inline skill 会把展开后的 prompt 注入主对话
- 模型可通过 `skill` 工具调用可模型调用的 skills
- 用户可通过 slash 直接执行用户可见的 skills

当前支持的 `SKILL.md` frontmatter 字段包括：

- `description`
- `arguments`
- `disable-model-invocation`
- `user-invocable`
- `model`
- `version`

### 7. MCP 子系统

当前 MCP 已经具备一个可运行的高层子系统，而不只是零散工具：

- 独立 `mcp/` 模块
- 项目级 `.mcp.json`
- settings 内的 MCP 配置
- transport 分层：
  - `stdio`
  - `http`
  - `sse`
- request-scoped HTTP 连接策略
- 连接 catalog / transport / session operations / runtime 分层
- MCP tools 动态注入会话工具池
- MCP prompts 进入统一 prompt command 模型
- MCP resources 列表与读取
- MCP skills 从 resources 发现并桥接进 skills registry
- MCP `needs-auth` 状态
- 简化版 OAuth HTTP/SSE 流程
- `McpAuthTool` 认证工具暴露
- 基础 `list_changed` handler 注册
- `claude-code-thy mcp ...` CLI
- 最小 MCP server 入口

#### 已接入的 MCP 运行时能力

- tools/list -> 动态 MCP tools
- prompts/list -> 统一 prompt commands
- resources/list -> 资源工具和 skill 发现
- `skill://` / `SKILL.md` 风格资源 -> MCP skills
- `needs-auth` -> 认证工具替代暴露

#### 作为 MCP Server

项目也可以对外作为 MCP server 使用：

- `claude-code-thy mcp serve`
- 支持 `ListTools`
- 支持 `CallTool`
- 使用现有 `ToolRuntime` 执行内置工具

### 8. 权限、安全与基础设施

- 工具级权限确认
- 已批准权限记忆
- sandbox policy
- file history
- 本地 skill 固定 roots 扫描
- 基础 LSP 文件通知

## 项目结构

主要目录如下：

```text
src/claude_code_thy/
  cli.py                  # CLI 入口
  runtime.py              # 对话运行时
  query_engine.py         # provider + tool loop
  commands.py             # slash 命令处理
  services.py             # 运行时服务聚合
  tools/                  # 内置工具与 ToolRuntime
  skills/                 # 本地 skill / MCP skill 统一模型与 registry
  mcp/                    # MCP client/runtime/server/auth
  session/                # transcript 存储
  tasks/                  # 后台任务系统
  ui/                     # Textual TUI
```

## 快速开始

### 推荐：conda 环境

```bash
conda env create -f environment.yml
conda activate claude-code-thy
pip install --no-cache-dir --force-reinstall .
claude-code-thy --help
```

### 直接从源码运行

```bash
PYTHONPATH=src python -m claude_code_thy --help
PYTHONPATH=src python -m claude_code_thy
PYTHONPATH=src python -m claude_code_thy --print "你好"
```

## 安装后的源码更新说明

如果你是通过下面命令安装的：

```bash
pip install --no-cache-dir --force-reinstall .
```

那么 `claude-code-thy` 命令运行的是“安装后的包”，不是源码热更新模式。

这意味着：

- 你改了 `src/` 里的代码，已安装命令不会自动生效
- 每次源码更新后，都应该重装一次

推荐重装命令：

```bash
pip install --no-cache-dir --force-reinstall .
```

如果命令入口没有刷新，可以再执行：

```bash
pip uninstall -y claude-code-thy
pip install --no-cache-dir --force-reinstall .
rehash
```

## 配置

### 1. `.env`

程序会在当前工作目录及其父目录中自动查找 `.env`。

可以先复制模板：

```bash
cp .env.example .env
```

常用变量：

```env
ANTHROPIC_API_KEY=
ANTHROPIC_AUTH_TOKEN=
ANTHROPIC_BASE_URL=https://api.anthropic.com
ANTHROPIC_MODEL=glm-4.5
API_TIMEOUT_MS=600000
CLAUDE_CODE_THY_MAX_TOKENS=4096
```

说明：

- `ANTHROPIC_API_KEY` 和 `ANTHROPIC_AUTH_TOKEN` 二选一即可
- `.env` 是运行时配置，不会被打进 wheel
- `pip install .` 不会“安装”你的 `.env`

### 2. settings

默认会从工作目录下读取：

```text
.claude-code-thy/settings.json
.claude-code-thy/settings.local.json
```

目前 settings 里可配置的主要域：

- `permissions`
- `sandbox`
- `tasks`
- `file_history`
- `skills`
- `lsp`
- `mcp`

### 3. `.mcp.json`

项目级 MCP 配置文件格式：

```json
{
  "mcpServers": {
    "demo": {
      "type": "http",
      "url": "http://localhost:18060/mcp"
    }
  }
}
```

支持的核心 transport：

- `stdio`
- `http`
- `sse`

配置层目前也识别这些高级 transport 名称，但尚未全部实现：

- `ws`
- `sdk`
- `sse-ide`
- `claudeai-proxy`

### 4. `SKILL.md`

一个最小的本地 skill 示例：

```md
---
description: Review a topic carefully
arguments:
  - topic
user-invocable: true
---

Please review ${topic} carefully and summarize the risks.
```

另一个本地 skill 示例：

```md
---
description: Investigate the workspace and return a concise report
---

Investigate the workspace and return a concise report.
```

## 常用命令

### 基础命令

```bash
/help
/status
/sessions
/resume
/model
/tools
/skills
/mcp
/init
/clear
```

### 工具相关命令

```bash
/bash ls -la
/read README.md
/write notes.txt -- hello
/edit README.md --old "old text" --new "new text"
/glob **/*.py
/grep SessionTranscript --content --path src
/skill review auth-flow
/agent --background -- 生成一份变更总结
```

### 任务相关命令

```bash
/tasks
/agents
/agent-run 生成一份变更总结
/agent-wait <task_id>
/task-stop <task_id>
/task-output <task_id>
```

### MCP CLI

```bash
claude-code-thy mcp list
claude-code-thy mcp get <name>
claude-code-thy mcp add-json <name> '{"type":"http","url":"http://localhost:18060/mcp"}'
claude-code-thy mcp add <name> http://localhost:18060/mcp --transport http
claude-code-thy mcp remove <name>
claude-code-thy mcp show-config
claude-code-thy mcp serve
```

### MCP 动态能力

```text
/mcp
/mcp__<server>__<prompt> <args>
/mcp__<server>__<tool> {"key":"value"}
```

说明：

- MCP tools 会按会话动态进入工具池
- MCP prompts 会进入统一 prompt command registry
- MCP skills 会通过资源发现后进入统一 skills registry
- 需要认证的 MCP server 会暴露认证工具，而不是只报错

## 验证与测试

项目目前带有一批针对主链路的测试，包括：

- 会话存储
- provider 工厂
- QueryEngine 工具循环
- CommandProcessor
- 工具运行时
- MCP config / helper / layer / auth runtime
- skills 统一命令模型

如果当前环境有 `pytest`，可以运行：

```bash
pytest
```

如果没有 `pytest`，至少可以做编译检查：

```bash
python -m compileall src tests
```

## 当前边界与尚未完全对齐的部分

虽然现在已经不是“简化 demo”，但它仍未完全等价于原项目。当前仍在继续补齐的主要方面：

- 更完整的 MCP UI 管理面板
- 更完整的 MCP OAuth / token refresh /复杂企业认证链
- 更完整的 MCP list_changed / reconnect / notification 体系
- 更完整的 skills hooks / shell frontmatter 执行
- 更复杂的 agent 协调与多 agent 工作流
- 更深的 BashTool classifier / 专属 UI / 注解体系
- 更高级的 transport 与企业配置来源

更准确地说，当前项目已经具备：

- 可运行的 Claude Code 风格终端主链路
- 可用的工具系统
- 可用的本地 skills
- 可用的 MCP tools / prompts / resources / skills / auth 起步版

但仍处在“继续向原项目收敛”的阶段。
