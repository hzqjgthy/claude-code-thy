from __future__ import annotations


def tool_label() -> str:
    """返回浏览器工具在界面中的显示标签。"""
    return "Browser"


def summarize_input(raw_input: object) -> str:
    """把浏览器工具输入压缩成一行摘要。"""
    if not isinstance(raw_input, dict):
        return ""
    action = str(raw_input.get("action", "")).strip()
    if action in {"open", "navigate"}:
        return f"{action} {raw_input.get('url', '')}".strip()
    if action in {"focus", "close", "snapshot", "screenshot"}:
        page_id = str(raw_input.get("page_id", "")).strip()
        return f"{action} {page_id}".strip()
    if action in {"click", "type"}:
        ref = str(raw_input.get("ref", "")).strip()
        return f"{action} {ref}".strip()
    if action == "press":
        return f"press {raw_input.get('key', '')}".strip()
    if action == "wait":
        text = str(raw_input.get("text", "")).strip()
        url_contains = str(raw_input.get("url_contains", "")).strip()
        time_ms = raw_input.get("time_ms")
        if text:
            return f"wait text={text}"
        if url_contains:
            return f"wait url~{url_contains}"
        if time_ms:
            return f"wait {time_ms}ms"
    return action


def extra_result_lines(metadata: dict[str, object]) -> list[str]:
    """补充浏览器结果里值得单独展示的附加信息。"""
    lines: list[str] = []
    structured = metadata.get("structured_data")
    if not isinstance(structured, dict):
        return lines

    action = str(structured.get("action", "")).strip()
    if action:
        lines.append(f"Action: {action}")
    if structured.get("page_id"):
        lines.append(f"Page: {structured['page_id']}")
    if structured.get("current_page_id"):
        lines.append(f"Current page: {structured['current_page_id']}")
    if structured.get("path"):
        lines.append(f"Saved: {structured['path']}")
    if structured.get("ref_count") is not None:
        lines.append(f"Refs: {structured['ref_count']}")
    return lines
