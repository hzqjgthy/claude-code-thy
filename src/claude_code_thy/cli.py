from __future__ import annotations

import asyncio
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from claude_code_thy.cli_mcp import mcp_app
from claude_code_thy.config import AppConfig
from claude_code_thy.mcp.utils import install_mcp_exception_handler
from claude_code_thy.models import ChatMessage
from claude_code_thy.providers import (
    ProviderConfigurationError,
    build_provider,
    build_provider_for_name,
)
from claude_code_thy.runtime import ConversationRuntime
from claude_code_thy.session.store import SessionStore
from claude_code_thy.tools import ToolRuntime, build_builtin_tools

app = typer.Typer(
    add_completion=False,
    help="claude-code-thy CLI and Web API launcher",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": False},
)
app.add_typer(mcp_app, name="mcp")
prompt_app = typer.Typer(help="Inspect rendered prompts and prompt sections.")
app.add_typer(prompt_app, name="prompt")
console = Console(stderr=True)
PRINT_SEPARATOR = "\n====================================\n"
PRINT_TOOL_OUTPUT_LIMIT = 200


@dataclass(slots=True)
class RootInvocation:
    """表示 `RootInvocation`。"""
    resume: str | None = None
    print_mode: bool = False
    list_sessions: bool = False
    model: str | None = None
    prompt_tokens: list[str] | None = None


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    resume: str | None = typer.Option(
        None,
        "--resume",
        "-r",
        help="Resume a prior session by session ID.",
    ),
    print_mode: bool = typer.Option(
        False,
        "--print",
        "-p",
        help="Run a single prompt in headless mode and print the response.",
    ),
    list_sessions: bool = typer.Option(
        False,
        "--list-sessions",
        help="List recent sessions and exit.",
    ),
    model: str | None = typer.Option(
        None,
        "--model",
        help="Override the model for this session.",
    ),
) -> None:
    """运行主入口逻辑。"""
    if ctx.invoked_subcommand:
        return

    _run_root_command(
        resume=resume,
        print_mode=print_mode,
        list_sessions=list_sessions,
        model=model,
        prompt_tokens=list(ctx.args),
    )


def run() -> None:
    """运行当前流程。"""
    invocation = _preprocess_root_invocation(sys.argv[1:])
    if invocation is not None:
        _run_root_command(
            resume=invocation.resume,
            print_mode=invocation.print_mode,
            list_sessions=invocation.list_sessions,
            model=invocation.model,
            prompt_tokens=invocation.prompt_tokens or [],
        )
        return
    app(prog_name="claude-code-thy")


def _run_root_command(
    *,
    resume: str | None,
    print_mode: bool,
    list_sessions: bool,
    model: str | None,
    prompt_tokens: list[str],
) -> None:
    """运行 `root_command`。"""
    session_store = SessionStore()

    if list_sessions:
        _print_recent_sessions(session_store)
        return

    if not print_mode:
        if resume or model:
            console.print(
                "[yellow]Interactive terminal UI has been removed. "
                "`--resume` and `--model` only affect `--print` mode. "
                "Starting the Web API server instead.[/yellow]"
            )
        _start_web_server(host="127.0.0.1", port=8002)
        return

    config = AppConfig.from_env()
    cwd = os.getcwd()
    try:
        provider = build_provider(config)
    except ProviderConfigurationError as error:
        console.print(f"[red]{error}[/red]")
        raise typer.Exit(code=1) from error
    runtime = ConversationRuntime(
        provider=provider,
        session_store=session_store,
    )

    if resume:
        try:
            session = session_store.load(resume)
        except FileNotFoundError as error:
            console.print(f"[red]{error}[/red]")
            raise typer.Exit(code=1) from error
    else:
        session = session_store.create(
            cwd=str(Path(cwd).resolve()),
            model=model or config.model,
            provider_name=provider.name,
        )
        session_store.save(session)

    if not session.model:
        session.model = config.model
    if model:
        session.model = model
    session.provider_name = provider.name
    session_store.save(session)

    if print_mode:
        prompt = " ".join(prompt_tokens).strip()
        if not prompt and not sys.stdin.isatty():
            prompt = sys.stdin.read().strip()
        if not prompt:
            console.print("[red]Print mode requires a prompt argument or piped stdin.[/red]")
            raise typer.Exit(code=1)
        asyncio.run(
            _run_print_mode(
                runtime,
                session,
                prompt,
                stream_output=config.headless_enable_stream_output,
            )
        )
        return


