from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel


def encode_sse(event: str, payload: BaseModel | dict[str, Any] | list[Any] | str) -> bytes:
    """把结构化数据编码成标准 SSE 数据帧。"""
    if isinstance(payload, BaseModel):
        data = payload.model_dump(mode="json")
    else:
        data = payload
    if isinstance(data, str):
        text = data
    else:
        text = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {text}\n\n".encode("utf-8")
