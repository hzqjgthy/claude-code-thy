import json

from claude_code_thy.commands import CommandProcessor
from claude_code_thy.mcp.types import McpPromptDefinition, McpServerConfig, McpServerConnection
from claude_code_thy.session.store import SessionStore
from claude_code_thy.tools import selection
from claude_code_thy.tools import ToolRuntime, build_builtin_tools


def build_processor(store: SessionStore) -> CommandProcessor:
    """构建 `processor`。"""
    return CommandProcessor(store, ToolRuntime(build_builtin_tools()))


def test_clear_command_clears_messages(tmp_path):
    """测试 `clear_command_clears_messages` 场景。"""
    store = SessionStore(root_dir=tmp_path)
    processor = build_processor(store)
    session = store.create(cwd=str(tmp_path))
    session.add_message("user", "hello")
    session.add_message("assistant", "world")
    store.save(session)

    outcome = processor.process(session, "/clear")

    assert outcome.should_refresh_only is True
    assert outcome.session.messages == []


def test_init_command_creates_claude_md(tmp_path):
    """测试 `init_command_creates_claude_md` 场景。"""
    store = SessionStore(root_dir=tmp_path / "sessions")
    processor = build_processor(store)
    session = store.create(cwd=str(tmp_path))
    store.save(session)

    outcome = processor.process(session, "/init")

    assert outcome.message_added is True
    assert (tmp_path / "CLAUDE.md").exists()


def test_resume_command_switches_session(tmp_path):
    """测试 `resume_command_switches_session` 场景。"""
    store = SessionStore(root_dir=tmp_path / "sessions")
    processor = build_processor(store)

    current = store.create(cwd=str(tmp_path / "current"))
    store.save(current)

    target = store.create(cwd=str(tmp_path / "target"))
    target.add_message("user", "target session")
    store.save(target)

    outcome = processor.process(current, f"/resume {target.session_id}")

    assert outcome.session.session_id == target.session_id
    assert outcome.should_refresh_only is True


def test_model_command_updates_session_model(tmp_path):
    """测试 `model_command_updates_session_model` 场景。"""
    store = SessionStore(root_dir=tmp_path / "sessions")
    processor = build_processor(store)
    session = store.create(cwd=str(tmp_path), model="glm-4.5", provider_name="test-provider")
    store.save(session)

    outcome = processor.process(session, "/model claude-sonnet-4-5")

    assert outcome.session.model == "claude-sonnet-4-5"
    assert outcome.message_added is True


def test_tools_command_lists_builtin_tools(tmp_path):
    """测试 `tools_command_lists_builtin_tools` 场景。"""
    store = SessionStore(root_dir=tmp_path / "sessions")
    processor = build_processor(store)
    session = store.create(cwd=str(tmp_path), model="glm-4.5", provider_name="test-provider")
    store.save(session)

    outcome = processor.process(session, "/tools")

    assert outcome.message_added is True
    assert "bash" in outcome.session.messages[-1].text
    assert "read-only" in outcome.session.messages[-1].text


def test_tools_command_shows_model_visible_section(monkeypatch, tmp_path):
    """测试 `/tools` 会区分手动可执行和主链可见工具。"""
    monkeypatch.setattr(selection, "MODEL_VISIBLE_TOOLS", ["read", "glob"])
    monkeypatch.setattr(selection, "SLASH_AVAILABLE_TOOLS", ["read", "bash", "glob"])

    store = SessionStore(root_dir=tmp_path / "sessions")
    processor = build_processor(store)
    session = store.create(cwd=str(tmp_path), model="glm-4.5", provider_name="test-provider")
    store.save(session)

    outcome = processor.process(session, "/tools")

    text = outcome.session.messages[-1].text
    assert "手动可执行工具：" in text
    assert "当前主链可见工具：" in text
    assert "- read" in text
    assert "- glob" in text


