from __future__ import annotations

import os


def expand_env_vars(value: str) -> str:
    """展开 `env_vars`。"""
    return os.path.expanduser(os.path.expandvars(value))
