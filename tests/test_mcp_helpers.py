import json

from claude_code_thy.mcp.names import (
    build_mcp_tool_name,
    build_prompt_command_name,
    matching_server_names,
    parse_dynamic_mcp_name,
)
from claude_code_thy.mcp.serializers import (
    render_prompt_result,
    serialize_mcp_tool_result,
    serialize_resource_read_result,
)


def test_dynamic_mcp_name_helpers_round_trip():
    """测试 `dynamic_mcp_name_helpers_round_trip` 场景。"""
    tool_name = build_mcp_tool_name("xiaohongshu-mcp", "check login/status")
    prompt_name = build_prompt_command_name("xiaohongshu-mcp", "daily summary")

    assert tool_name == "mcp__xiaohongshu_mcp__check_login_status"
    assert prompt_name == "mcp__xiaohongshu_mcp__daily_summary"
    assert parse_dynamic_mcp_name(tool_name) == ("xiaohongshu_mcp", "check_login_status")
    assert matching_server_names(["xiaohongshu-mcp", "other"], "xiaohongshu_mcp") == [
        "xiaohongshu-mcp"
    ]


def test_serialize_mcp_tool_result_is_json_safe():
    """测试 `serialize_mcp_tool_result_is_json_safe` 场景。"""
    class DummyTextContent:
        """表示 `DummyTextContent`。"""
        def __init__(self, text: str) -> None:
            """初始化实例状态。"""
            self.type = "text"
            self.text = text
            self.annotations = None
            self.meta = None

    class DummyResult:
        """保存 `DummyResult`。"""
        def __init__(self) -> None:
            """初始化实例状态。"""
            self.content = [DummyTextContent('{"status":"ok"}')]

    output, structured = serialize_mcp_tool_result(DummyResult())

    assert output == '{"status":"ok"}'
    assert json.dumps(structured, ensure_ascii=False)


def test_prompt_and_resource_serializers_share_json_safe_text_extraction():
    """测试 `prompt_and_resource_serializers_share_json_safe_text_extraction` 场景。"""
    class DummyTextContent:
        """表示 `DummyTextContent`。"""
        def __init__(self, text: str) -> None:
            """初始化实例状态。"""
            self.type = "text"
            self.text = text

    class DummyPromptMessage:
        """保存 `DummyPromptMessage`。"""
        def __init__(self, text: str) -> None:
            """初始化实例状态。"""
            self.content = [DummyTextContent(text)]

    class DummyPromptResult:
        """保存 `DummyPromptResult`。"""
        def __init__(self) -> None:
            """初始化实例状态。"""
            self.messages = [DummyPromptMessage("hello from prompt")]

    class DummyResourceContent:
        """表示 `DummyResourceContent`。"""
        def __init__(self) -> None:
            """初始化实例状态。"""
            self.uri = "memo://1"
            self.mimeType = "text/plain"
            self.text = "hello from resource"

    class DummyResourceResult:
        """保存 `DummyResourceResult`。"""
        def __init__(self) -> None:
            """初始化实例状态。"""
            self.contents = [DummyResourceContent()]

    output, structured = serialize_resource_read_result(DummyResourceResult())

    assert render_prompt_result(DummyPromptResult()) == "hello from prompt"
    assert output == "hello from resource"
    assert json.dumps(structured, ensure_ascii=False)
