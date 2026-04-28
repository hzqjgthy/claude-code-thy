from __future__ import annotations

from claude_code_thy.models import build_session_title
from claude_code_thy.commands import CommandProcessor, CommandOutcome
from claude_code_thy.models import SessionTranscript
from claude_code_thy.providers.base import Provider
from claude_code_thy.query_engine import QueryEngine
from claude_code_thy.session.runtime_state import (
    add_approved_permission,
    get_pending_permission,
    pending_request,
)
from claude_code_thy.session.store import SessionStore
from claude_code_thy.tools import ToolError, ToolEventHandler, ToolRuntime, build_builtin_tools


class ConversationRuntime:
    """串起 slash 命令、普通对话、权限确认和任务通知的总入口。"""
    def __init__(
        self,
        *,
        provider: Provider,
        session_store: SessionStore,
        query_max_iterations: int | None = None,
    ) -> None:
        """创建对话运行所需的工具运行时、命令处理器和查询引擎。"""
        self.provider = provider
        self.session_store = session_store
        self.tool_runtime = ToolRuntime(build_builtin_tools())
        self.command_processor = CommandProcessor(session_store, self.tool_runtime)
        resolved_query_max_iterations = query_max_iterations
        if resolved_query_max_iterations is None:
            provider_config = getattr(provider, "config", None)
            configured_value = getattr(provider_config, "query_max_iterations", None)
            if isinstance(configured_value, int):
                resolved_query_max_iterations = configured_value
        self.query_engine = QueryEngine(
            provider=provider,
            session_store=session_store,
            tool_runtime=self.tool_runtime,
            max_iterations=resolved_query_max_iterations or 1000,
        )
        self._logged_sessions_in_process: set[str] = set()

    async def handle(
        self,
        session: SessionTranscript,
        prompt: str,
        *,
        tool_event_handler: ToolEventHandler | None = None,
    ) -> CommandOutcome:
        """处理一条用户输入，并决定走命令、权限恢复还是正常对话。"""
        prompt = prompt.strip()
        if not prompt:
            return CommandOutcome(session=session)

        log_session = session
        log_manager = self._ensure_session_logging(log_session, prompt=prompt)
        if log_manager is not None:
            log_manager.start_turn(
                log_session,
                prompt=prompt,
                input_kind=self._input_kind(log_session, prompt),
                stream=False,
            )
        start_message_count = len(log_session.messages)
        wrapped_tool_event_handler = self._compose_tool_event_handler(log_session, tool_event_handler)
        ended_with_error = False

        try:
            pending = get_pending_permission(session)
            if pending is not None:
                resolution = self._parse_permission_response(prompt)
                request = pending_request(session)
                if resolution is None:
                    text = (
                        request.prompt_text()
                        if request is not None
                        else "当前有一个待确认的权限请求，请回复 `yes` 或 `no`。"
                    )
                    session.add_message(
                        "assistant",
                        text,
                        metadata={
                            "ui_kind": "permission_prompt",
                            **(
                                {"pending_permission": request.to_dict()}
                                if request is not None
                                else {}
                            ),
                        },
                    )
                    self.session_store.save(session)
                    return CommandOutcome(session=session, message_added=True)
                return await self.resolve_pending_permission(
                    session,
                    approved=resolution,
                    tool_event_handler=wrapped_tool_event_handler,
                    _skip_turn_logging=True,
                )

            if prompt.startswith("/"):
                outcome = self.command_processor.process(
                    session,
                    prompt,
                    event_handler=wrapped_tool_event_handler,
                )
                if log_manager is not None:
                    command, _, raw_args = prompt.partition(" ")
                    log_manager.record_command_parsed(
                        log_session,
                        raw_prompt=prompt,
                        command=command.strip().lower(),
                        raw_args=raw_args.strip(),
                        submit_prompt=outcome.submit_prompt,
                        model_override=outcome.model_override,
                    )
                if outcome.submit_prompt is not None:
                    original_model = session.model
                    if outcome.model_override:
                        session.model = outcome.model_override
                    session = await self.query_engine.submit(
                        outcome.session,
                        outcome.submit_prompt,
                        tool_event_handler=wrapped_tool_event_handler,
                    )
                    if outcome.model_override:
                        session.model = original_model
                        self.session_store.save(session)
                    if not outcome.suppress_task_notifications:
                        self._append_task_notifications(session)
                    return CommandOutcome(session=session, message_added=True)
                if not outcome.suppress_task_notifications:
                    self._append_task_notifications(outcome.session)
                return outcome

            session = await self.query_engine.submit(
                session,
                prompt,
                tool_event_handler=wrapped_tool_event_handler,
            )
            self._append_task_notifications(session)
            return CommandOutcome(session=session, message_added=True)
        except Exception as error:
            ended_with_error = True
            if log_manager is not None:
                log_manager.record_runtime_error(log_session, stage="runtime.handle", error=error)
            raise
        finally:
            if log_manager is not None:
                log_manager.finish_turn(
                    log_session,
                    new_message_count=max(len(log_session.messages) - start_message_count, 0),
                    ended_with_error=ended_with_error,
                    ended_with_pending_permission=get_pending_permission(log_session) is not None,
                )

    async def handle_stream(
        self,
        session: SessionTranscript,
        prompt: str,
        *,
        tool_event_handler: ToolEventHandler | None = None,
        text_delta_handler=None,
        message_added_handler=None,
    ) -> CommandOutcome:
        """处理一条输入，并在普通文本回复阶段发射增量文本事件。"""
        prompt = prompt.strip()
        if not prompt:
            return CommandOutcome(session=session)

        initial_message_count = len(session.messages)
        pending = get_pending_permission(session)
        if pending is not None:
            outcome = await self.handle(
                session,
                prompt,
                tool_event_handler=tool_event_handler,
            )
            self._emit_stream_messages(
                outcome.session,
                start_index=initial_message_count,
                message_added_handler=message_added_handler,
            )
            return outcome

        log_session = session
        log_manager = self._ensure_session_logging(log_session, prompt=prompt)
        if log_manager is not None:
            log_manager.start_turn(
                log_session,
                prompt=prompt,
                input_kind=self._input_kind(log_session, prompt),
                stream=True,
            )
        start_message_count = len(log_session.messages)
        wrapped_tool_event_handler = self._compose_tool_event_handler(log_session, tool_event_handler)
        ended_with_error = False

        try:
            if prompt.startswith("/"):
                outcome = self.command_processor.process(
                    session,
                    prompt,
                    event_handler=wrapped_tool_event_handler,
                )
                if log_manager is not None:
                    command, _, raw_args = prompt.partition(" ")
                    log_manager.record_command_parsed(
                        log_session,
                        raw_prompt=prompt,
                        command=command.strip().lower(),
                        raw_args=raw_args.strip(),
                        submit_prompt=outcome.submit_prompt,
                        model_override=outcome.model_override,
                    )
                if outcome.submit_prompt is not None:
                    original_model = session.model
                    if outcome.model_override:
                        session.model = outcome.model_override
                    session = await self.query_engine.stream_submit(
                        outcome.session,
                        outcome.submit_prompt,
                        tool_event_handler=wrapped_tool_event_handler,
                        text_delta_handler=text_delta_handler,
                        message_added_handler=message_added_handler,
                    )
                    if outcome.model_override:
                        session.model = original_model
                        self.session_store.save(session)
                    if not outcome.suppress_task_notifications:
                        task_start = len(session.messages)
                        self._append_task_notifications(session)
                        self._emit_stream_messages(
                            session,
                            start_index=task_start,
                            message_added_handler=message_added_handler,
                        )
                    return CommandOutcome(session=session, message_added=True)

                if not outcome.suppress_task_notifications:
                    task_start = len(outcome.session.messages)
                    self._append_task_notifications(outcome.session)
                    self._emit_stream_messages(
                        outcome.session,
                        start_index=task_start,
                        message_added_handler=message_added_handler,
                    )
                self._emit_stream_messages(
                    outcome.session,
                    start_index=initial_message_count,
                    message_added_handler=message_added_handler,
                )
                return outcome

            session = await self.query_engine.stream_submit(
                session,
                prompt,
                tool_event_handler=wrapped_tool_event_handler,
                text_delta_handler=text_delta_handler,
                message_added_handler=message_added_handler,
            )
            task_start = len(session.messages)
            self._append_task_notifications(session)
            self._emit_stream_messages(
                session,
                start_index=task_start,
                message_added_handler=message_added_handler,
            )
            return CommandOutcome(session=session, message_added=True)
        except Exception as error:
            ended_with_error = True
            if log_manager is not None:
                log_manager.record_runtime_error(log_session, stage="runtime.handle_stream", error=error)
            raise
        finally:
            if log_manager is not None:
                log_manager.finish_turn(
                    log_session,
                    new_message_count=max(len(log_session.messages) - start_message_count, 0),
                    ended_with_error=ended_with_error,
                    ended_with_pending_permission=get_pending_permission(log_session) is not None,
                )

    async def resolve_pending_permission(
        self,
        session: SessionTranscript,
        *,
        approved: bool,
        tool_event_handler: ToolEventHandler | None = None,
        _skip_turn_logging: bool = False,
    ) -> CommandOutcome:
        """显式恢复当前会话中挂起的权限确认，供 Web API 等非文本入口复用。"""
        pending = get_pending_permission(session)
        if pending is None:
            return CommandOutcome(session=session)

        log_manager = self._ensure_session_logging(
            session,
            prompt="批准待确认权限请求" if approved else "拒绝待确认权限请求",
        )
        if log_manager is not None and not _skip_turn_logging:
            log_manager.start_turn(
                session,
                prompt="批准待确认权限请求" if approved else "拒绝待确认权限请求",
                input_kind="permission_resolution",
                stream=False,
            )
        start_message_count = len(session.messages)
        ended_with_error = False
        wrapped_tool_event_handler = self._compose_tool_event_handler(session, tool_event_handler)

        request = pending_request(session)
        if approved and request is not None and request.approval_key:
            add_approved_permission(session, request.approval_key)
        if log_manager is not None:
            log_manager.record_permission_resolved(session, approved=approved, pending=pending)

        try:
            source_type = str(pending.get("source_type", ""))
            if source_type == "slash_command":
                outcome = self.command_processor.resume_pending_permission(
                    session,
                    pending,
                    approved=approved,
                    event_handler=wrapped_tool_event_handler,
                )
                if not outcome.suppress_task_notifications:
                    self._append_task_notifications(outcome.session)
                return outcome
            if source_type == "tool_call":
                session = await self.query_engine.resume_pending_tool_call(
                    session,
                    pending,
                    approved=approved,
                    tool_event_handler=wrapped_tool_event_handler,
                )
                self._append_task_notifications(session)
                return CommandOutcome(session=session, message_added=True)
            return CommandOutcome(session=session)
        except Exception as error:
            ended_with_error = True
            if log_manager is not None:
                log_manager.record_runtime_error(session, stage="runtime.resolve_pending_permission", error=error)
            raise
        finally:
            if log_manager is not None and not _skip_turn_logging:
                log_manager.finish_turn(
                    session,
                    new_message_count=max(len(session.messages) - start_message_count, 0),
                    ended_with_error=ended_with_error,
                    ended_with_pending_permission=get_pending_permission(session) is not None,
                )

    def _parse_permission_response(self, prompt: str) -> bool | None:
        """把用户输入解析成允许、拒绝或无法识别的权限回应。"""
        normalized = prompt.strip().lower()
        if normalized in {
            "y",
            "yes",
            "approve",
            "approved",
            "ok",
            "allow",
            "允许",
            "同意",
            "确认",
            "继续",
        }:
            return True
        if normalized in {
            "n",
            "no",
            "deny",
            "denied",
            "reject",
            "拒绝",
            "取消",
            "不允许",
            "不要",
        }:
            return False
        return None

    def _append_task_notifications(self, session: SessionTranscript) -> None:
        """把当前会话关联的后台任务完成通知追加到消息流中。"""
        try:
            manager = self.tool_runtime.services_for(session).task_manager
        except ToolError:
            return

        seen = session.runtime_state.get("task_notifications", {})
        if not isinstance(seen, dict):
            seen = {}

        changed = False
        for task in manager.list_task_records():
            task_session_id = ""
            if isinstance(task.metadata, dict):
                task_session_id = str(task.metadata.get("session_id", "")).strip()
            if task_session_id != session.session_id:
                continue
            if not task.is_terminal:
                continue
            marker = f"{task.status}:{task.finished_at or ''}:{task.return_code}"
            if seen.get(task.task_id) == marker:
                continue
            output = manager.read_output(task.task_id, tail_lines=40) or ""
            if task.task_type == "local_agent":
                headline = f"Agent 任务 {task.task_id} 已{self._status_cn(task.status)}。"
            else:
                headline = f"任务 {task.task_id} 已{self._status_cn(task.status)}。"
            if output.strip():
                headline = f"{headline}\n\n{output.strip()}"
            session.add_message(
                "assistant",
                headline,
                metadata={
                    "ui_kind": "task_notification",
                    "task_id": task.task_id,
                    "task_status": task.status,
                    "task_type": task.task_type,
                },
            )
            seen[task.task_id] = marker
            changed = True

        if changed:
            session.runtime_state["task_notifications"] = seen
            self.session_store.save(session)

    def _status_cn(self, status: str) -> str:
        """把内部任务状态码转换成更直观的中文描述。"""
        mapping = {
            "completed": "完成",
            "failed": "失败",
            "killed": "停止",
            "exited": "退出",
            "running": "运行",
            "pending": "等待",
        }
        return mapping.get(status, status)

    async def aclose(self) -> None:
        """关闭当前对话运行期里持有的长生命周期工具资源。"""
        await self.tool_runtime.aclose()

    def _emit_stream_messages(
        self,
        session: SessionTranscript,
        *,
        start_index: int,
        message_added_handler,
    ) -> None:
        """把某个索引之后新增的消息顺序发给流式消费方。"""
        if message_added_handler is None:
            return
        for index in range(start_index, len(session.messages)):
            message_added_handler(index, session.messages[index])

    def _ensure_session_logging(self, session: SessionTranscript, *, prompt: str):
        """确保 session 已绑定日志管理器和消息 hook。"""
        try:
            services = self.tool_runtime.services_for(session)
        except ToolError:
            return None
        log_manager = services.session_log_manager
        log_manager.attach_message_hook(session)
        if session.session_id in self._logged_sessions_in_process:
            return log_manager

        bundle, created = log_manager.ensure_bundle(session)
        if bundle is not None and created:
            self.session_store.save(session)
            inferred_title = session.title
            if inferred_title is None and prompt and not prompt.startswith("/") and get_pending_permission(session) is None:
                inferred_title = build_session_title(prompt)
            log_manager.record_session_started(
                session,
                provider_name=self.provider.name,
                model=session.model or getattr(getattr(self.provider, "config", None), "model", "") or "",
                title=inferred_title,
            )
        else:
            log_manager.record_session_resumed(
                session,
                provider_name=self.provider.name,
                model=session.model or getattr(getattr(self.provider, "config", None), "model", "") or "",
            )
        self._logged_sessions_in_process.add(session.session_id)
        return log_manager

    def _compose_tool_event_handler(
        self,
        session: SessionTranscript,
        external_handler: ToolEventHandler | None,
    ) -> ToolEventHandler | None:
        """把外部事件处理器和日志记录器组合成一个 handler。"""
        log_manager = self._ensure_session_logging(session, prompt="")
        if log_manager is None:
            return external_handler

        def _handler(tool_event) -> None:
            log_manager.record_tool_event(session, tool_event)
            if external_handler is not None:
                external_handler(tool_event)

        return _handler

    def _input_kind(self, session: SessionTranscript, prompt: str) -> str:
        """根据当前上下文推断本轮输入类型。"""
        if get_pending_permission(session) is not None:
            return "permission_resolution"
        if prompt.startswith("/"):
            return "slash_command"
        return "chat"
