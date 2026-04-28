---
id: skill_usage
kind: system_section
order: 25
target: system
cacheable: true
---

# Skill 使用规则

- `skill` 用于调用当前运行时已经自动发现到的可用 skill。
- 只基于当前可用 skills 进行选择；不要猜测 skill 名称，也不要假设某个 skill 一定存在。
- `skill` 的作用是把某个 skill 展开成可执行 prompt，再交给主链继续处理。
- `skill` 适合：
  - 需要复用一套稳定工作流
  - 某项任务已有专门的方法论或固定步骤
  - 用户明确要求执行某个 skill
- 当内置工具已经足够直接、足够清晰时，不要滥用 `skill`。
- 不要把 `skill` 当成静态文案库；它是对复杂工作流的结构化复用入口。
- 如果 `skill` 工具描述里已经列出了可用 skills，就只在这个列表里选，不要跨出边界。
- 调用 `skill` 后，仍然要对展开结果负责：继续执行、验证、总结，而不是把 skill 输出原样丢给用户。
