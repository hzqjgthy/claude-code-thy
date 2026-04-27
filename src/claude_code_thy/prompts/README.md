# prompts 模块说明

## 1. 模块定位

`claude_code_thy.prompts` 负责把项目中的提示词资源、运行时上下文和 provider 注入规则统一收口，生成主链请求真正会发给模型的 prompt。

这个模块解决的是下面几类问题：

- 提示词正文不再写死在 Python 脚本中
- system 规则、动态上下文、provider 差异化提示统一管理
- skills、MCP、`CLAUDE.md`、项目上下文等动态信息在一处收集
- Anthropic-compatible 和 OpenAI Responses-compatible 两条 provider 走统一上层 prompt 构建逻辑
- 可以通过 CLI / Web API 直接查看“最终实际注入的 prompt”

一句话概括：

> 这个模块是 `claude-code-thy` 的提示词运行时，不是单纯的 markdown 目录。

---

## 2. 当前目录结构

```text
prompts/
├── __init__.py
├── README.md
├── frontmatter.py
├── loader.py
├── registry.py
├── context.py
├── builder.py
├── renderers.py
├── bundle.py
├── types.py
├── sections/
│   ├── 00_identity.md
│   ├── 10_workflow.md
│   ├── 20_tool_usage.md
│   ├── 25_skill_usage.md
│   ├── 30_permissions_and_safety.md
│   ├── 40_output_style.md
│   └── 50_verification_and_reporting.md
├── templates/
│   ├── 10_environment.md
│   ├── 20_mcp_instructions.md
│   ├── 30_user_context.md
│   └── 40_project_context.md
└── providers/
    ├── anthropic.md
    └── openai_responses.md
```

同时支持工作区覆盖目录：

```text
.claude-code-thy/prompts/
├── overrides/
├── append/
└── disabled/
```

---

## 3. 模块职责拆分

### 3.1 `frontmatter.py`

负责解析 prompt markdown 文件顶部的简化 frontmatter。

当前支持：

- `id`
- `order`
- `target`
- `cacheable`
- `provider`
- `required-variable` / `required-variables`

这个文件是 prompts 自己的 frontmatter 解析器，和 `skills` 模块解耦，避免导入环。

### 3.2 `loader.py`

负责从三类来源加载 prompt 资源：

- 包内置资源
- 工作区 `overrides/`
- 工作区 `append/`

并同时处理：

- `disabled/` 禁用规则
- provider 过滤
- mtime 缓存
- frontmatter 解析

核心类：

- `PromptFileLoader`

### 3.3 `registry.py`

负责把资源按用途分组暴露给上层。

核心类：

- `PromptResourceRegistry`

当前提供三组资源：

- `list_sections()`
- `list_templates()`
- `list_provider_sections(provider_name)`

### 3.4 `context.py`

负责收集动态上下文。

当前收集内容包括：

- 环境信息：workspace、cwd、provider、model、shell、OS、日期
- `CLAUDE.md` 链路上的用户上下文
- `PROJECT_CONTEXT.md` 和 git snapshot 组成的项目上下文
- 已连接 MCP server 的 `instructions`
- 当前会话下可用 skill 名称列表，仅作为 debug meta

核心类：

- `PromptContextBuilder`

### 3.5 `builder.py`

负责把：

- sections
- templates
- provider sections
- 动态变量

组装成 `PromptBundle`。

它做的工作包括：

- 资源合并
- `required_variables` 过滤
- 简单模板变量替换
- 生成 `RenderedPromptSection`

核心类：

- `PromptBuilder`

### 3.6 `renderers.py`

负责把 `PromptBundle` 收敛成 provider 可直接消费的两段文本：

- `system_text`
- `user_context_text`

核心函数：

- `render_prompt_bundle()`

### 3.7 `bundle.py`

对外暴露统一入口，供服务层和调试入口复用。

核心类：

- `PromptRuntime`

外部通常只需要用这两个方法：

- `build_bundle(...)`
- `build_rendered_prompt(...)`

### 3.8 `types.py`

定义整个模块的核心数据结构：

- `PromptResource`
- `RenderedPromptSection`
- `PromptContextData`
- `PromptBundle`
- `RenderedPrompt`

---

## 4. 运行链路

当前主链请求的大致链路如下：

```text
QueryEngine
  -> ToolRuntime.services_for(session)
  -> ToolServices.prompt_runtime.build_rendered_prompt(...)
  -> Provider.complete(...) / Provider.stream_complete(...)
  -> provider 把 system_text / user_context_text 注入请求体
```

