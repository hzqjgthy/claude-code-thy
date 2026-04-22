from __future__ import annotations

import json
import subprocess

from .auth import get_oauth_authorization_header
from .types import McpServerConfig


def get_server_headers(config: McpServerConfig) -> dict[str, str]:
    """返回 `server_headers`。"""
    headers = {
        **get_oauth_authorization_header(config),
        **dict(config.headers),
    }
    if not config.headers_helper:
        return headers
    try:
        completed = subprocess.run(
            config.headers_helper,
            shell=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except OSError:
        return headers
    if completed.returncode != 0 or not completed.stdout.strip():
        return headers
    try:
        dynamic = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return headers
    if not isinstance(dynamic, dict):
        return headers
    for key, value in dynamic.items():
        if isinstance(key, str) and isinstance(value, str):
            headers[key] = value
    return headers
