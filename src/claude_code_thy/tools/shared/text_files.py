from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class TextFileSnapshot:
    """表示 `TextFileSnapshot`。"""
    content: str
    encoding: str
    newline: str
    had_bom: bool = False


def read_text_snapshot(path: Path) -> TextFileSnapshot:
    """读取 `text_snapshot`。"""
    raw = path.read_bytes()
    had_bom = raw.startswith(b"\xff\xfe")
    encoding = "utf-16le" if had_bom else "utf-8"
    content = (
        raw[2:].decode("utf-16le", errors="replace")
        if had_bom
        else raw.decode("utf-8", errors="replace")
    )
    newline = detect_newline(content)
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    return TextFileSnapshot(
        content=normalized,
        encoding=encoding,
        newline=newline,
        had_bom=had_bom,
    )


def write_text_snapshot(
    path: Path,
    content: str,
    *,
    encoding: str = "utf-8",
    newline: str = "\n",
    had_bom: bool = False,
) -> None:
    """写入 `text_snapshot`。"""
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    if newline == "\r\n":
        normalized = normalized.replace("\n", "\r\n")
    elif newline == "\r":
        normalized = normalized.replace("\n", "\r")

    if encoding == "utf-16le":
        data = normalized.encode("utf-16le")
        if had_bom:
            data = b"\xff\xfe" + data
        path.write_bytes(data)
        return

    path.write_text(normalized, encoding="utf-8")


def detect_newline(text: str) -> str:
    """处理 `detect_newline`。"""
    if "\r\n" in text:
        return "\r\n"
    if "\r" in text:
        return "\r"
    return "\n"