def test_mcp_command_lists_configured_servers(tmp_path):
    """测试 `mcp_command_lists_configured_servers` 场景。"""
    (tmp_path / ".mcp.json").write_text(
        '{"mcpServers":{"demo":{"type":"http","url":"http://localhost:18060/mcp"}}}',
        encoding="utf-8",
    )
    store = SessionStore(root_dir=tmp_path / "sessions")
    processor = build_processor(store)
    session = store.create(cwd=str(tmp_path), model="glm-4.5", provider_name="test-provider")
    store.save(session)

    outcome = processor.process(session, "/mcp")

    assert outcome.message_added is True
    assert "demo" in outcome.session.messages[-1].text
    assert "http" in outcome.session.messages[-1].text


def test_tasks_command_suppresses_task_notifications(tmp_path):
    """测试 `tasks_command_suppresses_task_notifications` 场景。"""
    store = SessionStore(root_dir=tmp_path / "sessions")
    processor = build_processor(store)
    session = store.create(cwd=str(tmp_path), model="glm-4.5", provider_name="test-provider")
    store.save(session)

    outcome = processor.process(session, "/tasks")

    assert outcome.message_added is True
    assert outcome.suppress_task_notifications is True


def test_agents_command_suppresses_task_notifications(tmp_path):
    """测试 `agents_command_suppresses_task_notifications` 场景。"""
    store = SessionStore(root_dir=tmp_path / "sessions")
    processor = build_processor(store)
    session = store.create(cwd=str(tmp_path), model="glm-4.5", provider_name="test-provider")
    store.save(session)

    outcome = processor.process(session, "/agents")

    assert outcome.message_added is True
    assert outcome.suppress_task_notifications is True


def test_mcp_prompt_command_is_executed(tmp_path):
    """测试 `mcp_prompt_command_is_executed` 场景。"""
    store = SessionStore(root_dir=tmp_path / "sessions")
    processor = build_processor(store)
    session = store.create(cwd=str(tmp_path), model="glm-4.5", provider_name="test-provider")
    store.save(session)
    services = processor.tool_runtime.services_for(session)

    class DummyMgr:
        """表示 `DummyMgr`。"""
        async def refresh_all(self):
            """刷新 `all`。"""
            return []

        def cached_prompts(self):
            """处理 `cached_prompts`。"""
            return {
                "demo": [
                    McpPromptDefinition(
                        name="hello_prompt",
                        description="hello",
                        arguments=("topic",),
                    )
                ]
            }

        def cached_tools(self):
            """处理 `cached_tools`。"""
            return {}

        def cached_resources(self):
            """处理 `cached_resources`。"""
            return {}

        async def get_prompt(self, server_name, prompt_name, arguments=None):
            """返回 `prompt`。"""
            return {"prompt": prompt_name, "arguments": arguments}

    services.mcp_manager = DummyMgr()

    outcome = processor.process(session, "/mcp__demo__hello_prompt world")

    assert outcome.submit_prompt is not None
    assert "hello_prompt" in outcome.submit_prompt


def test_dynamic_mcp_tool_slash_command_executes(tmp_path):
    """测试 `dynamic_mcp_tool_slash_command_executes` 场景。"""
    store = SessionStore(root_dir=tmp_path / "sessions")
    processor = build_processor(store)
    session = store.create(cwd=str(tmp_path), model="glm-4.5", provider_name="test-provider")
    store.save(session)
    services = processor.tool_runtime.services_for(session)

    from claude_code_thy.mcp.types import McpToolDefinition

    class DummyMgr:
        """表示 `DummyMgr`。"""
        async def refresh_all(self):
            """刷新 `all`。"""
            return []

        def cached_tools(self):
            """处理 `cached_tools`。"""
            return {
                "demo": [
                    McpToolDefinition(
                        name="check_login_status",
                        description="check login",
                        input_schema={"type": "object", "properties": {}, "required": []},
                        annotations={"readOnlyHint": True, "original_name": "check_login_status"},
                    )
                ]
            }

        def cached_prompts(self):
            """处理 `cached_prompts`。"""
            return {}

        def cached_resources(self):
            """处理 `cached_resources`。"""
            return {}

        async def call_tool(self, server_name, tool_name, arguments=None):
            """处理 `call_tool`。"""
            return {"content": f"{server_name}:{tool_name}:ok"}

    services.mcp_manager = DummyMgr()

    outcome = processor.process(session, "/mcp__demo__check_login_status")

    assert outcome.message_added is True
    assert "check_login_status" in outcome.session.messages[-1].text


