from __future__ import annotations


def tool_label() -> str:
    return "Agent"


def summarize_input(raw_input: object) -> str:
    if not isinstance(raw_input, dict):
        return ""
    description = str(raw_input.get("description", "")).strip()
    prompt = str(raw_input.get("prompt", "")).strip()
    return description or prompt


def extra_result_lines(metadata: dict[str, object]) -> list[str]:
    lines: list[str] = []
    structured = metadata.get("structured_data")
    if not isinstance(structured, dict):
        return lines
    if structured.get("task_id"):
        lines.append(f"Task: {structured['task_id']}")
    if structured.get("status"):
        lines.append(f"Status: {structured['status']}")
    if structured.get("output_path"):
        lines.append(f"Output: {structured['output_path']}")
    if structured.get("auto_backgrounded"):
        lines.append("Auto-backgrounded")
    return lines