关键接入点：

- [query_engine.py](./../query_engine.py)
- [services.py](./../services.py)
- [providers/anthropic.py](./../providers/anthropic.py)
- [providers/openai_responses.py](./../providers/openai_responses.py)

---

## 5. prompt 资源如何分类

### 5.1 `sections/`

放稳定规则。

例如：

- 身份定义
- 工作方式
- 工具使用规则
- skill 使用规则
- 安全与权限规则
- 输出风格
- 验证与汇报

这些资源主要进入 `system_text`。

### 5.2 `templates/`

放动态上下文模板。

例如：

- 当前环境
- MCP server instructions
- 用户上下文
- 项目上下文

其中：

- `10_environment.md`
- `20_mcp_instructions.md`

当前进入 `system_text`

- `30_user_context.md`
- `40_project_context.md`

当前进入 `user_context_text`

### 5.3 `providers/`

放 provider 少量差异化补充规则。

当前分别有：

- `anthropic.md`
- `openai_responses.md`

---

## 6. 动态内容和自动发现的边界

这里很容易误解，尤其是 skills 和上下文相关内容。

### 6.1 skills 不是靠模板维护的

本地 skills 的发现仍然是自动的，来自：

- `.claude-code-thy/skills/**/SKILL.md`
- `settings.skills.search_roots`
- MCP runtime 暴露出的 MCP skills

模型感知当前可用 skills 的主要通道是：

- `skill` 工具自身的动态 description

也就是说：

- **skill 列表不是通过 `templates/*.md` 写进去的**
- **`25_skill_usage.md` 只负责 skill 的使用规则，不负责 skill 名称列表**

### 6.2 工具 schema 不是靠模板维护的

本地工具和 MCP 工具的：

- `name`
- `description`
- `input_schema`

都继续通过 provider 请求体中的结构化 `tools` 字段传给模型。

所以：

- **不要在模板里复述工具 schema**
- `20_tool_usage.md` 只讲“怎么用工具”，不讲“每个工具长什么样”

### 6.3 上下文模板不是会话存储

`30_user_context.md` 和 `40_project_context.md` 是模板，不是数据存储文件。

它们只定义“这段动态上下文在 prompt 里怎么呈现”。

真正动态的数据来自运行时：

- `CLAUDE.md`
- `PROJECT_CONTEXT.md`
- git snapshot

真正的会话历史仍然存在：

- `.claude-code-thy/sessions/*.json`

不会写回 `templates/*.md`。

---

## 7. provider 注入方式

### 7.1 Anthropic-compatible

当前注入方式：

- `system_text` -> 请求体 `system`
- `user_context_text` -> 追加到消息头部，作为一条 `role=user` 的 meta 文本消息

实现文件：

- [anthropic.py](./../providers/anthropic.py)

### 7.2 OpenAI Responses-compatible

当前注入方式：

- `system_text` -> 请求体 `instructions`
- `user_context_text` -> 追加到 `input` 最前面的一条 user message item

实现文件：

- [openai_responses.py](./../providers/openai_responses.py)

额外说明：

- OpenAI Responses 这条链路还会把 prompt 指纹写入 runtime state
- 这样在使用 `previous_response_id` 时，只有 prompt 没变才会复用

---

## 8. 工作区覆盖规则

工作区可以通过 `.claude-code-thy/prompts/` 对内置资源做三类控制。

### 8.1 `overrides/`

按相对路径覆盖内置资源。

例如：

```text
.claude-code-thy/prompts/overrides/sections/20_tool_usage.md
```

会覆盖内置的：

```text
src/claude_code_thy/prompts/sections/20_tool_usage.md
```

### 8.2 `append/`

附加新的 prompt 资源，不覆盖内置内容。

### 8.3 `disabled/`

通过文件名、资源 id、相对路径或文件内容中的 key 禁用某个资源。

例如禁用：

- `25_skill_usage.md`
- `skill_usage`

---

## 9. 调试入口

### 9.1 CLI

当前已经支持：

```bash
claude-code-thy prompt dump --session <session_id>
claude-code-thy prompt dump --session <session_id> --provider anthropic-compatible
claude-code-thy prompt dump --session <session_id> --provider openai-responses-compatible
```

该命令会输出：

- 当前 session / provider / model / workspace
- 启用的 sections 列表
- `system_text`
- `user_context_text`
- context values
- debug meta

实现文件：

