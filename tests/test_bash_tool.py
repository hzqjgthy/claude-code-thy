from claude_code_thy.models import SessionTranscript
from claude_code_thy.tools import PermissionRequiredError, ToolRuntime, build_builtin_tools


def build_runtime() -> ToolRuntime:
    """构建 `runtime`。"""
    return ToolRuntime(build_builtin_tools())


def test_bash_grep_no_matches_is_not_error(tmp_path):
    """测试 `bash_grep_no_matches_is_not_error` 场景。"""
    runtime = build_runtime()
    session = SessionTranscript(session_id="bash-1", cwd=str(tmp_path))
    (tmp_path / "README.md").write_text("hello\nworld\n", encoding="utf-8")

    result = runtime.execute_input(
        "bash",
        {"command": "grep definitely_no_match README.md"},
        session,
    )

    assert result.ok is True
    assert result.metadata["return_code_interpretation"] == "No matches found"


def test_bash_multiple_cd_requires_permission(tmp_path):
    """测试 `bash_multiple_cd_requires_permission` 场景。"""
    runtime = build_runtime()
    session = SessionTranscript(session_id="bash-2", cwd=str(tmp_path))

    try:
        runtime.execute_input(
            "bash",
            {"command": "cd src && cd .. && pwd"},
            session,
        )
    except PermissionRequiredError as error:
        assert "Multiple directory changes" in error.request.reason
    else:
        raise AssertionError("Expected PermissionRequiredError")


def test_bash_sed_in_place_generates_edit_preview(tmp_path):
    """测试 `bash_sed_in_place_generates_edit_preview` 场景。"""
    runtime = build_runtime()
    session = SessionTranscript(session_id="bash-3", cwd=str(tmp_path))
    path = tmp_path / "sample.txt"
    path.write_text("hello world\n", encoding="utf-8")

    result = runtime.execute_input(
        "bash",
        {"command": "sed -i '' 's/world/universe/' sample.txt"},
        session,
    )

    assert result.ok is True
    assert result.ui_kind == "edit"
    assert result.display_name == "Update"
    assert result.structured_data["type"] == "update"
    assert "universe" in path.read_text(encoding="utf-8")


def test_bash_advanced_shell_syntax_requires_permission(tmp_path):
    """测试 `bash_advanced_shell_syntax_requires_permission` 场景。"""
    runtime = build_runtime()
    session = SessionTranscript(session_id="bash-4", cwd=str(tmp_path))

    try:
        runtime.execute_input(
            "bash",
            {"command": "echo $(pwd)"},
            session,
        )
    except PermissionRequiredError as error:
        assert "Advanced shell syntax" in error.request.reason
    else:
        raise AssertionError("Expected PermissionRequiredError")


def test_bash_without_description_uses_command_in_summary(tmp_path):
    """测试 `bash_without_description_uses_command_in_summary` 场景。"""
    runtime = build_runtime()
    session = SessionTranscript(session_id="bash-5", cwd=str(tmp_path))

    result = runtime.execute("bash", "-- echo hello-bash", session)

    assert result.ok is True
    assert result.summary == "命令：echo hello-bash"
    assert isinstance(result.structured_data, dict)
    assert result.structured_data["description"] == "echo hello-bash"
    assert result.output == "hello-bash"
