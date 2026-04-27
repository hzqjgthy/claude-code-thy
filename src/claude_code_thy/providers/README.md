# Providers 请求体说明

本文档主要说明两件事：

- 当前项目发给 LLM 的请求体长什么样
- 请求体里每个字段是怎么来的、什么时候出现、代码里由哪段逻辑拼出来

当前只有两种 provider：

- `anthropic-compatible`
- `openai-responses-compatible`

对应源码：

- `src/claude_code_thy/providers/anthropic.py`
- `src/claude_code_thy/providers/openai_responses.py`

## 1. 总体调用链

主链调用模型时，路径是：

1. `QueryEngine` 调用 `provider.complete(session, tools)`
2. provider 根据 `SessionTranscript` 和 `ToolSpec` 列表拼请求体
3. provider 发 HTTP 请求
4. provider 把响应解析成统一的 `ProviderResponse`

这份文档只重点讲第 2 步，也就是“请求体怎么拼”。

## 2. 请求体的上游输入

provider 不是凭空拼 JSON，请求体主要来自两个上游对象。

### `SessionTranscript`

定义在 `src/claude_code_thy/models.py`。

当前和请求体直接相关的字段：

- `model`
  当前会话指定模型；如果为空，provider 会回退到 `AppConfig.model`
- `messages`
  整个会话消息历史；这是请求体里 `messages` 或 `input` 的主要来源
- `runtime_state`
  只有 `openai-responses-compatible` 会用，主要保存 `previous_response_id` 相关状态

### `ToolSpec`

定义在 `src/claude_code_thy/tools/base.py`。

当前和请求体直接相关的字段：

- `name`
- `description`
- `input_schema`

provider 当前不会把 `read_only`、`concurrency_safe`、`search_behavior` 发给模型。

## 2.1 `role` 字段：当前项目实际值 vs 官方支持值

你现在问的重点是“请求里的对话历史中，`role` 官方到底支持哪些值”。

这里要分成两层看：

- 当前项目实际发出去的 `role`
- 官方协议允许的 `role`

### `anthropic-compatible`

#### 当前项目实际会发出的值

- `user`
- `assistant`

原因：

- 本地 `tool` 消息会被改写成 `role: "user"`
- 普通 `user` / `assistant` 消息原样保留

#### Anthropic 官方支持的值

Anthropic Messages API 的 `messages[*].role` 官方只支持：

- `user`
- `assistant`

注意：

- Anthropic 没有把 `system` 放在 `messages[*].role` 里
- 如果你要传 system prompt，Anthropic 是用顶层 `system` 参数，不是 `messages[*].role = "system"`

### `openai-responses-compatible`

这里先说“请求输入 message item”的官方 role，不说响应里 message 对象的扩展 role。

#### 当前项目实际会发出的值

- `user`

原因：

- 用户消息被转成 `role: "user"`
- 助手消息当前也被包装成一个 `role: "user"` 的上下文说明文本
- 工具消息退化成普通文本时，也是 `role: "user"`
- 结构化工具结果走的是 `function_call_output`，那条路径里没有 `role`

#### OpenAI 官方对“请求输入 message item”支持的值

OpenAI Responses API 在请求里的 `input[].role` 官方支持：

- `user`
- `assistant`
- `system`
- `developer`

注意：

- 这是“请求输入 message item”的 role 可选项
- 不是“所有 message 类型对象在所有上下文中的全部 role 枚举”

### 一个容易混淆的点

OpenAI 文档里在更宽泛的 message/item 对象定义中，还能看到一些额外 role，例如：

- `tool`
- `unknown`
- `critic`
- `discriminator`

但这些不是你当前最该关注的“普通请求输入对话历史 message role”集合。

如果你讨论的是“你主动发给 Responses API 的输入消息”，优先看这一组：

- `user`
- `assistant`
- `system`
- `developer`

## 3. `anthropic-compatible` 请求体

源码入口：

- `AnthropicCompatibleProvider._request()`

### 3.1 最终请求 URL

请求 URL 来自：

- `config.anthropic_base_url`

规范化逻辑在：

- `_build_endpoint(base_url)`

规则：

- 如果 base URL 已经以 `/messages` 结尾，直接用
- 如果以 `/v1` 结尾，补成 `/v1/messages`
- 否则补成 `/v1/messages`

例如：

- `https://api.anthropic.com`
  -> `https://api.anthropic.com/v1/messages`
- `https://host.example/v1`
  -> `https://host.example/v1/messages`
- `https://host.example/custom/messages`
  -> 原样使用

### 3.2 请求头

请求头由 `_headers()` 生成。

固定字段：

```json
{
  "content-type": "application/json",
  "anthropic-version": "2023-06-01"
}
```

条件字段：

- 如果 `config.anthropic_api_key` 非空，追加：

```json
{
  "x-api-key": "<ANTHROPIC_API_KEY>"
}
```

- 如果 `config.anthropic_auth_token` 非空，追加：

```json
{
  "Authorization": "Bearer <ANTHROPIC_AUTH_TOKEN>"
}
```

### 3.3 请求体总结构

代码里实际拼出的 payload 结构是：

```json
{
  "model": "<session.model or config.model>",
  "max_tokens": 4096,
  "messages": [
    {
      "role": "user",
      "content": [
        {
          "type": "text",
          "text": "你好"
        }
      ]
    }
  ],
  "tools": [
    {
      "name": "read",
      "description": "读取文件",
      "input_schema": {
        "type": "object",
        "properties": {
          "file_path": {
            "type": "string"
          }
        },
        "required": ["file_path"]
      }
    }
  ]
}
```

注意：

- `tools` 是条件字段，没有工具时不会出现

### 3.4 每个字段的来源和解析

#### `model`

来源：

- `session.model or config.model`

含义：

- 优先使用当前会话模型
- 如果当前会话没有单独指定模型，就用全局配置模型

#### `max_tokens`

来源：

- `config.max_tokens`

含义：

- 单次输出 token 上限

#### `messages`

来源：

- `session.messages`

生成逻辑：

- `[self._message_to_api(message) for message in session.messages]`

也就是说，请求体会带整个会话历史，不做裁剪，不做摘要，不做增量。

