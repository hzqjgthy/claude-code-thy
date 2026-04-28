from __future__ import annotations

from datetime import datetime
from pathlib import Path
import threading

from claude_code_thy.models import ChatMessage, SessionTranscript, utc_now
from claude_code_thy.prompts.types import RenderedPrompt
from claude_code_thy.settings import SessionLogSettings
from claude_code_thy.tools.base import ToolEvent, ToolResult

from .formatters import (
    render_assistant_message_block,
    render_command_parsed_block,
    render_llm_turn_block,
    render_session_resumed_block,
    render_session_started_block,
    render_turn_finished_block,
    render_turn_paused_block,
    render_turn_started_block,
)
from .jsonl_writer import JsonlWriter
from .paths import SessionLogBundle, build_log_prefix, build_session_log_bundle, resolve_output_dir
from .records import (
    LlmTurnLogContext,
    SESSION_LOG_RECORD_VERSION,
    SessionLogRecord,
    ToolCallLogContext,
)
from .serializers import (
    format_local_time,
    serialize_exception,
    serialize_message,
    serialize_tool_event,
    serialize_tool_result,
    summarize_prompt_bundle,
    summarize_request_preview,
)
from .text_writer import TextWriter


class SessionLogManager:
    """管理每个 session 的 `.log` 与 `.jsonl` 双轨日志输出。"""

    def __init__(self, workspace_root: Path, settings: SessionLogSettings) -> None:
        """保存工作区路径、日志配置以及文件写入器。"""
        self.workspace_root = workspace_root.resolve()
        self.settings = settings
        self.output_dir = resolve_output_dir(self.workspace_root, settings.output_dir)
        self._jsonl_writer = JsonlWriter()
        self._text_writer = TextWriter()
        self._locks: dict[str, threading.Lock] = {}

    def enabled(self) -> bool:
        """返回当前日志系统是否启用。"""
        return self.settings.enabled and (self.settings.write_human_log or self.settings.write_jsonl_log)

    def attach_message_hook(self, session: SessionTranscript) -> None:
        """为当前 session 挂接消息追加回调。"""
        if not self.enabled() or session.message_added_hook is not None:
            return

        def _hook(current_session: SessionTranscript, message_index: int, message: ChatMessage) -> None:
            self.record_message(current_session, message_index, message)

        session.message_added_hook = _hook

    def ensure_bundle(self, session: SessionTranscript) -> tuple[SessionLogBundle | None, bool]:
        """确保当前 session 已经有固定日志前缀，并返回对应路径。"""
        if not self.enabled():
            return None, False
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            prefix = str(session.runtime_state.get("log_bundle_prefix", "")).strip()
            created = False
            if not prefix:
                now_local = datetime.now().astimezone()
                prefix = build_log_prefix(session.session_id, now_local)
                session.runtime_state["log_bundle_prefix"] = prefix
                session.runtime_state["log_started_at"] = now_local.astimezone().isoformat()
                created = True
            started_at_local = str(session.runtime_state.get("log_started_at", "")).strip()
            bundle = build_session_log_bundle(self.output_dir, prefix)
            if started_at_local:
                bundle.started_at_local = started_at_local
            return bundle, created
        except Exception:
            return None, False

    def record_session_started(
        self,
        session: SessionTranscript,
        *,
        provider_name: str,
        model: str,
        title: str | None = None,
    ) -> None:
        """记录第一次进入日志系统时的会话头信息。"""
        bundle, _ = self.ensure_bundle(session)
        if bundle is None:
            return
        now = utc_now()
        data = {
            "session_id": session.session_id,
            "cwd": session.cwd,
            "provider_name": provider_name,
            "model": model,
            "title": title or session.title or "",
            "log_path": str(bundle.log_path),
            "jsonl_path": str(bundle.jsonl_path),
            "started_at_utc": now,
            "started_at_local_readable": format_local_time(now),
        }
        self._record(session, "session_started", data, turn_index=0, llm_turn_index=0)
        self._append_human(session, render_session_started_block(data))

    def record_session_resumed(
        self,
        session: SessionTranscript,
        *,
        provider_name: str,
        model: str,
    ) -> None:
        """记录已有 session 在新运行周期内被恢复。"""
        bundle, _ = self.ensure_bundle(session)
        if bundle is None:
            return
        now = utc_now()
        data = {
            "session_id": session.session_id,
            "provider_name": provider_name,
            "model": model,
            "log_path": str(bundle.log_path),
            "jsonl_path": str(bundle.jsonl_path),
            "resumed_at_utc": now,
            "resumed_at_local_readable": format_local_time(now),
        }
        self._record(session, "session_resumed", data, turn_index=0, llm_turn_index=0)
        self._append_human(session, render_session_resumed_block(data))

    def start_turn(self, session: SessionTranscript, *, prompt: str, input_kind: str, stream: bool) -> int:
        """开启一轮新的交互处理，并写入 turn_started。"""
        existing = self._current_turn_state(session)
        if existing is not None and input_kind == "permission_resolution":
            return int(existing.get("turn_index", 0) or 0)
        if existing is not None:
            return int(existing.get("turn_index", 0) or 0)

        turn_index = int(session.runtime_state.get("session_log_turn_index", 0) or 0) + 1
        now = utc_now()
        state = {
            "turn_index": turn_index,
            "prompt": prompt,
            "input_kind": input_kind,
            "stream": stream,
            "message_count_start": len(session.messages),
            "started_at_utc": now,
            "started_at_local_readable": format_local_time(now),
            "open": True,
            "paused": False,
        }
        session.runtime_state["session_log_turn_index"] = turn_index
        session.runtime_state["session_log_current_turn_index"] = turn_index
        session.runtime_state["session_log_current_turn_open"] = True
        session.runtime_state["session_log_current_turn_had_error"] = False
        session.runtime_state["session_log_current_turn_state"] = state
        session.runtime_state["session_log_current_llm_turn_index"] = 0
        session.runtime_state["session_log_current_llm_turn_ordinal"] = 0
        session.runtime_state["session_log_current_llm_tool_call_ordinal"] = 0
        session.runtime_state.pop("session_log_current_llm_turn_state", None)
        self._record(session, "turn_started", dict(state), turn_index=turn_index, llm_turn_index=0)
        self._append_human(session, render_turn_started_block(turn_index, state))
        return turn_index

    def pause_turn(self, session: SessionTranscript, *, reason: str = "pending_permission") -> None:
        """记录当前交互轮进入等待权限确认的暂停状态。"""
        state = self._current_turn_state(session)
        if state is None:
            return
        if bool(state.get("paused")):
            return
        state["paused"] = True
        session.runtime_state["session_log_current_turn_state"] = state
        data = {
            "turn_index": int(state.get("turn_index", 0) or 0),
            "reason": reason,
        }
        self._record(
            session,
            "turn_paused",
            data,
            turn_index=int(state.get("turn_index", 0) or 0),
            llm_turn_index=self.current_llm_turn_index(session),
        )
        self._append_human(session, render_turn_paused_block(int(state.get("turn_index", 0) or 0), data))

    def finish_turn(
        self,
        session: SessionTranscript,
        *,
        new_message_count: int,
        ended_with_error: bool,
        ended_with_pending_permission: bool,
    ) -> None:
        """写入交互轮最终结束状态。"""
        if ended_with_pending_permission:
            self.pause_turn(session, reason="pending_permission")
            return

        state = self._current_turn_state(session)
        turn_index = self.current_turn_index(session)
        recorded_had_error = bool(session.runtime_state.get("session_log_current_turn_had_error"))
        resolved_ended_with_error = bool(ended_with_error or recorded_had_error)
        status = "error" if resolved_ended_with_error else "success"
        effective_message_count = new_message_count
        if state is not None:
            started_message_count = int(state.get("message_count_start", 0) or 0)
            effective_message_count = max(len(session.messages) - started_message_count, 0)

        if self._current_llm_turn_state(session) is not None:
            self.finish_llm_turn(session, status="error" if resolved_ended_with_error else "success")

        data = {
            "turn_index": turn_index,
            "new_message_count": effective_message_count,
            "ended_with_error": resolved_ended_with_error,
            "ended_with_pending_permission": False,
            "status": status,
        }
        self._record(session, "turn_finished", data, turn_index=turn_index, llm_turn_index=0)
        self._append_human(session, render_turn_finished_block(turn_index, data))
        session.runtime_state["session_log_current_turn_had_error"] = False
        session.runtime_state["session_log_current_turn_open"] = False
        session.runtime_state.pop("session_log_current_turn_state", None)
        session.runtime_state["session_log_current_llm_turn_index"] = 0
        session.runtime_state["session_log_current_llm_turn_ordinal"] = 0
        session.runtime_state["session_log_current_llm_tool_call_ordinal"] = 0
        session.runtime_state.pop("session_log_current_llm_turn_state", None)

    def current_turn_index(self, session: SessionTranscript) -> int:
        """返回当前 session 最近一次活跃的交互轮编号。"""
        return int(session.runtime_state.get("session_log_current_turn_index", 0) or 0)

    def current_llm_turn_index(self, session: SessionTranscript) -> int:
        """返回当前 session 最近一次活跃的 LLM 轮编号。"""
        return int(session.runtime_state.get("session_log_current_llm_turn_index", 0) or 0)

    def start_llm_turn(
        self,
        session: SessionTranscript,
        *,
        provider_name: str,
        request_preview: dict[str, object],
        rendered_prompt: RenderedPrompt,
    ) -> LlmTurnLogContext:
        """开启一个新的 LLM 轮，并建立后续工具调用要归属的上下文。"""
        if self._current_llm_turn_state(session) is not None:
            self.finish_llm_turn(session, status="success")
        turn_index = self.current_turn_index(session)
        llm_turn_index = int(session.runtime_state.get("session_log_current_llm_turn_ordinal", 0) or 0) + 1
        now = utc_now()
        summary = summarize_request_preview(request_preview)
        state = {
            "interaction_turn_index": turn_index,
            "llm_turn_index": llm_turn_index,
            "provider_name": provider_name,
            "started_at_utc": now,
            "started_at_local_readable": format_local_time(now),
            "request_preview_summary": summary,
            "prompt_bundle_summary": (
                summarize_prompt_bundle(rendered_prompt)
                if self.settings.include_prompt_bundle_summary
                else {}
            ),
            "assistant_text": "",
            "tool_calls": [],
            "status": "running",
        }
        session.runtime_state["session_log_current_llm_turn_ordinal"] = llm_turn_index
        session.runtime_state["session_log_current_llm_turn_index"] = llm_turn_index
        session.runtime_state["session_log_current_llm_tool_call_ordinal"] = 0
        session.runtime_state["session_log_current_llm_turn_state"] = state
        self._record(
            session,
            "llm_turn_started",
            {
                "provider_name": provider_name,
                "request_preview_summary": summary,
                "prompt_bundle_summary": state["prompt_bundle_summary"],
                "started_at_utc": now,
                "started_at_local_readable": format_local_time(now),
            },
            turn_index=turn_index,
            llm_turn_index=llm_turn_index,
        )
        return LlmTurnLogContext(
            turn_index=turn_index,
            llm_turn_index=llm_turn_index,
            provider_name=provider_name,
        )

    def finish_llm_turn(self, session: SessionTranscript, *, status: str) -> None:
        """完成当前 LLM 轮，并把聚合后的块落到人类日志。"""
        state = self._current_llm_turn_state(session)
        if state is None:
            return
        state["status"] = status
        error = state.get("error")
        self._record(
            session,
            "llm_turn_finished",
            {
                "provider_name": str(state.get("provider_name", "")),
                "status": status,
                "assistant_text": str(state.get("assistant_text", "")),
                "tool_call_count": len(state.get("tool_calls", []) if isinstance(state.get("tool_calls"), list) else []),
                "error": error if isinstance(error, dict) else {},
            },
            turn_index=int(state.get("interaction_turn_index", 0) or 0),
            llm_turn_index=int(state.get("llm_turn_index", 0) or 0),
        )
        self._append_human(session, render_llm_turn_block(state, self.settings))
        session.runtime_state["session_log_current_llm_turn_index"] = 0
        session.runtime_state["session_log_current_llm_tool_call_ordinal"] = 0
        session.runtime_state.pop("session_log_current_llm_turn_state", None)

    def record_command_parsed(
        self,
        session: SessionTranscript,
        *,
        raw_prompt: str,
        command: str,
        raw_args: str,
        submit_prompt: str | None,
        model_override: str | None,
    ) -> None:
        """记录 slash 命令解析结果。"""
        data = {
            "raw_prompt": raw_prompt,
            "command": command,
            "raw_args": raw_args,
            "submit_prompt": submit_prompt or "",
            "model_override": model_override or "",
        }
        self._record(session, "command_parsed", data, llm_turn_index=self.current_llm_turn_index(session))
        self._append_human(session, render_command_parsed_block(data))

    def record_provider_request(
        self,
        session: SessionTranscript,
        *,
        provider_name: str,
        request_preview: dict[str, object],
        rendered_prompt: RenderedPrompt,
    ) -> None:
        """记录一次 provider 请求的脱敏预览。"""
        payload: dict[str, object] = {
            "provider_name": provider_name,
            "request_preview_summary": summarize_request_preview(request_preview),
        }
        if self.settings.include_request_preview:
            payload["request_preview"] = request_preview
        if self.settings.include_prompt_bundle_summary:
            payload["prompt_bundle_summary"] = summarize_prompt_bundle(rendered_prompt)
        session.runtime_state["session_log_last_request_preview_summary"] = payload["request_preview_summary"]
        if self.settings.include_request_preview:
            session.runtime_state["session_log_last_request_preview"] = request_preview
        self._record(session, "provider_request", payload, llm_turn_index=self.current_llm_turn_index(session))
        llm_state = self._current_llm_turn_state(session)
        if llm_state is not None:
            llm_state["provider_name"] = provider_name
            llm_state["request_preview_summary"] = payload["request_preview_summary"]
            llm_state["prompt_bundle_summary"] = payload.get("prompt_bundle_summary", {})
            session.runtime_state["session_log_current_llm_turn_state"] = llm_state

    def record_provider_response(self, session: SessionTranscript, response) -> None:
        """记录 provider 最终标准化响应。"""
        payload: dict[str, object] = {
            "display_text": getattr(response, "display_text", ""),
            "tool_calls": [
                {
                    "id": call.id,
                    "name": call.name,
                    "input": call.input,
                }
                for call in getattr(response, "tool_calls", []) or []
            ],
        }
        if self.settings.include_provider_response_blocks:
            payload["content_blocks"] = getattr(response, "content_blocks", []) or []
        self._record(session, "provider_response", payload, llm_turn_index=self.current_llm_turn_index(session))
        llm_state = self._current_llm_turn_state(session)
        if llm_state is not None:
            display_text = str(getattr(response, "display_text", "") or "").strip()
            if display_text:
                llm_state["assistant_text"] = display_text
            session.runtime_state["session_log_current_llm_turn_state"] = llm_state

    def record_provider_error(
        self,
        session: SessionTranscript,
        *,
        stage: str,
        error: BaseException,
        provider_name: str,
        request_preview: dict[str, object] | None = None,
        tool_name: str | None = None,
        tool_use_id: str | None = None,
        input_data: dict[str, object] | None = None,
    ) -> None:
        """记录 provider 层错误。"""
        self._mark_current_turn_error(session)
        now = utc_now()
        payload = {
            "stage": stage,
            "provider_name": provider_name,
            "occurred_at_utc": now,
            "occurred_at_local_readable": format_local_time(now),
            **serialize_exception(error, include_traceback=self.settings.include_traceback),
        }
        if request_preview is not None:
            payload["request_preview_summary"] = summarize_request_preview(request_preview)
            if self.settings.include_request_preview:
                payload["request_preview"] = request_preview
        else:
            cached_summary = session.runtime_state.get("session_log_last_request_preview_summary")
            if isinstance(cached_summary, dict):
                payload["request_preview_summary"] = cached_summary
            cached_preview = session.runtime_state.get("session_log_last_request_preview")
            if self.settings.include_request_preview and isinstance(cached_preview, dict):
                payload["request_preview"] = cached_preview
        if tool_name:
            payload["tool_name"] = tool_name
        if tool_use_id:
            payload["tool_use_id"] = tool_use_id
        if input_data is not None:
            payload["input_data"] = input_data
        self._record(session, "provider_error", payload, llm_turn_index=self.current_llm_turn_index(session))
        llm_state = self._current_llm_turn_state(session)
        if llm_state is not None:
            llm_state["error"] = serialize_exception(error, include_traceback=self.settings.include_traceback)
            llm_state["status"] = "error"
            session.runtime_state["session_log_current_llm_turn_state"] = llm_state

    def record_runtime_error(self, session: SessionTranscript, *, stage: str, error: BaseException) -> None:
        """记录运行时层面的异常。"""
        self._mark_current_turn_error(session)
        now = utc_now()
        payload = {
            "stage": stage,
            "occurred_at_utc": now,
            "occurred_at_local_readable": format_local_time(now),
            **serialize_exception(error, include_traceback=self.settings.include_traceback),
        }
        self._record(session, "runtime_error", payload, llm_turn_index=self.current_llm_turn_index(session))
        llm_state = self._current_llm_turn_state(session)
        if llm_state is not None and "error" not in llm_state:
            llm_state["error"] = serialize_exception(error, include_traceback=self.settings.include_traceback)
            llm_state["status"] = "error"
            session.runtime_state["session_log_current_llm_turn_state"] = llm_state

    def record_message(self, session: SessionTranscript, message_index: int, message: ChatMessage) -> None:
        """记录一条追加到 transcript 的消息。"""
        payload = serialize_message(message)
        payload["message_index"] = message_index
        self._record(session, "message_added", payload, llm_turn_index=self.current_llm_turn_index(session))

        if message.role != "assistant" or not message.text.strip():
            return
        if self._current_llm_turn_state(session) is not None:
            return
        metadata = message.metadata or {}
        ui_kind = str(metadata.get("ui_kind", "")).strip()
        turn_state = self._current_turn_state(session) or {}
        input_kind = str(turn_state.get("input_kind", "")).strip()
        if ui_kind == "permission_prompt":
            return
        if input_kind == "slash_command" or ui_kind == "task_notification":
            self._append_human(session, render_assistant_message_block(message.text))

    def record_tool_event(self, session: SessionTranscript, event: ToolEvent) -> None:
        """记录工具执行过程中的阶段性事件。"""
        self._record(session, "tool_event", serialize_tool_event(event), llm_turn_index=self.current_llm_turn_index(session))

    def begin_tool_call(
        self,
        session: SessionTranscript,
        *,
        tool_name: str,
        tool_use_id: str | None,
        surface: str,
        input_data: dict[str, object],
    ) -> ToolCallLogContext:
        """记录一次工具调用开始，并返回后续完成时要复用的上下文。"""
        ordinal = int(session.runtime_state.get("session_log_current_llm_tool_call_ordinal", 0) or 0) + 1
        session.runtime_state["session_log_current_llm_tool_call_ordinal"] = ordinal
        llm_turn_index = self.current_llm_turn_index(session)
        call_ref = tool_use_id or f"{surface}:{tool_name}:{self.current_turn_index(session)}:{llm_turn_index}:{ordinal}"
        context = ToolCallLogContext(
            call_ref=call_ref,
            ordinal=ordinal,
            tool_name=tool_name,
            tool_use_id=tool_use_id,
            surface=surface,
            llm_turn_index=llm_turn_index,
            input_data=dict(input_data),
        )
        self._record(
            session,
            "tool_call_started",
            {
                "call_ref": context.call_ref,
                "ordinal": context.ordinal,
                "tool_name": context.tool_name,
                "tool_use_id": context.tool_use_id or "",
                "surface": context.surface,
                "input_data": context.input_data,
            },
            llm_turn_index=context.llm_turn_index,
        )
        self._human_llm_add_tool_call(session, context)
        return context

    def finish_tool_call(self, session: SessionTranscript, context: ToolCallLogContext, result: ToolResult) -> None:
        """记录一次工具调用完成。"""
        payload = serialize_tool_result(result)
        payload.update(
            {
                "call_ref": context.call_ref,
                "ordinal": context.ordinal,
                "tool_use_id": context.tool_use_id or "",
                "surface": context.surface,
            }
        )
        self._record(session, "tool_call_finished", payload, llm_turn_index=context.llm_turn_index)
        self._human_llm_set_tool_result(session, context.call_ref, payload)

    def finish_tool_error(
        self,
        session: SessionTranscript,
        context: ToolCallLogContext,
        *,
        error: BaseException,
        output: str,
    ) -> None:
        """把工具执行异常也落成一条 tool_call_finished。"""
        payload = {
            "call_ref": context.call_ref,
            "ordinal": context.ordinal,
            "tool_name": context.tool_name,
            "tool_use_id": context.tool_use_id or "",
            "surface": context.surface,
            "ok": False,
            "summary": output,
            "display_name": context.tool_name,
            "ui_kind": "error",
            "output": output,
            "preview": "",
            "metadata": serialize_exception(error, include_traceback=self.settings.include_traceback),
            "structured_data": None,
        }
        self._record(session, "tool_call_finished", payload, llm_turn_index=context.llm_turn_index)
        self._human_llm_set_tool_result(session, context.call_ref, payload)

    def record_permission_requested(
        self,
        session: SessionTranscript,
        context: ToolCallLogContext,
        *,
        reason: str,
        input_data: dict[str, object],
        original_input: dict[str, object],
        user_modified: bool,
        request_data: dict[str, object],
    ) -> None:
        """记录一次工具权限确认请求。"""
        payload = {
            "call_ref": context.call_ref,
            "ordinal": context.ordinal,
            "tool_name": context.tool_name,
            "tool_use_id": context.tool_use_id or "",
            "reason": reason,
            "input_data": input_data,
            "original_input": original_input,
            "user_modified": user_modified,
            "request": request_data,
        }
        self._record(session, "permission_requested", payload, llm_turn_index=context.llm_turn_index)
        self._human_llm_set_permission_requested(session, context.call_ref, reason, request_data)

        pending = session.runtime_state.get("session_log_pending_tool_calls")
        if not isinstance(pending, dict):
            pending = {}
        pending[context.call_ref] = {
            "call_ref": context.call_ref,
            "ordinal": context.ordinal,
            "tool_name": context.tool_name,
            "tool_use_id": context.tool_use_id or "",
            "surface": context.surface,
            "llm_turn_index": context.llm_turn_index,
            "input_data": context.input_data,
        }
        session.runtime_state["session_log_pending_tool_calls"] = pending

    def record_permission_resolved(self, session: SessionTranscript, *, approved: bool, pending: dict[str, object]) -> None:
        """记录一次权限请求被用户同意或拒绝。"""
        llm_turn_index = self._llm_turn_index_from_pending(session, pending) or self.current_llm_turn_index(session)
        payload = {
            "approved": approved,
            "tool_name": str(pending.get("tool_name", "")).strip(),
            "tool_use_id": str(pending.get("tool_use_id", "")).strip(),
            "approval_key": (
                str(pending.get("request", {}).get("approval_key", "")).strip()
                if isinstance(pending.get("request"), dict)
                else ""
            ),
        }
        self._record(session, "permission_resolved", payload, llm_turn_index=llm_turn_index)
        self._human_llm_set_permission_resolved(session, pending, approved=approved)

    def record_text_delta(self, session: SessionTranscript, text: str) -> None:
        """按配置选择是否记录 provider 的文本增量。"""
        if not text:
            return
        llm_state = self._current_llm_turn_state(session)
        if llm_state is not None and not str(llm_state.get("assistant_text", "")).strip():
            llm_state["assistant_text"] = str(llm_state.get("assistant_text", "")) + text
            session.runtime_state["session_log_current_llm_turn_state"] = llm_state
        if not self.settings.include_text_deltas:
            return
        self._record(session, "provider_text_delta", {"text": text}, llm_turn_index=self.current_llm_turn_index(session))

    def take_pending_tool_call(
        self,
        session: SessionTranscript,
        *,
        tool_name: str,
        tool_use_id: str | None,
        input_data: dict[str, object],
    ) -> ToolCallLogContext | None:
        """取回一次因权限中断而挂起的工具调用上下文。"""
        pending = session.runtime_state.get("session_log_pending_tool_calls")
        if not isinstance(pending, dict) or not pending:
            return None

        if tool_use_id:
            target = pending.pop(tool_use_id, None)
            if target is None:
                for key, item in list(pending.items()):
                    if not isinstance(item, dict):
                        continue
                    if str(item.get("tool_use_id", "")).strip() == tool_use_id:
                        target = pending.pop(key, None)
                        break
            if target is not None:
                session.runtime_state["session_log_pending_tool_calls"] = pending
                return self._context_from_pending(target)

        for key, item in list(pending.items()):
            if not isinstance(item, dict):
                continue
            if str(item.get("tool_name", "")).strip() != tool_name:
                continue
            target = pending.pop(key, None)
            session.runtime_state["session_log_pending_tool_calls"] = pending
            return self._context_from_pending(target)
        return None

    def _context_from_pending(self, data: object) -> ToolCallLogContext | None:
        """把持久化的 pending tool call 信息恢复为上下文对象。"""
        if not isinstance(data, dict):
            return None
        return ToolCallLogContext(
            call_ref=str(data.get("call_ref", "")).strip() or str(data.get("tool_use_id", "")).strip(),
            ordinal=int(data.get("ordinal", 0) or 0),
            tool_name=str(data.get("tool_name", "")).strip(),
            tool_use_id=str(data.get("tool_use_id", "")).strip() or None,
            surface=str(data.get("surface", "")).strip() or "model",
            llm_turn_index=int(data.get("llm_turn_index", 0) or 0),
            input_data=data.get("input_data") if isinstance(data.get("input_data"), dict) else {},
        )

    def _record(
        self,
        session: SessionTranscript,
        event: str,
        data: dict[str, object],
        *,
        turn_index: int | None = None,
        llm_turn_index: int | None = None,
    ) -> None:
        """把一条统一事件写入 `.jsonl`。"""
        if not self.enabled():
            return
        bundle, _ = self.ensure_bundle(session)
        if bundle is None:
            return
        lock = self._locks.setdefault(session.session_id, threading.Lock())
        try:
            with lock:
                actual_turn_index = turn_index if turn_index is not None else self.current_turn_index(session)
                actual_llm_turn_index = (
                    llm_turn_index
                    if llm_turn_index is not None
                    else self.current_llm_turn_index(session)
                )
                event_index = int(session.runtime_state.get("session_log_event_index", 0) or 0) + 1
                session.runtime_state["session_log_event_index"] = event_index
                record = SessionLogRecord(
                    version=SESSION_LOG_RECORD_VERSION,
                    session_id=session.session_id,
                    turn_index=actual_turn_index,
                    llm_turn_index=actual_llm_turn_index,
                    event_index=event_index,
                    timestamp=utc_now(),
                    event=event,
                    data=data,
                )
                if self.settings.write_jsonl_log:
                    self._jsonl_writer.append(bundle.jsonl_path, record)
        except Exception:
            return

    def _append_human(self, session: SessionTranscript, text: str) -> None:
        """向人类可读日志追加一段文本。"""
        if not self.settings.write_human_log or not text:
            return
        bundle, _ = self.ensure_bundle(session)
        if bundle is None:
            return
        lock = self._locks.setdefault(session.session_id, threading.Lock())
        try:
            with lock:
                self._text_writer.append(bundle.log_path, text)
        except Exception:
            return

    def _mark_current_turn_error(self, session: SessionTranscript) -> None:
        """标记当前 turn 已经发生过错误，供最终汇总状态使用。"""
        session.runtime_state["session_log_current_turn_had_error"] = True

    def _current_turn_state(self, session: SessionTranscript) -> dict[str, object] | None:
        """读取当前交互轮状态。"""
        state = session.runtime_state.get("session_log_current_turn_state")
        return state if isinstance(state, dict) else None

    def _current_llm_turn_state(self, session: SessionTranscript) -> dict[str, object] | None:
        """读取当前 LLM 轮聚合状态。"""
        state = session.runtime_state.get("session_log_current_llm_turn_state")
        return state if isinstance(state, dict) else None

    def _human_llm_add_tool_call(self, session: SessionTranscript, context: ToolCallLogContext) -> None:
        """把一条工具调用骨架挂到当前 LLM 轮下。"""
        llm_state = self._current_llm_turn_state(session)
        if llm_state is None:
            return
        tool_calls = llm_state.get("tool_calls")
        if not isinstance(tool_calls, list):
            tool_calls = []
        tool_calls.append(
            {
                "call_ref": context.call_ref,
                "ordinal": context.ordinal,
                "tool_name": context.tool_name,
                "tool_use_id": context.tool_use_id or "",
                "surface": context.surface,
                "input_data": context.input_data,
            }
        )
        llm_state["tool_calls"] = tool_calls
        session.runtime_state["session_log_current_llm_turn_state"] = llm_state

    def _human_llm_set_tool_result(self, session: SessionTranscript, call_ref: str, result: dict[str, object]) -> None:
        """把工具结果挂到当前 LLM 轮的对应工具项上。"""
        tool = self._human_llm_find_tool(session, call_ref)
        if tool is None:
            return
        tool["result"] = result

    def _human_llm_set_permission_requested(
        self,
        session: SessionTranscript,
        call_ref: str,
        reason: str,
        request_data: dict[str, object],
    ) -> None:
        """把权限请求挂到当前 LLM 轮的对应工具项上。"""
        tool = self._human_llm_find_tool(session, call_ref)
        if tool is None:
            return
        tool["permission_requested"] = {
            "reason": reason,
            "request": request_data,
        }

    def _human_llm_set_permission_resolved(
        self,
        session: SessionTranscript,
        pending: dict[str, object],
        *,
        approved: bool,
    ) -> None:
        """把权限同意/拒绝结果挂到当前 LLM 轮的对应工具项上。"""
        tool = self._human_llm_find_tool_for_pending(session, pending)
        if tool is None:
            return
        tool["permission_resolved"] = {
            "approved": approved,
            "approval_key": (
                str(pending.get("request", {}).get("approval_key", "")).strip()
                if isinstance(pending.get("request"), dict)
                else ""
            ),
        }

    def _human_llm_find_tool(self, session: SessionTranscript, call_ref: str) -> dict[str, object] | None:
        """按 call_ref 在当前 LLM 轮里查找工具项。"""
        llm_state = self._current_llm_turn_state(session)
        if llm_state is None:
            return None
        tool_calls = llm_state.get("tool_calls")
        if not isinstance(tool_calls, list):
            return None
        for tool in tool_calls:
            if not isinstance(tool, dict):
                continue
            if str(tool.get("call_ref", "")).strip() == call_ref:
                return tool
        return None

    def _human_llm_find_tool_for_pending(self, session: SessionTranscript, pending: dict[str, object]) -> dict[str, object] | None:
        """按 pending_permission 数据在当前 LLM 轮里定位工具项。"""
        llm_state = self._current_llm_turn_state(session)
        if llm_state is None:
            return None
        tool_calls = llm_state.get("tool_calls")
        if not isinstance(tool_calls, list):
            return None
        tool_use_id = str(pending.get("tool_use_id", "")).strip()
        tool_name = str(pending.get("tool_name", "")).strip()
        if tool_use_id:
            for tool in tool_calls:
                if not isinstance(tool, dict):
                    continue
                if str(tool.get("tool_use_id", "")).strip() == tool_use_id:
                    return tool
        for tool in tool_calls:
            if not isinstance(tool, dict):
                continue
            if str(tool.get("tool_name", "")).strip() == tool_name:
                return tool
        return None

    def _llm_turn_index_from_pending(self, session: SessionTranscript, pending: dict[str, object]) -> int:
        """从 pending 权限状态里推断出所属的 LLM 轮编号。"""
        tool_use_id = str(pending.get("tool_use_id", "")).strip()
        if tool_use_id:
            pending_calls = session.runtime_state.get("session_log_pending_tool_calls")
            if isinstance(pending_calls, dict):
                target = pending_calls.get(tool_use_id)
                if not isinstance(target, dict):
                    for item in pending_calls.values():
                        if not isinstance(item, dict):
                            continue
                        if str(item.get("tool_use_id", "")).strip() == tool_use_id:
                            target = item
                            break
                if isinstance(target, dict):
                    return int(target.get("llm_turn_index", 0) or 0)
        llm_state = self._current_llm_turn_state(session)
        if llm_state is None:
            return 0
        return int(llm_state.get("llm_turn_index", 0) or 0)
