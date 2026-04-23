# agent 工具详解

这篇文档专门分析当前项目里的 `agent` 工具实现。

这里的“agent 工具”不是一个抽象概念，而是项目中的内置工具 `agent`，对应源码：

- `src/claude_code_thy/tools/AgentTool/AgentTool.py`

它的作用是：

- 启动一个本地子 agent 来处理任务
- 可以前台等待结果
- 也可以转成后台任务

## 1. agent 工具在系统里的定位

当前项目里的 `agent` 不是单独的 agent runtime，也不是内存里的“子会话对象”。

它本质上是：

- 一个内置工具
- 一个后台任务启动器
- 一个本地 CLI 子进程调度器

也就是说，它并不是“在当前 Python 进程里再创建一个 agent 对象继续跑”，而是：

- 由当前进程启动一个新的本地命令行进程
- 让那个新进程再跑一次 `claude-code-thy`
- 用子进程的输出结果来代表“子 agent 的执行结果”

所以，从实现本质看，当前 `agent` 工具更像：

“把子任务执行能力包装成一个工具”

## 2. 它是怎么注册进系统的

`agent` 是默认内置工具之一，注册位置在：

- `src/claude_code_thy/tools/builtin.py`

当前默认内置工具列表里包含：

- `AgentTool()`
- `BashTool()`
- `ReadTool()`
- `EditTool()`
- `WriteTool()`
- `GlobTool()`
- `GrepTool()`
- `SkillTool()`
- `ListMcpResourcesTool()`
- `ReadMcpResourceTool()`

也就是说：

- 用户 slash 命令能调它
- 主链模型也能看到它
- 子 agent 启动后也能再次看到它

## 3. 它有哪些入口

当前项目里和 agent 相关的入口不止一个。

### 3.1 `/agent`

这是最直接的入口。

它本质上是：

- 通过 slash 命令直接调用 `agent` 工具

特点：

- 默认前台等待
- 支持 `--background`
- 支持 `--model`
- 支持 `--description`
- 支持 `--wait-timeout-ms`

### 3.2 `/agent-run`

这是一个快捷命令。

它不是一个单独实现的新系统，而是：

- 内部再调用一次 `agent` 工具
- 并强制 `run_in_background = True`

也就是说：

- `/agent-run` 永远是后台运行

### 3.3 `/agent-wait`

这是用来等待已有 agent 任务完成的命令。

它不会新建 agent，只会：

- 根据 `task_id`
- 到后台任务系统里轮询状态
- 读取输出文件

## 4. agent 工具的输入结构

`agent` 工具当前暴露给模型的 schema 大致是：

- `prompt`
- `description`
- `model`
- `run_in_background`
- `wait_timeout_ms`
- `name`

其中：

- `prompt` 是唯一必填字段
- `run_in_background` 控制是否直接后台运行
- `wait_timeout_ms` 控制前台最多等多久
- `model` 可以覆盖当前会话模型

这里有一个实现现状要注意：

- `name` 虽然定义在 schema 里
- 但当前实际执行逻辑里并没有真正用到它

所以目前看，它更像是“未来预留字段”。

## 5. `/agent` 的参数解析规则

`/agent` 的解析规则不是纯粹的 argparse 全吞，而是人为拆成了两段：

- 前半段：选项区
- 后半段：真正的 prompt

当前支持两种典型形式：

### 5.1 没有选项

```bash
/agent -- 请总结 README.md
```

这里的 `--` 表示：

- 后面整段都当 prompt

### 5.2 有选项

```bash
/agent --background --model glm-5 -- 请总结 README.md
```

这里的含义是：

- `--background --model glm-5` 是选项
- 最后 `--` 后面的是 prompt

这套解析方式的好处是：

- prompt 里可以比较自由地写中文和空格

但也带来一个小问题：

- 文档用法和真正解析细节之间并不完全直观
- 第一次看源码的人容易误以为它是普通 shell 风格参数解析

## 6. agent 工具真正执行时做了什么

`AgentTool.execute_input(...)` 的主流程很清楚：

### 第一步：读取输入

它会先拿到：

- `prompt`
- `description`
- `model`
- `run_in_background`
- `wait_timeout_ms`

