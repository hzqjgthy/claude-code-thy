from __future__ import annotations

import json
from pathlib import Path

from .records import SessionLogRecord


class JsonlWriter:
    """负责把结构化日志逐条追加到 `.jsonl` 文件。"""

    def append(self, path: Path, record: SessionLogRecord) -> None:
        """以 JSONL 形式追加一条记录。"""
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record.to_dict(), ensure_ascii=False))
            handle.write("\n")
            handle.flush()
