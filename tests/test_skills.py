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


def test_explicit_skill_slash_command_submits_expanded_prompt(tmp_path):
    """测试 `/skill <name> ...` 会展开 skill 并提交给主链模型。"""
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

    outcome = asyncio.run(runtime.handle(session, "/skill review auth-flow"))

    assert outcome.session.messages[0].role == "user"
    assert "Please review auth-flow carefully." in outcome.session.messages[0].text
    assert outcome.session.messages[1].text.startswith("echo:Base directory for this skill:")
    assert "Please review auth-flow carefully." in outcome.session.messages[1].text


def test_context_fork_skill_now_runs_inline_via_explicit_skill_command(tmp_path):
    """测试旧的 `context: fork` frontmatter 会被忽略，并通过 `/skill` 正常 inline 执行。"""
    skill_dir = tmp_path / ".claude-code-thy" / "skills" / "inspect"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "description: Inspect a target\n"
        "arguments:\n"
        "  - target\n"
        "context: fork\n"
        "agent: general-purpose\n"
        "effort: high\n"
        "---\n"
        "Please inspect ${target} carefully.\n",
        encoding="utf-8",
    )

    store = SessionStore(root_dir=tmp_path / "sessions")
    runtime = ConversationRuntime(provider=EchoProvider(), session_store=store)
    session = store.create(cwd=str(tmp_path), model="dummy", provider_name="echo")
    store.save(session)

    outcome = asyncio.run(runtime.handle(session, "/skill inspect build"))

    assert outcome.session.messages[0].role == "user"
    assert "Please inspect build carefully." in outcome.session.messages[0].text
    assert outcome.session.messages[1].text.startswith("echo:Base directory for this skill:")
    assert "Please inspect build carefully." in outcome.session.messages[1].text


def test_single_skill_slash_command_is_not_supported(tmp_path):
    """测试 `/<skill名>` 这条隐式 slash 通路不再对用户开放。"""
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

    assert "暂不支持命令 `/review`" in outcome.session.messages[-1].text


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


def test_skill_frontmatter_paths_does_not_hide_command(tmp_path):
    """测试 `paths` frontmatter 已被忽略，不再影响 skill 是否可见。"""
    skill_dir = tmp_path / ".claude-code-thy" / "skills" / "python-review"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "description: Review Python files\n"
        "paths:\n"
        "  - src/*.py\n"
        "---\n"
        "Review ${args}.\n",
        encoding="utf-8",
    )

    store = SessionStore(root_dir=tmp_path / "sessions")
    runtime = ConversationRuntime(provider=EchoProvider(), session_store=store)
    session = store.create(cwd=str(tmp_path), model="dummy", provider_name="echo")
    store.save(session)
    services = runtime.tool_runtime.services_for(session)

    commands = services.command_registry.list_user_commands(session, services)

    assert any(command.name == "python-review" for command in commands)


def test_reading_file_no_longer_discovers_parent_skill_dir(tmp_path):
    """测试读取文件后，不会再按父目录自动发现工作区里的散落 skill。"""
    feature_dir = tmp_path / "feature"
    feature_dir.mkdir()
    (feature_dir / "SKILL.md").write_text(
        "---\n"
        "description: Hidden parent skill\n"
        "---\n"
        "Inspect feature files.\n",
        encoding="utf-8",
    )
    (feature_dir / "note.txt").write_text("hello\n", encoding="utf-8")

    store = SessionStore(root_dir=tmp_path / "sessions")
    runtime = ConversationRuntime(provider=EchoProvider(), session_store=store)
    session = store.create(cwd=str(tmp_path), model="dummy", provider_name="echo")
    store.save(session)
    services = runtime.tool_runtime.services_for(session)

    before = services.command_registry.list_user_commands(session, services)
    assert all(command.name != "feature" for command in before)

    result = runtime.tool_runtime.execute_input(
        "read",
        {"file_path": "feature/note.txt"},
        session,
    )

    assert result.ok is True

    after = services.command_registry.list_user_commands(session, services)
    assert all(command.name != "feature" for command in after)
