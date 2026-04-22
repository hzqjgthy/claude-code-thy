from __future__ import annotations


def tool_label() -> str:
    """处理 `tool_label`。"""
    return "Glob"


def summarize_input(raw_input: object) -> str:
    """汇总 `input`。"""
    if not isinstance(raw_input, dict):
        return ""
    pattern = raw_input.get("pattern", "")
    path = raw_input.get("path")
    return f'pattern: "{pattern}"' + (f', path: "{path}"' if path else "")


def extra_result_lines(metadata: dict[str, object]) -> list[str]:
    """处理 `extra_result_lines`。"""
    return []
