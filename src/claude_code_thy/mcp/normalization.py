from __future__ import annotations

import re


def normalize_name_for_mcp(name: str) -> str:
    collapsed = re.sub(r"[^a-zA-Z0-9]+", "_", name.strip())
    collapsed = re.sub(r"_+", "_", collapsed).strip("_")
    return collapsed.lower() or "mcp"
