# claude-code-thy

`claude-code-thy` 是一个以 Python 为主、对照原项目重写的 Claude Code 风格终端工程。

当前目标不是做一个简化 demo，而是持续把主链路、工具体系、会话恢复、任务、多 agent、TUI 体验逐步补齐到接近原项目。

## 当前进度

目前已经接入并可实际使用的能力：

- 命令入口：`claude-code-thy`
- 源码入口：`python -m claude_code_thy`
- 与原项目风格接近的 TUI 欢迎页和一体化聊天界面
- 会话持久化与 `--resume <session-id>` 恢复
- `-p/--print` 无头单次对话模式
- Anthropic 兼容 API provider
- 首批内置工具主链路：
  - `agent`
  - `bash`
  - `read`
  - `write`
  - `edit`
  - `glob`
  - `grep`
- 模型自动调用工具主链路
- 统一工具生命周期底座：
  - 输入解析
  - 输入校验
  - 权限检查
  - 拒绝态结果
  - 工具结果映射
- 会话级权限确认流
- `bash` sandbox 执行适配层
- 后台任务与任务状态恢复
- 最小可运行的 `local_agent` 链路
- 文件历史快照
- 基础动态 skills 发现
- 基础 LSP 文件通知

## 仍在持续补齐

和原项目相比，下面这些部分还没有完全等价：

- `AgentTool` 还不是原项目完整的多 agent 协调体系
- `BashTool` 还缺原项目完整 classifier、sandbox 注解和专属 UI 深度
- MCP、plugins、完整 skills 体系仍在继续补
- 权限规则、hooks、任务调度和工具 UI 仍会继续向原项目收敛

当前 MCP 已开始进入可用建设阶段：

- 已建立 `mcp/` 子系统骨架
- 已支持读取项目级 `.mcp.json`
- 已支持基础 MCP server 配置管理
- 已接入 `claude-code-thy mcp ...` 子命令起步版
- 已接入 `/mcp` 配置快照命令
- 已建立最小 MCP server 入口
- 已支持把已连接 MCP server 的 tools 接入会话级工具池
- 已支持把 MCP prompts 作为动态 slash command 执行
- 已支持基础 MCP resources 列表与读取工具

如果你现在使用它，建议把它理解为：

- 主链路已可用
- 很多关键基础设施已经接上
- 但还处在“持续向原项目逼近”的阶段

## 快速开始

推荐使用 conda 环境：

```bash
conda env create -f environment.yml
conda activate claude-code-thy
pip install --no-cache-dir --force-reinstall .
claude-code-thy --help
```

常用运行方式：

```bash
claude-code-thy
claude-code-thy --model glm-4.5
claude-code-thy -p "你好"
claude-code-thy --resume <session-id>
claude-code-thy --list-sessions
```

如果只想从源码直接运行：

```bash
PYTHONPATH=src python -m claude_code_thy --help
PYTHONPATH=src python -m claude_code_thy -p "你好"
```

## 包模式说明

如果你是通过下面这条命令安装的：

```bash
pip install --no-cache-dir --force-reinstall .
```

那么你运行的 `claude-code-thy` 是“安装后的包版本”，不是源码热更新模式。

这意味着：

- 你修改源码后，已安装命令不会自动跟着变
- 每次源码有更新，都应该重新安装一次

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

## `.env` 配置

程序会在“当前运行工作目录及其父目录”中自动查找 `.env` 文件。

可以先复制模板：

```bash
cp .env.example .env
```

常用配置项：

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
- `.env` 是运行时配置文件，不会被打进安装包
- `pip install .` 不会“安装”你的 `.env`
- 如果你切换到别的工作目录运行，是否能读到 `.env` 取决于该目录及其父目录是否存在 `.env`

## 常用命令

基础命令：

```bash
/help
/status
/sessions
/resume
/model
/tools
/mcp
/init
/clear
```

工具相关命令：

