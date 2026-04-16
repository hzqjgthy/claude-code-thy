from __future__ import annotations


def tool_label() -> str:
    return "Search"


def summarize_input(raw_input: object) -> str:
    if not isinstance(raw_input, dict):
        return ""
    pattern = raw_input.get("pattern", "")
    path = raw_input.get("path")
    return f'pattern: "{pattern}"' + (f', path: "{path}"' if path else "")


def extra_result_lines(metadata: dict[str, object]) -> list[str]:
    mode = metadata.get("mode")
    return [f"Mode: {mode}"] if mode else []
