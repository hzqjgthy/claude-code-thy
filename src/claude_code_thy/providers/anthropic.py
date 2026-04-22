from __future__ import annotations

import asyncio
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from claude_code_thy.config import AppConfig
from claude_code_thy.models import SessionTranscript
from claude_code_thy.providers.base import Provider, ProviderError, ProviderResponse, ToolCallRequest
from claude_code_thy.tools.base import ToolSpec


class AnthropicCompatibleProvider(Provider):
    """兼容 Anthropic Messages 风格接口的 provider 实现。"""
    name = "anthropic-compatible"

    def __init__(self, config: AppConfig) -> None:
        """保存当前 provider 需要的配置项。"""
        self.config = config

    async def complete(
        self,
        session: SessionTranscript,
        tools: list[ToolSpec],
    ) -> ProviderResponse:
        """在线程池中执行同步 HTTP 请求，避免阻塞事件循环。"""
        return await asyncio.to_thread(self._request, session, tools)

    def _request(
        self,
        session: SessionTranscript,
        tools: list[ToolSpec],
    ) -> ProviderResponse:
        """发送一次 messages 请求，并提取文本块和工具调用块。"""
        endpoint = self._build_endpoint(self.config.anthropic_base_url)
        payload = {
            "model": session.model or self.config.model,
            "max_tokens": self.config.max_tokens,
            "messages": [self._message_to_api(message) for message in session.messages],
        }
        if tools:
            payload["tools"] = [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.input_schema,
                }
                for tool in tools
            ]
        request = Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers=self._headers(),
            method="POST",
        )

        try:
            with urlopen(request, timeout=self.config.api_timeout_ms / 1000) as response:
                data = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            try:
                message = error.read().decode("utf-8", errors="replace")
            except Exception:
                message = str(error)
            raise ProviderError(f"HTTP {error.code}: {message}") from error
        except URLError as error:
            raise ProviderError(f"网络错误：{error}") from error
        except json.JSONDecodeError as error:
            raise ProviderError("响应不是有效 JSON") from error

        error = data.get("error")
        if error not in (None, "", {}):
            raise ProviderError(str(error))

        content = data.get("content", [])
        if not isinstance(content, list):
            raise ProviderError("响应中没有有效 content 列表")

        text_blocks: list[str] = []
        tool_calls: list[ToolCallRequest] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text":
                text = str(block.get("text", ""))
                if text.strip():
                    text_blocks.append(text)
            if block.get("type") == "tool_use":
                tool_calls.append(
                    ToolCallRequest(
                        id=str(block.get("id", "")),
                        name=str(block.get("name", "")),
                        input=block.get("input", {}) if isinstance(block.get("input", {}), dict) else {},
                    )
                )

        display_text = "\n".join(text_blocks).strip()
        if not display_text and not tool_calls:
            raise ProviderError("响应中没有可显示的文本内容")

        return ProviderResponse(
            display_text=display_text,
            content_blocks=content,
            tool_calls=tool_calls,
        )

    def _headers(self) -> dict[str, str]:
        """构造 Anthropic 兼容接口所需的请求头。"""
        headers = {
            "content-type": "application/json",
            "anthropic-version": "2023-06-01",
        }
        if self.config.anthropic_api_key:
            headers["x-api-key"] = self.config.anthropic_api_key
        if self.config.anthropic_auth_token:
            headers["Authorization"] = f"Bearer {self.config.anthropic_auth_token}"
        return headers

    def _build_endpoint(self, base_url: str) -> str:
        """兼容根地址、`/v1` 地址和完整 `/messages` 地址。"""
        normalized = base_url.rstrip("/")
        if normalized.endswith("/messages"):
            return normalized
        if normalized.endswith("/v1"):
            return f"{normalized}/messages"
        return f"{normalized}/v1/messages"

    def _message_to_api(self, message) -> dict[str, object]:
        """把本地消息转换成 Anthropic Messages API 需要的消息结构。"""
        if message.role == "tool":
            return {
                "role": "user",
                "content": message.content_blocks or [{"type": "text", "text": message.text}],
            }
        return {
            "role": message.role,
            "content": message.content_blocks or [{"type": "text", "text": message.text}],
        }