def _preprocess_root_invocation(argv: list[str]) -> RootInvocation | None:
    """处理 `preprocess_root_invocation`。"""
    invocation = RootInvocation()
    index = 0

    while index < len(argv):
        token = argv[index]

        if token in {"--help", "-h"}:
            return None
        if token == "--":
            remaining = argv[index + 1 :]
            if invocation.print_mode and remaining:
                invocation.prompt_tokens = remaining
                return invocation
            return None
        if token in {"--resume", "-r"}:
            index += 1
            if index >= len(argv):
                return None
            invocation.resume = argv[index]
            index += 1
            continue
        if token == "--model":
            index += 1
            if index >= len(argv):
                return None
            invocation.model = argv[index]
            index += 1
            continue
        if token in {"--print", "-p"}:
            invocation.print_mode = True
            index += 1
            continue
        if token == "--list-sessions":
            invocation.list_sessions = True
            index += 1
            continue
        if token.startswith("-"):
            return None

        if invocation.print_mode:
            invocation.prompt_tokens = argv[index:]
            return invocation
        return None

    return None


def _print_recent_sessions(session_store: SessionStore) -> None:
    """处理 `print_recent_sessions`。"""
    summaries = session_store.list_recent(limit=10)
    if not summaries:
        console.print("No sessions found.")
        return

    table = Table(title="Recent Sessions")
    table.add_column("Session ID", style="cyan")
    table.add_column("Updated")
    table.add_column("Title")
    table.add_column("Model")
    table.add_column("cwd")

    for summary in summaries:
        table.add_row(
            summary.session_id,
            summary.updated_at,
            summary.title or "(untitled)",
            summary.model or "(unset)",
            summary.cwd,
        )

    console.print(table)


async def _run_print_mode(
    runtime: ConversationRuntime,
    session,
    prompt: str,
    *,
    stream_output: bool,
) -> None:
    """运行 `print_mode`。"""
    install_mcp_exception_handler(asyncio.get_running_loop())
    try:
        if stream_output:
            renderer = _HeadlessStreamRenderer()
            await runtime.handle_stream(
                session,
                prompt,
                text_delta_handler=renderer.on_text_delta,
                message_added_handler=renderer.on_message_added,
            )
            renderer.finalize()
            return

        prior_message_count = len(session.messages)
        outcome = await runtime.handle(session, prompt)
        session = outcome.session
        new_messages = session.messages[prior_message_count:]
        rendered = _render_print_mode_messages(new_messages)
        if rendered:
            print(rendered)
    finally:
        await runtime.aclose()


def _render_print_mode_messages(messages: list[ChatMessage]) -> str:
    """把本轮新增消息格式化为适合终端阅读的无头输出。"""
    blocks: list[str] = []
    for message in messages:
        block = _render_print_mode_message(message)
        if block:
            blocks.append(block)
    return PRINT_SEPARATOR.join(blocks)


def _render_print_mode_message(message: ChatMessage) -> str:
    """把单条 assistant/tool 消息转成终端打印块。"""
    if message.role == "assistant":
        return message.text.strip()
    if message.role != "tool":
        return ""

    metadata = message.metadata or {}
    display_name = str(metadata.get("display_name") or metadata.get("tool_name") or "Tool").strip()
    summary = str(metadata.get("summary") or "").strip()
    output = str(metadata.get("output") or "").strip()
    preview = str(metadata.get("preview") or "").strip()
    if not output:
        output = preview or message.text.strip()

    lines = [f"工具: {display_name}"]
    if summary:
        lines.append(f"摘要: {summary}")
    if output:
        lines.append("输出:")
        lines.append(_truncate_print_tool_output(output))
    return "\n".join(lines).strip()


def _truncate_print_tool_output(text: str) -> str:
    """把工具正文截断到固定长度，避免无头模式刷屏。"""
    if len(text) <= PRINT_TOOL_OUTPUT_LIMIT:
        return text
    return f"{text[:PRINT_TOOL_OUTPUT_LIMIT]}..."


