from __future__ import annotations

import re

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
    def __init__(
        self,
        *,
        provider: Provider,
        session_store: SessionStore,
    ) -> None:
        self.provider = provider
        self.session_store = session_store
        self.tool_runtime = ToolRuntime(build_builtin_tools())
        self.command_processor = CommandProcessor(session_store, self.tool_runtime)
        self.query_engine = QueryEngine(
            provider=provider,
            session_store=session_store,
            tool_runtime=self.tool_runtime,
        )

    async def handle(
        self,
        session: SessionTranscript,
        prompt: str,
        *,
        tool_event_handler: ToolEventHandler | None = None,
    ) -> CommandOutcome:
        prompt = prompt.strip()
        if not prompt:
            return CommandOutcome(session=session)

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

            if resolution and request is not None and request.approval_key:
                add_approved_permission(session, request.approval_key)

            source_type = str(pending.get("source_type", ""))
            if source_type == "slash_command":
                outcome = self.command_processor.resume_pending_permission(
                    session,
                    pending,
                    approved=resolution,
                    event_handler=tool_event_handler,
                )
                self._append_task_notifications(outcome.session)
                return outcome
            if source_type == "tool_call":
                session = await self.query_engine.resume_pending_tool_call(
                    session,
                    pending,
                    approved=resolution,
                    tool_event_handler=tool_event_handler,
                )
                self._append_task_notifications(session)
                return CommandOutcome(session=session, message_added=True)

        if prompt.startswith("/"):
            outcome = self.command_processor.process(
                session,
                prompt,
                event_handler=tool_event_handler,
            )
            self._append_task_notifications(outcome.session)
            return outcome

        explicit_tool = self._match_explicit_tool_request(session, prompt)
        if explicit_tool is not None:
            session.add_message(
                "user",
                prompt,
                content_blocks=[{"type": "text", "text": prompt}],
            )
            self.session_store.save(session)
            outcome = self.command_processor.run_tool_input(
                session,
                explicit_tool,
                {},
                event_handler=tool_event_handler,
            )
            self._append_task_notifications(outcome.session)
            return outcome

        session = await self.query_engine.submit(
            session,
            prompt,
            tool_event_handler=tool_event_handler,
        )
        self._append_task_notifications(session)
        return CommandOutcome(session=session, message_added=True)

    def _parse_permission_response(self, prompt: str) -> bool | None:
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
        mapping = {
            "completed": "完成",
            "failed": "失败",
            "killed": "停止",
            "exited": "退出",
            "running": "运行",
            "pending": "等待",
        }
        return mapping.get(status, status)

    def _match_explicit_tool_request(
        self,
        session: SessionTranscript,
        prompt: str,
    ) -> str | None:
        lowered = prompt.lower()
        if not any(marker in prompt for marker in ("使用", "调用", "执行")) and not any(
            marker in lowered for marker in ("use ", "call ", "run ")
        ):
            return None
        matches: list[str] = []
        for tool in self.tool_runtime.list_tools_for_session(session):
            if not tool.name.startswith("mcp__"):
                continue
            if tool.name not in prompt:
                continue
            required = tool.input_schema.get("required", [])
            if isinstance(required, list) and len(required) == 0:
                matches.append(tool.name)
        if len(matches) == 1:
            return matches[0]
        return None
