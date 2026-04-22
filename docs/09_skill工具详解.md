# skill 工具详解

这篇文档专门分析当前项目里的 `skill` 工具，以及它背后的整个 skills 子系统。

这里说的 “skill 工具”，不是泛指“项目支持 skills”，而是项目里那个真正暴露给模型和 slash 命令系统的内置工具：

- `src/claude_code_thy/tools/SkillTool/SkillTool.py`

但如果只看这个工具本体，其实是不够的。因为 `skill` 工具只是执行入口，真正让它成立的，是下面这整套模块：

- `skills/types.py`
- `skills/frontmatter.py`
- `skills/loader.py`
- `skills/manager.py`
- `skills/registry.py`
- `skills/mcp_bridge.py`

所以可以先给一个总定义：

当前项目里的 `skill` 工具，本质上是：

- 一个统一命令模型的执行器
- 一个把本地 skill、MCP skill、MCP prompt 接到同一套运行时里的桥梁
- 一个把 inline skill 和 fork skill 分流执行的入口

## 1. skill 工具在系统中的定位

当前项目的 skills 不是靠“读一个 markdown 然后直接拼字符串”这么简单。

它已经被拆成了几层：

### 1.1 `SkillManager`

负责：

- 发现 skill 目录
- 根据路径触发规则补充 skill 目录
- 记录当前会话中“已经发现过哪些 skill”

但它本身还不是“真正的 skill 运行系统”，更像一个目录发现器。

### 1.2 `SkillLoader`

负责：

- 读取 `SKILL.md`
- 解析 frontmatter
- 生成统一的 `PromptCommandSpec`

### 1.3 `PromptCommandRegistry`

负责：

- 合并本地 skill、MCP skill、MCP prompt
- 区分“用户可调用”和“模型可调用”
- 渲染 prompt
- 处理参数替换

### 1.4 `SkillTool`

负责：

- 接收 `{"skill": "...", "args": "..."}` 这种执行请求
- 去 registry 找命令对象
- 渲染 prompt
- 根据 execution_context 决定是 inline 还是 fork

所以从职责看：

- `SkillManager` 发现目录
- `SkillLoader` 解析 skill 文件
- `PromptCommandRegistry` 管理统一命令对象
- `SkillTool` 真正执行命令对象

## 2. 当前 skill 工具如何注册进系统

`skill` 是默认内置工具之一，注册位置在：

- `src/claude_code_thy/tools/builtin.py`

也就是说它和下面这些工具是同级的：

- `agent`
- `bash`
- `read`
- `edit`
- `write`
- `glob`
- `grep`

这意味着两件事：

- 用户可以直接通过 slash 命令显式使用它
- 主链模型也能看到它的工具 schema

所以 `skill` 工具不是“只给 slash 用的特殊分支”，而是项目真实暴露给运行时的一等工具。

## 3. skill 工具本体长什么样

`SkillTool` 的几个固定字段如下：

- `name = "skill"`
- `description = "执行本地 skill 或 MCP skill。inline skill 会把技能提示注入当前上下文，fork skill 会在子 agent 中执行。"`
- `usage = "skill <skill_name> [args]"`

它的输入 schema 很简单：

- `skill`
- `args`

其中：

- `skill` 必填
- `args` 可选

也就是说，从模型视角看，`skill` 工具就是：

“给我一个技能名字，再给我一段参数文本”

然后剩下的事情都交给项目内部解析。

## 4. slash 命令和 skill 工具是什么关系

当前系统里，skill 有两种主要入口：

### 4.1 直接 slash 命令

例如：

```bash
/review auth-flow
```

这时不会先走 `skill` 工具，而是：

- `CommandProcessor` 识别 `/review`
- 去 `PromptCommandRegistry` 找同名命令对象
- 如果是 inline，就直接把渲染后的 prompt 提交给主链模型
- 如果是 fork，就转而调用 `skill` 工具

也就是说：

- 用户看到的是 `/review`
- 内部底层执行时，fork skill 最终还是会落到 `skill` 工具

### 4.2 显式调用 `skill` 工具

例如：

```bash
/skill review auth-flow
```

这时是直接执行 `SkillTool.execute_input(...)`

所以：

