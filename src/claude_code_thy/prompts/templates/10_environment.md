---
id: environment
kind: template
order: 110
target: system
cacheable: false
---

# 当前环境

- Workspace root: {{ workspace_root }}
- Session cwd: {{ session_cwd }}
- Provider: {{ provider_name }}
- Model: {{ model }}
- Shell: {{ shell }}
- OS: {{ os_name }}
- Date: {{ current_date }}