#### `tools`

来源：

- 当前轮传进 `complete(session, tools)` 的 `tools` 参数

生成逻辑：

- 每个 `ToolSpec` 转成：
  - `name`
  - `description`
  - `input_schema`

只有当 `tools` 非空时，payload 才会出现 `tools` 字段。

### 3.5 `messages` 里每条消息怎么转

逻辑在：

- `_message_to_api(message)`

#### 普通用户消息

本地消息：

```python
ChatMessage(role="user", text="你好")
```

会转成：

```json
{
  "role": "user",
  "content": [
    {
      "type": "text",
      "text": "你好"
    }
  ]
}
```

如果 `content_blocks` 已经存在，则直接用 `content_blocks`，不会重新包装成单个 text block。

#### 普通助手消息

本地消息：

```python
ChatMessage(role="assistant", text="你好，有什么可以帮你？")
```

会转成：

```json
{
  "role": "assistant",
  "content": [
    {
      "type": "text",
      "text": "你好，有什么可以帮你？"
    }
  ]
}
```

#### 工具消息

本地消息如果 `role == "tool"`，Anthropic provider 会强制转成：

```json
{
  "role": "user",
  "content": ...
}
```

也就是说：

- 在 Anthropic 兼容接口里，工具结果会以“用户侧内容”的形式塞回上下文

如果工具消息有 `content_blocks`，直接用它；否则退化成：

```json
[
  {
    "type": "text",
    "text": "<message.text>"
  }
]
```

### 3.6 `tools` 里每个工具怎么转

一个内部 `ToolSpec`：

```python
ToolSpec(
    name="read",
    description="读取文件",
    input_schema={...}
)
```

会转成：

```json
{
  "name": "read",
  "description": "读取文件",
  "input_schema": { ... }
}
```

字段逐个解释：

- `name`
  模型调用工具时必须回传这个名字
- `description`
  给模型看的工具说明
- `input_schema`
  工具的 JSON Schema，告诉模型参数结构

### 3.7 `anthropic-compatible` 的响应体 / 输出字段

源码解析入口：

- `AnthropicCompatibleProvider._request()`

当前代码对响应 JSON 真正关心的顶层字段只有两个：

- `error`
- `content`

一个典型响应大致会长这样：

```json
{
  "id": "msg_xxx",
  "type": "message",
  "role": "assistant",
  "model": "claude-xxx",
  "content": [
    {
      "type": "text",
      "text": "你好，有什么可以帮你？"
    }
  ],
  "stop_reason": "end_turn",
  "stop_sequence": null,
  "usage": {
    "input_tokens": 123,
    "output_tokens": 45
  }
}
```

当前项目里，各字段的处理方式如下。

#### 顶层字段：`error`

读取方式：

- `data.get("error")`

处理规则：

- 如果 `error` 不是 `None`、空字符串、空对象，就直接抛 `ProviderError(str(error))`

也就是说：

- `error` 是错误短路字段
- 一旦非空，不再继续解析 `content`

#### 顶层字段：`content`

读取方式：

- `data.get("content", [])`

处理规则：

- 必须是 `list`
- 否则抛：
  - `ProviderError("响应中没有有效 content 列表")`

#### 顶层字段：`id` / `type` / `role` / `model` / `stop_reason` / `usage`

当前代码：

- 不读取
- 不保存
- 不写入会话运行态

也就是说：

- 即使服务端返回这些字段，当前 provider 也直接忽略

### 3.8 `content` 列表里每种 block 怎么解析

provider 当前只识别两类 block。

#### block 类型 1：`text`

例如：

```json
{
  "type": "text",
  "text": "你好，有什么可以帮你？"
}
```

代码读取字段：

- `type`
- `text`

处理规则：

- 如果 `type == "text"`
- 且 `text.strip()` 非空
- 就把 `text` 追加到 `text_blocks`

最终多个 text block 会被：

- `"\n".join(text_blocks).strip()`

拼成内部结果里的：

- `ProviderResponse.display_text`

#### block 类型 2：`tool_use`

例如：

```json
{
  "type": "tool_use",
  "id": "toolu_xxx",
  "name": "read",
  "input": {
    "file_path": "README.md"
  }
}
```

代码读取字段：

- `type`
- `id`
- `name`
- `input`

处理规则：

- 如果 `type == "tool_use"`
- 就构造一个 `ToolCallRequest`

字段映射如下：

- `ToolCallRequest.id`
  <- `block["id"]`
- `ToolCallRequest.name`
  <- `block["name"]`
- `ToolCallRequest.input`
  <- `block["input"]`

其中 `input` 必须是 `dict`，否则会退化成空对象：

```python
{}
```

#### 其他 block 类型

当前代码：

- 全部忽略

### 3.9 最终内部输出长什么样

Anthropic provider 解析完成后，统一返回：

```python
ProviderResponse(
    display_text="<拼好的文本>",
    content_blocks=<原始 content 列表>,
    tool_calls=<解析出的 ToolCallRequest 列表>,
)
```

字段解释：

- `display_text`
  来自所有 `content[].type == "text"` 的 `text`
- `content_blocks`
  直接保存原始 `content`
- `tool_calls`
  来自所有 `content[].type == "tool_use"` 的解析结果

如果最终：

- 没有文本
- 也没有工具调用

则抛：

- `ProviderError("响应中没有可显示的文本内容")`

## 4. `openai-responses-compatible` 请求体

源码入口：

- `OpenAIResponsesProvider._request()`
- `OpenAIResponsesProvider._build_payload()`

这个 provider 比 Anthropic 复杂得多，因为它支持两种模式：

- 全量历史模式
- `previous_response_id` 增量续写模式

### 4.1 当前实现的重要结论

- 当前不区分 OpenAI 官方和第三方兼容网关
- 只要你设置了 `OPENAI_RESPONSES_BASE_URL`，都会走同一套代码
- 是否使用 `previous_response_id`，只看环境变量 `OPENAI_RESPONSES_USE_PREVIOUS_RESPONSE_ID`

### 4.2 最终请求 URL

请求 URL 来自：

- `config.openai_responses_base_url`