- slash 技能名是“更自然的入口”
- `skill` 工具是“统一执行入口”

## 5. 统一命令模型是什么

当前项目里，本地 skill、MCP skill、MCP prompt，最后都会被统一成：

- `PromptCommandSpec`

这是整个 skill 系统最关键的统一数据结构。

当前它能表达的信息包括：

- `name`
- `description`
- `kind`
- `loaded_from`
- `source`
- `content`
- `arg_names`
- `allowed_tools`
- `when_to_use`
- `version`
- `model`
- `disable_model_invocation`
- `user_invocable`
- `execution_context`
- `agent`
- `effort`
- `paths`
- `display_name`
- `skill_root`
- `server_name`
- `original_name`
- `resource_uri`
- `metadata`

这说明当前项目不是把 skill 当“纯文本模板”，而是当成一个完整的“可执行 prompt 命令对象”。

## 6. `SKILL.md` 是怎么被解析的

本地 skill 文件的标准入口是：

- `SKILL.md`

`SkillLoader` 会做这些事：

### 6.1 读取文件

如果目录下没有 `SKILL.md`，就直接忽略。

### 6.2 解析 frontmatter

如果文件以：

```markdown
---
...
---
```

开头，就会被当作 frontmatter 文档解析。

### 6.3 支持的核心字段

当前至少支持这些字段：

- `description`
- `when-to-use` / `when_to_use`
- `arguments`
- `allowed-tools`
- `disable-model-invocation`
- `user-invocable`
- `context`
- `agent`
- `effort`
- `paths`
- `name`
- `version`
- `model`

### 6.4 正文内容

frontmatter 之后剩下的正文，会被当成这个 skill 的 prompt 模板内容。

如果 `description` 没写，就会从正文里自动提取一句最像摘要的话。

## 7. frontmatter 解析的几个实现特点

当前 frontmatter 不是靠第三方 yaml 库做的，而是项目自己写了一个轻量解析器。

它支持的能力包括：

- 简单 `key: value`
- 缩进列表
- 布尔值
- JSON 数组风格字符串
- 逗号分隔字符串列表

优点是：

- 依赖少
- 行为可控

代价是：

- 不是完整 YAML
- 复杂嵌套结构支持有限

所以当前 skill frontmatter 适合：

- 简洁配置
- 不适合复杂层级元数据

## 8. 本地 skill 是如何被发现的

当前项目默认只认：

- `.claude-code-thy/skills`

旧的：

- `.claude/skills`

已经不再是默认路径。

除此之外，还支持：

- `settings.skills.search_roots`
- `settings.skills.triggers`

### 8.1 `search_roots`

可以额外指定技能搜索根目录。

### 8.2 `triggers`

可以按路径模式触发 skill 目录。

例如：

- 某类文件被访问后
- 自动把某个 skill 目录加入当前会话可见范围

### 8.3 邻近发现

如果某个文件路径的父目录链上存在 `SKILL.md`，也会被发现。

所以本地 skill 的发现策略是：

- 默认根目录
- 配置的根目录
- 路径触发目录
- 当前访问路径附近的 `SKILL.md`

## 9. 当前会话里的 skill 为什么会变化

这是 skills 系统的一个重要特点。

当前会话里可见的 skill，不一定是固定死的。

原因是：

- 工具在访问文件时，会把 touched paths 写入会话状态
- `SkillManager` 会根据这些路径补充 discovered skill dirs
- `PromptCommandRegistry` 再根据这些状态决定当前会话应显示哪些命令

也就是说：

- 你读了某些文件之后
- 当前可用 skill 列表可能会变化

这是当前项目 skill 系统相对“静态模板系统”的一个增强点。

## 10. `PromptCommandRegistry` 在做什么

这个模块是整个 skill 系统的中枢。

它主要负责：

### 10.1 聚合三类命令

- 本地 skill
- MCP prompt
- MCP skill

### 10.2 区分两类可见性

- `list_user_commands(...)`
- `list_model_commands(...)`

也就是说：

- 有些命令允许用户 slash 调
- 有些命令允许模型自动调
- 这两者不是完全一样

### 10.3 渲染 prompt

给定：

- 一个 `PromptCommandSpec`
- 一段 `raw_args`

