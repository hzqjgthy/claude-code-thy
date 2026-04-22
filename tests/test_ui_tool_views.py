from rich.console import Console

from claude_code_thy.ui.tool_views import build_tool_result_message


def render_to_text(metadata: dict[str, object]) -> str:
    """渲染 `to_text`。"""
    console = Console(force_terminal=False, width=120, record=True)
    console.print(build_tool_result_message(metadata))
    return console.export_text()


def test_bash_tool_result_message_deduplicates_command_summary() -> None:
    """测试 `bash_tool_result_message_deduplicates_command_summary` 场景。"""
    text = render_to_text(
        {
            "tool_name": "bash",
            "display_name": "Bash",
            "summary": "命令：echo hello-bash",
            "ui_kind": "bash",
            "output": "hello-bash",
            "structured_data": {
                "command": "echo hello-bash",
                "description": "echo hello-bash",
                "command_kind": "command",
            },
        }
    )

    assert "⏺ Bash 命令：echo hello-bash" in text
    assert "\n  echo hello-bash\n" not in text
    assert "hello-bash" in text


def test_read_tool_result_message_keeps_line_count_on_own_line() -> None:
    """测试 `read_tool_result_message_keeps_line_count_on_own_line` 场景。"""
    text = render_to_text(
        {
            "tool_name": "read",
            "display_name": "Read",
            "summary": "读取文件：manual-secret/token.txt",
            "ui_kind": "read",
            "output": "     1\tsuper-secret-token",
            "structured_data": {
                "type": "text",
                "file_path": "manual-secret/token.txt",
                "num_lines": 1,
                "start_line": 1,
                "total_lines": 1,
                "total_bytes": 18,
            },
        }
    )

    assert "⏺ Read 读取文件：manual-secret/token.txt\n  Read 1 line" in text
