from __future__ import annotations

from pathlib import Path


class TextWriter:
    """负责把人类可读日志追加到 `.log` 文件。"""

    def append(self, path: Path, text: str) -> None:
        """把一段已经格式化好的文本追加到日志文件。"""
        if not text:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(text)
            if not text.endswith("\n"):
                handle.write("\n")
            handle.flush()
