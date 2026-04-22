from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from claude_code_thy.models import SessionTranscript
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


class Provider(ABC):
    """抽象出不同 LLM 提供方的统一调用接口。"""
    name = "provider"

    @abstractmethod
    async def complete(
        self,
        session: SessionTranscript,
        tools: list[ToolSpec],
    ) -> ProviderResponse:
        """根据会话历史和可用工具生成下一轮响应。"""
        raise NotImplementedError
