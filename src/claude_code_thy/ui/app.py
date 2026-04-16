from __future__ import annotations

from pathlib import Path

from rich import box
from rich.align import Align
from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Input, Static

from claude_code_thy import APP_DISPLAY_NAME, APP_VERSION
from claude_code_thy.models import ChatMessage, SessionTranscript
from claude_code_thy.providers.base import Provider
from claude_code_thy.runtime import ConversationRuntime
from claude_code_thy.session.store import SessionStore
from claude_code_thy.tools import ToolEvent
from claude_code_thy.ui.tool_views import (
    build_permission_prompt_message,
    build_task_notification_message,
    build_tool_call_message,
    build_tool_result_message,
    tool_label,
    truncate_single_line,
)


def format_cwd(path: str) -> str:
    home = str(Path.home())
    if path.startswith(home):
        return path.replace(home, "~", 1)
    return path

class ClaudeCodeThyApp(App[None]):
    CSS_PATH = "styles.tcss"
    BINDINGS = [("ctrl+c", "quit", "Quit")]

    def __init__(
        self,
        *,
        session: SessionTranscript,
        session_store: SessionStore,
        provider: Provider,
    ) -> None:
        super().__init__()
        self.session = session
        self.session_store = session_store
        self.provider = provider
        self._pending_prompt: str | None = None
        self.runtime = ConversationRuntime(
            provider=provider,
            session_store=session_store,
        )

    def compose(self) -> ComposeResult:
        yield Static(id="hero")
        with VerticalScroll(id="chat_surface"):
            yield Vertical(id="message_list")
            yield Static(id="tool_status")
            yield Static(id="resume_hint")
            with Horizontal(id="input_row"):
                yield Static("❯", id="prompt_glyph")
                yield Input(placeholder="", id="prompt_input")

    def on_mount(self) -> None:
        self._render_hero()
        self._render_messages()
        self._render_resume_hint()
        self._update_tool_status_from_messages()
        self.query_one("#prompt_input", Input).focus()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        prompt = event.value.strip()
        if not prompt:
            return

        input_widget = self.query_one("#prompt_input", Input)
        input_widget.disabled = True
        input_widget.value = ""
        self._pending_prompt = prompt
        self._render_messages()
        self._set_tool_status("Working…")

        outcome = await self.runtime.handle(
            self.session,
            prompt,
            tool_event_handler=self._handle_tool_event,
        )
        self.session = outcome.session
        self._pending_prompt = None
        self._render_hero()
        self._render_messages()
        self._render_resume_hint()
        self._update_tool_status_from_messages()

        input_widget.disabled = False
        input_widget.focus()

    def _handle_tool_event(self, event: ToolEvent) -> None:
        label = tool_label(event.tool_name)
        if event.phase == "queued":
            self._set_tool_status(f"{label}: queued")
            return
        if event.phase == "running":
            self._set_tool_status(f"{label}: {truncate_single_line(event.summary)}")
            return
        if event.phase == "progress":
            detail = truncate_single_line(event.detail) if event.detail else ""
            if detail:
                self._set_tool_status(f"{label}: {truncate_single_line(event.summary)} · {detail}")
            else:
                self._set_tool_status(f"{label}: {truncate_single_line(event.summary)}")
            return
        if event.phase == "error":
            self._set_tool_status(f"{label}: error")
            return
        if event.phase == "permission":
            self._set_tool_status(f"{label}: waiting for approval")
            return
        if event.phase == "result":
            self._set_tool_status(f"{label}: done")

    def _render_hero(self) -> None:
        self.query_one("#hero", Static).update(self._build_hero_panel())

    def _render_messages(self) -> None:
        message_list = self.query_one("#message_list", Vertical)
        message_list.remove_children()

        for message in self.session.messages:
            renderable = self._build_message(message)
            if renderable is None:
                continue
            message_list.mount(Static(renderable, classes="message"))

        if self._pending_prompt:
            pending = ChatMessage(role="user", text=self._pending_prompt)
            renderable = self._build_message(pending)
            if renderable is not None:
                message_list.mount(Static(renderable, classes="message"))

        self._scroll_chat_end()

    def _render_resume_hint(self) -> None:
        hint = (
            "Resume this session with:\n"
            f"claude-code-thy --resume {self.session.session_id}"
        )
        self.query_one("#resume_hint", Static).update(Text(hint, style="#9aa4b2"))
        self._scroll_chat_end()

    def _set_tool_status(self, text: str) -> None:
        self.query_one("#tool_status", Static).update(Text(text, style="#9aa4b2"))
        self._scroll_chat_end()

    def _update_tool_status_from_messages(self) -> None:
        running_tasks = []
        try:
            running_tasks = [
                task
                for task in self.runtime.tool_runtime.services_for(self.session).task_manager.list_task_records()
                if task.status == "running"
            ]
        except Exception:
            running_tasks = []
        if running_tasks:
            self._set_tool_status(f"Running tasks: {len(running_tasks)}")
            return
        if not self.session.messages:
            self._set_tool_status("")
            return

        for message in reversed(self.session.messages):
            metadata = message.metadata or {}
            if message.role == "assistant" and metadata.get("ui_kind") == "permission_prompt":
                self._set_tool_status("Waiting for approval")
                return
            if message.role == "tool" and metadata.get("summary"):
                self._set_tool_status(f"Last tool: {truncate_single_line(str(metadata['summary']))}")
                return
        self._set_tool_status("")

    def _build_message(self, message: ChatMessage) -> RenderableType | None:
        metadata = message.metadata or {}

        if message.role == "user":
            prefix = Text("❯ ", style="bold #f5f7fa")
            body = Text(message.text, style="#f5f7fa")
            return Group(Text(""), Text.assemble(prefix, body))

        if message.role == "assistant" and metadata.get("tool_calls"):
            return build_tool_call_message(message.text, message.metadata.get("tool_calls", []))

        if message.role == "assistant" and metadata.get("ui_kind") == "permission_prompt":
            return build_permission_prompt_message(message.text, metadata)

        if message.role == "assistant" and metadata.get("ui_kind") == "task_notification":
            if not self._should_render_task_notification(metadata):
                return None
            return build_task_notification_message(message.text, metadata)

        if message.role == "tool" and metadata:
            return build_tool_result_message(metadata)

        if not message.text.strip():
            return None

        prefix = Text("⏺ ", style="bold #f5f7fa")
        body = Text(message.text, style="#f5f7fa")
        return Group(Text(""), Text.assemble(prefix, body))

    def _should_render_task_notification(self, metadata: dict[str, object]) -> bool:
        task_id = str(metadata.get("task_id", "")).strip()
        if not task_id:
            return False
        try:
            task = self.runtime.tool_runtime.services_for(self.session).task_manager.get(task_id)
        except Exception:
            return False
        if task is None or not isinstance(task.metadata, dict):
            return False
        return str(task.metadata.get("session_id", "")).strip() == self.session.session_id

    def _scroll_chat_end(self) -> None:
        self.query_one("#chat_surface", VerticalScroll).scroll_end(animate=False)

    def _build_hero_panel(self) -> RenderableType:
        left = Group(
            Text(""),
            Align.center(Text("Welcome back!", style="bold #f5f7fa")),
            Text(""),
            Align.center(Text("▐▛███▜▌", style="#f5f7fa")),
            Align.center(Text("▝▜█████▛▘", style="#f5f7fa")),
            Align.center(Text("  ▘▘ ▝▝", style="#f5f7fa")),
            Text(""),
            Align.center(Text(f"{self.session.model or 'glm-4.5'} · API Usage Billing", style="#d7e3f4")),
            Align.center(Text(format_cwd(self.session.cwd), style="#9aa4b2")),
        )

        tips = Text("Run /init to create a CLAUDE.md file with instructions and context for Claude.")
        tips.truncate(46, overflow="ellipsis")

        right = Group(
            Text("Tips for getting started", style="bold #f5f7fa"),
            Text(str(tips), style="#d7e3f4"),
            Rule(style="#344054"),
            Text("Recent activity", style="bold #f5f7fa"),
            *self._build_recent_activity_lines(),
        )

        grid = Table.grid(expand=True)
        grid.add_column(ratio=3)
        grid.add_column(ratio=2)
        grid.add_row(left, right)

        return Panel(
            grid,
            title=f"{APP_DISPLAY_NAME} v{APP_VERSION}",
            title_align="left",
            border_style="#d7e3f4",
            box=box.ROUNDED,
            padding=(1, 1),
        )

    def _build_recent_activity_lines(self) -> list[RenderableType]:
        recent = [
            summary
            for summary in self.session_store.list_recent(limit=4)
            if summary.session_id != self.session.session_id
        ]
        if not recent:
            return [Text("No recent activity", style="#d7e3f4"), Text(""), Text("")]

        summary = recent[0]
        return [
            Text(summary.title or "Untitled session", style="#d7e3f4"),
            Text(format_cwd(summary.cwd), style="#9aa4b2"),
            Text(""),
        ]
