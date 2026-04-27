from __future__ import annotations

import asyncio
import hashlib
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import httpx

from claude_code_thy.config import AppConfig
from claude_code_thy.models import ChatMessage, SessionTranscript
from claude_code_thy.prompts.types import RenderedPrompt
from claude_code_thy.providers.base import (
    Provider,
    ProviderError,
    ProviderResponse,
    ProviderStreamEvent,
    ToolCallRequest,
    iter_sse_events,
)
from claude_code_thy.tools.base import ToolSpec


DEFAULT_OPENAI_RESPONSES_USER_AGENT = "python-requests/2.31.0"
OPENAI_RESPONSES_STATE_KEY = "openai_responses"


class OpenAIResponsesProvider(Provider):
    """兼容 OpenAI Responses 风格接口，并负责本地会话到请求体的映射。"""
    name = "openai-responses-compatible"

    def __init__(self, config: AppConfig) -> None:
        """保存当前 provider 需要的配置项。"""
        self.config = config

    async def complete(
        self,
        session: SessionTranscript,
        tools: list[ToolSpec],
        prompt: RenderedPrompt | None = None,
    ) -> ProviderResponse:
        """在线程池中发起同步 HTTP 请求，避免阻塞事件循环。"""
        return await asyncio.to_thread(self._request, session, tools, prompt)

    async def stream_complete(
        self,
        session: SessionTranscript,
        tools: list[ToolSpec],
        prompt: RenderedPrompt | None = None,
    ):
        """以 SSE 方式流式拉取 Responses 结果，并产出标准化增量事件。"""
        payload = self._build_payload(session, tools, prompt=prompt)
        try:
            if prompt is None:
                async for event in self._stream_request(session, tools, payload):
                    yield event
            else:
                async for event in self._stream_request(session, tools, payload, prompt):
                    yield event
        except httpx.HTTPStatusError as error:
            if "previous_response_id" in payload:
                state = self._provider_state(session)
                state["use_previous_response_id"] = False
                fallback_payload = self._build_payload(
                    session,
                    tools,
                    prompt=prompt,
                    force_full_history=True,
                )
                try:
                    if prompt is None:
                        async for event in self._stream_request(session, tools, fallback_payload):
                            yield event
                    else:
                        async for event in self._stream_request(session, tools, fallback_payload, prompt):
                            yield event
                except httpx.HTTPStatusError as fallback_error:
                    raise await self._httpx_error(fallback_error) from fallback_error
            else:
                raise await self._httpx_error(error) from error
        except httpx.HTTPError as error:
            raise ProviderError(str(error)) from error

    def _request(
        self,
        session: SessionTranscript,
        tools: list[ToolSpec],
        prompt: RenderedPrompt | None = None,
    ) -> ProviderResponse:
        """发送一次 Responses 请求，并把返回结果整理成统一 ProviderResponse。"""
        state = self._provider_state(session)
        payload = self._build_payload(session, tools, prompt=prompt)

        try:
            data = self._send_payload(payload)
        except HTTPError as error:
            if "previous_response_id" in payload:
                state["use_previous_response_id"] = False
                fallback_payload = self._build_payload(
                    session,
                    tools,
                    prompt=prompt,
                    force_full_history=True,
                )
                try:
                    data = self._send_payload(fallback_payload)
                except HTTPError as fallback_error:
                    raise self._http_error(fallback_error) from fallback_error
            else:
                raise self._http_error(error) from error
        except URLError as error:
            raise ProviderError(f"网络错误：{error}") from error
        except json.JSONDecodeError as error:
            raise ProviderError("响应不是有效 JSON") from error

        error = data.get("error")
        if error not in (None, "", {}):
            raise ProviderError(self._stringify_error(error))

        output = data.get("output", [])
        if not isinstance(output, list):
            raise ProviderError("响应中没有有效 output 列表")

        display_text = self._extract_output_text(output)
        tool_calls = self._extract_tool_calls(output)
        if not display_text and not tool_calls:
            raise ProviderError("响应中没有可显示文本或可执行工具调用")

        response_id = str(data.get("id", "")).strip()
        if response_id:
            state["last_response_id"] = response_id
            state["last_response_message_count"] = len(session.messages) + 1
            state["last_prompt_fingerprint"] = self._prompt_fingerprint(prompt)

        return ProviderResponse(
            display_text=display_text,
            content_blocks=output,
            tool_calls=tool_calls,
        )

    async def _stream_request(
        self,
        session: SessionTranscript,
        tools: list[ToolSpec],
        payload: dict[str, object],
        prompt: RenderedPrompt | None = None,
    ):
        """发起一条流式 Responses 请求，并把增量文本和最终响应统一输出。"""
        stream_payload = dict(payload)
        stream_payload["stream"] = True
        endpoint = self._build_endpoint(self.config.openai_responses_base_url)
        timeout_s = self.config.api_timeout_ms / 1000
        text_parts: list[str] = []
        completed_response: ProviderResponse | None = None
        pending_tool_calls: dict[str, dict[str, object]] = {}

        async with httpx.AsyncClient(
            headers=self._headers(),
            timeout=httpx.Timeout(timeout_s, connect=timeout_s),
        ) as client:
            async with client.stream("POST", endpoint, json=stream_payload) as response:
                response.raise_for_status()
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
                    if event_type == "response.output_text.delta":
                        delta = str(data.get("delta", ""))
                        if delta:
                            text_parts.append(delta)
                            yield ProviderStreamEvent(type="text_delta", text=delta)
                        continue
                    if event_type == "response.output_item.added":
                        self._capture_stream_tool_item(pending_tool_calls, data.get("item"))
                        continue
                    if event_type == "response.output_item.done":
                        self._capture_stream_tool_item(pending_tool_calls, data.get("item"))
                        continue
                    if event_type == "response.function_call_arguments.delta":
                        item_id = str(data.get("item_id", "")).strip()
                        delta = str(data.get("delta", ""))
                        if item_id and delta:
                            pending_tool_calls.setdefault(item_id, {}).setdefault("arguments_parts", []).append(delta)
                        continue
                    if event_type == "response.function_call_arguments.done":
                        item_id = str(data.get("item_id", "")).strip()
                        arguments = str(data.get("arguments", ""))
                        if item_id:
                            pending_tool_calls.setdefault(item_id, {})["arguments"] = arguments
                        continue
                    if event_type == "response.completed":
                        response_payload = data.get("response")
                        if isinstance(response_payload, dict):
                            completed_response = self._provider_response_from_payload(
                                session,
                                response_payload,
                                prompt=prompt,
                            )
                        continue
                    if event_type == "error":
                        raise ProviderError(self._stringify_error(data.get("error") or data))

        if completed_response is None:
            completed_response = self._fallback_stream_response(session, text_parts, pending_tool_calls)
        yield ProviderStreamEvent(type="response", response=completed_response)

    def _build_payload(
        self,
        session: SessionTranscript,
        tools: list[ToolSpec],
        prompt: RenderedPrompt | None = None,
        *,
        force_full_history: bool = False,
    ) -> dict[str, object]:
        """根据会话状态组装请求体，并决定走全量历史还是增量续写。"""
        payload = {
            "model": session.model or self.config.model,
            "stream": False,
            "parallel_tool_calls": False,
            "max_output_tokens": self.config.max_tokens,
        }
        if prompt is not None and prompt.system_text.strip():
            payload["instructions"] = prompt.system_text

        previous_response_id = None if force_full_history else self._previous_response_id_for_request(session, prompt)
        if previous_response_id:
            payload["previous_response_id"] = previous_response_id
            payload["input"] = self._build_incremental_input(session)
        else:
            payload["input"] = self._build_input(session, prompt=prompt)

        if tools:
            payload["tools"] = [self._tool_to_api(tool) for tool in tools]
        if self.config.openai_responses_reasoning_effort:
            payload["reasoning"] = {"effort": self.config.openai_responses_reasoning_effort}
        return payload

    def _send_payload(self, payload: dict[str, object]) -> dict[str, object]:
        """把请求体 POST 到 Responses 端点并解析 JSON 响应。"""
        request = Request(
            self._build_endpoint(self.config.openai_responses_base_url),
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=self._headers(),
            method="POST",
        )
        with urlopen(request, timeout=self.config.api_timeout_ms / 1000) as response:
            return json.loads(response.read().decode("utf-8"))

    def build_request_preview(
        self,
        session: SessionTranscript,
        tools: list[ToolSpec],
        prompt: RenderedPrompt | None = None,
    ) -> dict[str, object]:
        """构造一份不包含敏感认证信息的 Responses 请求预览。"""
        payload = self._build_payload(session, tools, prompt=prompt, force_full_history=False)
        return {
            "provider": self.name,
            "endpoint": self._build_endpoint(self.config.openai_responses_base_url),
            "method": "POST",
            "headers": self._redacted_headers(self._headers()),
            "json_body": payload,
        }

    def _provider_response_from_payload(
        self,
        session: SessionTranscript,
        payload: dict[str, object],
        *,
        prompt: RenderedPrompt | None = None,
    ) -> ProviderResponse:
        """把完整 Responses payload 转换成统一 ProviderResponse，并更新会话状态。"""
        output = payload.get("output", [])
        if not isinstance(output, list):
            raise ProviderError("响应中没有有效 output 列表")

        display_text = self._extract_output_text(output)
        tool_calls = self._extract_tool_calls(output)
        if not display_text and not tool_calls:
            raise ProviderError("响应中没有可显示文本或可执行工具调用")

        response_id = str(payload.get("id", "")).strip()
        if response_id:
            state = self._provider_state(session)
            state["last_response_id"] = response_id
            state["last_response_message_count"] = len(session.messages) + 1
            state["last_prompt_fingerprint"] = self._prompt_fingerprint(prompt)

        return ProviderResponse(
            display_text=display_text,
            content_blocks=output,
            tool_calls=tool_calls,
        )

    def _fallback_stream_response(
        self,
        session: SessionTranscript,
        text_parts: list[str],
        pending_tool_calls: dict[str, dict[str, object]],
    ) -> ProviderResponse:
        """在没有 response.completed 全量载荷时，用流式累积结果兜底构造响应。"""
        tool_calls: list[ToolCallRequest] = []
        for builder in pending_tool_calls.values():
            name = str(builder.get("name", "")).strip()
            call_id = str(builder.get("call_id") or builder.get("id") or "").strip()
            if not name or not call_id:
                continue
            arguments = str(builder.get("arguments", "")).strip()
            if not arguments:
                parts = builder.get("arguments_parts", [])
                if isinstance(parts, list):
                    arguments = "".join(str(part) for part in parts)
            tool_calls.append(
                ToolCallRequest(
                    id=call_id,
                    name=name,
                    input=self._parse_json_object(arguments),
                )
            )
        display_text = "".join(text_parts)
        if not display_text and not tool_calls:
            raise ProviderError("流式响应在结束前没有生成文本或工具调用")
        return ProviderResponse(
            display_text=display_text,
            content_blocks=[],
            tool_calls=tool_calls,
        )

    def _capture_stream_tool_item(
        self,
        pending_tool_calls: dict[str, dict[str, object]],
        item: object,
    ) -> None:
        """从流式 output item 中提取 function_call 的标识和基础元数据。"""
        if not isinstance(item, dict):
            return
        if str(item.get("type", "")).strip() != "function_call":
            return
        item_id = str(item.get("id", "")).strip()
        if not item_id:
            return
        builder = pending_tool_calls.setdefault(item_id, {})
        builder["id"] = item_id
        builder["call_id"] = str(item.get("call_id") or item_id).strip()
        builder["name"] = str(item.get("name", "")).strip()
        arguments = str(item.get("arguments", "")).strip()
        if arguments:
            builder["arguments"] = arguments

    def _previous_response_id_for_request(
        self,
        session: SessionTranscript,
        prompt: RenderedPrompt | None,
    ) -> str | None:
        """在启用该特性时，取出上一轮返回的 response id 供续写使用。"""
        if not self.config.openai_responses_use_previous_response_id:
            return None
        state = self._provider_state(session)
        if state.get("use_previous_response_id", True) is False:
            return None
        stored_fingerprint = str(state.get("last_prompt_fingerprint", ""))
        if stored_fingerprint != self._prompt_fingerprint(prompt):
            return None
        response_id = str(state.get("last_response_id", "")).strip()
        if not response_id:
            return None
        message_count = state.get("last_response_message_count")
        if not isinstance(message_count, int):
            return None
        if message_count < 0 or message_count > len(session.messages):
            return None
        return response_id

    def _build_incremental_input(self, session: SessionTranscript) -> list[dict[str, object]]:
        """只把上一轮响应之后新增的消息转换成增量输入。"""
        state = self._provider_state(session)
        message_count = state.get("last_response_message_count")
        if not isinstance(message_count, int):
            return self._build_input(session, prompt=None)
        new_messages = session.messages[message_count:]
        items: list[dict[str, object]] = []
        for message in new_messages:
            items.extend(self._message_to_input_items(message))
        return items

    def _provider_state(self, session: SessionTranscript) -> dict[str, object]:
        """在会话运行态里取出本 provider 的私有缓存。"""
        state = session.runtime_state.get(OPENAI_RESPONSES_STATE_KEY)
        if isinstance(state, dict):
            return state
        fresh: dict[str, object] = {}
        session.runtime_state[OPENAI_RESPONSES_STATE_KEY] = fresh
        return fresh

    def _build_input(
        self,
        session: SessionTranscript,
        *,
        prompt: RenderedPrompt | None = None,
    ) -> list[dict[str, object]]:
        """把整个会话历史转换成 Responses API 的 input 数组。"""
        items: list[dict[str, object]] = []
        if prompt is not None and prompt.user_context_text.strip():
            items.append(self._message_item("user", prompt.user_context_text))
        for message in session.messages:
            items.extend(self._message_to_input_items(message))
        return items

    def _prompt_fingerprint(self, prompt: RenderedPrompt | None) -> str:
        """把当前 prompt 关键文本收敛成一个稳定指纹，用于 previous_response_id 复用判断。"""
        if prompt is None:
            return ""
        payload = f"{prompt.system_text}\n\n{prompt.user_context_text}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _message_to_input_items(self, message: ChatMessage) -> list[dict[str, object]]:
        """按消息角色把本地消息映射成 Responses API 支持的输入块。"""
        if message.role == "user":
            return [self._message_item("user", message.text)]
        if message.role == "assistant":
            return self._assistant_items(message)
        if message.role == "tool":
            return self._tool_items(message)
        return []

    def _assistant_items(self, message: ChatMessage) -> list[dict[str, object]]:
        """把助手文本和工具调用历史转换成可续写的上下文片段。"""
        items: list[dict[str, object]] = []
        if message.text.strip():
            items.append(
                self._message_item(
                    "user",
                    f"上一轮助手回复（仅作上下文参考）：\n{message.text}",
                )
            )
        for tool_call in self._tool_calls_from_message(message):
            call_id = str(tool_call.get("id") or tool_call.get("call_id") or "").strip()
            name = str(tool_call.get("name", "")).strip()
            if not call_id or not name:
                continue
            arguments = tool_call.get("input", {})
            if not isinstance(arguments, dict):
                arguments = {}
            items.append(
                {
                    "type": "function_call",
                    "call_id": call_id,
                    "name": name,
                    "arguments": json.dumps(arguments, ensure_ascii=False),
                }
            )
        return items

    def _tool_items(self, message: ChatMessage) -> list[dict[str, object]]:
        """把 tool 消息优先转成结构化 function_call_output，无法结构化时退化成文本。"""
        metadata = message.metadata or {}
        blocks = message.content_blocks or []
        call_id = str(metadata.get("tool_use_id", "")).strip()
        raw_output: object = message.text

        if blocks and isinstance(blocks[0], dict):
            first = blocks[0]
            if not call_id:
                call_id = str(first.get("tool_use_id") or first.get("call_id") or "").strip()
            if first.get("type") == "function_call_output":
                raw_output = first.get("output", message.text)
            elif first.get("type") == "tool_result":
                raw_output = first.get("content", message.text)

        if call_id:
            return [
                {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": self._serialize_tool_output(raw_output),
                }
            ]

        tool_name = str(metadata.get("tool_name", "")).strip()
        fallback = message.text.strip()
        if tool_name:
            fallback = f"Tool `{tool_name}` result:\n{fallback}".strip()
        if not fallback:
            return []
        return [self._message_item("user", fallback)]

    def _tool_calls_from_message(self, message: ChatMessage) -> list[dict[str, object]]:
        """从 assistant 消息的 metadata 或 content_blocks 中提取工具调用记录。"""
        metadata = message.metadata or {}
        metadata_calls = metadata.get("tool_calls")
        if isinstance(metadata_calls, list):
            return [item for item in metadata_calls if isinstance(item, dict)]

        calls: list[dict[str, object]] = []
        for block in message.content_blocks or []:
            if not isinstance(block, dict):
                continue
            block_type = str(block.get("type", "")).strip()
            if block_type == "function_call":
                calls.append(
                    {
                        "id": block.get("call_id") or block.get("id"),
                        "name": block.get("name"),
                        "input": self._parse_json_object(str(block.get("arguments", "") or "")),
                    }
                )
            elif block_type == "tool_use":
                calls.append(
                    {
                        "id": block.get("id"),
                        "name": block.get("name"),
                        "input": block.get("input") if isinstance(block.get("input"), dict) else {},
                    }
                )
        return calls

    def _extract_output_text(self, output: list[dict[str, object]]) -> str:
        """从 Responses 的 output 列表中拼出可直接展示的文本。"""
        texts: list[str] = []
        for item in output:
            if not isinstance(item, dict):
                continue
            if str(item.get("type", "")).strip() != "message":
                continue
            for content in item.get("content", []) or []:
                if not isinstance(content, dict):
                    continue
                content_type = str(content.get("type", "")).strip()
                if content_type in {"output_text", "text"}:
                    text = str(content.get("text", ""))
                    if text.strip():
                        texts.append(text)
        return "\n".join(texts).strip()

    def _extract_tool_calls(self, output: list[dict[str, object]]) -> list[ToolCallRequest]:
        """从 Responses 返回中提取待执行的 function_call。"""
        calls: list[ToolCallRequest] = []
        for item in output:
            if not isinstance(item, dict):
                continue
            if str(item.get("type", "")).strip() != "function_call":
                continue
            name = str(item.get("name", "")).strip()
            call_id = str(item.get("call_id") or item.get("id") or "").strip()
            if not name or not call_id:
                continue
            arguments = self._parse_json_object(str(item.get("arguments", "") or ""))
            calls.append(
                ToolCallRequest(
                    id=call_id,
                    name=name,
                    input=arguments,
                )
            )
        return calls

    def _tool_to_api(self, tool: ToolSpec) -> dict[str, object]:
        """把内部工具定义转换成 Responses API 所需的 function schema。"""
        return {
            "type": "function",
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.input_schema,
            "strict": False,
        }

    def _headers(self) -> dict[str, str]:
        """构造请求头，并在配置存在时附带鉴权信息。"""
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": DEFAULT_OPENAI_RESPONSES_USER_AGENT,
        }
        if self.config.openai_responses_api_key:
            headers["Authorization"] = f"Bearer {self.config.openai_responses_api_key}"
        return headers

    def _build_endpoint(self, base_url: str) -> str:
        """兼容传入根地址、`/v1` 地址和完整 `/responses` 地址。"""
        normalized = base_url.rstrip("/")
        if normalized.endswith("/responses"):
            return normalized
        if normalized.endswith("/v1"):
            return f"{normalized}/responses"
        return f"{normalized}/v1/responses"

    def _message_item(self, role: str, text: str) -> dict[str, object]:
        """创建最基础的文本消息输入块。"""
        return {
            "type": "message",
            "role": role,
            "content": [{"type": "input_text", "text": text}],
        }

    def _parse_json_object(self, raw: str) -> dict[str, object]:
        """把工具参数字符串解析成 JSON object，并在格式错误时抛出 provider 错误。"""
        text = raw.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as error:
            raise ProviderError(f"工具参数不是有效 JSON object：{text}") from error
        if not isinstance(parsed, dict):
            raise ProviderError("工具参数必须是 JSON object")
        return parsed

    def _serialize_tool_output(self, value: object) -> str:
        """把工具输出尽量稳定地转成字符串，供 function_call_output 使用。"""
        if isinstance(value, str):
            return value
        try:
            return json.dumps(value, ensure_ascii=False)
        except TypeError:
            return str(value)

    def _stringify_error(self, error: object) -> str:
        """把服务端返回的错误结构整理成便于展示的文本。"""
        if isinstance(error, str):
            return error
        if isinstance(error, dict):
            code = str(error.get("code", "")).strip()
            message = str(error.get("message", "")).strip()
            if code and message:
                return f"{code}: {message}"
            if message:
                return message
            return json.dumps(error, ensure_ascii=False)
        return str(error)

    def _http_error(self, error: HTTPError) -> ProviderError:
        """尽量读取 HTTP 错误响应体，生成更完整的异常信息。"""
        try:
            message = error.read().decode("utf-8", errors="replace")
        except Exception:
            message = str(error)
        return ProviderError(f"HTTP {error.code}: {message}")

    async def _httpx_error(self, error: httpx.HTTPStatusError) -> ProviderError:
        """尽量读取异步 HTTP 错误响应体，生成更完整的异常信息。"""
        try:
            message = (await error.response.aread()).decode("utf-8", errors="replace")
        except Exception:
            message = str(error)
        return ProviderError(f"HTTP {error.response.status_code}: {message}")
