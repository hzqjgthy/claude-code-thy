from __future__ import annotations


def tool_label() -> str:
    """处理 `tool_label`。"""
    return "Bash"


def summarize_input(raw_input: object) -> str:
    """汇总 `input`。"""
    if not isinstance(raw_input, dict):
        return ""
    description = raw_input.get("description")
    command = raw_input.get("command", "")
    return str(description or command)


def extra_result_lines(metadata: dict[str, object]) -> list[str]:
    """处理 `extra_result_lines`。"""
    lines: list[str] = []
    if metadata.get("rejected"):
        lines.append("Rejected")
    if metadata.get("analysis_backend"):
        lines.append(f"Analysis: {metadata['analysis_backend']}")
    features = metadata.get("analysis_features")
    if isinstance(features, dict):
        enabled = [
            name.replace("has_", "")
            for name, value in features.items()
            if name.startswith("has_") and value
        ]
        if enabled:
            lines.append("Shell features: " + ", ".join(enabled))
    if metadata.get("sandbox_requested") and not metadata.get("sandbox_applied"):
        lines.append("Sandbox requested but adapter fallback was used")
    if metadata.get("sandbox_violation"):
        lines.append(f"Sandbox: {metadata['sandbox_violation']}")
    if metadata.get("return_code_interpretation"):
        lines.append(str(metadata["return_code_interpretation"]))
    if metadata.get("background_task_id"):
        lines.append(f"Task: {metadata['background_task_id']}")
    return lines
