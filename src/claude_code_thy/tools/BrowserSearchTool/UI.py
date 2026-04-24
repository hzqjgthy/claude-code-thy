from __future__ import annotations


def tool_label() -> str:
    """返回浏览器搜索工具的界面标签。"""
    return "Browser Search"


def summarize_input(raw_input: object) -> str:
    """把搜索输入压成一行摘要。"""
    if not isinstance(raw_input, dict):
        return ""
    query = str(raw_input.get("query", "")).strip()
    return f"search {query}".strip()


def extra_result_lines(metadata: dict[str, object]) -> list[str]:
    """补充浏览器搜索结果里的统计信息。"""
    lines: list[str] = []
    structured = metadata.get("structured_data")
    if not isinstance(structured, dict):
        return lines
    if structured.get("search_engine"):
        lines.append(f"Engine: {structured['search_engine']}")
    if structured.get("parser"):
        lines.append(f"Parser: {structured['parser']}")
    if structured.get("result_count") is not None:
        lines.append(f"Results: {structured['result_count']}")
    if structured.get("open_count") is not None:
        lines.append(f"Expanded: {structured['open_count']}")
    return lines