然后会做两件默认补全：

- `description` 为空时，自动生成 `Agent: <prompt前48字符>`
- `model` 为空时，继承当前 session 的 `model`

### 第二步：启动本地子 agent 任务

然后会调用：

- `context.services.task_manager.start_local_agent(...)`

注意，这一步非常关键。

这意味着：

- `agent` 工具自己并不直接调模型
- 它只是把任务交给后台任务管理器

### 第三步：按前台或后台分叉

如果：

- `run_in_background = True`

那就立即返回一个后台任务结果。

如果：

- `run_in_background = False`

那就进入一个前台轮询循环：

- 每隔一小段时间检查任务状态
- 读取最近输出预览
- 如有新输出，就发 progress event
- 如果任务结束，返回最终结果
- 如果超时，则自动转成后台模式

## 7. 它到底是怎么启动“子 agent”的

这是当前实现里最核心的一层。

`BackgroundTaskManager.start_local_agent(...)` 里并不是创建 Python 对象继续跑，而是：

- 构造一个新的命令行启动参数
- 再拉起一个新的本地进程

最终启动形式大致是：

```bash
claude-code-thy --print <prompt>
```

如果指定了模型，还会加上：

```bash
--model <model>
```

所以本质上，子 agent 是：

- 再起一个新的 `claude-code-thy` 进程
- 这个进程走无头模式 `--print`
- 输出写到后台任务文件中

所以当前项目的“子 agent”并不是轻量的对象级复用，而是：

- 进程级复用 CLI

## 8. agent launcher 的解析优先级

后台任务系统为了决定“子 agent 到底怎么启动”，有一套 launcher 解析逻辑。

优先级大致是：

### 8.1 环境变量优先

如果设置了：

```bash
CLAUDE_CODE_THY_AGENT_LAUNCHER
```

就优先使用它。

### 8.2 当前 argv0

如果当前主程序本身就是从 `claude-code-thy` 命令启动的，就优先复用这个命令。

### 8.3 系统 `which`

如果环境里能找到：

```bash
claude-code-thy
```

也会优先用它。

### 8.4 最后兜底

如果上面都不成立，就退回：

```bash
python -m claude_code_thy
```

这套策略的优点是：

- 尽量保证子 agent 和主进程用同一套入口

但它也意味着：

- 当前环境是否装好 editable package
- 当前解释器是不是对的
- 当前命令入口能不能找到

这些问题都会直接影响 `agent` 工具是否能正常工作。

## 9. 前台模式和后台模式分别返回什么

### 9.1 前台模式

如果子 agent 在等待时间内完成，返回的是一个“完成结果”。

典型特征：

- `ok = True` 或 `False`
- `summary = Agent completed: ...`
- `output` 里有子 agent 输出
- `structured_data` 里带：
  - `task_id`
  - `status`
  - `prompt`
  - `description`
  - `output_path`
  - `output_preview`

### 9.2 后台模式

如果一开始就是后台，或者前台超时自动转后台，返回的是一个“任务已运行”的结果。

典型特征：

- `summary = Agent running in background`
  或
- `summary = Agent auto-backgrounded`

同时会带：

- `task_id`
- `output_path`
- `status = running`

这让主链后续可以：

- 用 `/agent-wait`
- 用 `/task-output`
- 或等自动任务通知

来继续追踪结果。

## 10. agent 任务在后台任务系统里是什么样的

后台任务系统不是专门为 agent 单独写的，而是通用的。

agent 只是其中一种任务类型。

它的几个关键字段通常是：

- `task_type = local_agent`
- `task_kind = agent`
- `command = agent-run: <prompt>`

同时会落两类文件：

### 10.1 状态文件

例如：

- `<task_id>.json`

里面记录：

- 状态
- return code
- output_path
- metadata

### 10.2 输出文件

例如：

- `<task_id>.output`

里面就是子 agent 的标准输出。

## 11. 任务完成后怎么回到当前会话里

当前项目的主会话不是持续监听子进程 stdout，而是：

- 任务跑在后台
- 输出落盘
- 主会话在合适时机检查任务状态

如果某个任务属于当前会话，并且已经进入终态，那么：

