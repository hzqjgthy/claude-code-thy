from claude_code_thy.models import ChatMessage, SessionTranscript
from claude_code_thy.permissions import PermissionRequest
from claude_code_thy.server.presenters import present_message, present_pending_permission


def test_present_message_maps_tool_result_metadata():
    """测试 `present_message_maps_tool_result_metadata` 场景。"""
    message = ChatMessage(
        role="tool",
        text="工具 `read` 执行成功",
        content_blocks=[
            {
                "type": "tool_result",
                "tool_use_id": "call_001",
                "is_error": False,
                "content": "hello",
            }
        ],
        metadata={
            "tool_name": "read",
            "display_name": "Read",
            "ui_kind": "read",
            "ok": True,
            "summary": "读取文件：README.md",
            "output": "hello",
            "preview": "",
            "structured_data": {"type": "text"},
            "tool_use_id": "call_001",
        },
    )

    dto = present_message("session-1", 2, message)

    assert dto.kind == "tool_result"
    assert dto.tool_result is not None
    assert dto.tool_result.tool_name == "read"
    assert dto.tool_result.tool_use_id == "call_001"


def test_present_pending_permission_maps_runtime_state():
    """测试 `present_pending_permission_maps_runtime_state` 场景。"""
    session = SessionTranscript(session_id="s1", cwd="/tmp/project")
    request = PermissionRequest.create(
        tool_name="read",
        target="path",
        value="/tmp/project/secret.txt",
        reason="需要确认",
        approval_key="read:path:/tmp/project/secret.txt",
    )
    session.runtime_state["pending_permission"] = {
        "request": request.to_dict(),
        "source_type": "tool_call",
        "tool_name": "read",
        "input_data": {"file_path": "secret.txt"},
        "tool_use_id": "call_123",
    }

    dto = present_pending_permission(session)

    assert dto is not None
    assert dto.tool_name == "read"
    assert dto.request.prompt_text
    assert dto.tool_use_id == "call_123"
