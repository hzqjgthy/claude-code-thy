from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Literal

from claude_code_thy.models import SessionTranscript
from claude_code_thy.prompts.types import RenderedPrompt
from claude_code_thy.tools.base import ToolSpec


class ProviderError(RuntimeError):
    """统一表示模型提供方调用失败。"""
    pass


class ProviderConfigurationError(RuntimeError):
    """表示提供方初始化时的配置错误。"""
    pass


@dataclass(slots=True)
class ToolCallRequest:
    """描述模型返回的一次工具调用请求。"""
    id: str
    name: str
    input: dict[str, object]


@dataclass(slots=True)
class ProviderResponse:
    """封装一次模型响应中的文本与工具调用。"""
    display_text: str
    content_blocks: list[dict[str, object]] = field(default_factory=list)
    tool_calls: list[ToolCallRequest] = field(default_factory=list)


@dataclass(slots=True)
class ProviderStreamEvent:
    """表示 provider 流式生成过程中的标准化事件。"""
    type: Literal["text_delta", "response"]
    text: str = ""
    response: ProviderResponse | None = None


@dataclass(slots=True)
class ServerSentEvent:
    """表示解析后的单条 SSE 事件。"""
    event: str
    data: str


async def iter_sse_events(response: Any) -> AsyncIterator[ServerSentEvent]:
    """把 HTTP 响应体按标准 SSE 帧解析成事件流。"""
    event_name = ""
    data_lines: list[str] = []

    async for raw_line in response.aiter_lines():
        line = raw_line.rstrip("\r")
        if not line:
            if data_lines:
                yield ServerSentEvent(
                    event=event_name,
                    data="\n".join(data_lines),
                )
            event_name = ""
            data_lines = []
            continue
        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            event_name = line[6:].strip()
            continue
        if line.startswith("data:"):
            data_lines.append(line[5:].strip())

    if data_lines:
        yield ServerSentEvent(
            event=event_name,
            data="\n".join(data_lines),
        )


class Provider(ABC):
    """抽象出不同 LLM 提供方的统一调用接口。"""
    name = "provider"

    @abstractmethod
    async def complete(
        self,
        session: SessionTranscript,
        tools: list[ToolSpec],
        prompt: RenderedPrompt | None = None,
    ) -> ProviderResponse:
        """根据会话历史和可用工具生成下一轮响应。"""
        raise NotImplementedError

    async def stream_complete(
        self,
        session: SessionTranscript,
        tools: list[ToolSpec],
        prompt: RenderedPrompt | None = None,
    ) -> AsyncIterator[ProviderStreamEvent]:
        """默认退化成一次性完成，再把整段文本作为一个 delta 输出。"""
        response = await self.complete(session, tools, prompt=prompt)
        if response.display_text:
            yield ProviderStreamEvent(
                type="text_delta",
                text=response.display_text,
            )
        yield ProviderStreamEvent(
            type="response",
            response=response,
        )

    def build_request_preview(
        self,
        session: SessionTranscript,
        tools: list[ToolSpec],
        prompt: RenderedPrompt | None = None,
    ) -> dict[str, object]:
        """返回当前 provider 将要发送的请求预览。"""
        return {
            "provider": self.name,
            "endpoint": "",
            "method": "POST",
            "headers": {},
            "json_body": {
                "model": session.model,
                "system_text": prompt.system_text if prompt is not None else "",
                "user_context_text": prompt.user_context_text if prompt is not None else "",
                "message_count": len(session.messages),
                "tool_names": [tool.name for tool in tools],
            },
        }

    def _redacted_headers(self, headers: dict[str, str]) -> dict[str, str]:
        """对调试输出中的敏感请求头做脱敏。"""
        redacted: dict[str, str] = {}
        for key, value in headers.items():
            lowered = key.lower()
            if lowered in {"authorization", "x-api-key"} and value:
                redacted[key] = "***"
                continue
            redacted[key] = value
        return redacted
