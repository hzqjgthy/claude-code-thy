from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class EditInstruction:
    old_string: str
    new_string: str
    replace_all: bool = False