def test_dynamic_mcp_tool_disabled_for_slash_reports_selection_error(monkeypatch, tmp_path):
    """测试动态 MCP 工具被 slash 列表禁用时会给出明确提示。"""
    monkeypatch.setattr(selection, "SLASH_AVAILABLE_TOOLS", ["read", "bash"])

    store = SessionStore(root_dir=tmp_path / "sessions")
    processor = build_processor(store)
    session = store.create(cwd=str(tmp_path), model="glm-4.5", provider_name="test-provider")
    store.save(session)
    services = processor.tool_runtime.services_for(session)

    from claude_code_thy.mcp.types import McpToolDefinition

    class DummyMgr:
        async def refresh_all(self):
            return []

        def cached_tools(self):
            return {
                "demo": [
                    McpToolDefinition(
                        name="check_login_status",
                        description="check login",
                        input_schema={"type": "object", "properties": {}, "required": []},
                        annotations={"readOnlyHint": True, "original_name": "check_login_status"},
                    )
                ]
            }

        def cached_prompts(self):
            return {}

        def cached_resources(self):
            return {}

    services.mcp_manager = DummyMgr()

    outcome = processor.process(session, "/mcp__demo__check_login_status")

    assert outcome.message_added is True
    assert "未允许通过 slash 执行" in outcome.session.messages[-1].text


def test_dynamic_mcp_tool_without_permission_rule_executes_directly(tmp_path):
    """测试动态 `mcp__*` 工具在没配权限规则时会直接执行。"""
    store = SessionStore(root_dir=tmp_path / "sessions")
    processor = build_processor(store)
    session = store.create(cwd=str(tmp_path), model="glm-4.5", provider_name="test-provider")
    store.save(session)
    services = processor.tool_runtime.services_for(session)

    from claude_code_thy.mcp.types import McpToolDefinition

    class DummyMgr:
        """表示 `DummyMgr`。"""
        async def refresh_all(self):
            """刷新 `all`。"""
            return []

        def cached_tools(self):
            """处理 `cached_tools`。"""
            return {
                "xiaohongshu-mcp": [
                    McpToolDefinition(
                        name="check_login_status",
                        description="check login",
                        input_schema={"type": "object", "properties": {}, "required": []},
                        annotations={"original_name": "check_login_status"},
                    )
                ]
            }

        def cached_prompts(self):
            """处理 `cached_prompts`。"""
            return {}

        def cached_resources(self):
            """处理 `cached_resources`。"""
            return {}

        async def call_tool(self, server_name, tool_name, arguments=None):
            """处理 `call_tool`。"""
            return {"content": f"{server_name}:{tool_name}:{arguments}"}

    services.mcp_manager = DummyMgr()

    outcome = processor.process(session, "/mcp__xiaohongshu_mcp__check_login_status")

    assert outcome.message_added is True
    assert "pending_permission" not in outcome.session.runtime_state
    assert "结构化输入" not in outcome.session.messages[-1].text
    assert "check_login_status" in outcome.session.messages[-1].text


