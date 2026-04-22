from __future__ import annotations

from pathlib import Path


def _agent_output_task_id(file_path: str) -> str | None:
    """处理 `agent_output_task_id`。"""
    path = Path(file_path)
    if path.suffix == ".output" and "tasks" in path.parts:
        return path.stem
    return None


def _is_plan_file(file_path: str) -> bool:
    """返回是否满足 `is_plan_file` 条件。"""
    path = Path(file_path)
    return "plans" in path.parts

def tool_label() -> str:
    """处理 `tool_label`。"""
    return "Read"


def summarize_input(raw_input: object) -> str:
    """汇总 `input`。"""
    if not isinstance(raw_input, dict):
        return ""
    file_path = raw_input.get("file_path", "")
    if isinstance(file_path, str):
        agent_task_id = _agent_output_task_id(file_path)
        if agent_task_id:
            return agent_task_id
        if _is_plan_file(file_path):
            return file_path
    pages = raw_input.get("pages")
    if pages:
        return f"{file_path} · pages {pages}"
    if raw_input.get("offset") or raw_input.get("limit"):
        start = int(raw_input.get("offset", 1) or 1)
        limit = raw_input.get("limit")
        if limit:
            return f"{file_path} · lines {start}-{start + int(limit) - 1}"
        return f"{file_path} · from line {start}"
    return str(file_path)


def extra_result_lines(metadata: dict[str, object]) -> list[str]:
    """处理 `extra_result_lines`。"""
    lines: list[str] = []
    structured = metadata.get("structured_data")
    if isinstance(structured, dict):
        file_path = str(structured.get("file_path", ""))
        agent_task_id = _agent_output_task_id(file_path)
        if agent_task_id:
            lines.append(f"Agent task: {agent_task_id}")
        if _is_plan_file(file_path):
            lines.append("Reading plan file")
    return lines