它会输出最终 prompt 文本。

### 10.4 参数替换

支持：

- `${name}`
- `{{name}}`
- `${args}`
- `{{args}}`

### 10.5 skill 目录变量

如果是本地 skill，还会自动注入：

- `Base directory for this skill: ...`
- `${CLAUDE_SESSION_ID}`
- `${CLAUDE_SKILL_DIR}`

所以 skill prompt 渲染，不是简单拼接，而是带上下文注入的。

## 11. `user_invocable` 和 `disable_model_invocation` 的区别

这是 skills 系统里非常容易混淆的两个字段。

### 11.1 `user_invocable`

表示：

- 用户能不能通过 slash 命令显式调用

如果是：

```yaml
user-invocable: false
```

那它不会出现在用户 slash 命令列表里。

### 11.2 `disable_model_invocation`

表示：

- 模型能不能把这个命令当作自动可调用能力

所以这两个不是一回事：

- 一个控制用户入口
- 一个控制模型入口

## 12. `execution_context` 的两种模式

当前 skill 最重要的运行模式差异，就是：

- `inline`
- `fork`

### 12.1 inline

这是默认模式。

行为是：

- skill 渲染出一段 prompt
- 直接注入当前主链上下文

也就是说：

- skill 不会新开子 agent
- 它只是生成 prompt 文本给当前主链继续使用

`SkillTool` 在这个模式下返回的是：

- `ok=True`
- `ui_kind="skill"`
- `tool_result_content = prompt`

所以从主链角度看：

- inline skill 更像“上下文增强器”

### 12.2 fork

如果：

```yaml
context: fork
```

那么 `SkillTool` 不会把 prompt 直接注入当前主链，而是：

- 先把 skill prompt 渲染出来
- 再调用 `AgentTool`
- 在子 agent 中执行

也就是说：

- fork skill 的底层执行器就是 `agent` 工具

## 13. fork skill 会如何包装 prompt

fork skill 不是简单把正文原样丢给子 agent。

当前实现还会附加一些辅助信息：

### 13.1 `allowed_tools`

如果 frontmatter 里声明了：

```yaml
allowed-tools:
  - read
  - grep
```

会被附加成：

```text
Recommended tools for this skill:
- read
- grep
```

### 13.2 `effort`

如果声明了：

```yaml
effort: medium
```

也会被附加成：

```text
Recommended effort: medium
```

但这里要注意：

- 这些目前只是 prompt 层软提示
- 不是硬限制

也就是说当前 fork skill 并没有真正把子 agent 的工具能力收窄到 `allowed_tools`

## 14. 当前 skill 工具真正返回给主链的是什么

这取决于是 inline 还是 fork。

### 14.1 inline skill

返回的是一个 `ToolResult`，里面最重要的是：

- `summary = Skill inline: <command.name>`
- `output = 渲染后的 prompt`
- `structured_data.prompt = 渲染后的 prompt`
- `tool_result_content = prompt`

换句话说：

- 它返回的不是“执行结果”
- 而是一段“要继续交给主链模型消费的 prompt”

### 14.2 fork skill

返回的是 `AgentTool` 的结果。

所以它的结果形态会像 agent：

- 完成结果
- 后台任务结果
- auto-backgrounded 结果

## 15. MCP skill 和本地 skill 是怎么统一起来的

当前项目一个很好的点是：

- MCP skill 不另起一套格式
- 而是尽量复用本地 skill 的 frontmatter 解析规则

流程大致是：

### 15.1 MCP prompt

MCP prompt 会被转换成：

- `kind = "mcp_prompt"`

这类命令：

- 允许用户调
- 默认不允许模型自动调用

### 15.2 MCP skill

MCP 资源里如果看起来像：

- `skill://...`
- `/skill.md`
- 或资源名就是 `skill.md`

就会被视为 skill 资源。

随后会：

- 读取资源内容
- 解析 frontmatter
- 生成一个 `PromptCommandSpec`
- `kind = "mcp_skill"`

这说明：

- MCP skill 和本地 skill 在统一命令模型里几乎是同构的

## 16. MCP prompt 和 MCP skill 的区别

这是当前 skills 系统里一个非常重要的边界。