规范化逻辑在：

- `_build_endpoint(base_url)`

规则：

- 如果 base URL 已以 `/responses` 结尾，直接用
- 如果以 `/v1` 结尾，补成 `/v1/responses`
- 否则补成 `/v1/responses`

例如：

- `https://api.openai.com`
  -> `https://api.openai.com/v1/responses`
- `https://host.example/v1`
  -> `https://host.example/v1/responses`
- `https://host.example/custom/responses`
  -> 原样使用

### 4.3 请求头

请求头由 `_headers()` 生成。

固定字段：

```json
{
  "Content-Type": "application/json",
  "Accept": "application/json",
  "User-Agent": "python-requests/2.31.0"
}
```

条件字段：

- 如果 `config.openai_responses_api_key` 非空，追加：

```json
{
  "Authorization": "Bearer <OPENAI_RESPONSES_API_KEY>"
}
```

### 4.4 请求体总结构：全量历史模式

当不使用 `previous_response_id` 时，请求体长这样：

```json
{
  "model": "gpt-5.4",
  "stream": false,
  "parallel_tool_calls": false,
  "max_output_tokens": 4096,
  "input": [
    {
      "type": "message",
      "role": "user",
      "content": [
        {
          "type": "input_text",
          "text": "你好"
        }
      ]
    }
  ],
  "tools": [
    {
      "type": "function",
      "name": "read",
      "description": "读取文件",
      "parameters": {
        "type": "object",
        "properties": {
          "file_path": {
            "type": "string"
          }
        },
        "required": ["file_path"]
      },
      "strict": false
    }
  ],
  "reasoning": {
    "effort": "xhigh"
  }
}
```

注意：

- `tools` 是条件字段
- `reasoning` 是条件字段

### 4.5 请求体总结构：增量续写模式

当使用 `previous_response_id` 且当前会话状态允许时，请求体长这样：

```json
{
  "model": "gpt-5.4",
  "stream": false,
  "parallel_tool_calls": false,
  "max_output_tokens": 4096,
  "previous_response_id": "resp_xxx",
  "input": [
    {
      "type": "message",
      "role": "user",
      "content": [
        {
          "type": "input_text",
          "text": "你是什么模型"
        }
      ]
    }
  ]
}
```

这时有两个关键点：

- `previous_response_id` 出现了
- `input` 只包含“上一轮响应之后新增的消息”，不是整段历史

### 4.6 每个字段的来源和解析

#### `model`

来源：

- `session.model or config.model`

#### `stream`

当前不是固定写死，而是由调用路径决定：

- 普通非流式 provider 调用：`false`
- Web / 无头逐字输出链路：`true`

是否启用“逐字冒字”不再由 provider 专属环境变量控制，而是由：

- `CLAUDE_CODE_THY_WEB_ENABLE_STREAM_OUTPUT`
- `CLAUDE_CODE_THY_HEADLESS_ENABLE_STREAM_OUTPUT`

这两个全局输出开关控制。

#### `parallel_tool_calls`

固定写死：

```json
false
```

当前项目不让模型一轮里并行调多组工具链。

#### `max_output_tokens`

来源：

- `config.max_tokens`

#### `previous_response_id`

这是条件字段。

出现条件：

1. `config.openai_responses_use_previous_response_id == True`
2. `session.runtime_state["openai_responses"]["use_previous_response_id"]` 不是 `False`
3. `session.runtime_state["openai_responses"]["last_response_id"]` 非空
4. `last_response_message_count` 是合法整数，且没有越界

满足这些条件才会出现。

来源函数：

- `_previous_response_id_for_request(session)`

#### `input`

这是最核心字段。

来源：

- 如果不走 `previous_response_id`
  - `_build_input(session)`
  - 即整个会话历史

- 如果走 `previous_response_id`
  - `_build_incremental_input(session)`
  - 即上一轮响应之后新增的消息

#### `tools`

这是条件字段。

只有当前轮 `tools` 非空时才会出现。

每个内部 `ToolSpec` 会被 `_tool_to_api()` 转成：

```json
{
  "type": "function",
  "name": "<tool.name>",
  "description": "<tool.description>",
  "parameters": "<tool.input_schema>",
  "strict": false
}
```

字段解释：

- `type`
  固定是 `"function"`
- `name`
  工具名
- `description`
  工具说明
- `parameters`
  对应内部 `ToolSpec.input_schema`
- `strict`
  当前固定是 `false`

#### `reasoning`

这是条件字段。

当 `config.openai_responses_reasoning_effort` 非空时，才会出现：

```json
{
  "reasoning": {
    "effort": "<config.openai_responses_reasoning_effort>"
  }
}
```

### 4.7 `input` 里每条消息怎么转

逻辑在：

- `_message_to_input_items(message)`

`input` 不是简单的聊天数组，而是一个 item 数组。

当前会出现 4 种 item。

#### 类型 1：普通文本消息

由 `_message_item(role, text)` 构造，结构固定是：

```json
{
  "type": "message",
  "role": "user",
  "content": [
    {
      "type": "input_text",
      "text": "你好"
    }
  ]
}
```

字段解释：

- `type`
  固定 `"message"`
- `role`
  当前实现里常见是 `"user"`
- `content`
  数组，当前只放一个 `input_text`

#### 类型 2：工具调用历史 `function_call`

结构：

```json
{
  "type": "function_call",
  "call_id": "call_xxx",
  "name": "read",
  "arguments": "{\"file_path\":\"README.md\"}"
}
```

字段解释：

- `type`
  固定 `"function_call"`
- `call_id`
  工具调用 ID
- `name`
  工具名
- `arguments`
  注意这里是 JSON 字符串，不是 object

来源：

- 助手消息里的工具调用记录

提取优先级：

1. `message.metadata["tool_calls"]`
2. `message.content_blocks`

#### 类型 3：工具调用结果 `function_call_output`

结构：

```json
{
  "type": "function_call_output",
  "call_id": "call_xxx",
  "output": "{\"ok\":true}"
}
```

字段解释：

- `type`
  固定 `"function_call_output"`
- `call_id`
  对应上一次 function call 的 ID
- `output`
  工具输出的字符串版本

