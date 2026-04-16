from __future__ import annotations

import os
import asyncio
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from claude_code_thy.config import AppConfig
from claude_code_thy.providers import ProviderConfigurationError, build_provider
from claude_code_thy.runtime import ConversationRuntime
from claude_code_thy.session.store import SessionStore
from claude_code_thy.ui.app import ClaudeCodeThyApp

app = typer.Typer(add_completion=False, help="claude-code-thy terminal application")
console = Console(stderr=True)


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
    prompt_parts: list[str] | None = typer.Argument(
        None,
        help="Optional prompt text. Used directly in --print mode.",
    ),
) -> None:
    if ctx.invoked_subcommand:
        return

    config = AppConfig.from_env()
    session_store = SessionStore()
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

    if list_sessions:
        _print_recent_sessions(session_store)
        return

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
        prompt = " ".join(prompt_parts or []).strip()
        if not prompt and not sys.stdin.isatty():
            prompt = sys.stdin.read().strip()
        if not prompt:
            console.print("[red]Print mode requires a prompt argument or piped stdin.[/red]")
            raise typer.Exit(code=1)
        asyncio.run(_run_print_mode(runtime, session, prompt))
        return

    ui = ClaudeCodeThyApp(
        session=session,
        session_store=session_store,
        provider=provider,
    )
    ui.run()


def run() -> None:
    app(prog_name="claude-code-thy")


def _print_recent_sessions(session_store: SessionStore) -> None:
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
) -> None:
    prior_message_count = len(session.messages)
    outcome = await runtime.handle(session, prompt)
    session = outcome.session
    new_messages = session.messages[prior_message_count:]
    assistant_messages = [message.text for message in new_messages if message.role == "assistant"]
    if assistant_messages:
        print("\n".join(assistant_messages))