class _HeadlessStreamRenderer:
    """把流式 assistant delta 和即时消息格式化为终端可读输出。"""

    def __init__(self) -> None:
        """初始化输出状态。"""
        self._printed_blocks = 0
        self._streaming_assistant = False
        self._pending_newline = False

    def on_text_delta(self, text: str) -> None:
        """收到 assistant 文本增量时，按 token 直接追加到终端。"""
        if not text:
            return
        if not self._streaming_assistant:
            self._start_block()
            self._streaming_assistant = True
        print(text, end="", flush=True)

    def on_message_added(self, _index: int, message: ChatMessage) -> None:
        """收到落盘后的新增消息时，补齐 tool 和非流式 assistant 展示。"""
        if message.role == "assistant":
            if self._streaming_assistant:
                self._streaming_assistant = False
                self._pending_newline = True
                return
            block = _render_print_mode_message(message)
            if block:
                self._print_block(block)
            return

        if message.role == "tool":
            block = _render_print_mode_message(message)
            if block:
                self._print_block(block)

    def finalize(self) -> None:
        """在本轮输出结束时补一个收尾换行，避免 shell 提示符贴在正文后面。"""
        if self._streaming_assistant or self._pending_newline:
            print()
        self._streaming_assistant = False
        self._pending_newline = False

    def _print_block(self, block: str) -> None:
        """打印一整块非增量消息。"""
        self._start_block()
        print(block, end="")
        self._pending_newline = True

    def _start_block(self) -> None:
        """开始一个新的输出块，必要时补换行和分隔线。"""
        if self._pending_newline:
            print()
            self._pending_newline = False
        if self._printed_blocks > 0:
            print("=========")
        self._printed_blocks += 1


@app.command("serve-web")
def serve_web(
    host: str = typer.Option("127.0.0.1", "--host", help="Host to bind the Web API server."),
    port: int = typer.Option(8002, "--port", help="Port to bind the Web API server."),
) -> None:
    """启动前后端分离模式使用的 Web API 服务。"""
    _start_web_server(host=host, port=port)


def _start_web_server(*, host: str, port: int) -> None:
    """启动 Web API 服务，供默认入口和显式 serve-web 命令共用。"""
    try:
        import uvicorn
        from claude_code_thy.server import create_app
    except ImportError as error:
        console.print(
            "[red]Web server dependencies are not installed. "
            "Please reinstall the project so FastAPI dependencies are available.[/red]"
        )
        raise typer.Exit(code=1) from error

    uvicorn.run(create_app(), host=host, port=port, log_level="info")


@prompt_app.command("dump")
def prompt_dump(
    session_id: str = typer.Option(..., "--session", help="Session ID to inspect."),
    provider: str | None = typer.Option(
        None,
        "--provider",
        help="Optional provider override for prompt rendering.",
    ),
) -> None:
    """打印某个会话当前会被注入到模型请求中的 prompt 结构。"""
    session_store = SessionStore()
    try:
        session = session_store.load(session_id)
    except FileNotFoundError as error:
        console.print(f"[red]{error}[/red]")
        raise typer.Exit(code=1) from error

    config = AppConfig.from_env()
    provider_name = provider or session.provider_name or config.provider
    model_name = session.model or config.model

    tool_runtime = ToolRuntime(build_builtin_tools())
    services = tool_runtime.services_for(session)
    rendered_prompt = services.prompt_runtime.build_rendered_prompt(
        session,
        services,
        provider_name=provider_name,
        model=model_name,
    )
    preview_provider = build_provider_for_name(provider_name, config)
    request_preview = preview_provider.build_request_preview(
        session,
        tool_runtime.list_tool_specs_for_session(
            session,
            allow_sync_refresh=False,
        ),
        prompt=rendered_prompt,
    )

    console.print(f"[bold]Session:[/bold] {session.session_id}")
    console.print(f"[bold]Provider:[/bold] {provider_name}")
    console.print(f"[bold]Model:[/bold] {model_name}")
    console.print(f"[bold]Workspace:[/bold] {rendered_prompt.bundle.workspace_root}")
    console.print()
    console.print("[bold]Sections:[/bold]")
    for section in rendered_prompt.bundle.sections:
        console.print(
            f"- {section.order} | {section.target} | {section.id} | {section.relative_name}"
        )
    console.print()
    console.print("[bold]System Text:[/bold]")
    console.print(rendered_prompt.system_text or "(empty)")
    console.print()
    console.print("[bold]User Context Text:[/bold]")
    console.print(rendered_prompt.user_context_text or "(empty)")
    console.print()
    console.print("[bold]Context Values:[/bold]")
    for key in sorted(rendered_prompt.bundle.context_data.variables):
        value = rendered_prompt.bundle.context_data.variables[key]
        preview = value if len(value) <= 400 else f"{value[:400]}..."
        console.print(f"- {key}: {preview}")
    console.print()
    console.print("[bold]Debug Meta:[/bold]")
    for key, value in rendered_prompt.bundle.context_data.debug_meta.items():
        console.print(f"- {key}: {value}")
    console.print()
    console.print("[bold]Request Preview:[/bold]")
    console.print_json(json=json.dumps(request_preview, ensure_ascii=False))

    asyncio.run(tool_runtime.aclose())