来源：

- `tool` 消息

provider 会优先从以下位置找 `call_id`：

1. `message.metadata["tool_use_id"]`
2. `message.content_blocks[0]["tool_use_id"]`
3. `message.content_blocks[0]["call_id"]`

如果找到了 `call_id`，就走结构化 `function_call_output`。

#### 类型 4：工具结果退化文本

如果工具消息没有 `call_id`，就不会生成 `function_call_output`，而是退化成普通文本消息：

```json
{
  "type": "message",
  "role": "user",
  "content": [
    {
      "type": "input_text",
      "text": "Tool `read` result:\n<message.text>"
    }
  ]
}
```

### 4.8 各角色消息的具体映射

#### 用户消息 `role == "user"`

本地消息：

```python
ChatMessage(role="user", text="你好")
```

转成：

```json
[
  {
    "type": "message",
    "role": "user",
    "content": [
      {
        "type": "input_text",
        "text": "你好"
      }
    ]
  }
]
```

#### 助手消息 `role == "assistant"`

助手消息会拆成两部分。

第一部分：如果 `message.text` 非空，转成一个“上下文说明文本”：

```json
{
  "type": "message",
  "role": "user",
  "content": [
    {
      "type": "input_text",
      "text": "上一轮助手回复（仅作上下文参考）：\n<message.text>"
    }
  ]
}
```

第二部分：如果 assistant 消息里带工具调用记录，再追加若干 `function_call` item。

也就是说：

- assistant 文本不会以 `"role": "assistant"` 原样回传
- 当前实现会把它包装成“供上下文参考的 user 文本”

#### 工具消息 `role == "tool"`

优先转 `function_call_output`。

如果无法结构化关联到 `call_id`，才退化成普通文本消息。

### 4.9 `previous_response_id` 的本地状态字段

这些字段不在请求体里，但决定请求体长什么样。

保存在：

- `session.runtime_state["openai_responses"]`

字段如下：

- `last_response_id`
  上一轮服务端返回的 response ID

- `last_response_message_count`
  上一轮完成时，会话里已经有多少条消息

- `use_previous_response_id`
  当前会话是否还继续尝试增量续写

它们的作用：

- 决定本轮请求是否带 `previous_response_id`
- 决定本轮 `input` 是全量历史还是增量消息

### 4.10 `previous_response_id` 失败后的回退

如果本轮 payload 带了：

- `previous_response_id`

并且服务端返回 `HTTPError`，当前实现会：

1. 把本地状态里的 `use_previous_response_id` 改成 `False`
2. 重新构造一个“不带 previous_response_id”的全量历史请求体
3. 再发一次请求

所以当前策略是：

- 优先尝试增量续写
- 网关不支持就自动退回全量历史

### 4.11 `openai-responses-compatible` 的响应体 / 输出字段

源码解析入口：

- `OpenAIResponsesProvider._request()`

当前代码对响应 JSON 真正关心的顶层字段有三个：

- `id`
- `error`
- `output`

一个典型响应大致会长这样：

```json
{
  "id": "resp_xxx",
  "object": "response",
  "model": "gpt-5.4",
  "output": [
    {
      "type": "message",
      "id": "msg_xxx",
      "role": "assistant",
      "content": [
        {
          "type": "output_text",
          "text": "你好！有什么我可以帮你的吗？"
        }
      ]
    }
  ],
  "usage": {
    "input_tokens": 100,
    "output_tokens": 20
  }
}
```

如果模型要调用工具，`output` 中还会出现：

```json
{
  "type": "function_call",
  "id": "fc_xxx",
  "call_id": "call_xxx",
  "name": "read",
  "arguments": "{\"file_path\":\"README.md\"}"
}
```

当前项目里，各字段的处理方式如下。

#### 顶层字段：`id`

读取方式：

- `str(data.get("id", "")).strip()`

处理规则：

- 如果非空，就写入：
  - `session.runtime_state["openai_responses"]["last_response_id"]`
- 同时写入：
  - `last_response_message_count = len(session.messages) + 1`

这个字段不会直接显示给用户，但会影响下轮请求是否带：

- `previous_response_id`

#### 顶层字段：`error`

读取方式：

- `data.get("error")`

处理规则：

- 如果 `error` 不是 `None`、空字符串、空对象，就通过 `_stringify_error(error)` 转成字符串
- 然后抛出 `ProviderError(...)`

支持的错误形态：

- 字符串
- 对象
- 其他任意值

#### 顶层字段：`output`

读取方式：

- `data.get("output", [])`

处理规则：

- 必须是 `list`
- 否则抛：
  - `ProviderError("响应中没有有效 output 列表")`

#### 顶层字段：`object` / `model` / `usage` / 其他

当前代码：

- 不读取
- 不保存
- 不进入 `ProviderResponse`

### 4.12 `output` 列表里每种 item 怎么解析

当前代码主要识别两类 item。

#### item 类型 1：`message`

例如：

```json
{
  "type": "message",
  "id": "msg_xxx",
  "role": "assistant",
  "content": [
    {
      "type": "output_text",
      "text": "你好！有什么我可以帮你的吗？"
    }
  ]
}
```

代码读取字段：

- `type`
- `content`

在 `content` 子数组里，只识别：

- `type == "output_text"`
- `type == "text"`

子块示例：

```json
{
  "type": "output_text",
  "text": "你好！有什么我可以帮你的吗？"
}
```

或：

```json
{
  "type": "text",
  "text": "你好！有什么我可以帮你的吗？"
}
```

处理规则：

- 只要子块 `type` 是 `output_text` 或 `text`
- 且 `text.strip()` 非空
- 就把 `text` 追加到 `texts`

最终多个文本块会被：

- `"\n".join(texts).strip()`

拼成内部结果里的：

- `ProviderResponse.display_text`

#### item 类型 2：`function_call`

例如：

```json
{
  "type": "function_call",
  "id": "fc_xxx",
  "call_id": "call_xxx",
  "name": "read",
  "arguments": "{\"file_path\":\"README.md\"}"
}
```

代码读取字段：

- `type`
- `name`
- `call_id`
- `id`
- `arguments`