- `ConversationRuntime` 会把任务通知插入消息流

对 `local_agent` 任务，展示标题是：

- `Agent 任务 <task_id> 已完成`
- 或失败、退出、停止等状态

这说明从体验上，项目把 agent 当成了一等任务能力，而不是普通 bash 命令的别名。

## 12. agent 工具和 skill 系统的关系

当前版本里，`agent` 和 `skill` 是两条彼此独立的能力链：

- `agent` 负责启动本地子任务
- `skill` 负责生成并注入技能提示

从架构地位上看，`AgentTool` 已经不只是一个普通工具，而是：

- 本地子任务执行底座

## 13. 主链 agent 能不能调用 agent 工具

可以，而且当前实现里没有专门阻止。

原因很简单：

- `agent` 是默认内置工具
- 主链会把所有当前可见工具 spec 发给模型
- 所以模型可以正常返回 `tool_call(name=\"agent\")`

更进一步说：

- 子 agent 启动后，本质上又是一次新的 `claude-code-thy --print`
- 新进程里也会重新加载同样的内置工具

所以当前系统实际上支持：

- 主链 agent 调 `agent`
- 子 agent 再调 `agent`

也就是：

- 递归 agent 调 agent

当前代码里没有看到这些硬限制：

- 最大 agent 深度
- 每会话最大 agent 派生数
- 主链允许、子链禁止
- 模型层禁止直接调 `agent`

所以从能力边界上说，当前是偏宽松的。

## 14. 当前实现的优点

### 14.1 复用性强

它没有单独做一套复杂 agent runtime，而是：

- 复用现有 CLI
- 复用后台任务系统
- 复用 UI 通知系统

### 14.2 调试路径直观

出了问题时，比较容易排查：

- 任务状态看 json
- 输出看 `.output`
- 启动入口看 launcher

## 15. 当前实现的不足

### 15.1 它不是轻量子 agent

当前实现每次都：

- 再起一个本地 CLI 进程

所以它不是“同进程轻量执行”，而是：

- 新建独立进程执行

### 15.2 没有硬能力隔离

虽然 skill 的 `allowed_tools`、`effort` 会写进 prompt，但现在主要还是软提示，不是硬限制。

也就是说：

- 子 agent 默认能力边界比较宽

### 15.3 schema 和实现不完全一致

比如：

- `name` 字段声明了
- 当前却没实际使用

说明接口设计还没有完全收口。

### 15.4 递归风险没管住

当前主链和子链都能继续调 `agent`，理论上可能出现：

- agent 套 agent
- 任务树膨胀

### 15.5 实时性一般

当前输出预览主要靠：

- 轮询
- 读输出文件尾部

结构化程度和实时性都比较一般。

## 16. 当前测试覆盖了哪些点

现有测试已经覆盖了一些关键行为：

### 16.1 agent 会继承当前会话模型

也就是如果不显式传 `model`，它会优先用当前 session 的模型。

### 16.2 默认 description 会自动生成

默认形式是：

```text
Agent: <prompt前48字符>
```

### 16.3 `/agent-run` 能启动后台任务

### 16.4 `/agents` 能列出 agent 任务

### 16.5 `/agent-wait` 能等待并读取结果

### 16.6 后台任务管理器能真实启动一个 local_agent 任务

## 17. 现有测试还没覆盖到的点

更值得注意的空白点包括：

- 前台超时后自动后台化
- launcher 选择逻辑
- `name` 字段实际用途
- 递归 agent 调 agent 的行为边界
- `allowed_tools` 只是提示、不是硬限制
- progress event 在 UI 中的完整消费链

## 18. 总结

当前项目里的 `agent` 工具，本质上可以概括成一句话：

“一个把本地子任务执行能力包装成工具的 CLI 子进程调度器。”

它的优点是：

- 统一
- 简单
- 复用性强

它的短板也很明显：

- 不是轻量级同进程执行
- 没有硬限制
- agent 递归边界还没收住

但从当前项目整体结构看，它已经是一个很核心的基础能力，因为：

- `/agent`
- `/agent-run`
- `/agent-wait`

实际上都建立在这套能力之上。
