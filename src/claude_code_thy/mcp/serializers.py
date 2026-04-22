from __future__ import annotations

import json


def to_jsonable(value: object) -> object:
    """转换为 `jsonable`。"""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(item) for item in value]
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            return to_jsonable(model_dump())
        except Exception:
            pass
    if hasattr(value, "__dict__"):
        data = {
            key: item
            for key, item in vars(value).items()
            if not key.startswith("_")
        }
        if data:
            return to_jsonable(data)
    return str(value)


def render_jsonable(value: object) -> str:
    """渲染 `jsonable`。"""
    return json.dumps(value, ensure_ascii=False, indent=2)


def serialize_mcp_tool_result(result: object) -> tuple[str, object]:
    """序列化 `mcp_tool_result`。"""
    if result is None:
        return "", {}
    content = getattr(result, "content", None)
    if isinstance(content, str):
        return content, {"content": content}
    if isinstance(content, list):
        normalized = [to_jsonable(item) for item in content]
        return _join_text_parts(_extract_text_parts(content, normalized)), {"content": normalized}
    normalized = to_jsonable(result)
    if isinstance(normalized, (dict, list)):
        return render_jsonable(normalized), normalized
    return str(normalized), {"content": str(normalized)}


def render_prompt_result(result: object) -> str:
    """渲染 `prompt_result`。"""
    if result is None:
        return ""
    messages = getattr(result, "messages", None)
    if isinstance(messages, list):
        chunks: list[str] = []
        for message in messages:
            content = getattr(message, "content", None)
            if isinstance(content, str):
                chunks.append(content)
                continue
            if not isinstance(content, list):
                continue
            normalized = [to_jsonable(block) for block in content]
            chunks.extend(_extract_text_parts(content, normalized))
        return _join_text_parts(chunks)
    normalized = to_jsonable(result)
    if isinstance(normalized, (dict, list)):
        return render_jsonable(normalized)
    return str(normalized)


def serialize_resource_read_result(result: object) -> tuple[str, dict[str, object]]:
    """序列化 `resource_read_result`。"""
    if result is None:
        return "", {"contents": []}
    contents = getattr(result, "contents", None)
    if not isinstance(contents, list):
        normalized = to_jsonable(result)
        if isinstance(normalized, dict):
            return render_jsonable(normalized), {"contents": normalized}
        return str(normalized), {"contents": []}

    normalized: list[dict[str, object]] = []
    text_parts: list[str] = []
    for item in contents:
        entry = _resource_entry(item)
        normalized.append(entry)
        if isinstance(entry.get("text"), str):
            text_parts.append(str(entry["text"]))
        elif isinstance(entry.get("blob"), str):
            text_parts.append(
                f"[binary blob: {entry.get('mimeType', 'application/octet-stream')}]"
            )
    return _join_text_parts(text_parts), {"contents": normalized}


def _extract_text_parts(raw_items: list[object], normalized_items: list[object]) -> list[str]:
    """提取 `text_parts`。"""
    text_parts: list[str] = []
    for raw_item, normalized in zip(raw_items, normalized_items, strict=False):
        if isinstance(normalized, dict) and isinstance(normalized.get("text"), str):
            text_parts.append(str(normalized["text"]))
            continue
        text = getattr(raw_item, "text", None)
        if isinstance(text, str):
            text_parts.append(text)
    return text_parts


def _join_text_parts(parts: list[str]) -> str:
    """处理 `join_text_parts`。"""
    return "\n".join(part for part in parts if part.strip())


def _resource_entry(item: object) -> dict[str, object]:
    """处理 `resource_entry`。"""
    if isinstance(item, dict):
        return {str(key): to_jsonable(value) for key, value in item.items()}
    entry: dict[str, object] = {}
    for attr in ("uri", "mimeType", "text", "blob"):
        value = getattr(item, attr, None)
        if value is not None:
            entry[attr] = to_jsonable(value)
    return entry
