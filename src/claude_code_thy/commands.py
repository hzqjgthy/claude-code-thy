from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Iterable

from claude_code_thy.mcp.names import build_mcp_tool_name
from claude_code_thy.mcp.utils import run_async_sync
from claude_code_thy.models import SessionTranscript
from claude_code_thy.permissions import PermissionRequest
from claude_code_thy.session.runtime_state import clear_pending_permission, set_pending_permission
from claude_code_thy.session.store import SessionStore, SessionSummary
from claude_code_thy.tools.SkillTool import resolve_skill_prompt
from claude_code_thy.tools import PermissionRequiredError, ToolError, ToolEventHandler, ToolRuntime


@dataclass(slots=True)
class CommandOutcome:
    """描述一条 slash 命令执行后的会话变化和后续动作。"""
    session: SessionTranscript
    message_added: bool = False
    should_refresh_only: bool = False
    submit_prompt: str | None = None
    model_override: str | None = None
    suppress_task_notifications: bool = False


class CommandProcessor:
    """解析 slash 命令，并把它们分发到工具、会话操作或 prompt command。"""
    def __init__(self, session_store: SessionStore, tool_runtime: ToolRuntime) -> None:
        """注入会话存储和工具运行时，供命令执行时复用。"""
        self.session_store = session_store
        self.tool_runtime = tool_runtime

    def process(
        self,
        session: SessionTranscript,
        raw_prompt: str,
        *,
        event_handler: ToolEventHandler | None = None,
    ) -> CommandOutcome:
        """解析一条 slash 命令，并执行对应的本地逻辑或工具调用。"""
        command_line = raw_prompt.strip()
        command, _, raw_args = command_line.partition(" ")
        command = command.lower()
        normalized_command = self._normalize_dynamic_command_name(command)
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
            return self._append_message(session, self._tools_text(session))
        if command == "/skills":
            return self._append_message(session, self._skills_text(session))
        if command == "/mcp":
            return self._append_message(session, self._mcp_text(session))
        if command == "/tasks":
            return self._append_message(
                session,
                self._tasks_text(session),
                suppress_task_notifications=True,
            )
        if command == "/agents":
            return self._append_message(
                session,
                self._agents_text(session),
                suppress_task_notifications=True,
            )
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
        if command in {"/browser-search", "/browser_search"}:
            return self._run_tool(session, "browser_search", raw_args, event_handler=event_handler)
        if command == "/browser":
            return self._run_tool(session, "browser", raw_args, event_handler=event_handler)
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
        if command == "/skill":
            return self._run_skill_command(session, raw_args)
        if command == "/clear":
            session.clear_messages()
            self.session_store.save(session)
            return CommandOutcome(session=session, should_refresh_only=True)
        if command == "/resume":
            return self._resume(session, args)

        dynamic_tool = self._run_dynamic_tool(
            session,
            normalized_command,
            raw_args,
            event_handler=event_handler,
        )
        if dynamic_tool is not None:
            return dynamic_tool

        prompt_command = self._run_prompt_command(
            session,
            normalized_command,
            raw_args,
            event_handler=event_handler,
        )
        if prompt_command is not None:
            return prompt_command

        if normalized_command.startswith("/mcp__"):
            return self._append_message(
                session,
                self._missing_mcp_dynamic_command_text(session, normalized_command),
            )

        return self._append_message(
            session,
            f"暂不支持命令 `{command}`。\n\n可用命令：/help /status /sessions /resume /model /tools /skills /mcp /tasks /agents /agent /agent-run /agent-wait /task-stop /task-output /bash /browser-search /browser /read /write /edit /glob /grep /skill /init /clear",
        )

    def resume_pending_permission(
        self,
        session: SessionTranscript,
        pending: dict[str, object],
        *,
        approved: bool,
        event_handler: ToolEventHandler | None = None,
    ) -> CommandOutcome:
        """在用户确认后恢复一次被权限中断的 slash 命令执行。"""
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
            log_manager = self.tool_runtime.services_for(session).session_log_manager
            log_context = log_manager.take_pending_tool_call(
                session,
                tool_name=tool_name,
                tool_use_id=None,
                input_data=input_data if isinstance(input_data, dict) else {},
            )
            rejected = self.tool_runtime.render_rejected(
                tool_name,
                input_data if isinstance(input_data, dict) else {},
                session,
                reason=reason or "权限请求已拒绝。",
                original_input=original_input if isinstance(original_input, dict) else None,
            )
            if log_context is not None:
                log_manager.finish_tool_call(session, log_context, rejected)
            session.add_message(
                "tool",
                rejected.render(),
                metadata=rejected.message_metadata(),
            )
            self.session_store.save(session)
            return CommandOutcome(session=session, message_added=True)

        try:
            log_manager = self.tool_runtime.services_for(session).session_log_manager
            log_context = log_manager.take_pending_tool_call(
                session,
                tool_name=tool_name,
                tool_use_id=None,
                input_data=input_data if isinstance(input_data, dict) else {},
            )
            has_structured_input = "input_data" in pending and isinstance(input_data, dict)
            if has_structured_input:
                result = self.tool_runtime.execute_input(
                    tool_name,
                    input_data,
                    session,
                    original_input=original_input if isinstance(original_input, dict) else None,
                    event_handler=event_handler,
                    log_context=log_context,
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

    def run_tool_input(
        self,
        session: SessionTranscript,
        tool_name: str,
        input_data: dict[str, object],
        *,
        event_handler: ToolEventHandler | None = None,
    ) -> CommandOutcome:
        """运行 `tool_input`。"""
        try:
            result = self.tool_runtime.execute_input(
                tool_name,
                input_data,
                session,
                original_input=input_data,
                event_handler=event_handler,
            )
        except PermissionRequiredError as error:
            set_pending_permission(
                session,
                error.request,
                source_type="slash_command",
                tool_name=tool_name,
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

    def _append_message(
        self,
        session: SessionTranscript,
        text: str,
        *,
        suppress_task_notifications: bool = False,
    ) -> CommandOutcome:
        """向会话追加一条助手消息，并返回标准命令结果。"""
        session.add_message("assistant", text)
        self.session_store.save(session)
        return CommandOutcome(
            session=session,
            message_added=True,
            suppress_task_notifications=suppress_task_notifications,
        )

    def _help_text(self) -> str:
        """返回内置 slash 命令总览。"""
        return (
            "可用命令：\n"
            "/help      查看命令帮助\n"
            "/status    查看当前会话状态\n"
            "/sessions  查看最近会话\n"
            "/resume    恢复指定或最近会话\n"
            "/model     查看或设置当前模型\n"
            "/tools     查看可用工具\n"
            "/skills    查看可用 skills / prompt commands\n"
            "/mcp       查看当前 MCP server 配置快照\n"
            "/tasks     查看后台任务\n"
            "/agents    查看 agent 任务\n"
            "/agent     通过内置工具启动 agent\n"
            "/agent-run 启动一个后台 agent\n"
            "/agent-wait 等待 agent 完成\n"
            "/task-stop 停止后台任务\n"
            "/task-output 查看后台任务输出尾部\n"
            "/bash      执行 shell 命令\n"
            "/browser-search 搜索网页并展开结果\n"
            "/browser   控制隔离浏览器\n"
            "/read      读取文件\n"
            "/write     写入文件\n"
            "/edit      按 old/new 规则编辑文件\n"
            "/glob      按 pattern 查找文件\n"
            "/grep      搜索文本\n"
            "/skill     显式执行一个 skill\n"
            "/init      在当前目录创建 CLAUDE.md\n"
            "/clear     清空当前会话消息"
        )

    def _status_text(self, session: SessionTranscript) -> str:
        """汇总当前会话的模型、消息数、工具数和恢复命令。"""
        transcript_path = self.session_store.path_for(session.session_id)
        return (
            "当前会话状态：\n"
            f"session_id: {session.session_id}\n"
            f"title: {session.title or '(empty)'}\n"
            f"cwd: {session.cwd}\n"
            f"provider: {session.provider_name or 'unknown'}\n"
            f"model: {session.model or '(unset)'}\n"
            f"messages: {len(session.messages)}\n"
            f"execution_tools: {len(self.tool_runtime.list_tools_for_session(session, surface='execution'))}\n"
            f"model_tools: {len(self.tool_runtime.list_tools_for_session(session, surface='model'))}\n"
            f"transcript: {transcript_path}\n\n"
            f"恢复命令：claude-code-thy --resume {session.session_id}"
        )

    def _sessions_text(self) -> str:
        """列出最近保存的会话，方便用户恢复。"""
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
        """切换到指定会话，或在未传参时恢复最近一次其他会话。"""
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
        """在当前目录生成一个基础版 `CLAUDE.md`。"""
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
        """查看或切换当前会话使用的模型。"""
        if not args:
            return self._append_message(
                session,
                f"当前模型：{session.model or '(unset)'}",
            )

        session.model = args[0]
        self.session_store.save(session)
        return self._append_message(session, f"已将当前会话模型切换为：{session.model}")

    def _tools_text(self, session: SessionTranscript) -> str:
        """列出当前会话可见的工具及其只读/搜索等元信息。"""
        execution_tools = self.tool_runtime.list_tools_for_session(session, surface="execution")
        model_tools = self.tool_runtime.list_tools_for_session(session, surface="model")
        model_tool_names = {tool.name for tool in model_tools}

        lines = ["手动可执行工具："]
        for tool in execution_tools:
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
            if tool.name in model_tool_names:
                meta.append("model-visible")
            meta_text = f" [{' · '.join(meta)}]" if meta else ""
            lines.append(f"- {tool.name}{meta_text}: {tool.description}{suffix}")

        if model_tools:
            lines.append("")
            lines.append("当前主链可见工具：")
            for tool in model_tools:
                lines.append(f"- {tool.name}")
        return "\n".join(lines)

    def _tasks_text(self, session: SessionTranscript) -> str:
        """列出后台任务快照，供用户查看运行状态。"""
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

    def _mcp_text(self, session: SessionTranscript) -> str:
        """输出 MCP server 连接状态摘要。"""
        connections = self.tool_runtime.services_for(session).mcp_manager.snapshot()
        if not connections:
            return "当前没有配置 MCP server。"
        lines = ["MCP servers："]
        for connection in connections:
            detail = connection.error or connection.config.url or connection.config.command
            lines.append(
                f"- {connection.name} | {connection.config.scope}/{connection.config.type} | {connection.status} | {detail}"
            )
        lines.append("")
        lines.append("可使用 `claude-code-thy mcp list` 查看连接详情。")
        return "\n".join(lines)

    def _skills_text(self, session: SessionTranscript) -> str:
        """列出当前会话可触发的本地 skill、MCP skill 和 MCP prompt。"""
        services = self.tool_runtime.services_for(session)
        try:
            run_async_sync(services.mcp_manager.refresh_all())
        except Exception:
            pass
        commands = services.command_registry.list_user_commands(session, services)
        if not commands:
            return "当前没有可用 skills。"
        lines = ["可用 skills / prompt commands："]
        for command in commands:
            if command.kind == "mcp_prompt":
                lines.append(f"- /{command.name}: {command.description}")
                continue
            lines.append(f"- /skill {command.name}: {command.description}")
        return "\n".join(lines)

    def _agents_text(self, session: SessionTranscript) -> str:
        """只过滤展示后台任务中的本地 agent 任务。"""
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
        """用 agent 工具启动一个后台子 agent 任务。"""
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
        """阻塞等待指定 agent 任务完成，并读取其最新输出。"""
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
        """读取后台任务输出文件的尾部内容。"""
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
        """停止指定后台任务。"""
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
        """以原始字符串参数运行一个内置工具。"""
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
        """把会话摘要格式化成便于终端阅读的一行文本。"""
        return (
            f"- {summary.session_id} | {summary.updated_at} | "
            f"{summary.title or '(untitled)'} | {summary.model or '(no-model)'} | {summary.cwd}"
        )

    def _run_prompt_command(
        self,
        session: SessionTranscript,
        command: str,
        raw_args: str,
        *,
        event_handler: ToolEventHandler | None = None,
    ) -> CommandOutcome | None:
        """执行仍允许直接 slash 调用的 prompt command，目前主要是 MCP prompt。"""
        services = self.tool_runtime.services_for(session)
        if command.startswith("/mcp__"):
            try:
                run_async_sync(services.mcp_manager.refresh_all())
            except Exception:
                pass
        prompt_command = services.command_registry.find_user_command(session, services, command)
        if prompt_command is None:
            return None
        if prompt_command.kind != "mcp_prompt":
            return None
        rendered = services.command_registry.render_prompt(
            prompt_command,
            raw_args,
            session,
            services,
        ).strip()
        if not rendered:
            return self._append_message(session, f"命令 `{prompt_command.name}` 没有生成文本内容。")
        return CommandOutcome(
            session=session,
            submit_prompt=rendered,
            model_override=prompt_command.model,
        )

    def _run_skill_command(
        self,
        session: SessionTranscript,
        raw_args: str,
    ) -> CommandOutcome:
        """执行显式用户入口 `/skill <skill_name> [args]`。"""
        text = raw_args.strip()
        if not text:
            return self._append_message(session, "用法：/skill <skill_name> [args]")

        skill_name, _, skill_args = text.partition(" ")
        skill_name = skill_name.strip()
        skill_args = skill_args.strip()
        if not skill_name:
            return self._append_message(session, "用法：/skill <skill_name> [args]")

        services = self.tool_runtime.services_for(session)
        try:
            run_async_sync(services.mcp_manager.refresh_all())
        except Exception:
            pass
        try:
            prompt_command, rendered = resolve_skill_prompt(
                session,
                services,
                skill_name,
                skill_args,
                user_invoked=True,
            )
        except ToolError as error:
            return self._append_message(session, str(error))
        if not rendered:
            return self._append_message(session, f"skill `{prompt_command.name}` 没有生成文本内容。")
        return CommandOutcome(
            session=session,
            submit_prompt=rendered,
            model_override=prompt_command.model,
        )

    def _run_dynamic_tool(
        self,
        session: SessionTranscript,
        command: str,
        raw_args: str,
        *,
        event_handler: ToolEventHandler | None = None,
    ) -> CommandOutcome | None:
        """处理 `/mcp__...` 形式的动态工具命令，并解析 JSON 参数。"""
        if not command.startswith("/mcp__"):
            return None
        tool_name = command[1:]
        if not self.tool_runtime.can_resolve_tool_for_session(session, tool_name):
            return None
        if not self.tool_runtime.has_tool_for_session(session, tool_name, surface="execution"):
            return self._append_message(
                session,
                f"工具 `{tool_name}` 当前未允许通过 slash 执行。",
            )
        raw = raw_args.strip()
        if not raw:
            input_data: dict[str, object] = {}
        else:
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                return self._append_message(
                    session,
                    "动态 MCP 工具 slash 调用当前要求参数为 JSON object，例如：/mcp__server__tool {\"key\":\"value\"}",
                )
            if not isinstance(parsed, dict):
                return self._append_message(session, "动态 MCP 工具参数必须是 JSON object。")
            input_data = parsed
        return self.run_tool_input(
            session,
            tool_name,
            input_data,
            event_handler=event_handler,
        )

    def _missing_mcp_dynamic_command_text(
        self,
        session: SessionTranscript,
        command: str,
    ) -> str:
        """在动态 MCP 命令未注册时，输出诊断信息帮助定位问题。"""
        manager = self.tool_runtime.services_for(session).mcp_manager
        refresh_error = ""
        try:
            run_async_sync(manager.refresh_all())
        except Exception as error:
            refresh_error = str(error)

        cached_tools = manager.cached_tools()
        cached_prompts = manager.cached_prompts()
        connections = manager.snapshot()

        lines = [f"MCP 动态命令未命中：`{command}`"]
        if refresh_error:
            lines.append(f"最近一次 MCP 刷新失败：{refresh_error}")

        if connections:
            lines.append("")
            lines.append("当前 MCP server 状态：")
            for connection in connections:
                detail = connection.error or connection.config.url or connection.config.command or "-"
                lines.append(
                    f"- {connection.name} | {connection.status} | {connection.config.type} | {detail}"
                )

        dynamic_tools = sorted(
            build_mcp_tool_name(server_name, definition.name)
            for server_name, definitions in cached_tools.items()
            for definition in definitions
        )
        if dynamic_tools:
            lines.append("")
            lines.append("当前已注册的 MCP tools：")
            lines.extend(f"- /{name}" for name in dynamic_tools[:40])
        else:
            lines.append("")
            lines.append("当前没有成功注册任何 MCP 动态工具。")

        services = self.tool_runtime.services_for(session)
        dynamic_prompts = sorted(
            command_spec.name
            for command_spec in services.command_registry.list_user_commands(
                session,
                services,
            )
            if command_spec.kind == "mcp_prompt"
        )
        if dynamic_prompts:
            lines.append("")
            lines.append("当前已注册的 MCP prompts：")
            lines.extend(f"- /{name}" for name in dynamic_prompts[:20])

        lines.append("")
        lines.append("这通常说明模型层可能说出过工具名，但当前 slash 命令分发时并没有把这个动态工具注册进来。")
        return "\n".join(lines)

    def _normalize_dynamic_command_name(self, command: str) -> str:
        """去掉结尾标点，避免中文输入法影响命令匹配。"""
        normalized = command.strip()
        while normalized and normalized[-1] in "。.!！?？，,：:；;、）)]】」』”’":
            normalized = normalized[:-1].rstrip()
        return normalized



def format_session_summaries(summaries: Iterable[SessionSummary]) -> str:
    """把一组会话摘要格式化成制表符分隔的文本。"""
    lines = []
    for summary in summaries:
        lines.append(
            f"{summary.session_id}\t{summary.updated_at}\t{summary.title or '(untitled)'}\t{summary.cwd}"
        )
    return "\n".join(lines)
