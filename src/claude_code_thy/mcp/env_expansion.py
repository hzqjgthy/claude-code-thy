from __future__ import annotations

import os


def expand_env_vars(value: str) -> str:
    return os.path.expanduser(os.path.expandvars(value))