处理规则：

- 只有 `type == "function_call"` 才会进入工具调用解析
- `call_id` 优先取 `item["call_id"]`
- 如果没有，再退回 `item["id"]`
- `arguments` 必须能解析成 JSON object

字段映射如下：

- `ToolCallRequest.id`
  <- `call_id` 或 `id`
- `ToolCallRequest.name`
  <- `name`
- `ToolCallRequest.input`
  <- 解析后的 `arguments`

如果：

- `name` 为空
- 或 `call_id/id` 为空

则这条 `function_call` 会被忽略。

#### 其他 item 类型

当前代码：

- 全部忽略

### 4.13 `function_call.arguments` 字段的解析规则

`arguments` 在响应里是字符串，不是对象。

例如：

```json
"{\"file_path\":\"README.md\"}"
```

解析逻辑在：

- `_parse_json_object(raw)`

规则：

- 空字符串 -> `{}`
- 非法 JSON -> 抛 `ProviderError`
- JSON 合法但结果不是 object -> 抛 `ProviderError("工具参数必须是 JSON object")`

也就是说：

- `arguments` 必须最终落成 `dict[str, object]`

### 4.14 最终内部输出长什么样

OpenAI Responses provider 解析完成后，统一返回：

```python
ProviderResponse(
    display_text="<拼好的文本>",
    content_blocks=<原始 output 列表>,
    tool_calls=<解析出的 ToolCallRequest 列表>,
)
```

字段解释：

- `display_text`
  来自所有 `output[].type == "message"` 中可识别文本块的 `text`
- `content_blocks`
  直接保存原始 `output`
- `tool_calls`
  来自所有 `output[].type == "function_call"` 的解析结果

如果最终：

- 没有文本
- 也没有工具调用

则抛：

- `ProviderError("响应中没有可显示文本或可执行工具调用")`

## 5. 两种 provider 请求体对比

### `anthropic-compatible`

顶层字段：

- `model`
- `max_tokens`
- `messages`
- `tools`（条件字段）

特点：

- 结构简单
- 直接把整个会话历史放进 `messages`
- 工具结果消息会转成 `role="user"`

### `openai-responses-compatible`

顶层字段：

- `model`
- `stream`
- `parallel_tool_calls`
- `max_output_tokens`
- `input`
- `previous_response_id`（条件字段）
- `tools`（条件字段）
- `reasoning`（条件字段）

特点：

- 顶层字段更多
- `input` 不是传统聊天数组，而是 item 数组
- 支持 `previous_response_id`
- 工具历史和工具结果会拆成 `function_call` / `function_call_output`

## 6. 两种 provider 的输出字段对比

### `anthropic-compatible`

当前代码实际消费的顶层响应字段：

- `error`
- `content`

当前代码实际消费的 block 字段：

- `content[].type`
- `content[].text`
- `content[].id`
- `content[].name`
- `content[].input`

最终内部输出：

- `ProviderResponse.display_text`
- `ProviderResponse.content_blocks`
- `ProviderResponse.tool_calls`

### `openai-responses-compatible`

当前代码实际消费的顶层响应字段：

- `id`
- `error`
- `output`

当前代码实际消费的 item 字段：

- `output[].type`
- `output[].content`
- `output[].name`
- `output[].call_id`
- `output[].id`
- `output[].arguments`

当前代码实际消费的 `message.content[]` 子字段：

- `type`
- `text`

最终内部输出：

- `ProviderResponse.display_text`
- `ProviderResponse.content_blocks`
- `ProviderResponse.tool_calls`

## 7. tool 历史注入机制

你前面问到一个关键点：

- 两种请求里虽然对话历史都有 `role`
- 但为什么看起来没有 `role = tool`
- 那工具历史到底有没有注入进去

结论是：

- 有
- 而且两条 provider 线都有
- 只是工具历史主要不是靠 `role` 字段表达，而是靠特殊 block / 特殊 item 类型表达

### 7.1 本地会话里工具历史怎么保存

无论走哪种 provider，工具执行完之后，`QueryEngine` 都会先把结果写回本地会话。

代码在：

- `QueryEngine._append_tool_result()`
- `QueryEngine._append_tool_error()`

写回的本地消息结构是：

- `role = "tool"`
- `text = result.render()` 或错误文本
- `content_blocks = [{"type": "tool_result", ...}]`

成功结果写入的 block 结构：

```json
[
  {
    "type": "tool_result",
    "tool_use_id": "<tool_use_id>",
    "is_error": false,
    "content": "<result.content_for_model()>"
  }
]
```

失败结果写入的 block 结构：

```json
[
  {
    "type": "tool_result",
    "tool_use_id": "<tool_use_id>",
    "is_error": true,
    "content": "<error text>"
  }
]
```

这一步非常关键：

- provider 并不是直接拿工具执行结果
- 而是下一轮从 `session.messages` 里重新把工具历史取出来，再转换成各自协议需要的格式

### 7.2 `anthropic-compatible` 怎么注入 tool 历史

Anthropic 这条线有两种工具历史：

- 工具调用历史
- 工具结果历史

#### 工具调用历史

当模型上一轮返回工具调用时，QueryEngine 会把整段原始 `response.content_blocks` 保存到 assistant 消息里。

也就是说 assistant 消息的 `content_blocks` 里会保留：

- `type = "tool_use"`
- `id`
- `name`
- `input`

下一轮发请求时，Anthropic provider 对普通 assistant 消息的处理是：

- 如果 `message.content_blocks` 存在，就直接把它作为 `content` 发回去

所以：

- 上一轮的 `tool_use` 历史会被完整注入下一轮

#### 工具结果历史

工具执行后，本地消息是：

- `role = "tool"`
- `content_blocks = [{"type": "tool_result", ...}]`

Anthropic provider 在 `_message_to_api(message)` 里遇到 `role == "tool"` 时，不会把它发成 `role = "tool"`，而是改写成：

```json
{
  "role": "user",
  "content": [
    {
      "type": "tool_result",
      "tool_use_id": "<tool_use_id>",
      "is_error": false,
      "content": "..."
    }
  ]
}
```

所以结论是：