### 16.1 MCP prompt

特点：

- 来源是 MCP prompt 定义
- `kind = mcp_prompt`
- `loaded_from = mcp_prompt`
- `disable_model_invocation = True`

也就是说：

- 用户可以 slash 调
- 但模型默认不会把它当自动能力

### 16.2 MCP skill

特点：

- 来源是 MCP resource 中的 skill 文档
- `kind = mcp_skill`
- `loaded_from = mcp`

它会沿用本地 skill 那一套字段，例如：

- `arguments`
- `allowed-tools`
- `context`
- `effort`
- `paths`

所以：

- MCP prompt 更像远端 prompt API
- MCP skill 更像远端 skill 文档

## 17. 当前项目中 `skill` 工具给模型暴露的样子

从模型视角看，`skill` 就是一个普通工具：

- `name = "skill"`
- `description = "... 可用 skills: ..."`
- `input_schema = {"skill": ..., "args": ...}`

也就是说模型不会直接看到某个 skill 的 markdown 内容，而是：

- 看到一个统一的 `skill` 工具
- 再看到它 description 里列出的可用 skills

然后模型可以调用：

```json
{
  "skill": "review",
  "args": "auth-flow"
}
```

这和 slash 命令系统的设计是一致的。

## 18. 当前测试覆盖了什么

现有测试已经覆盖了 skills 里一些关键行为：

### 18.1 inline skill slash 命令会展开成 prompt

测试了：

- `/review auth-flow`
- 最终会提交渲染后的 prompt

### 18.2 旧 `.claude/skills` 路径不会默认加载

说明项目已经明确收敛到：

- `.claude-code-thy/skills`

### 18.3 MCP prompt 会通过统一 registry 工作

说明当前 MCP prompt 已经不再是命令层 special-case。

### 18.4 `skill` 工具可以执行来自 registry 的 MCP skill

说明：

- `SkillTool` 对本地 skill 和 MCP skill 的执行方式已经统一

## 19. 当前 skill 系统的优点

### 19.1 分层比早期方案清晰很多

现在不是把所有逻辑塞进一个 `SkillManager` 里，而是已经分成：

- 发现
- 解析
- 注册
- 执行

### 19.2 本地 skill 与 MCP skill 用同一命令模型

这一点非常重要。

它意味着：

- 后续扩展不会再分裂成两套体系

### 19.3 `PromptCommandSpec` 表达力足够强

当前字段已经足够覆盖：

- 用户入口
- 模型入口
- 参数化模板
- inline/fork
- MCP 来源

### 19.4 fork skill 复用了 agent 工具

这让当前设计更统一，不会再平行维护第二套“子任务执行系统”。

## 20. 当前 skill 系统的不足

### 20.1 `allowed_tools` 现在只是软提示

这是目前最明显的一个差距。

它现在只会在 fork skill 时被拼进 prompt：

- “Recommended tools for this skill: ...”

但没有硬约束。

### 20.2 `agent`、`effort` 等字段还没有完全落地

比如：

- `effort` 现在只是作为文本提示
- `agent` 字段也没有形成完整的 agent 选择策略

### 20.3 本地 skill 的执行结果仍偏“prompt 注入”

inline skill 当前更像：

- prompt 模板生成器

而不是“带结构化执行计划的技能”

### 20.4 还没有真正的 hooks / shell frontmatter 执行能力

当前系统虽然已经比以前清晰很多，但还没做：

- hooks
- shell frontmatter 执行
- 严格能力边界

## 21. 当前 skill 工具的一句话总结

当前项目里的 `skill` 工具，可以概括成：

“统一命令模型的执行入口，用一套 PromptCommandSpec 同时承载本地 skill、MCP skill 和 MCP prompt，并按 inline 或 fork 两种模式执行。”

如果只看工具本体，它其实很轻。

真正有价值的是它背后的这套体系：

- 统一命令对象
- frontmatter 解析
- 本地目录发现
- registry 聚合
- fork 复用 agent
- MCP skill 桥接

所以从架构地位上说，`skill` 工具已经不只是一个小工具，而是当前项目里：

- 命令模型统一化
- skills 子系统
- MCP prompt / skill 融合

这三件事的共同落点。