```bash
/bash ls -la
/read README.md
/write notes.txt -- hello
/edit README.md --old "old text" --new "new text"
/glob **/*.py
/grep SessionTranscript --content --path src
/agent --background -- 生成一份变更总结
```

任务相关命令：

```bash
/tasks
/agents
/agent-run 生成一份变更总结
/agent-wait <task_id>
/task-stop <task_id>
/task-output <task_id>
```

MCP CLI：

```bash
claude-code-thy mcp list
claude-code-thy mcp get <name>
claude-code-thy mcp add-json <name> '{"type":"http","url":"http://localhost:18060/mcp"}'
claude-code-thy mcp add <name> http://localhost:18060/mcp --transport http
claude-code-thy mcp remove <name>
claude-code-thy mcp show-config
claude-code-thy mcp serve
```

MCP 动态能力：

```text
/mcp
/mcp__<server>__<prompt> <args>
```

说明：

- 已连接 MCP server 暴露的 tools 会按会话动态进入工具池
- MCP prompts 当前会被映射为动态 slash command
- MCP resources 当前通过下面两个工具接入：
  - `list_mcp_resources`
  - `read_mcp_resource`

## 当前工具能力摘要

### `bash`

- 支持前台执行和后台执行
- 已接入权限检查
- 已接入 sandbox 决策与执行适配
- 已支持基础进度事件
- 已支持 `sed -i` 类编辑结果预览
- 已增加 shell 结构分析：
  - command substitution
  - process substitution
  - heredoc
  - subshell
  - function definition

### `read`

- 支持文本读取
- 支持 `offset/limit` 窗口读取
- 支持图片读取
- 支持 PDF 读取和分页读取
- 支持 notebook 读取
- 支持 UTF-16 / BOM 文本

### `write`

- 支持完整文件覆盖写入
- 已接入未先 read 拦截
- 已接入文件历史快照
- 已输出结构化 diff
- git 仓库内会附带单文件 `git_diff`
- 已支持 rejected diff 结果

### `edit`

- 支持单条 old/new 编辑
- 支持 `edits` 数组批量编辑
- 已接入未先 read 拦截
- 已保留编码 / BOM / 换行
- 已输出结构化 diff
- git 仓库内会附带单文件 `git_diff`
- 已支持 `user_modified` 结果层和 rejected diff

### `glob` / `grep`

- 已接入路径权限检查
- 优先使用 `rg`
- 回退到 Python 实现
- 已支持内容模式 / 文件模式 / 计数模式

### `agent`

- 已作为内置工具接入主链路
- 支持前台等待
- 支持后台运行
- 支持任务输出落盘
- 支持任务完成通知回灌

## 数据目录

默认情况下，项目运行数据会写到当前工作目录下：

```text
.claude-code-thy/
```

其中通常包括：

- `sessions/`
- `tasks/`
- `file-history/`

也可以通过环境变量指定根目录：

```bash
CLAUDE_CODE_THY_HOME=/your/path
```

## 工作区设置

工作区设置文件默认路径：

```text
.claude-code-thy/settings.json
```

也支持：

```text
.claude-code-thy/settings.local.json
```

以及环境变量覆盖：

```bash
CLAUDE_CODE_THY_SETTINGS=/your/settings.json
```

当前设置文件已经支持：

- permissions
- read_ignore_patterns
- sandbox
- tasks
- file_history
- skills
- lsp
- mcp

更详细说明可查看：

- [docs/infrastructure.md](./docs/infrastructure.md)

## 开发与验证

如果当前环境没有安装测试依赖，可以先安装：

```bash
pip install pytest
```

运行测试：

```bash
PYTHONPATH=src python -m pytest
```

如果只是做快速验证，也可以先跑编译检查：

```bash
python -m compileall src/claude_code_thy tests
```

## 说明

- 当前默认推荐 conda 环境
- 不再以项目内 `.venv` 作为默认方案
- 如果你使用的是安装包模式，源码改完后记得重新执行：

```bash
pip install --no-cache-dir --force-reinstall .
```
