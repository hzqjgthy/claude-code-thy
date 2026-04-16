from claude_code_thy.commands import CommandProcessor
from claude_code_thy.session.store import SessionStore
from claude_code_thy.tools import ToolRuntime, build_builtin_tools


def build_processor(store: SessionStore) -> CommandProcessor:
    return CommandProcessor(store, ToolRuntime(build_builtin_tools()))


def test_clear_command_clears_messages(tmp_path):
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
    store = SessionStore(root_dir=tmp_path / "sessions")
    processor = build_processor(store)
    session = store.create(cwd=str(tmp_path))
    store.save(session)

    outcome = processor.process(session, "/init")

    assert outcome.message_added is True
    assert (tmp_path / "CLAUDE.md").exists()


def test_resume_command_switches_session(tmp_path):
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
    store = SessionStore(root_dir=tmp_path / "sessions")
    processor = build_processor(store)
    session = store.create(cwd=str(tmp_path), model="glm-4.5", provider_name="test-provider")
    store.save(session)

    outcome = processor.process(session, "/model claude-sonnet-4-5")

    assert outcome.session.model == "claude-sonnet-4-5"
    assert outcome.message_added is True


def test_tools_command_lists_builtin_tools(tmp_path):
    store = SessionStore(root_dir=tmp_path / "sessions")
    processor = build_processor(store)
    session = store.create(cwd=str(tmp_path), model="glm-4.5", provider_name="test-provider")
    store.save(session)

    outcome = processor.process(session, "/tools")

    assert outcome.message_added is True
    assert "bash" in outcome.session.messages[-1].text
    assert "read-only" in outcome.session.messages[-1].text


def test_read_command_uses_tool_runtime(tmp_path):
    (tmp_path / "README.md").write_text("hello tool read", encoding="utf-8")
    store = SessionStore(root_dir=tmp_path / "sessions")
    processor = build_processor(store)
    session = store.create(cwd=str(tmp_path), model="glm-4.5", provider_name="test-provider")
    store.save(session)

    outcome = processor.process(session, "/read README.md")

    assert outcome.message_added is True
    assert "hello tool read" in outcome.session.messages[-1].text


def test_edit_command_uses_tool_runtime(tmp_path):
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
