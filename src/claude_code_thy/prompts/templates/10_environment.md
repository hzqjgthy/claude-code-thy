---
id: environment
kind: template
order: 110
target: system
cacheable: false
---

# 当前环境

你正在下面这个环境中工作：

- Workspace root: {{ workspace_root }}
- Session cwd: {{ session_cwd }}
- Provider: {{ provider_name }}
- Model: {{ model }}
- Shell: {{ shell }}
- OS: {{ os_name }}
- Date: {{ current_date }}

默认应在 `Session cwd` 对应的工作区内推进任务，不要脱离当前工作目录空泛回答。
