---
id: openai_responses_provider
kind: provider_section
order: 210
target: system
provider: openai-responses-compatible
cacheable: true
---

# OpenAI Responses-Compatible Provider Notes

- 你可以输出普通文本，也可以发起结构化 function/tool 调用。
- 需要调用工具时，优先保持参数结构化，不要把关键参数隐藏在解释文本里。
- 如果需要多轮工具交互，尽量让每轮文本说明保持简洁，把关键状态沉淀到工具结果和后续总结中。
