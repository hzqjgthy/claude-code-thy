import asyncio
import json

from claude_code_thy.providers.base import Provider, ProviderResponse
from claude_code_thy.runtime import ConversationRuntime
from claude_code_thy.session.store import SessionStore


class DummyProvider(Provider):
    """实现 `Dummy` 提供方。"""
    name = "dummy"

    async def complete(self, session, tools, prompt=None):
        """完成当前流程。"""
        _ = (session, tools, prompt)
        return ProviderResponse(
            display_text="ok",
            content_blocks=[{"type": "text", "text": "ok"}],
            tool_calls=[],
        )


def test_read_permission_prompt_is_consumed_after_yes(tmp_path):
    """测试 `read_permission_prompt_is_consumed_after_yes` 场景。"""
    settings_dir = tmp_path / ".claude-code-thy"
    settings_dir.mkdir()
    (settings_dir / "settings.local.json").write_text(
        json.dumps(
            {
                "permissions": [
                    {
                        "effect": "ask",
                        "tool": "read",
                        "target": "path",
                        "pattern": str((tmp_path / "secret" / "*").resolve()),
                        "description": "read secret requires confirmation",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    secret_dir = tmp_path / "secret"
    secret_dir.mkdir()
    (secret_dir / "token.txt").write_text("super-secret-token\n", encoding="utf-8")

    store = SessionStore(root_dir=tmp_path / "sessions")
    runtime = ConversationRuntime(provider=DummyProvider(), session_store=store)
    session = store.create(cwd=str(tmp_path), model="dummy", provider_name="dummy")
    store.save(session)

    prompted = asyncio.run(runtime.handle(session, "/read secret/token.txt"))
    assert prompted.session.messages[-1].role == "assistant"
    assert prompted.session.messages[-1].metadata["ui_kind"] == "permission_prompt"

    approved = asyncio.run(runtime.handle(prompted.session, "yes"))
    assert approved.session.runtime_state["approved_permissions"]
    assert "pending_permission" not in approved.session.runtime_state
    assert approved.session.messages[-1].role == "tool"
    assert "super-secret-token" in approved.session.messages[-1].text

    repeated = asyncio.run(runtime.handle(approved.session, "/read secret/token.txt"))
    assert repeated.session.messages[-1].role == "tool"
    assert repeated.session.messages[-1].metadata["ui_kind"] == "read"
    assert repeated.session.messages[-1].metadata.get("ui_kind") != "permission_prompt"


def test_resolve_pending_permission_without_prompt_text_entry(tmp_path):
    """测试 `resolve_pending_permission_without_prompt_text_entry` 场景。"""
    settings_dir = tmp_path / ".claude-code-thy"
    settings_dir.mkdir()
    (settings_dir / "settings.local.json").write_text(
        json.dumps(
            {
                "permissions": [
                    {
                        "effect": "ask",
                        "tool": "read",
                        "target": "path",
                        "pattern": str((tmp_path / "secret" / "*").resolve()),
                        "description": "read secret requires confirmation",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    secret_dir = tmp_path / "secret"
    secret_dir.mkdir()
    (secret_dir / "token.txt").write_text("super-secret-token\n", encoding="utf-8")

    store = SessionStore(root_dir=tmp_path / "sessions")
    runtime = ConversationRuntime(provider=DummyProvider(), session_store=store)
    session = store.create(cwd=str(tmp_path), model="dummy", provider_name="dummy")
    store.save(session)

    prompted = asyncio.run(runtime.handle(session, "/read secret/token.txt"))
    resolved = asyncio.run(
        runtime.resolve_pending_permission(prompted.session, approved=True)
    )

    assert "pending_permission" not in resolved.session.runtime_state
    assert resolved.session.messages[-1].role == "tool"
    assert "super-secret-token" in resolved.session.messages[-1].text
