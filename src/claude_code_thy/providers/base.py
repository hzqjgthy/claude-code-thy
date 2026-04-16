from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from claude_code_thy.models import SessionTranscript
from claude_code_thy.tools.base import ToolSpec


class ProviderError(RuntimeError):
    pass


class ProviderConfigurationError(RuntimeError):
    pass


@dataclass(slots=True)
class ToolCallRequest:
    id: str
    name: str
    input: dict[str, object]


@dataclass(slots=True)
class ProviderResponse:
    display_text: str
    content_blocks: list[dict[str, object]] = field(default_factory=list)
    tool_calls: list[ToolCallRequest] = field(default_factory=list)


class Provider(ABC):
    name = "provider"

    @abstractmethod
    async def complete(
        self,
        session: SessionTranscript,
        tools: list[ToolSpec],
    ) -> ProviderResponse:
        raise NotImplementedError
