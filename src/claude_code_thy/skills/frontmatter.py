from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass(slots=True)
class FrontmatterDocument:
    metadata: dict[str, object]
    content: str


def parse_frontmatter_document(text: str) -> FrontmatterDocument:
    if not text.startswith("---\n"):
        return FrontmatterDocument(metadata={}, content=text)

    lines = text.splitlines()
    end_index = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            end_index = index
            break
    if end_index is None:
        return FrontmatterDocument(metadata={}, content=text)

    metadata = _parse_frontmatter_lines(lines[1:end_index])
    content = "\n".join(lines[end_index + 1 :]).lstrip("\n")
    return FrontmatterDocument(metadata=metadata, content=content)


def parse_bool(value: object, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "on", "1"}:
            return True
        if normalized in {"false", "no", "off", "0"}:
            return False
    return default


def parse_string_list(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return ()
        if stripped.startswith("[") and stripped.endswith("]"):
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, list):
                return tuple(str(item).strip() for item in parsed if str(item).strip())
        return tuple(
            part.strip()
            for part in stripped.replace("\n", ",").split(",")
            if part.strip()
        )
    if isinstance(value, list):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return ()


def extract_description_from_markdown(content: str) -> str:
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("```"):
            continue
        if line.startswith("#"):
            line = line.lstrip("#").strip()
            if line:
                return line
            continue
        if line.startswith(("-", "*")):
            line = line[1:].strip()
        if line:
            return line
    return "Skill"


def normalize_frontmatter_key(key: str) -> str:
    return key.strip().lower().replace("_", "-")


def _parse_frontmatter_lines(lines: list[str]) -> dict[str, object]:
    result: dict[str, object] = {}
    index = 0
    while index < len(lines):
        raw = lines[index]
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            index += 1
            continue
        if ":" not in raw:
            index += 1
            continue

        key, value = raw.split(":", 1)
        normalized_key = normalize_frontmatter_key(key)
        value = value.strip()

        if value:
            result[normalized_key] = _parse_scalar(value)
            index += 1
            continue

        list_items: list[object] = []
        index += 1
        while index < len(lines):
            nested = lines[index]
            if not nested.startswith(("  ", "\t")):
                break
            nested_value = nested.strip()
            if nested_value.startswith("- "):
                list_items.append(_parse_scalar(nested_value[2:].strip()))
            elif nested_value:
                list_items.append(_parse_scalar(nested_value))
            index += 1

        if list_items:
            result[normalized_key] = list_items
        else:
            result[normalized_key] = ""
    return result


def _parse_scalar(value: str) -> object:
    stripped = value.strip()
    if not stripped:
        return ""
    if stripped.startswith(("'", '"')) and stripped.endswith(("'", '"')) and len(stripped) >= 2:
        return stripped[1:-1]
    lowered = stripped.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if stripped.startswith("[") and stripped.endswith("]"):
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            return stripped
        if isinstance(parsed, list):
            return [str(item) if not isinstance(item, (str, bool, int, float)) else item for item in parsed]
        return parsed
    return stripped