def test_dynamic_mcp_tool_honors_ask_rule_from_settings_local(tmp_path):
    """测试动态 `mcp__*` 工具会遵守 `settings.local.json` 中的 ask 规则。"""
    settings_dir = tmp_path / ".claude-code-thy"
    settings_dir.mkdir()
    (settings_dir / "settings.local.json").write_text(
        json.dumps(
            {
                "permissions": [
                    {
                        "effect": "ask",
                        "tool": "mcp__xiaohongshu_mcp__check_login_status",
                        "target": "command",
                        "pattern": "mcp__xiaohongshu_mcp__check_login_status",
                        "description": "dynamic mcp tool requires confirmation",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    store = SessionStore(root_dir=tmp_path / "sessions")
    processor = build_processor(store)
    session = store.create(cwd=str(tmp_path), model="glm-4.5", provider_name="test-provider")
    store.save(session)
    services = processor.tool_runtime.services_for(session)

    from claude_code_thy.mcp.types import McpToolDefinition

    class DummyMgr:
        """表示 `DummyMgr`。"""
        async def refresh_all(self):
            """刷新 `all`。"""
            return []

        def cached_tools(self):
            """处理 `cached_tools`。"""
            return {
                "xiaohongshu-mcp": [
                    McpToolDefinition(
                        name="check_login_status",
                        description="check login",
                        input_schema={"type": "object", "properties": {}, "required": []},
                        annotations={"original_name": "check_login_status"},
                    )
                ]
            }

        def cached_prompts(self):
            """处理 `cached_prompts`。"""
            return {}

        def cached_resources(self):
            """处理 `cached_resources`。"""
            return {}

        async def call_tool(self, server_name, tool_name, arguments=None):
            """处理 `call_tool`。"""
            return {"content": f"{server_name}:{tool_name}:{arguments}"}

    services.mcp_manager = DummyMgr()

    prompted = processor.process(session, "/mcp__xiaohongshu_mcp__check_login_status")
    pending = prompted.session.runtime_state.get("pending_permission")

    assert isinstance(pending, dict)
    assert pending.get("tool_name") == "mcp__xiaohongshu_mcp__check_login_status"

    resumed = processor.resume_pending_permission(prompted.session, pending, approved=True)

    assert resumed.message_added is True
    assert "check_login_status" in resumed.session.messages[-1].text

def test_dynamic_mcp_tool_slash_command_tolerates_trailing_punctuation(tmp_path):
    """测试 `dynamic_mcp_tool_slash_command_tolerates_trailing_punctuation` 场景。"""
    store = SessionStore(root_dir=tmp_path / "sessions")
    processor = build_processor(store)
    session = store.create(cwd=str(tmp_path), model="glm-4.5", provider_name="test-provider")
    store.save(session)
    services = processor.tool_runtime.services_for(session)

    from claude_code_thy.mcp.types import McpToolDefinition

    class DummyMgr:
        """表示 `DummyMgr`。"""
        async def refresh_all(self):
            """刷新 `all`。"""
            return []

        def cached_tools(self):
            """处理 `cached_tools`。"""
            return {
                "xiaohongshu-mcp": [
                    McpToolDefinition(
                        name="check_login_status",
                        description="check login",
                        input_schema={"type": "object", "properties": {}, "required": []},
                        annotations={"readOnlyHint": True, "original_name": "check_login_status"},
                    )
                ]
            }

        def cached_prompts(self):
            """处理 `cached_prompts`。"""
            return {}

        def cached_resources(self):
            """处理 `cached_resources`。"""
            return {}

        def snapshot(self):
            """处理 `snapshot`。"""
            return []

        async def call_tool(self, server_name, tool_name, arguments=None):
            """处理 `call_tool`。"""
            return {"content": f"{server_name}:{tool_name}:ok"}

    services.mcp_manager = DummyMgr()

    outcome = processor.process(session, "/mcp__xiaohongshu_mcp__check_login_status。")

    assert outcome.message_added is True
    assert "check_login_status" in outcome.session.messages[-1].text


def test_missing_dynamic_mcp_command_reports_mcp_diagnostics(tmp_path):
    """测试 `missing_dynamic_mcp_command_reports_mcp_diagnostics` 场景。"""
    store = SessionStore(root_dir=tmp_path / "sessions")
    processor = build_processor(store)
    session = store.create(cwd=str(tmp_path), model="glm-4.5", provider_name="test-provider")
    store.save(session)
    services = processor.tool_runtime.services_for(session)

    class DummyMgr:
        """表示 `DummyMgr`。"""
        async def refresh_all(self):
            """刷新 `all`。"""
            return []

        def cached_tools(self):
            """处理 `cached_tools`。"""
            return {}

        def cached_prompts(self):
            """处理 `cached_prompts`。"""
            return {}

        def cached_resources(self):
            """处理 `cached_resources`。"""
            return {}

        def snapshot(self):
            """处理 `snapshot`。"""
            return [
                McpServerConnection(
                    name="xiaohongshu-mcp",
                    status="connected",
                    config=McpServerConfig(
                        name="xiaohongshu-mcp",
                        scope="project",
                        type="http",
                        url="http://localhost:18060/mcp",
                    ),
                )
            ]

    services.mcp_manager = DummyMgr()

    outcome = processor.process(session, "/mcp__xiaohongshu_mcp__check_login_status")

    assert outcome.message_added is True
    assert "MCP 动态命令未命中" in outcome.session.messages[-1].text
    assert "xiaohongshu-mcp" in outcome.session.messages[-1].text


def test_dynamic_mcp_tool_slash_command_resolves_from_server_lookup(tmp_path):
    """测试 `dynamic_mcp_tool_slash_command_resolves_from_server_lookup` 场景。"""
    store = SessionStore(root_dir=tmp_path / "sessions")
    processor = build_processor(store)
    session = store.create(cwd=str(tmp_path), model="glm-4.5", provider_name="test-provider")
    store.save(session)
    services = processor.tool_runtime.services_for(session)

    from claude_code_thy.mcp.types import McpToolDefinition

    class DummyMgr:
        """表示 `DummyMgr`。"""
        async def refresh_all(self):
            """刷新 `all`。"""
            return []

        def configs(self):
            """处理 `configs`。"""
            return {
                "xiaohongshu-mcp": McpServerConfig(
                    name="xiaohongshu-mcp",
                    scope="project",
                    type="http",
                    url="http://localhost:18060/mcp",
                )
            }

        def cached_tools(self):
            """处理 `cached_tools`。"""
            return {}

        def cached_prompts(self):
            """处理 `cached_prompts`。"""
            return {}

        def cached_resources(self):
            """处理 `cached_resources`。"""
            return {}

        def snapshot(self):
            """处理 `snapshot`。"""
            return []

        async def list_tools(self, server_name):
            """列出 `tools`。"""
            assert server_name == "xiaohongshu-mcp"
            return [
                McpToolDefinition(
                    name="check_login_status",
                    description="check login",
                    input_schema={"type": "object", "properties": {}, "required": []},
                    annotations={"readOnlyHint": True, "original_name": "check_login_status"},
                )
            ]

        async def call_tool(self, server_name, tool_name, arguments=None):
            """处理 `call_tool`。"""
            return {"content": f"{server_name}:{tool_name}:ok"}

    services.mcp_manager = DummyMgr()

    outcome = processor.process(session, "/mcp__xiaohongshu_mcp__check_login_status")

    assert outcome.message_added is True
    assert "check_login_status" in outcome.session.messages[-1].text



def test_read_command_uses_tool_runtime(tmp_path):
    """测试 `read_command_uses_tool_runtime` 场景。"""
    (tmp_path / "README.md").write_text("hello tool read", encoding="utf-8")
    store = SessionStore(root_dir=tmp_path / "sessions")
    processor = build_processor(store)
    session = store.create(cwd=str(tmp_path), model="glm-4.5", provider_name="test-provider")
    store.save(session)

    outcome = processor.process(session, "/read README.md")

    assert outcome.message_added is True
    assert "hello tool read" in outcome.session.messages[-1].text


def test_edit_command_uses_tool_runtime(tmp_path):
    """测试 `edit_command_uses_tool_runtime` 场景。"""
    (tmp_path / "file.txt").write_text("hello old world", encoding="utf-8")
    store = SessionStore(root_dir=tmp_path / "sessions")
    processor = build_processor(store)
    session = store.create(cwd=str(tmp_path), model="glm-4.5", provider_name="test-provider")
    store.save(session)
    processor.process(session, "/read file.txt")

    outcome = processor.process(session, '/edit file.txt --old "old" --new "new"')

    assert outcome.message_added is True
    assert "编辑文件" in outcome.session.messages[-1].text
    assert (tmp_path / "file.txt").read_text(encoding="utf-8") == "hello new world"


def test_agent_run_command_starts_local_agent_task(tmp_path, monkeypatch):
    """测试 `agent_run_command_starts_local_agent_task` 场景。"""
    src_dir = tmp_path.parent / "src"
    project_src = __import__("pathlib").Path(__file__).resolve().parents[1] / "src"
    monkeypatch.setenv("PYTHONPATH", str(project_src))

    store = SessionStore(root_dir=tmp_path / "sessions")
    processor = build_processor(store)
    session = store.create(cwd=str(tmp_path), model="glm-4.5", provider_name="test-provider")
    store.save(session)

    outcome = processor.process(session, "/agent-run hello agent")

    assert outcome.message_added is True
    assert "已启动后台 agent" in outcome.session.messages[-1].text


def test_agents_command_lists_agent_tasks(tmp_path, monkeypatch):
    """测试 `agents_command_lists_agent_tasks` 场景。"""
    project_src = __import__("pathlib").Path(__file__).resolve().parents[1] / "src"
    monkeypatch.setenv("PYTHONPATH", str(project_src))

    store = SessionStore(root_dir=tmp_path / "sessions")
    processor = build_processor(store)
    session = store.create(cwd=str(tmp_path), model="glm-4.5", provider_name="test-provider")
    store.save(session)

    processor.process(session, "/agent-run hello agent")
    outcome = processor.process(session, "/agents")

    assert outcome.message_added is True
    assert "Agent 任务" in outcome.session.messages[-1].text


def test_task_stop_command_stops_background_task(tmp_path):
    """测试 `task_stop_command_stops_background_task` 场景。"""
    store = SessionStore(root_dir=tmp_path / "sessions")
    processor = build_processor(store)
    session = store.create(cwd=str(tmp_path), model="glm-4.5", provider_name="test-provider")
    store.save(session)

    outcome = processor.process(session, "/bash --background -- python -c 'import time; time.sleep(5)'")
    task_id = outcome.session.messages[-1].metadata.get("structured_data", {}).get("background_task_id")

    assert task_id is not None

    outcome = processor.process(outcome.session, f"/task-stop {task_id}")

    assert "已停止任务" in outcome.session.messages[-1].text


def test_agent_wait_command_returns_agent_status(tmp_path, monkeypatch):
    """测试 `agent_wait_command_returns_agent_status` 场景。"""
    project_src = __import__("pathlib").Path(__file__).resolve().parents[1] / "src"
    monkeypatch.setenv("PYTHONPATH", str(project_src))

    store = SessionStore(root_dir=tmp_path / "sessions")
    processor = build_processor(store)
    session = store.create(cwd=str(tmp_path), model="glm-4.5", provider_name="test-provider")
    store.save(session)

    launched = processor.process(session, "/agent-run hello wait")
    text = launched.session.messages[-1].text
    task_id = text.split("：", 1)[1].split("\n", 1)[0]

    outcome = processor.process(launched.session, f"/agent-wait {task_id} 5")

    assert outcome.message_added is True
    assert f"Agent {task_id} 当前状态：" in outcome.session.messages[-1].text