- Anthropic 有完整 tool 历史注入
- 只是“工具结果历史”发出去时角色是 `user`
- 不是 `tool`

#### Anthropic 这条线你要重点看的字段

工具调用历史看：

- `assistant.content[].type == "tool_use"`
- `assistant.content[].id`
- `assistant.content[].name`
- `assistant.content[].input`

工具结果历史看：

- `user.content[].type == "tool_result"`
- `user.content[].tool_use_id`
- `user.content[].is_error`
- `user.content[].content`

### 7.3 `openai-responses-compatible` 怎么注入 tool 历史

OpenAI Responses 这条线同样有两种工具历史：

- 工具调用历史
- 工具结果历史

但它们不会走普通 `role = tool` message，而是拆成专门的 item 类型。

#### 工具调用历史

assistant 消息里会保留工具调用记录，来源有两种：

1. `message.metadata["tool_calls"]`
2. `message.content_blocks`

下一轮发请求时，OpenAI provider 会把这些工具调用历史转成：

```json
{
  "type": "function_call",
  "call_id": "<call_id>",
  "name": "<tool_name>",
  "arguments": "{\"key\":\"value\"}"
}
```

所以：

- OpenAI Responses 里的工具调用历史不是 `role` 表达
- 而是 `type = "function_call"`

#### 工具结果历史

本地 `role = "tool"` 的消息，OpenAI provider 优先尝试转成：

```json
{
  "type": "function_call_output",
  "call_id": "<tool_use_id>",
  "output": "<serialized tool output>"
}
```

这里会优先从以下位置找调用 ID：

1. `message.metadata["tool_use_id"]`
2. `message.content_blocks[0]["tool_use_id"]`
3. `message.content_blocks[0]["call_id"]`

如果找到了 `call_id`，就走标准结构化注入：

- `type = "function_call_output"`

如果没找到，才退化成普通文本 message：

```json
{
  "type": "message",
  "role": "user",
  "content": [
    {
      "type": "input_text",
      "text": "Tool `read` result:\n..."
    }
  ]
}
```

所以结论是：

- OpenAI Responses 也有完整 tool 历史注入
- 标准路径是：
  - `function_call`
  - `function_call_output`
- 不是靠 `role = tool`

#### OpenAI 这条线你要重点看的字段

工具调用历史看：

- `output/input[].type == "function_call"`
- `call_id`
- `name`
- `arguments`

工具结果历史看：

- `input[].type == "function_call_output"`
- `call_id`
- `output`

### 7.4 一句话总结

如果只盯着 `role` 看，你会误以为“没有 tool 历史”。

实际上：

- Anthropic：tool 历史靠 `tool_use` / `tool_result`
- OpenAI Responses：tool 历史靠 `function_call` / `function_call_output`

也就是说：

- `role` 只负责普通消息层
- tool 历史主要靠结构化 block / item 层

## 8. 当前最值得关注的几个字段

如果你主要是为了调试请求体，最值得看的字段其实就这些。

### Anthropic

- `model`
- `messages`
- `tools`

### OpenAI Responses

- `model`
- `input`
- `tools`
- `previous_response_id`
- `reasoning`

如果你主要是为了调试响应体，最值得看的字段是：

### Anthropic

- `error`
- `content`
- `content[].type`
- `content[].text`
- `content[].id`
- `content[].name`
- `content[].input`

### OpenAI Responses

- `id`
- `error`
- `output`
- `output[].type`
- `output[].content`
- `output[].call_id`
- `output[].name`
- `output[].arguments`

## 9. 如果你要继续调试，建议看哪里

### 想看 Anthropic 请求体到底怎么拼

看：

- `src/claude_code_thy/providers/anthropic.py`

重点函数：

- `_request`
- `_message_to_api`
- `_headers`
- `_build_endpoint`

想看 Anthropic 响应体怎么解析，也还是看 `_request`。

### 想看 OpenAI Responses 请求体到底怎么拼

看：

- `src/claude_code_thy/providers/openai_responses.py`

重点函数：

- `_build_payload`
- `_build_input`
- `_build_incremental_input`
- `_message_to_input_items`
- `_assistant_items`
- `_tool_items`
- `_tool_to_api`
- `_previous_response_id_for_request`

想看 OpenAI Responses 响应体怎么解析，重点再加这几个函数：

- `_request`
- `_extract_output_text`
- `_extract_tool_calls`
- `_parse_json_object`

如果你后面要的话，我还可以继续帮你做两件事：

1. 再补一份“真实请求体示例文档”，直接用你项目当前工具列表生成一份完整样例 JSON
2. 在 provider 里加一个 debug 开关，把每次实际发送的请求体保存到文件，方便你逐轮检查

## 10. 完整实例

下面这些例子都只关注：

- 请求体
- 模型输出体
- 本地对话历史如何追加
- 下一轮请求体如何从历史重新构造

为便于阅读，示例里省略了和当前问题无关的字段。

---

### 10.1 Anthropic：纯文本一问一答

这是最简单的情况，没有工具调用。

#### 第 1 轮请求体

```json
{
  "model": "glm-4.5",
  "max_tokens": 4096,
  "messages": [
    {
      "role": "user",
      "content": [
        {
          "type": "text",
          "text": "你好"
        }
      ]
    }
  ]
}
```

#### 第 1 轮输出体

```json
{
  "id": "msg_001",
  "type": "message",
  "role": "assistant",
  "content": [
    {
      "type": "text",
      "text": "你好，有什么可以帮你的吗？"
    }
  ]
}
```

#### 解析后写回本地会话的 assistant 消息

```json
{
  "role": "assistant",
  "text": "你好，有什么可以帮你的吗？",
  "content_blocks": [
    {
      "type": "text",
      "text": "你好，有什么可以帮你的吗？"
    }
  ],
  "metadata": null
}
```

#### 下一轮如果用户继续提问，请求体会这样增长

```json
{
  "model": "glm-4.5",
  "max_tokens": 4096,
  "messages": [
    {
      "role": "user",
      "content": [
        {
          "type": "text",
          "text": "你好"
        }
      ]
    },
    {
      "role": "assistant",
      "content": [
        {
          "type": "text",
          "text": "你好，有什么可以帮你的吗？"
        }
      ]
    },
    {
      "role": "user",
      "content": [
        {
          "type": "text",
          "text": "你是什么模型"
        }
      ]
    }
  ]
}
```

