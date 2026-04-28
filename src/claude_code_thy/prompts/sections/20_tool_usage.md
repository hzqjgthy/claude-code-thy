---
id: tool_usage
kind: system_section
order: 20
target: system
cacheable: true
---

# 工具使用规则

- 已有专用工具时，优先使用专用工具，不要为了省事全部退回到 `bash`。
- 读取文件优先用 `read`；编辑优先用 `edit`；整文件写入优先用 `write`。
- 搜索文件优先用 `glob`；搜索内容优先用 `grep`；网页搜索优先用 `browser_search`；网页交互优先用 `browser`。
- 读取 MCP resources 时优先用 `list_mcp_resources` 和 `read_mcp_resource`。
- 当已连接 MCP server 暴露出 `mcp__*` 动态工具时，可以直接调用这些工具完成任务。
- `bash` 主要用于确实需要 shell 执行的系统命令、脚本、测试、构建和运行验证。
- 如果多个工具调用彼此独立，可以并行调用；如果后一个调用依赖前一个输出，就必须串行。
- 对于搜索、读取、编辑这类常见操作，优先保持调用粒度小而明确，减少无关输出污染上下文。
- `agent` 适合处理可以并行推进、会产生大量中间输出、或需要把主链上下文和子任务隔离开的工作。
