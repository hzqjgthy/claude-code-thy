from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from claude_code_thy.models import SessionTranscript
from claude_code_thy.permissions import PermissionRequest
from claude_code_thy.session.runtime_state import clear_pending_permission, set_pending_permission
from claude_code_thy.session.store import SessionStore, SessionSummary
from claude_code_thy.tools import PermissionRequiredError, ToolError, ToolEventHandler, ToolRuntime


@dataclass(slots=True)
class CommandOutcome:
    session: SessionTranscript
    message_added: bool = False
    should_refresh_only: bool = False


class CommandProcessor:
    def __init__(self, session_store: SessionStore, tool_runtime: ToolRuntime) -> None:
        self.session_store = session_store
        self.tool_runtime = tool_runtime

    def process(
        self,
        session: SessionTranscript,
        raw_prompt: str,
        *,
        event_handler: ToolEventHandler | None = None,
    ) -> CommandOutcome:
        command_line = raw_prompt.strip()
        command, _, raw_args = command_line.partition(" ")
        command = command.lower()
        raw_args = raw_args.strip()
        args = raw_args.split() if raw_args else []

        if command == "/help":
            return self._append_message(session, self._help_text())
        if command == "/status":
            return self._append_message(session, self._status_text(session))
        if command == "/sessions":
            return self._append_message(session, self._sessions_text())
        if command == "/init":
            return self._append_message(session, self._init_claude_md(session.cwd))
        if command == "/model":
            return self._model(session, args)
        if command == "/tools":
            return self._append_message(session, self._tools_text())
        if command == "/tasks":
            return self._append_message(session, self._tasks_text(session))
        if command == "/agents":
            return self._append_message(session, self._agents_text(session))
        if command == "/agent":
            return self._run_tool(session, "agent", raw_args, event_handler=event_handler)
        if command == "/agent-run":
            return self._append_message(session, self._agent_run(session, raw_args))
        if command == "/agent-wait":
            return self._append_message(session, self._agent_wait(session, args))
        if command == "/task-stop":
            return self._append_message(session, self._task_stop(session, args))
        if command == "/task-output":
            return self._append_message(session, self._task_output_text(session, args))
        if command == "/bash":
            return self._run_tool(session, "bash", raw_args, event_handler=event_handler)
        if command == "/read":
            return self._run_tool(session, "read", raw_args, event_handler=event_handler)
        if command == "/write":
            return self._run_tool(session, "write", raw_args, event_handler=event_handler)
        if command == "/edit":
            return self._run_tool(session, "edit", raw_args, event_handler=event_handler)
        if command == "/glob":
            return self._run_tool(session, "glob", raw_args, event_handler=event_handler)
        if command == "/grep":
            return self._run_tool(session, "grep", raw_args, event_handler=event_handler)
        if command == "/clear":
            session.clear_messages()
            self.session_store.save(session)
            return CommandOutcome(session=session, should_refresh_only=True)
        if command == "/resume":
            return self._resume(session, args)

        return self._append_message(
            session,
            f"暂不支持命令 `{command}`。\n\n可用命令：/help /status /sessions /resume /model /tools /tasks /agents /agent /agent-run /agent-wait /task-stop /task-output /bash /read /write /edit /glob /grep /init /clear",
        )

    def resume_pending_permission(
        self,
        session: SessionTranscript,
        pending: dict[str, object],
        *,
        approved: bool,
        event_handler: ToolEventHandler | None = None,
    ) -> CommandOutcome:
        tool_name = str(pending.get("tool_name", "")).strip()
        raw_args = str(pending.get("raw_args", ""))
        input_data = pending.get("input_data", {})
        original_input = pending.get("original_input", {})

        request_data = pending.get("request", {})
        request = (
            PermissionRequest.from_dict(request_data)
            if isinstance(request_data, dict)
            else None
        )
        clear_pending_permission(session)

        if not tool_name:
            self.session_store.save(session)
            return CommandOutcome(session=session)

        if not approved:
            reason = request.reason if request is not None else ""
            rejected = self.tool_runtime.render_rejected(
                tool_name,
                input_data if isinstance(input_data, dict) else {},
                session,
                reason=reason or "权限请求已拒绝。",
                original_input=original_input if isinstance(original_input, dict) else None,
            )
            session.add_message(
                "tool",
                rejected.render(),
                metadata=rejected.message_metadata(),
            )
            self.session_store.save(session)
            return CommandOutcome(session=session, message_added=True)

        try:
            if isinstance(input_data, dict) and input_data:
                result = self.tool_runtime.execute_input(
                    tool_name,
                    input_data,
                    session,
                    original_input=original_input if isinstance(original_input, dict) else None,
                    event_handler=event_handler,
                )
            else:
                result = self.tool_runtime.execute(
                    tool_name,
                    raw_args,
                    session,
                    event_handler=event_handler,
                )
        except PermissionRequiredError as error:
            set_pending_permission(
                session,
                error.request,
                source_type="slash_command",
                tool_name=tool_name,
                raw_args=raw_args,
                input_data=error.input_data,
                original_input=error.original_input,
                user_modified=error.user_modified,
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
            return CommandOutcome(session=session, message_added=True)
        except ToolError as error:
            session.add_message(
                "tool",
                f"工具 `{tool_name}` 执行失败：{error}",
                metadata={
                    "tool_name": tool_name,
                    "display_name": tool_name,
                    "ui_kind": "error",
                    "ok": False,
                    "summary": f"工具 `{tool_name}` 执行失败",
                    "metadata": {},
                    "preview": "",
                    "output": str(error),
                },
            )
            self.session_store.save(session)
            return CommandOutcome(session=session, message_added=True)

        session.add_message(
            "tool",
            result.render(),
            metadata=result.message_metadata(),
        )
        self.session_store.save(session)
        return CommandOutcome(session=session, message_added=True)

    def _append_message(self, session: SessionTranscript, text: str) -> CommandOutcome:
        session.add_message("assistant", text)
        self.session_store.save(session)
        return CommandOutcome(session=session, message_added=True)

    def _help_text(self) -> str:
        return (
            "可用命令：\n"
            "/help      查看命令帮助\n"
            "/status    查看当前会话状态\n"
            "/sessions  查看最近会话\n"
            "/resume    恢复指定或最近会话\n"
            "/model     查看或设置当前模型\n"
            "/tools     查看可用工具\n"
            "/tasks     查看后台任务\n"
            "/agents    查看 agent 任务\n"
            "/agent     通过内置工具启动 agent\n"
            "/agent-run 启动一个后台 agent\n"
            "/agent-wait 等待 agent 完成\n"
            "/task-stop 停止后台任务\n"
            "/task-output 查看后台任务输出尾部\n"
            "/bash      执行 shell 命令\n"
            "/read      读取文件\n"
            "/write     写入文件\n"
            "/edit      按 old/new 规则编辑文件\n"
            "/glob      按 pattern 查找文件\n"
            "/grep      搜索文本\n"
            "/init      在当前目录创建 CLAUDE.md\n"
            "/clear     清空当前会话消息"
        )

    def _status_text(self, session: SessionTranscript) -> str:
        transcript_path = self.session_store.path_for(session.session_id)
        return (
            "当前会话状态：\n"
            f"session_id: {session.session_id}\n"
            f"title: {session.title or '(empty)'}\n"
            f"cwd: {session.cwd}\n"
            f"provider: {session.provider_name or 'unknown'}\n"
            f"model: {session.model or '(unset)'}\n"
            f"messages: {len(session.messages)}\n"
            f"tools: {len(self.tool_runtime.list_tools())}\n"
            f"transcript: {transcript_path}\n\n"
            f"恢复命令：claude-code-thy --resume {session.session_id}"
        )

    def _sessions_text(self) -> str:
        sessions = self.session_store.list_recent(limit=10)
        if not sessions:
            return "当前还没有可恢复的会话。"

        lines = ["最近会话："]
        for summary in sessions:
            lines.append(self._format_summary(summary))
        return "\n".join(lines)

    def _resume(
        self,
        current_session: SessionTranscript,
        args: list[str],
    ) -> CommandOutcome:
        target_session: SessionTranscript | None = None

        if args:
            target = args[0]
            try:
                if target == "latest":
                    target_session = self.session_store.load_latest(exclude_session_id=current_session.session_id)
                else:
                    target_session = self.session_store.load(target)
            except FileNotFoundError:
                return self._append_message(current_session, f"未找到会话：{target}")
        else:
            target_session = self.session_store.load_latest(exclude_session_id=current_session.session_id)

        if target_session is None:
            return self._append_message(current_session, "没有找到可恢复的其他会话。")

        return CommandOutcome(session=target_session, should_refresh_only=True)

    def _init_claude_md(self, cwd: str) -> str:
        path = Path(cwd) / "CLAUDE.md"
        if path.exists():
            return f"CLAUDE.md 已存在：{path}"

        content = (
            "# CLAUDE.md\n\n"
            "这是 `claude-code-thy` 生成的项目说明文件。\n\n"
            "你可以在这里补充：\n\n"
            "- 项目目标\n"
            "- 代码规范\n"
            "- 常用命令\n"
            "- 测试方式\n"
            "- 注意事项\n"
        )
        path.write_text(content, encoding="utf-8")
        return f"已创建 CLAUDE.md：{path}"

    def _model(self, session: SessionTranscript, args: list[str]) -> CommandOutcome:
        if not args:
            return self._append_message(
                session,
                f"当前模型：{session.model or '(unset)'}",
            )

        session.model = args[0]
        self.session_store.save(session)
        return self._append_message(session, f"已将当前会话模型切换为：{session.model}")

    def _tools_text(self) -> str:
        lines = ["可用工具："]
        for tool in self.tool_runtime.list_tools():
            suffix = f"\n  用法: {tool.usage}" if getattr(tool, "usage", "") else ""
            meta: list[str] = []
            if tool.is_read_only():
                meta.append("read-only")
            if tool.is_concurrency_safe():
                meta.append("concurrency-safe")
            behavior = tool.search_behavior()
            if behavior.get("is_search"):
                meta.append("search")
            if behavior.get("is_read"):
                meta.append("read")
            meta_text = f" [{' · '.join(meta)}]" if meta else ""
            lines.append(f"- {tool.name}{meta_text}: {tool.description}{suffix}")
        return "\n".join(lines)

    def _tasks_text(self, session: SessionTranscript) -> str:
        tasks = self.tool_runtime.services_for(session).task_manager.list_task_records()
        if not tasks:
            return "当前没有后台任务。"

        lines = ["后台任务："]
        for task in tasks[:20]:
            status = task.status
            if task.return_code is not None:
                status = f"{status} (exit={task.return_code})"
            task_kind = getattr(task, "task_kind", task.task_type)
            description = getattr(task, "description", "")
            command = getattr(task, "command", "")
            lines.append(
                f"- {task.task_id} | {task.task_type}/{task_kind} | {status} | {description or command} | {task.started_at}"
            )
        return "\n".join(lines)

    def _agents_text(self, session: SessionTranscript) -> str:
        tasks = [
            task
            for task in self.tool_runtime.services_for(session).task_manager.list_task_records()
            if task.task_type == "local_agent"
        ]
        if not tasks:
            return "当前没有 agent 任务。"
        lines = ["Agent 任务："]
        for task in tasks[:20]:
            status = task.status
            if task.return_code is not None:
                status = f"{status} (exit={task.return_code})"
            prompt = str(task.metadata.get("prompt", "")).strip()
            lines.append(f"- {task.task_id} | {status} | {prompt or task.description}")
        return "\n".join(lines)

    def _agent_run(self, session: SessionTranscript, raw_args: str) -> str:
        prompt = raw_args.strip()
        if not prompt:
            return "用法：/agent-run <prompt>"
        result = self.tool_runtime.execute_input(
            "agent",
            {
                "prompt": prompt,
                "description": f"Agent: {prompt[:48]}",
                "model": session.model,
                "run_in_background": True,
            },
            session,
        )
        task_id = ""
        if isinstance(result.structured_data, dict):
            task_id = str(result.structured_data.get("task_id", "")).strip()
        lines = [f"已启动后台 agent：{task_id or '(unknown)'}", f"prompt: {prompt}"]
        if isinstance(result.structured_data, dict) and result.structured_data.get("output_path"):
            lines.append(f"输出文件: {result.structured_data['output_path']}")
        if task_id:
            lines.append(f"可使用 `/task-output {task_id}` 查看输出。")
        return "\n".join(lines)

    def _agent_wait(self, session: SessionTranscript, args: list[str]) -> str:
        if not args:
            return "用法：/agent-wait <task_id> [timeout_seconds]"
        task_id = args[0]
        timeout_seconds = 30.0
        if len(args) > 1:
            try:
                timeout_seconds = max(0.1, float(args[1]))
            except ValueError:
                return "timeout_seconds 必须是数字。"
        manager = self.tool_runtime.services_for(session).task_manager
        task = manager.wait_for_task(task_id, timeout_seconds=timeout_seconds)
        if task is None:
            return f"未找到 agent 任务：{task_id}"
        if task.task_type != "local_agent":
            return f"任务 {task_id} 不是 agent 任务。"
        output = manager.read_output(task_id, tail_lines=120) or ""
        header = f"Agent {task_id} 当前状态：{task.status}"
        if output.strip():
            return f"{header}\n\n{output}"
        return header

    def _task_output_text(self, session: SessionTranscript, args: list[str]) -> str:
        if not args:
            return "用法：/task-output <task_id> [lines]"

        task_id = args[0]
        tail_lines = 120
        if len(args) > 1:
            try:
                tail_lines = max(1, int(args[1]))
            except ValueError:
                return "lines 必须是正整数。"

        manager = self.tool_runtime.services_for(session).task_manager
        task = manager.get(task_id)
        if task is None:
            return f"未找到后台任务：{task_id}"
        task = manager.refresh(task)
        output = manager.read_output(task_id, tail_lines=tail_lines)
        if output is None:
            return f"未找到后台任务：{task_id}"
        if not output.strip():
            return f"任务 {task_id} 暂无输出。状态：{task.status}"
        return (
            f"任务 {task_id} 输出尾部（最近 {tail_lines} 行）：\n\n"
            f"{output}"
        )

    def _task_stop(self, session: SessionTranscript, args: list[str]) -> str:
        if not args:
            return "用法：/task-stop <task_id>"
        task_id = args[0]
        manager = self.tool_runtime.services_for(session).task_manager
        task = manager.stop_task(task_id)
        if task is None:
            return f"未找到后台任务：{task_id}"
        return f"已停止任务：{task_id}，当前状态：{task.status}"

    def _run_tool(
        self,
        session: SessionTranscript,
        tool_name: str,
        raw_args: str,
        *,
        event_handler: ToolEventHandler | None = None,
    ) -> CommandOutcome:
        try:
            result = self.tool_runtime.execute(
                tool_name,
                raw_args,
                session,
                event_handler=event_handler,
            )
        except PermissionRequiredError as error:
            set_pending_permission(
                session,
                error.request,
                source_type="slash_command",
                tool_name=tool_name,
                raw_args=raw_args,
                input_data=error.input_data,
                original_input=error.original_input,
                user_modified=error.user_modified,
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
            return CommandOutcome(session=session, message_added=True)
        except ToolError as error:
            session.add_message(
                "tool",
                f"工具 `{tool_name}` 执行失败：{error}",
                metadata={
                    "tool_name": tool_name,
                    "display_name": tool_name,
                    "ui_kind": "error",
                    "ok": False,
                    "summary": f"工具 `{tool_name}` 执行失败",
                    "metadata": {},
                    "preview": "",
                    "output": str(error),
                },
            )
            self.session_store.save(session)
            return CommandOutcome(session=session, message_added=True)

        session.add_message(
            "tool",
            result.render(),
            metadata=result.message_metadata(),
        )
        self.session_store.save(session)
        return CommandOutcome(session=session, message_added=True)

    def _format_summary(self, summary: SessionSummary) -> str:
        return (
            f"- {summary.session_id} | {summary.updated_at} | "
            f"{summary.title or '(untitled)'} | {summary.model or '(no-model)'} | {summary.cwd}"
        )


def format_session_summaries(summaries: Iterable[SessionSummary]) -> str:
    lines = []
    for summary in summaries:
        lines.append(
            f"{summary.session_id}\t{summary.updated_at}\t{summary.title or '(untitled)'}\t{summary.cwd}"
        )
    return "\n".join(lines)
