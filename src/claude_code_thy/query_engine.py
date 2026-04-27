from __future__ import annotations

import asyncio
from typing import Callable

from claude_code_thy.models import ChatMessage, SessionTranscript
from claude_code_thy.prompts.types import RenderedPrompt
from claude_code_thy.session.runtime_state import clear_pending_permission, set_pending_permission
from claude_code_thy.providers.base import Provider, ProviderError, ProviderResponse
from claude_code_thy.session.store import SessionStore
from claude_code_thy.tools import (
    PermissionRequiredError,
    ToolError,
    ToolEvent,
    ToolEventHandler,
    ToolRuntime,
)

TextDeltaHandler = Callable[[str], None]
MessageAddedHandler = Callable[[int, ChatMessage], None]


class QueryEngine:
    """驱动一轮对话完成、工具执行和权限暂停/恢复的主循环。"""
    def __init__(
        self,
        *,
        provider: Provider,
        session_store: SessionStore,
        tool_runtime: ToolRuntime,
        max_iterations: int = 1000,
    ) -> None:
        """注入模型提供方、会话存储、工具运行时和单轮最大自动推进次数。"""
        self.provider = provider
        self.session_store = session_store
        self.tool_runtime = tool_runtime
        self.max_iterations = max(1, max_iterations)

    async def submit(
        self,
        session: SessionTranscript,
        prompt: str,
        *,
        tool_event_handler: ToolEventHandler | None = None,
    ) -> SessionTranscript:
        """把用户输入写入会话后，持续推进直到模型停下或等待权限。"""
        session.add_message(
            "user",
            prompt,
            content_blocks=[{"type": "text", "text": prompt}],
        )
        self.session_store.save(session)
        return await self._complete_until_pause(
            session,
            tool_event_handler=tool_event_handler,
        )

    async def stream_submit(
        self,
        session: SessionTranscript,
        prompt: str,
        *,
        tool_event_handler: ToolEventHandler | None = None,
        text_delta_handler: TextDeltaHandler | None = None,
        message_added_handler: MessageAddedHandler | None = None,
    ) -> SessionTranscript:
        """把用户输入写入会话后，以流式方式推进整轮“模型 -> 工具 -> 模型”。"""
        session.add_message(
            "user",
            prompt,
            content_blocks=[{"type": "text", "text": prompt}],
        )
        self.session_store.save(session)
        self._emit_message_added(session, message_added_handler)
        return await self._complete_until_pause_stream(
            session,
            tool_event_handler=tool_event_handler,
            text_delta_handler=text_delta_handler,
            message_added_handler=message_added_handler,
        )

    async def resume_pending_tool_call(
        self,
        session: SessionTranscript,
        pending: dict[str, object],
        *,
        approved: bool,
        tool_event_handler: ToolEventHandler | None = None,
    ) -> SessionTranscript:
        """在用户确认后恢复上一次被权限中断的工具调用。"""
        tool_name = str(pending.get("tool_name", "")).strip()
        tool_use_id = str(pending.get("tool_use_id", "")).strip() or None
        input_data = pending.get("input_data", {})
        original_input = pending.get("original_input", {})
        request = pending.get("request", {})

        if not tool_name or not isinstance(input_data, dict):
            clear_pending_permission(session)
            self.session_store.save(session)
            return session

        clear_pending_permission(session)

        if approved:
            try:
                result = await self._execute_tool_input(
                    tool_name,
                    input_data,
                    session,
                    tool_use_id=tool_use_id,
                    original_input=original_input if isinstance(original_input, dict) else None,
                    event_handler=tool_event_handler,
                )
            except PermissionRequiredError as error:
                return self._pause_for_permission(
                    session,
                    error,
                    tool_name=tool_name,
                    input_data=input_data,
                    tool_use_id=tool_use_id,
                    tool_event_handler=tool_event_handler,
                )
            except ToolError as error:
                self._append_tool_error(
                    session,
                    tool_name,
                    f"工具 `{tool_name}` 执行失败：{error}",
                    tool_use_id=tool_use_id,
                )
                self.session_store.save(session)
                return await self._complete_until_pause(
                    session,
                    tool_event_handler=tool_event_handler,
                )

            self._append_tool_result(session, result, tool_use_id=tool_use_id)
            self.session_store.save(session)
            if self._should_pause_after_tool_result(tool_name):
                return session
            return await self._complete_until_pause(
                session,
                tool_event_handler=tool_event_handler,
            )

        denied_reason = ""
        if isinstance(request, dict):
            denied_reason = str(request.get("reason", "")).strip()
        rejected = self.tool_runtime.render_rejected(
            tool_name,
            input_data if isinstance(input_data, dict) else {},
            session,
            surface="model",
            reason=denied_reason or f"工具 `{tool_name}` 执行被用户拒绝。",
            tool_use_id=tool_use_id,
            original_input=original_input if isinstance(original_input, dict) else None,
        )
        self._append_tool_result(session, rejected, tool_use_id=tool_use_id)
        self.session_store.save(session)
        return await self._complete_until_pause(
            session,
            tool_event_handler=tool_event_handler,
        )

    async def _complete_until_pause(
        self,
        session: SessionTranscript,
        *,
        tool_event_handler: ToolEventHandler | None = None,
    ) -> SessionTranscript:
        """循环执行“模型回复 -> 工具调用”，直到拿到最终文本或需要暂停。"""
        for _ in range(self.max_iterations):
            try:
                await self.tool_runtime.warm_tool_specs_for_session(session)
                rendered_prompt = self._build_rendered_prompt(session)
                response = await self.provider.complete(
                    session,
                    self.tool_runtime.list_tool_specs_for_session(
                        session,
                        allow_sync_refresh=False,
                    ),
                    prompt=rendered_prompt,
                )
            except ProviderError as error:
                session.add_message("assistant", f"API 调用失败：{error}")
                self.session_store.save(session)
                return session

            session.add_message(
                "assistant",
                response.display_text,
                content_blocks=response.content_blocks,
                metadata={
                    "tool_calls": [
                        {"id": call.id, "name": call.name, "input": call.input}
                        for call in response.tool_calls
                    ]
                }
                if response.tool_calls
                else None,
            )
            self.session_store.save(session)

            if not response.tool_calls:
                return session

            for call in response.tool_calls:
                if tool_event_handler is not None:
                    tool_event_handler(
                        ToolEvent(
                            tool_name=call.name,
                            phase="queued",
                            summary=f"准备执行 {call.name}",
                            metadata={"input": call.input},
                        )
                    )
                try:
                    result = await self._execute_tool_input(
                        call.name,
                        call.input,
                        session,
                        tool_use_id=call.id,
                        original_input=call.input,
                        event_handler=tool_event_handler,
                    )
                except PermissionRequiredError as error:
                    return self._pause_for_permission(
                        session,
                        error,
                        tool_name=call.name,
                        input_data=call.input,
                        tool_use_id=call.id,
                        tool_event_handler=tool_event_handler,
                    )
                except ToolError as error:
                    result_text = f"工具 `{call.name}` 执行失败：{error}"
                    if tool_event_handler is not None:
                        tool_event_handler(
                            ToolEvent(
                                tool_name=call.name,
                                phase="error",
                                summary=result_text,
                            )
                        )
                    self._append_tool_error(
                        session,
                        call.name,
                        result_text,
                        tool_use_id=call.id,
                    )
                    self.session_store.save(session)
                    continue

                if tool_event_handler is not None:
                    tool_event_handler(
                        ToolEvent(
                            tool_name=call.name,
                            phase="result",
                            summary=result.summary,
                            metadata={"ok": result.ok},
                        )
                    )
                self._append_tool_result(session, result, tool_use_id=call.id)
                self.session_store.save(session)
                if self._should_pause_after_tool_result(call.name):
                    return session

        session.add_message(
            "assistant",
            f"工具调用轮次超出限制（{self.max_iterations}），已停止自动执行。",
        )
        self.session_store.save(session)
        return session

    async def _complete_until_pause_stream(
        self,
        session: SessionTranscript,
        *,
        tool_event_handler: ToolEventHandler | None = None,
        text_delta_handler: TextDeltaHandler | None = None,
        message_added_handler: MessageAddedHandler | None = None,
    ) -> SessionTranscript:
        """循环执行流式“模型回复 -> 工具调用”，并在文本增量到达时向外发射。"""
        for _ in range(self.max_iterations):
            try:
                await self.tool_runtime.warm_tool_specs_for_session(session)
                response = await self._stream_provider_response(
                    session,
                    text_delta_handler=text_delta_handler,
                )
            except ProviderError as error:
                session.add_message("assistant", f"API 调用失败：{error}")
                self.session_store.save(session)
                self._emit_message_added(session, message_added_handler)
                return session

            session.add_message(
                "assistant",
                response.display_text,
                content_blocks=response.content_blocks,
                metadata={
                    "tool_calls": [
                        {"id": call.id, "name": call.name, "input": call.input}
                        for call in response.tool_calls
                    ]
                }
                if response.tool_calls
                else None,
            )
            self.session_store.save(session)
            self._emit_message_added(session, message_added_handler)

            if not response.tool_calls:
                return session

            for call in response.tool_calls:
                if tool_event_handler is not None:
                    tool_event_handler(
                        ToolEvent(
                            tool_name=call.name,
                            phase="queued",
                            summary=f"准备执行 {call.name}",
                            metadata={"input": call.input},
                        )
                    )
                try:
                    result = await self._execute_tool_input(
                        call.name,
                        call.input,
                        session,
                        tool_use_id=call.id,
                        original_input=call.input,
                        event_handler=tool_event_handler,
                    )
                except PermissionRequiredError as error:
                    paused = self._pause_for_permission(
                        session,
                        error,
                        tool_name=call.name,
                        input_data=call.input,
                        tool_use_id=call.id,
                        tool_event_handler=tool_event_handler,
                    )
                    self._emit_message_added(session, message_added_handler)
                    return paused
                except ToolError as error:
                    result_text = f"工具 `{call.name}` 执行失败：{error}"
                    if tool_event_handler is not None:
                        tool_event_handler(
                            ToolEvent(
                                tool_name=call.name,
                                phase="error",
                                summary=result_text,
                            )
                        )
                    self._append_tool_error(
                        session,
                        call.name,
                        result_text,
                        tool_use_id=call.id,
                    )
                    self.session_store.save(session)
                    self._emit_message_added(session, message_added_handler)
                    continue

                if tool_event_handler is not None:
                    tool_event_handler(
                        ToolEvent(
                            tool_name=call.name,
                            phase="result",
                            summary=result.summary,
                            metadata={"ok": result.ok},
                        )
                    )
                self._append_tool_result(session, result, tool_use_id=call.id)
                self.session_store.save(session)
                self._emit_message_added(session, message_added_handler)
                if self._should_pause_after_tool_result(call.name):
                    return session

        session.add_message(
            "assistant",
            f"工具调用轮次超出限制（{self.max_iterations}），已停止自动执行。",
        )
        self.session_store.save(session)
        self._emit_message_added(session, message_added_handler)
        return session

    def _pause_for_permission(
        self,
        session: SessionTranscript,
        error: PermissionRequiredError,
        *,
        tool_name: str,
        input_data: dict[str, object],
        tool_use_id: str | None,
        tool_event_handler: ToolEventHandler | None,
    ) -> SessionTranscript:
        """把权限请求写入会话状态，并向前端发出确认提示。"""
        set_pending_permission(
            session,
            error.request,
            source_type="tool_call",
            tool_name=tool_name,
            input_data=input_data,
            original_input=(
                error.original_input if isinstance(error.original_input, dict) else input_data
            ),
            user_modified=error.user_modified,
            tool_use_id=tool_use_id,
        )
        if tool_event_handler is not None:
            tool_event_handler(
                ToolEvent(
                    tool_name=tool_name,
                    phase="permission",
                    summary=error.request.reason or f"{tool_name} 需要权限确认",
                    metadata=error.request.to_dict(),
                )
            )
        session.add_message(
            "assistant",
            error.request.prompt_text(),
            metadata={
                "ui_kind": "permission_prompt",
                "pending_permission": error.request.to_dict(),
            },
        )
        self.session_store.save(session)
        return session

    def _should_pause_after_tool_result(self, tool_name: str) -> bool:
        """决定某类工具执行完后是否立刻把控制权交还给前端。"""
        return tool_name.startswith("mcp__")

    async def _execute_tool_input(
        self,
        tool_name: str,
        input_data: dict[str, object],
        session: SessionTranscript,
        *,
        tool_use_id: str | None = None,
        original_input: dict[str, object] | None = None,
        event_handler: ToolEventHandler | None = None,
    ):
        """执行工具输入，并对 MCP 工具额外施加 UI 等待超时保护。"""
        if not tool_name.startswith("mcp__"):
            return self.tool_runtime.execute_input(
                tool_name,
                input_data,
                session,
                surface="model",
                tool_use_id=tool_use_id,
                original_input=original_input,
                event_handler=event_handler,
            )

        timeout_s = self._mcp_ui_wait_timeout_seconds(session)
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(
                    lambda: self.tool_runtime.execute_input(
                        tool_name,
                        input_data,
                        session,
                        surface="model",
                        tool_use_id=tool_use_id,
                        original_input=original_input,
                        event_handler=None,
                    )
                ),
                timeout=timeout_s,
            )
        except asyncio.TimeoutError as error:
            raise ToolError(
                f"工具 `{tool_name}` 在 UI 等待阶段超时（>{int(timeout_s * 1000)} ms）"
            ) from error

    def _mcp_ui_wait_timeout_seconds(self, session: SessionTranscript) -> float:
        """从 MCP 配置推导出前端等待工具结果的超时时间。"""
        try:
            services = self.tool_runtime.services_for(session)
        except ToolError:
            return 30.0
        timeout_ms = services.settings.mcp.tool_call_timeout_ms
        return max(min(timeout_ms / 1000 + 1.0, 30.0), 1.0)

    def _append_tool_result(
        self,
        session: SessionTranscript,
        result,
        *,
        tool_use_id: str | None = None,
    ) -> None:
        """把成功或失败的工具结果追加进会话，供模型继续消费。"""
        session.add_message(
            "tool",
            result.render(),
            content_blocks=[
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "is_error": not result.ok,
                    "content": result.content_for_model(),
                }
            ],
            metadata=result.message_metadata(tool_use_id=tool_use_id),
        )

    def _append_tool_error(
        self,
        session: SessionTranscript,
        tool_name: str,
        result_text: str,
        *,
        tool_use_id: str | None = None,
    ) -> None:
        """把工具异常包装成统一的 tool 消息写回会话。"""
        session.add_message(
            "tool",
            result_text,
            content_blocks=[
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "is_error": True,
                    "content": result_text,
                }
            ],
            metadata={
                "tool_name": tool_name,
                "display_name": tool_name,
                "ui_kind": "error",
                "ok": False,
                "summary": result_text,
                "metadata": {},
                "preview": "",
                "output": result_text,
                **({"tool_use_id": tool_use_id} if tool_use_id else {}),
            },
        )

    async def _stream_provider_response(
        self,
        session: SessionTranscript,
        *,
        text_delta_handler: TextDeltaHandler | None = None,
    ) -> ProviderResponse:
        """消费 provider 的流式事件，并在结束后还原出完整 ProviderResponse。"""
        final_response: ProviderResponse | None = None
        rendered_prompt = self._build_rendered_prompt(session)
        async for event in self.provider.stream_complete(
            session,
            self.tool_runtime.list_tool_specs_for_session(
                session,
                allow_sync_refresh=False,
            ),
            prompt=rendered_prompt,
        ):
            if event.type == "text_delta":
                if text_delta_handler is not None and event.text:
                    text_delta_handler(event.text)
                continue
            if event.type == "response":
                final_response = event.response
        if final_response is None:
            raise ProviderError("流式响应在结束前没有返回最终结果")
        return final_response

    def _emit_message_added(
        self,
        session: SessionTranscript,
        message_added_handler: MessageAddedHandler | None,
    ) -> None:
        """在有新消息写入会话后通知外部消费方。"""
        if message_added_handler is None or not session.messages:
            return
        index = len(session.messages) - 1
        message_added_handler(index, session.messages[index])

    def _build_rendered_prompt(self, session: SessionTranscript) -> RenderedPrompt:
        """为当前会话构造本轮 provider 请求要使用的渲染后 prompt。"""
        services = self.tool_runtime.services_for(session)
        provider_config = getattr(self.provider, "config", None)
        resolved_model = session.model or getattr(provider_config, "model", "") or ""
        return services.prompt_runtime.build_rendered_prompt(
            session,
            services,
            provider_name=self.provider.name,
            model=resolved_model,
        )
