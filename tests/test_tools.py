from claude_code_thy.models import SessionTranscript
from claude_code_thy.tools import ToolRuntime, build_builtin_tools


def build_runtime() -> ToolRuntime:
    return ToolRuntime(build_builtin_tools())


def test_write_and_read_tool_round_trip(tmp_path):
    runtime = build_runtime()
    session = SessionTranscript(session_id="test", cwd=str(tmp_path))

    write_result = runtime.execute_input(
        "write",
        {"file_path": "notes.txt", "content": "hello world"},
        session,
    )
    read_result = runtime.execute("read", "notes.txt", session)

    assert write_result.ok is True
    assert read_result.ok is True
    assert "hello world" in read_result.output


def test_glob_tool_lists_matching_files(tmp_path):
    runtime = build_runtime()
    session = SessionTranscript(session_id="test", cwd=str(tmp_path))
    (tmp_path / "a.py").write_text("print('a')", encoding="utf-8")
    (tmp_path / "b.txt").write_text("b", encoding="utf-8")

    result = runtime.execute("glob", "*.py", session)

    assert result.ok is True
    assert "a.py" in result.output


def test_grep_tool_finds_matches(tmp_path):
    runtime = build_runtime()
    session = SessionTranscript(session_id="test", cwd=str(tmp_path))
    (tmp_path / "app.py").write_text("class SessionTranscript:\n    pass\n", encoding="utf-8")

    result = runtime.execute_input(
        "grep",
        {"pattern": "SessionTranscript", "glob": "*.py", "output_mode": "content"},
        session,
    )

    assert result.ok is True
    assert "SessionTranscript" in result.output


def test_read_tool_execute_input_supports_offset_and_limit(tmp_path):
    runtime = build_runtime()
    session = SessionTranscript(session_id="test", cwd=str(tmp_path))
    (tmp_path / "sample.txt").write_text("a\nb\nc\nd\n", encoding="utf-8")

    result = runtime.execute_input(
        "read",
        {"file_path": "sample.txt", "offset": 2, "limit": 2},
        session,
    )

    assert result.ok is True
    assert "     2\tb" in result.output
    assert "     3\tc" in result.output


def test_write_tool_preserves_crlf_newlines(tmp_path):
    runtime = build_runtime()
    session = SessionTranscript(session_id="test", cwd=str(tmp_path))
    path = tmp_path / "notes.txt"
    path.write_bytes(b"hello\r\nworld\r\n")

    runtime.execute("read", "notes.txt", session)
    result = runtime.execute_input(
        "write",
        {"file_path": "notes.txt", "content": "hello\ncodex\n"},
        session,
    )

    assert result.ok is True
    assert result.metadata["newline"] == repr("\r\n")
    assert path.read_bytes() == b"hello\r\ncodex\r\n"


def test_edit_tool_replaces_single_match(tmp_path):
    runtime = build_runtime()
    session = SessionTranscript(session_id="test", cwd=str(tmp_path))
    (tmp_path / "app.py").write_text("value = 'old'\n", encoding="utf-8")
    runtime.execute("read", "app.py", session)

    result = runtime.execute_input(
        "edit",
        {
            "file_path": "app.py",
            "old_string": "old",
            "new_string": "new",
        },
        session,
    )

    assert result.ok is True
    assert "old" in result.preview
    assert "new" in result.preview
    assert "new" in (tmp_path / "app.py").read_text(encoding="utf-8")


def test_edit_tool_preserves_utf16_bom(tmp_path):
    runtime = build_runtime()
    session = SessionTranscript(session_id="test", cwd=str(tmp_path))
    path = tmp_path / "utf16.txt"
    path.write_bytes(b"\xff\xfeh\x00i\x00\r\x00\n\x00")

    runtime.execute("read", "utf16.txt", session)
    result = runtime.execute_input(
        "edit",
        {
            "file_path": "utf16.txt",
            "old_string": "hi",
            "new_string": "hey",
        },
        session,
    )

    assert result.ok is True
    assert result.metadata["encoding"] == "utf-16le"
    assert path.read_bytes().startswith(b"\xff\xfe")


def test_edit_tool_supports_structured_edits(tmp_path):
    runtime = build_runtime()
    session = SessionTranscript(session_id="test", cwd=str(tmp_path))
    path = tmp_path / "multi.txt"
    path.write_text("alpha\nbeta\n", encoding="utf-8")

    runtime.execute("read", "multi.txt", session)
    result = runtime.execute_input(
        "edit",
        {
            "file_path": "multi.txt",
            "edits": [
                {"old_string": "alpha", "new_string": "ALPHA"},
                {"old_string": "beta", "new_string": "BETA"},
            ],
        },
        session,
    )

    assert result.ok is True
    assert result.metadata["num_edits"] == 2
    assert path.read_text(encoding="utf-8") == "ALPHA\nBETA\n"


def test_write_tool_returns_git_diff_when_in_repo(tmp_path):
    import subprocess

    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)

    runtime = build_runtime()
    session = SessionTranscript(session_id="test", cwd=str(tmp_path))

    result = runtime.execute_input(
        "write",
        {"file_path": "repo-file.txt", "content": "hello git\n"},
        session,
    )

    assert result.ok is True
    assert result.structured_data["git_diff"]["filename"] == "repo-file.txt"


def test_read_tool_supports_utf16_text(tmp_path):
    runtime = build_runtime()
    session = SessionTranscript(session_id="test", cwd=str(tmp_path))
    path = tmp_path / "utf16-read.txt"
    path.write_bytes(b"\xff\xfeh\x00i\x00\r\x00\n\x00")

    result = runtime.execute("read", "utf16-read.txt", session)

    assert result.ok is True
    assert "hi" in result.output


def test_render_rejected_edit_result_contains_diff(tmp_path):
    runtime = build_runtime()
    session = SessionTranscript(session_id="test", cwd=str(tmp_path))
    path = tmp_path / "edit.txt"
    path.write_text("before\n", encoding="utf-8")

    result = runtime.render_rejected(
        "edit",
        {
            "file_path": "edit.txt",
            "old_string": "before",
            "new_string": "after",
        },
        session,
        reason="user denied",
    )

    assert result.ok is False
    assert result.ui_kind == "rejected"
    assert result.structured_data["rejected"] is True
    assert "after" in result.preview


def test_agent_tool_can_launch_background_task(tmp_path):
    runtime = build_runtime()
    session = SessionTranscript(session_id="test", cwd=str(tmp_path), model="dummy")

    result = runtime.execute_input(
        "agent",
        {
            "prompt": "background test agent",
            "description": "background agent",
            "run_in_background": True,
        },
        session,
    )

    assert result.ok is True
    assert result.structured_data["status"] == "running"
    assert result.structured_data["task_id"]
