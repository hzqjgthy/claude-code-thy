from __future__ import annotations

import json
from pathlib import Path

from claude_code_thy.mcp.types import McpResourceDefinition


def serialize_resource_read_result(result: object) -> tuple[str, dict[str, object]]:
    if result is None:
        return "", {"contents": []}
    contents = getattr(result, "contents", None)
    if not isinstance(contents, list):
        if isinstance(result, dict):
            return json.dumps(result, ensure_ascii=False, indent=2), {"contents": result}
        return str(result), {"contents": []}

    normalized: list[dict[str, object]] = []
    text_parts: list[str] = []
    for item in contents:
        if isinstance(item, dict):
            entry = dict(item)
        else:
            entry = {}
            for attr in ("uri", "mimeType", "text"):
                value = getattr(item, attr, None)
                if value is not None:
                    entry[attr] = value
        normalized.append(entry)
        if isinstance(entry.get("text"), str):
            text_parts.append(str(entry["text"]))
        elif isinstance(entry.get("blob"), str):
            text_parts.append(f"[binary blob: {entry.get('mimeType', 'application/octet-stream')}]")
    return "\n".join(part for part in text_parts if part.strip()), {"contents": normalized}


def summarize_resources(resources: list[McpResourceDefinition]) -> str:
    if not resources:
        return "No resources found"
    return "\n".join(f"{resource.server}: {resource.name} <{resource.uri}>" for resource in resources)
