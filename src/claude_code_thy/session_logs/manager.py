from __future__ import annotations

from datetime import datetime
from pathlib import Path
import threading

from claude_code_thy.models import ChatMessage, SessionTranscript, utc_now
from claude_code_thy.prompts.types import RenderedPrompt
from claude_code_thy.settings import SessionLogSettings
from claude_code_thy.tools.base import ToolEvent, ToolResult

from .formatters import render_record
from .jsonl_writer import JsonlWriter
from .paths import SessionLogBundle, build_log_prefix, build_session_log_bundle, resolve_output_dir
from .records import SESSION_LOG_RECORD_VERSION, SessionLogRecord, ToolCallLogContext
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
        self._record(
            session,
            "session_started",
            {
                "session_id": session.session_id,
                "cwd": session.cwd,
                "provider_name": provider_name,
                "model": model,
                "title": title or session.title or "",
                "log_path": str(bundle.log_path),
                "jsonl_path": str(bundle.jsonl_path),
                "started_at_utc": now,
                "started_at_local_readable": format_local_time(now),
            },
            turn_index=0,
        )

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
        self._record(
            session,
            "session_resumed",
            {
                "session_id": session.session_id,
                "provider_name": provider_name,
                "model": model,
                "log_path": str(bundle.log_path),
                "jsonl_path": str(bundle.jsonl_path),
                "resumed_at_utc": now,
                "resumed_at_local_readable": format_local_time(now),
            },
            turn_index=0,
        )

    def start_turn(self, session: SessionTranscript, *, prompt: str, input_kind: str, stream: bool) -> int:
        """开启一轮新的用户输入处理，并写入 turn_started。"""
        turn_index = int(session.runtime_state.get("session_log_turn_index", 0) or 0) + 1
        session.runtime_state["session_log_turn_index"] = turn_index
        session.runtime_state["session_log_current_turn_index"] = turn_index
        session.runtime_state["session_log_current_tool_call_ordinal"] = 0
        session.runtime_state["session_log_current_turn_had_error"] = False
        now = utc_now()
        self._record(
            session,
            "turn_started",
            {
                "turn_index": turn_index,
                "prompt": prompt,
                "input_kind": input_kind,
                "stream": stream,
                "started_at_utc": now,
                "started_at_local_readable": format_local_time(now),
            },
            turn_index=turn_index,
        )
        return turn_index

    def finish_turn(
        self,
        session: SessionTranscript,
        *,
        new_message_count: int,
        ended_with_error: bool,
        ended_with_pending_permission: bool,
    ) -> None:
        """写入 turn_finished，总结本轮结束状态。"""
        turn_index = self.current_turn_index(session)
        recorded_had_error = bool(session.runtime_state.get("session_log_current_turn_had_error"))
        resolved_ended_with_error = bool(ended_with_error or recorded_had_error)
        status = "success"
        if ended_with_pending_permission:
            status = "pending_permission"
        elif resolved_ended_with_error:
            status = "error"
        self._record(
            session,
            "turn_finished",
            {
                "turn_index": turn_index,
                "new_message_count": new_message_count,
                "ended_with_error": resolved_ended_with_error,
                "ended_with_pending_permission": ended_with_pending_permission,
                "status": status,
            },
            turn_index=turn_index,
        )
        session.runtime_state["session_log_current_turn_had_error"] = False

    def current_turn_index(self, session: SessionTranscript) -> int:
        """返回当前 session 最近一次活跃的 turn 编号。"""
        return int(session.runtime_state.get("session_log_current_turn_index", 0) or 0)

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
        self._record(
            session,
            "command_parsed",
            {
                "raw_prompt": raw_prompt,
                "command": command,
                "raw_args": raw_args,
                "submit_prompt": submit_prompt or "",
                "model_override": model_override or "",
            },
        )

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
        self._record(session, "provider_request", payload)

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
        self._record(session, "provider_response", payload)

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
        self._record(session, "provider_error", payload)

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
        self._record(session, "runtime_error", payload)

    def record_message(self, session: SessionTranscript, message_index: int, message: ChatMessage) -> None:
        """记录一条追加到 transcript 的消息。"""
        payload = serialize_message(message)
        payload["message_index"] = message_index
        self._record(session, "message_added", payload)

    def record_tool_event(self, session: SessionTranscript, event: ToolEvent) -> None:
        """记录工具执行过程中的阶段性事件。"""
        self._record(session, "tool_event", serialize_tool_event(event))

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
        ordinal = int(session.runtime_state.get("session_log_current_tool_call_ordinal", 0) or 0) + 1
        session.runtime_state["session_log_current_tool_call_ordinal"] = ordinal
        call_ref = tool_use_id or f"{surface}:{tool_name}:{self.current_turn_index(session)}:{ordinal}"
        context = ToolCallLogContext(
            call_ref=call_ref,
            ordinal=ordinal,
            tool_name=tool_name,
            tool_use_id=tool_use_id,
            surface=surface,
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
        )
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
        self._record(session, "tool_call_finished", payload)

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
        self._record(session, "tool_call_finished", payload)

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
        self._record(
            session,
            "permission_requested",
            {
                "call_ref": context.call_ref,
                "ordinal": context.ordinal,
                "tool_name": context.tool_name,
                "tool_use_id": context.tool_use_id or "",
                "reason": reason,
                "input_data": input_data,
                "original_input": original_input,
                "user_modified": user_modified,
                "request": request_data,
            },
        )
        pending = session.runtime_state.get("session_log_pending_tool_calls")
        if not isinstance(pending, dict):
            pending = {}
        pending[context.call_ref] = {
            "call_ref": context.call_ref,
            "ordinal": context.ordinal,
            "tool_name": context.tool_name,
            "tool_use_id": context.tool_use_id or "",
            "surface": context.surface,
            "input_data": context.input_data,
        }
        session.runtime_state["session_log_pending_tool_calls"] = pending

    def record_permission_resolved(self, session: SessionTranscript, *, approved: bool, pending: dict[str, object]) -> None:
        """记录一次权限请求被用户同意或拒绝。"""
        self._record(
            session,
            "permission_resolved",
            {
                "approved": approved,
                "tool_name": str(pending.get("tool_name", "")).strip(),
                "tool_use_id": str(pending.get("tool_use_id", "")).strip(),
                "approval_key": (
                    str(pending.get("request", {}).get("approval_key", "")).strip()
                    if isinstance(pending.get("request"), dict)
                    else ""
                ),
            },
        )

    def record_text_delta(self, session: SessionTranscript, text: str) -> None:
        """按配置选择是否记录 provider 的文本增量。"""
        if not self.settings.include_text_deltas or not text:
            return
        self._record(session, "provider_text_delta", {"text": text})

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
            input_data=data.get("input_data") if isinstance(data.get("input_data"), dict) else {},
        )

    def _record(
        self,
        session: SessionTranscript,
        event: str,
        data: dict[str, object],
        *,
        turn_index: int | None = None,
    ) -> None:
        """把一条统一事件同时写入 `.jsonl` 和 `.log`。"""
        if not self.enabled():
            return
        bundle, _ = self.ensure_bundle(session)
        if bundle is None:
            return
        lock = self._locks.setdefault(session.session_id, threading.Lock())
        try:
            with lock:
                actual_turn_index = turn_index if turn_index is not None else self.current_turn_index(session)
                event_index = int(session.runtime_state.get("session_log_event_index", 0) or 0) + 1
                session.runtime_state["session_log_event_index"] = event_index
                record = SessionLogRecord(
                    version=SESSION_LOG_RECORD_VERSION,
                    session_id=session.session_id,
                    turn_index=actual_turn_index,
                    event_index=event_index,
                    timestamp=utc_now(),
                    event=event,
                    data=data,
                )
                if self.settings.write_jsonl_log:
                    self._jsonl_writer.append(bundle.jsonl_path, record)
                if self.settings.write_human_log:
                    rendered = render_record(record, self.settings)
                    if rendered:
                        self._text_writer.append(bundle.log_path, rendered)
        except Exception:
            return

    def _mark_current_turn_error(self, session: SessionTranscript) -> None:
        """标记当前 turn 已经发生过错误，供 `turn_finished` 汇总状态使用。"""
        session.runtime_state["session_log_current_turn_had_error"] = True