---

### 10.2 Anthropic：带 `read` 工具调用的完整两轮

这个例子最能说明：

- 工具调用结果是怎么回到对话历史里的
- 为什么 Anthropic 这条线虽然没有 `role = tool` 发出去，但其实工具历史是完整的

假设用户说：

- `请读取 README.md 的前几行`

当前轮主链暴露了 `read` 工具。

#### 第 1 轮请求体

```json
{
  "model": "glm-4.5",
  "max_tokens": 4096,
  "messages": [
    {
      "role": "user",
      "content": [
        {
          "type": "text",
          "text": "请读取 README.md 的前几行"
        }
      ]
    }
  ],
  "tools": [
    {
      "name": "read",
      "description": "读取文件",
      "input_schema": {
        "type": "object",
        "properties": {
          "file_path": {
            "type": "string"
          }
        },
        "required": ["file_path"]
      }
    }
  ]
}
```

#### 第 1 轮输出体：模型先发出工具调用

```json
{
  "id": "msg_002",
  "type": "message",
  "role": "assistant",
  "content": [
    {
      "type": "tool_use",
      "id": "toolu_001",
      "name": "read",
      "input": {
        "file_path": "README.md"
      }
    }
  ]
}
```

#### 解析后写回本地会话的 assistant 消息

```json
{
  "role": "assistant",
  "text": "",
  "content_blocks": [
    {
      "type": "tool_use",
      "id": "toolu_001",
      "name": "read",
      "input": {
        "file_path": "README.md"
      }
    }
  ],
  "metadata": {
    "tool_calls": [
      {
        "id": "toolu_001",
        "name": "read",
        "input": {
          "file_path": "README.md"
        }
      }
    ]
  }
}
```

#### 工具执行完成后，QueryEngine 写回本地会话的 tool 消息

注意，这一步还不是发给模型的请求体，而是本地历史里的中间态。

```json
{
  "role": "tool",
  "text": "工具 `read` 执行成功\n读取文件：README.md\n\n     1\t# Claude Code Thy\n     2\t...\n",
  "content_blocks": [
    {
      "type": "tool_result",
      "tool_use_id": "toolu_001",
      "is_error": false,
      "content": "     1\t# Claude Code Thy\n     2\t...\n"
    }
  ],
  "metadata": {
    "tool_name": "read",
    "tool_use_id": "toolu_001"
  }
}
```

#### 第 2 轮请求体：工具历史重新注入

这时 Anthropic provider 会把整个会话历史重新展开成：

```json
{
  "model": "glm-4.5",
  "max_tokens": 4096,
  "messages": [
    {
      "role": "user",
      "content": [
        {
          "type": "text",
          "text": "请读取 README.md 的前几行"
        }
      ]
    },
    {
      "role": "assistant",
      "content": [
        {
          "type": "tool_use",
          "id": "toolu_001",
          "name": "read",
          "input": {
            "file_path": "README.md"
          }
        }
      ]
    },
    {
      "role": "user",
      "content": [
        {
          "type": "tool_result",
          "tool_use_id": "toolu_001",
          "is_error": false,
          "content": "     1\t# Claude Code Thy\n     2\t...\n"
        }
      ]
    }
  ],
  "tools": [
    {
      "name": "read",
      "description": "读取文件",
      "input_schema": {
        "type": "object",
        "properties": {
          "file_path": {
            "type": "string"
          }
        },
        "required": ["file_path"]
      }
    }
  ]
}
```

这个例子里最关键的点是：

- 工具调用历史通过 assistant 的 `tool_use` 注入
- 工具结果历史通过 user 的 `tool_result` 注入
- 所以虽然没有 `role = tool` 发出去，tool 历史还是完整的

#### 第 2 轮输出体：模型基于工具结果继续回答

```json
{
  "id": "msg_003",
  "type": "message",
  "role": "assistant",
  "content": [
    {
      "type": "text",
      "text": "README.md 的前几行主要是在介绍 Claude Code Thy 项目本身。"
    }
  ]
}
```

---

### 10.3 OpenAI Responses：无 `previous_response_id` 的完整工具调用轮次

这个例子展示：

- 第一轮模型输出 `function_call`
- 工具结果怎么变成下一轮 `function_call_output`
- 为什么 OpenAI 这条线的 tool 历史主要不看 `role`

假设用户说：

- `请读取 README.md`

且当前轮暴露了 `read` 工具。

#### 第 1 轮请求体

```json
{
  "model": "gpt-5.4",
  "stream": false,
  "parallel_tool_calls": false,
  "max_output_tokens": 4096,
  "input": [
    {
      "type": "message",
      "role": "user",
      "content": [
        {
          "type": "input_text",
          "text": "请读取 README.md"
        }
      ]
    }
  ],
  "tools": [
    {
      "type": "function",
      "name": "read",
      "description": "读取文件",
      "parameters": {
        "type": "object",
        "properties": {
          "file_path": {
            "type": "string"
          }
        },
        "required": ["file_path"]
      },
      "strict": false
    }
  ]
}
```

#### 第 1 轮输出体：模型发起工具调用

```json
{
  "id": "resp_001",
  "output": [
    {
      "type": "function_call",
      "id": "fc_001",
      "call_id": "call_001",
      "name": "read",
      "arguments": "{\"file_path\":\"README.md\"}"
    }
  ]
}
```

#### 解析后写回本地会话的 assistant 消息

```json
{
  "role": "assistant",
  "text": "",
  "content_blocks": [
    {
      "type": "function_call",
      "id": "fc_001",
      "call_id": "call_001",
      "name": "read",
      "arguments": "{\"file_path\":\"README.md\"}"
    }
  ],
  "metadata": {
    "tool_calls": [
      {
        "id": "call_001",
        "name": "read",
        "input": {
          "file_path": "README.md"
        }
      }
    ]
  }
}
```

#### 工具执行完成后，写回本地会话的 tool 消息