- [cli.py](./../cli.py)

### 9.2 Web API

当前已经支持：

- `GET /api/runtime/prompt-preview`
- `GET /api/runtime/prompt-sections`

实现文件：

- [server/api/runtime.py](./../server/api/runtime.py)
- [server/presenters.py](./../server/presenters.py)
- [server/schemas.py](./../server/schemas.py)

---

## 10. package data

这些 markdown 文件需要随包一起发布和安装。

当前通过 [pyproject.toml](./../../../../pyproject.toml) 的 `tool.setuptools.package-data` 声明：

- `prompts/sections/*.md`
- `prompts/templates/*.md`
- `prompts/providers/*.md`

如果后面新增子目录或新增文件类型，需要同步更新这里。

---

## 11. 当前测试覆盖

这次提示词工程相关测试主要覆盖了四类能力。

### 11.1 prompt 资源加载与覆盖

测试文件：

- [tests/test_prompts.py](./../../../tests/test_prompts.py)

覆盖点：

- 能正确渲染 `CLAUDE.md` / `PROJECT_CONTEXT.md`
- `skill_usage` section 会出现
- `skills_summary` 这类旧设计不会出现
- `overrides/` 覆盖生效
- `disabled/` 禁用生效

### 11.2 provider 注入

测试文件：

- [tests/test_anthropic_provider.py](./../../../tests/test_anthropic_provider.py)
- [tests/test_openai_responses_provider.py](./../../../tests/test_openai_responses_provider.py)

覆盖点：

- Anthropic payload 正确注入 `system`
- Anthropic payload 正确注入 `user_context_text`
- OpenAI Responses payload 正确注入 `instructions`
- OpenAI Responses payload 正确注入首条 user meta context
- `previous_response_id` 和 prompt 指纹协同工作

### 11.3 QueryEngine 主链接入

测试文件：

- [tests/test_query_engine.py](./../../../tests/test_query_engine.py)

覆盖点：

- 流式和非流式主链都能正常工作
- prompt 接入后不会破坏工具循环
- prompt 接入后不会破坏动态 MCP 工具预热
- 普通文本提到 MCP 工具名时，不会回到已删除的本地硬匹配逻辑

### 11.4 Web 调试入口

测试文件：

- [tests/test_server_runtime_prompt_preview.py](./../../../tests/test_server_runtime_prompt_preview.py)

覆盖点：

- `/api/runtime/prompt-preview` 能返回完整渲染结果
- section 列表、`system_text`、`user_context_text` 都能正常查看

---

## 12. 建议的测试命令

如果你要单测这个模块本身，优先跑：

```bash
/Users/thy/miniforge3/envs/claude-code-thy/bin/python -m pytest -q \
  tests/test_prompts.py \
  tests/test_anthropic_provider.py \
  tests/test_openai_responses_provider.py \
  tests/test_server_runtime_prompt_preview.py \
  tests/test_query_engine.py \
  tests/test_server_chat.py \
  tests/test_server_presenters.py \
  tests/test_skills.py \
  tests/test_config.py
```

这组测试覆盖当前 prompt 系统的主要链路。

如果只想看 prompt 构建本身，最小命令是：

```bash
/Users/thy/miniforge3/envs/claude-code-thy/bin/python -m pytest -q tests/test_prompts.py
```

如果只想人工查看最终注入结果，可以直接用：

```bash
claude-code-thy prompt dump --session <session_id>
```

或者：

```bash
curl "http://127.0.0.1:8002/api/runtime/prompt-preview?session_id=<session_id>"
```

---

## 13. 后续扩展建议

如果继续扩展这个模块，建议优先考虑：

- 增加 prompt token 估算
- 增加 section 级缓存策略
- 增加 prompt 变更审计和更细的 debug meta
- 为工作区 `append/` 和 `overrides/` 提供更明确的冲突提示
- 在 Web 前端增加 prompt preview 面板

不建议优先做的方向：

- 引入复杂模板引擎
- 把工具 schema 再转成自然语言复述
- 把 skill 列表塞进单独模板维护

---

## 14. 快速结论

如果只记住这几个点就够了：

- `sections/` 放规则
- `templates/` 放动态上下文模板
- `providers/` 放 provider 少量差异
- skills 列表自动发现，不靠模板维护
- 工具 schema 结构化传输，不靠模板维护
- `PromptRuntime` 是外部统一入口
- `prompt dump` 和 `/api/runtime/prompt-preview` 是调试主入口
