from __future__ import annotations

import asyncio

from claude_code_thy.models import SessionTranscript
from claude_code_thy.session.runtime_state import clear_pending_permission, set_pending_permission
from claude_code_thy.providers.base import Provider, ProviderError
from claude_code_thy.session.store import SessionStore
from claude_code_thy.tools import (
    PermissionRequiredError,
    ToolError,
    ToolEvent,
    ToolEventHandler,
    ToolRuntime,
)


class QueryEngine:
    def __init__(
        self,
        *,
        provider: Provider,
        session_store: SessionStore,
        tool_runtime: ToolRuntime,
    ) -> None:
        self.provider = provider
        self.session_store = session_store
        self.tool_runtime = tool_runtime

    async def submit(
        self,
        session: SessionTranscript,
        prompt: str,
        *,
        tool_event_handler: ToolEventHandler | None = None,
    ) -> SessionTranscript:
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

    async def resume_pending_tool_call(
        self,
        session: SessionTranscript,
        pending: dict[str, object],
        *,
        approved: bool,
        tool_event_handler: ToolEventHandler | None = None,
    ) -> SessionTranscript:
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
        max_iterations = 1000
        for _ in range(max_iterations):
            try:
                response = await self.provider.complete(
                    session,
                    self.tool_runtime.list_tool_specs_for_session(session),
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
                    set_pending_permission(
                        session,
                        error.request,
                        source_type="tool_call",
                        tool_name=call.name,
                        input_data=call.input,
                        original_input=(
                            error.original_input if isinstance(error.original_input, dict) else call.input
                        ),
                        user_modified=error.user_modified,
                        tool_use_id=call.id,
                    )
                    if tool_event_handler is not None:
                        tool_event_handler(
                            ToolEvent(
                                tool_name=call.name,
                                phase="permission",
                                summary=error.request.reason or f"{call.name} 需要权限确认",
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

        session.add_message("assistant", "工具调用轮次超出限制，已停止自动执行。")
        self.session_store.save(session)
        return session

    def _should_pause_after_tool_result(self, tool_name: str) -> bool:
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
        if not tool_name.startswith("mcp__"):
            return self.tool_runtime.execute_input(
                tool_name,
                input_data,
                session,
                tool_use_id=tool_use_id,
                original_input=original_input,
                event_handler=event_handler,
            )

        timeout_s = self._mcp_ui_wait_timeout_seconds(session)
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(
                    self.tool_runtime.execute_input,
                    tool_name,
                    input_data,
                    session,
                    tool_use_id=tool_use_id,
                    original_input=original_input,
                    event_handler=None,
                ),
                timeout=timeout_s,
            )
        except asyncio.TimeoutError as error:
            raise ToolError(
                f"工具 `{tool_name}` 在 UI 等待阶段超时（>{int(timeout_s * 1000)} ms）"
            ) from error

    def _mcp_ui_wait_timeout_seconds(self, session: SessionTranscript) -> float:
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