```json
{
  "role": "tool",
  "text": "工具 `read` 执行成功\n读取文件：README.md\n\n     1\t# Claude Code Thy\n     2\t...\n",
  "content_blocks": [
    {
      "type": "tool_result",
      "tool_use_id": "call_001",
      "is_error": false,
      "content": "     1\t# Claude Code Thy\n     2\t...\n"
    }
  ],
  "metadata": {
    "tool_name": "read",
    "tool_use_id": "call_001"
  }
}
```

#### 第 2 轮请求体：全量历史模式下，tool 历史被重构成 `function_call` + `function_call_output`

```json
{
  "model": "gpt-5.4",
  "stream": false,
  "parallel_tool_calls": false,
  "max_output_tokens": 4096,
  "input": [
    {
      "type": "message",
      "role": "user",
      "content": [
        {
          "type": "input_text",
          "text": "请读取 README.md"
        }
      ]
    },
    {
      "type": "function_call",
      "call_id": "call_001",
      "name": "read",
      "arguments": "{\"file_path\":\"README.md\"}"
    },
    {
      "type": "function_call_output",
      "call_id": "call_001",
      "output": "     1\t# Claude Code Thy\n     2\t...\n"
    }
  ],
  "tools": [
    {
      "type": "function",
      "name": "read",
      "description": "读取文件",
      "parameters": {
        "type": "object",
        "properties": {
          "file_path": {
            "type": "string"
          }
        },
        "required": ["file_path"]
      },
      "strict": false
    }
  ]
}
```

这个例子里最关键的点是：

- assistant 里的工具调用历史被重构成 `function_call`
- tool 消息里的工具结果历史被重构成 `function_call_output`
- 不是靠 `role = tool`

#### 第 2 轮输出体：模型基于工具结果继续回答

```json
{
  "id": "resp_002",
  "output": [
    {
      "type": "message",
      "id": "msg_002",
      "role": "assistant",
      "content": [
        {
          "type": "output_text",
          "text": "README.md 主要是在介绍项目功能、配置和使用方式。"
        }
      ]
    }
  ]
}
```

---

### 10.4 OpenAI Responses：启用 `previous_response_id` 后，同一轮工具续写怎么构造

这个例子专门看：

- `previous_response_id` 模式下
- 工具结果如何不靠“全量历史重发”
- 而是靠“增量 input + previous_response_id”续写

假设上一轮第 1 次响应是：

```json
{
  "id": "resp_010",
  "output": [
    {
      "type": "function_call",
      "id": "fc_010",
      "call_id": "call_010",
      "name": "read",
      "arguments": "{\"file_path\":\"README.md\"}"
    }
  ]
}
```

provider 收到后，会在本地运行态里记住：

```json
{
  "last_response_id": "resp_010",
  "last_response_message_count": 2,
  "use_previous_response_id": true
}
```

然后工具执行完成，本地会话里新增一条 `role = "tool"` 消息。

#### 下一次请求体：不再重发整段历史，只发增量输入

```json
{
  "model": "gpt-5.4",
  "stream": false,
  "parallel_tool_calls": false,
  "max_output_tokens": 4096,
  "previous_response_id": "resp_010",
  "input": [
    {
      "type": "function_call_output",
      "call_id": "call_010",
      "output": "     1\t# Claude Code Thy\n     2\t...\n"
    }
  ],
  "tools": [
    {
      "type": "function",
      "name": "read",
      "description": "读取文件",
      "parameters": {
        "type": "object",
        "properties": {
          "file_path": {
            "type": "string"
          }
        },
        "required": ["file_path"]
      },
      "strict": false
    }
  ]
}
```

关键点：

- 这里 `input` 里已经没有第一轮的 user message
- 也没有再重复发那条 `function_call`
- 因为上一次响应上下文由 `previous_response_id = "resp_010"` 承接
- 这次只需要把新增的 `function_call_output` 补给模型

#### 这一次的输出体

```json
{
  "id": "resp_011",
  "output": [
    {
      "type": "message",
      "id": "msg_011",
      "role": "assistant",
      "content": [
        {
          "type": "output_text",
          "text": "README.md 的开头主要是在说明项目的用途。"
        }
      ]
    }
  ]
}
```

---

### 10.5 OpenAI Responses：启用 `previous_response_id` 后，用户下一次继续提问

在上个例子里，如果模型已经基于工具结果回答完，返回：

```json
{
  "id": "resp_011",
  "output": [
    {
      "type": "message",
      "content": [
        {
          "type": "output_text",
          "text": "README.md 的开头主要是在说明项目的用途。"
        }
      ]
    }
  ]
}
```

然后用户接着问：

- `再总结一下主要功能`

本地会话会新增一条 user 消息。

#### 下一轮请求体

```json
{
  "model": "gpt-5.4",
  "stream": false,
  "parallel_tool_calls": false,
  "max_output_tokens": 4096,
  "previous_response_id": "resp_011",
  "input": [
    {
      "type": "message",
      "role": "user",
      "content": [
        {
          "type": "input_text",
          "text": "再总结一下主要功能"
        }
      ]
    }
  ]
}
```

关键点：

- 这时也不会重发整段历史
- 只发“自 `resp_011` 之后新增的那条 user 消息”

---

### 10.6 一个总总结

如果你只看“请求里的 `role`”，你会漏掉最重要的 tool 历史链路。

真正应该这样看：

#### Anthropic

- 普通历史：
  - `messages[*].role = user / assistant`
- 工具调用历史：
  - `assistant.content[*].type = tool_use`
- 工具结果历史：
  - `user.content[*].type = tool_result`

#### OpenAI Responses

- 普通历史：
  - `input[*].type = message`
  - `input[*].role = user`
- 工具调用历史：
  - `input[*].type = function_call`
- 工具结果历史：
  - `input[*].type = function_call_output`

所以你要调试一轮完整的“模型 -> 工具 -> 模型”时，建议固定盯这几类字段：

- Anthropic：
  - `messages`
  - `content[].type`
  - `tool_use`
  - `tool_result`

- OpenAI Responses：
  - `input`
  - `input[].type`
  - `function_call`
  - `function_call_output`
  - `previous_response_id`
