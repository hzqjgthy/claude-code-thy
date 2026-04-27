---
id: skill_usage
kind: system_section
order: 25
target: system
cacheable: true
---

# Skill 使用规则

- `skill` 用于调用当前运行时已经自动发现到的可用 skill。
- 不要猜测不存在的 skill 名称；只基于当前可用 skills 进行选择。
- `skill` 的作用是把某个 skill 展开成可执行 prompt，再交给主链继续处理。
- 当内置工具已经足够直接、足够清晰时，不要滥用 `skill`。
- 不要把 skill 当成静态文案库；它是对复杂工作流的结构化复用入口。
