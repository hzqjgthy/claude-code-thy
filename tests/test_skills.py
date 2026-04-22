import asyncio

from claude_code_thy.models import SessionTranscript
from claude_code_thy.providers.base import Provider, ProviderResponse
from claude_code_thy.runtime import ConversationRuntime
from claude_code_thy.session.store import SessionStore
from claude_code_thy.skills.types import PromptCommandSpec


class EchoProvider(Provider):
    """实现 `Echo` 提供方。"""
    name = "echo"

    async def complete(self, session, tools):
        """完成当前流程。"""
        _ = tools
        return ProviderResponse(
            display_text=f"echo:{session.messages[-1].text}",
            content_blocks=[{"type": "text", "text": f"echo:{session.messages[-1].text}"}],
            tool_calls=[],
        )


def test_inline_skill_slash_command_submits_expanded_prompt(tmp_path):
    """测试 `inline_skill_slash_command_submits_expanded_prompt` 场景。"""
    skill_dir = tmp_path / ".claude-code-thy" / "skills" / "review"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "description: Review a topic\n"
        "arguments:\n"
        "  - topic\n"
        "---\n"
        "Please review ${topic} carefully.\n",
        encoding="utf-8",
    )

    store = SessionStore(root_dir=tmp_path / "sessions")
    runtime = ConversationRuntime(provider=EchoProvider(), session_store=store)
    session = store.create(cwd=str(tmp_path), model="dummy", provider_name="echo")
    store.save(session)

    outcome = asyncio.run(runtime.handle(session, "/review auth-flow"))

    assert outcome.session.messages[0].role == "user"
    assert "Please review auth-flow carefully." in outcome.session.messages[0].text
    assert outcome.session.messages[1].text.startswith("echo:Base directory for this skill:")
    assert "Please review auth-flow carefully." in outcome.session.messages[1].text


def test_old_dot_claude_skills_path_is_not_loaded_by_default(tmp_path):
    """测试 `old_dot_claude_skills_path_is_not_loaded_by_default` 场景。"""
    skill_dir = tmp_path / ".claude" / "skills" / "review"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "description: Review a topic\n"
        "arguments:\n"
        "  - topic\n"
        "---\n"
        "Please review ${topic} carefully.\n",
        encoding="utf-8",
    )

    store = SessionStore(root_dir=tmp_path / "sessions")
    runtime = ConversationRuntime(provider=EchoProvider(), session_store=store)
    session = store.create(cwd=str(tmp_path), model="dummy", provider_name="echo")
    store.save(session)
    services = runtime.tool_runtime.services_for(session)

    commands = services.command_registry.list_user_commands(session, services)

    assert all(command.name != "review" for command in commands)


def test_mcp_prompt_slash_command_uses_unified_registry(tmp_path):
    """测试 `mcp_prompt_slash_command_uses_unified_registry` 场景。"""
    store = SessionStore(root_dir=tmp_path / "sessions")
    runtime = ConversationRuntime(provider=EchoProvider(), session_store=store)
    session = store.create(cwd=str(tmp_path), model="dummy", provider_name="echo")
    store.save(session)
    services = runtime.tool_runtime.services_for(session)

    class DummyPrompt:
        """表示 `DummyPrompt`。"""
        name = "hello"
        description = "hello prompt"
        arguments = ("topic",)

    class DummyMgr:
        """表示 `DummyMgr`。"""
        async def refresh_all(self):
            """刷新 `all`。"""
            return []

        def cached_prompts(self):
            """处理 `cached_prompts`。"""
            return {"demo": [DummyPrompt()]}

        def cached_skill_commands(self):
            """处理 `cached_skill_commands`。"""
            return []

        def cached_tools(self):
            """处理 `cached_tools`。"""
            return {}

        async def get_prompt(self, server_name, prompt_name, arguments=None):
            """返回 `prompt`。"""
            return {"server": server_name, "prompt": prompt_name, "arguments": arguments or {}}

        def snapshot(self):
            """处理 `snapshot`。"""
            return []

    services.mcp_manager = DummyMgr()

    outcome = asyncio.run(runtime.handle(session, "/mcp__demo__hello world"))

    assert outcome.session.messages[0].role == "user"
    assert '"prompt": "hello"' in outcome.session.messages[0].text
    assert outcome.session.messages[1].text.startswith("echo:")


def test_skill_tool_executes_mcp_skill_from_registry(tmp_path):
    """测试 `skill_tool_executes_mcp_skill_from_registry` 场景。"""
    store = SessionStore(root_dir=tmp_path / "sessions")
    runtime = ConversationRuntime(provider=EchoProvider(), session_store=store)
    session = store.create(cwd=str(tmp_path), model="dummy", provider_name="echo")
    store.save(session)
    services = runtime.tool_runtime.services_for(session)

    class DummyMgr:
        """表示 `DummyMgr`。"""
        def cached_prompt_commands(self):
            """处理 `cached_prompt_commands`。"""
            return []

        def cached_skill_commands(self):
            """处理 `cached_skill_commands`。"""
            return [
                PromptCommandSpec(
                    name="demo:review",
                    description="Review from MCP",
                    kind="mcp_skill",
                    loaded_from="mcp",
                    source="mcp",
                    content="Review ${topic} from MCP.",
                    content_length=24,
                    arg_names=("topic",),
                    server_name="demo",
                )
            ]

        def cached_tools(self):
            """处理 `cached_tools`。"""
            return {}

    services.mcp_manager = DummyMgr()

    result = runtime.tool_runtime.execute_input(
        "skill",
        {"skill": "demo:review", "args": "oauth"},
        session,
    )

    assert result.ok is True
    assert "Review oauth from MCP." in result.output
