from claude_code_thy.models import SessionTranscript
from claude_code_thy.tools import ToolError, ToolRuntime, build_builtin_tools


def build_runtime() -> ToolRuntime:
    return ToolRuntime(build_builtin_tools())


def test_write_rejects_invalid_settings_json(tmp_path):
    runtime = build_runtime()
    session = SessionTranscript(session_id="guard-1", cwd=str(tmp_path))
    settings_dir = tmp_path / ".claude-code-thy"
    settings_dir.mkdir(parents=True, exist_ok=True)

    try:
        runtime.execute_input(
            "write",
            {"file_path": ".claude-code-thy/settings.json", "content": "{invalid json"},
            session,
        )
    except ToolError as error:
        assert "设置文件 JSON 无效" in str(error)
    else:
        raise AssertionError("Expected ToolError for invalid settings JSON")


def test_edit_rejects_invalid_settings_json(tmp_path):
    runtime = build_runtime()
    session = SessionTranscript(session_id="guard-2", cwd=str(tmp_path))
    settings_dir = tmp_path / ".claude-code-thy"
    settings_dir.mkdir(parents=True, exist_ok=True)
    path = settings_dir / "settings.json"
    path.write_text('{"sandbox": {"mode": "workspace-write"}}', encoding="utf-8")

    runtime.execute("read", ".claude-code-thy/settings.json", session)
    try:
        runtime.execute_input(
            "edit",
            {
                "file_path": ".claude-code-thy/settings.json",
                "old_string": '"workspace-write"',
                "new_string": "{invalid",
            },
            session,
        )
    except ToolError as error:
        assert "设置文件 JSON 无效" in str(error)
    else:
        raise AssertionError("Expected ToolError for invalid settings JSON")


def test_write_rejects_invalid_settings_value_types(tmp_path):
    runtime = build_runtime()
    session = SessionTranscript(session_id="guard-4", cwd=str(tmp_path))
    settings_dir = tmp_path / ".claude-code-thy"
    settings_dir.mkdir(parents=True, exist_ok=True)

    try:
        runtime.execute_input(
            "write",
            {
                "file_path": ".claude-code-thy/settings.json",
                "content": '{"sandbox": {"allow_network": "yes"}}',
            },
            session,
        )
    except ToolError as error:
        assert "设置文件无效" in str(error)
        assert "sandbox.allow_network" in str(error)
    else:
        raise AssertionError("Expected ToolError for invalid settings value type")


def test_read_rejects_large_full_text_read(tmp_path):
    runtime = build_runtime()
    session = SessionTranscript(session_id="guard-3", cwd=str(tmp_path))
    path = tmp_path / "large.txt"
    path.write_text("a" * (600 * 1024), encoding="utf-8")

    try:
        runtime.execute("read", "large.txt", session)
    except ToolError as error:
        assert "文件过大" in str(error)
    else:
        raise AssertionError("Expected ToolError for large full read")
