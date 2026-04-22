from __future__ import annotations

import json
import re
from pathlib import Path

from claude_code_thy.settings import validate_settings_document
from claude_code_thy.tools.base import ToolError


SECRET_PATTERNS = [
    ("api_key", re.compile(r"(?i)(api[_-]?key|token|secret)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{16,}")),
    ("private_key", re.compile(r"-----BEGIN [A-Z ]+PRIVATE KEY-----")),
]


def check_secret_like_content(file_path: Path, content: str) -> None:
    """检查 `secret_like_content`。"""
    normalized = str(file_path).lower()
    if "team" not in normalized and "memory" not in normalized:
        return
    labels = [label for label, pattern in SECRET_PATTERNS if pattern.search(content)]
    if labels:
        raise ToolError(
            f"Content contains potential secrets ({', '.join(labels)}) and cannot be written to team memory."
        )


def validate_settings_file_content(file_path: Path, content: str) -> None:
    """校验 `settings_file_content`。"""
    if not _is_settings_file(file_path):
        return
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as error:
        raise ToolError(f"设置文件 JSON 无效：{error}") from error
    errors = validate_settings_document(parsed)
    if errors:
        raise ToolError("设置文件无效：" + " ".join(errors))


def _is_settings_file(file_path: Path) -> bool:
    """返回是否满足 `is_settings_file` 条件。"""
    return file_path.name in {"settings.json", "settings.local.json"} and ".claude-code-thy" in str(file_path)
