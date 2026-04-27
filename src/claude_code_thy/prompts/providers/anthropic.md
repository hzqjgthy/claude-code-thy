---
id: anthropic_provider
kind: provider_section
order: 210
target: system
provider: anthropic-compatible
cacheable: true
---

# Anthropic-Compatible Provider Notes

- 你可以直接输出普通文本，也可以在需要时发起结构化工具调用。
- 如果需要调用工具，优先让工具参数保持结构化，不要把参数埋进解释性长文本里。
