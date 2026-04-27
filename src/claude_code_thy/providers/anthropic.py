from __future__ import annotations

import asyncio
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import httpx

from claude_code_thy.config import AppConfig
from claude_code_thy.models import SessionTranscript
from claude_code_thy.providers.base import (
    Provider,
    ProviderError,
    ProviderResponse,
    ProviderStreamEvent,
    ToolCallRequest,
    iter_sse_events,
)
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

    async def stream_complete(
        self,
        session: SessionTranscript,
        tools: list[ToolSpec],
    ):
        """以 SSE 方式流式拉取 Messages 结果，并标准化成文本增量事件。"""
        payload = self._build_payload(session, tools, stream=True)
        endpoint = self._build_endpoint(self.config.anthropic_base_url)
        timeout_s = self.config.api_timeout_ms / 1000
        text_blocks: dict[int, str] = {}
        tool_blocks: dict[int, dict[str, object]] = {}
        tool_input_parts: dict[int, list[str]] = {}

        async with httpx.AsyncClient(
            headers=self._headers(),
            timeout=httpx.Timeout(timeout_s, connect=timeout_s),
        ) as client:
            async with client.stream("POST", endpoint, json=payload) as response:
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as error:
                    raise await self._httpx_error(error) from error

                async for sse in iter_sse_events(response):
                    if sse.data == "[DONE]":
                        break
                    try:
                        data = json.loads(sse.data)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(data, dict):
                        continue

                    event_type = str(data.get("type") or sse.event or "").strip()
                    if event_type == "content_block_start":
                        self._capture_stream_content_block_start(
                            data,
                            text_blocks=text_blocks,
                            tool_blocks=tool_blocks,
                            tool_input_parts=tool_input_parts,
                        )
                        continue
                    if event_type == "content_block_delta":
                        delta = data.get("delta")
                        index = int(data.get("index", -1))
                        if not isinstance(delta, dict) or index < 0:
                            continue
                        delta_type = str(delta.get("type", "")).strip()
                        if delta_type == "text_delta":
                            text = str(delta.get("text", ""))
                            if text:
                                text_blocks[index] = text_blocks.get(index, "") + text
                                yield ProviderStreamEvent(type="text_delta", text=text)
                        elif delta_type == "input_json_delta":
                            partial_json = str(delta.get("partial_json", ""))
                            if partial_json:
                                tool_input_parts.setdefault(index, []).append(partial_json)
                        continue
                    if event_type == "content_block_stop":
                        self._finalize_stream_tool_block(
                            int(data.get("index", -1)),
                            tool_blocks=tool_blocks,
                            tool_input_parts=tool_input_parts,
                        )
                        continue
                    if event_type == "error":
                        raise ProviderError(str(data.get("error") or data))

        yield ProviderStreamEvent(
            type="response",
            response=self._build_stream_response(text_blocks, tool_blocks),
        )

    def _request(
        self,
        session: SessionTranscript,
        tools: list[ToolSpec],
    ) -> ProviderResponse:
        """发送一次 messages 请求，并提取文本块和工具调用块。"""
        endpoint = self._build_endpoint(self.config.anthropic_base_url)
        payload = self._build_payload(session, tools, stream=False)
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

    def _build_payload(
        self,
        session: SessionTranscript,
        tools: list[ToolSpec],
        *,
        stream: bool,
    ) -> dict[str, object]:
        """构造 Anthropic Messages 请求体。"""
        payload: dict[str, object] = {
            "model": session.model or self.config.model,
            "max_tokens": self.config.max_tokens,
            "messages": [self._message_to_api(message) for message in session.messages],
            "stream": stream,
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
        return payload

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

    def _capture_stream_content_block_start(
        self,
        data: dict[str, object],
        *,
        text_blocks: dict[int, str],
        tool_blocks: dict[int, dict[str, object]],
        tool_input_parts: dict[int, list[str]],
    ) -> None:
        """记录流式 content_block_start 事件里的初始块信息。"""
        index = int(data.get("index", -1))
        content_block = data.get("content_block")
        if index < 0 or not isinstance(content_block, dict):
            return
        block_type = str(content_block.get("type", "")).strip()
        if block_type == "text":
            text_blocks[index] = str(content_block.get("text", ""))
            return
        if block_type == "tool_use":
            tool_blocks[index] = {
                "type": "tool_use",
                "id": str(content_block.get("id", "")).strip(),
                "name": str(content_block.get("name", "")).strip(),
                "input": {},
            }
            tool_input_parts[index] = []

    def _finalize_stream_tool_block(
        self,
        index: int,
        *,
        tool_blocks: dict[int, dict[str, object]],
        tool_input_parts: dict[int, list[str]],
    ) -> None:
        """在 tool_use 块结束时解析累计的 JSON 参数。"""
        if index < 0 or index not in tool_blocks:
            return
        raw = "".join(tool_input_parts.get(index, []))
        if not raw.strip():
            tool_blocks[index]["input"] = {}
            return
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as error:
            raise ProviderError(f"工具参数不是有效 JSON object：{raw}") from error
        if not isinstance(parsed, dict):
            raise ProviderError("工具参数必须是 JSON object")
        tool_blocks[index]["input"] = parsed

    def _build_stream_response(
        self,
        text_blocks: dict[int, str],
        tool_blocks: dict[int, dict[str, object]],
    ) -> ProviderResponse:
        """把 Anthropic 流式累积结果恢复成统一 ProviderResponse。"""
        content_blocks: list[dict[str, object]] = []
        tool_calls: list[ToolCallRequest] = []
        texts: list[str] = []

        for index in sorted(set(text_blocks) | set(tool_blocks)):
            if index in text_blocks:
                text = text_blocks[index]
                content_blocks.append({"type": "text", "text": text})
                if text.strip():
                    texts.append(text)
            if index in tool_blocks:
                block = tool_blocks[index]
                content_blocks.append(block)
                tool_calls.append(
                    ToolCallRequest(
                        id=str(block.get("id", "")).strip(),
                        name=str(block.get("name", "")).strip(),
                        input=block.get("input") if isinstance(block.get("input"), dict) else {},
                    )
                )

        display_text = "\n".join(text for text in texts if text.strip()).strip()
        if not display_text and not tool_calls:
            raise ProviderError("响应中没有可显示的文本内容")

        return ProviderResponse(
            display_text=display_text,
            content_blocks=content_blocks,
            tool_calls=tool_calls,
        )

    async def _httpx_error(self, error: httpx.HTTPStatusError) -> ProviderError:
        """尽量读取异步 HTTP 错误响应体，生成更完整的异常信息。"""
        try:
            message = (await error.response.aread()).decode("utf-8", errors="replace")
        except Exception:
            message = str(error)
        return ProviderError(f"HTTP {error.response.status_code}: {message}")
