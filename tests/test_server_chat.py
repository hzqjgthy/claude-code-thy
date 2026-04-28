import asyncio

from claude_code_thy.commands import CommandOutcome
from claude_code_thy.models import SessionTranscript
from claude_code_thy.server.api.chat import _stream_chat_turn_live
from claude_code_thy.server.api.sessions import _stream_permission_resolution_live


def test_stream_chat_turn_live_emits_assistant_delta_then_message_then_done():
    """测试 Web 流式聊天会按 assistant_delta -> message -> done 顺序发出 SSE。"""
    session = SessionTranscript(session_id="s1", cwd="/tmp")

    class DummyRuntime:
        """模拟一个最小流式 runtime。"""

        async def handle_stream(
            self,
            session,
            prompt,
            *,
            tool_event_handler=None,
            text_delta_handler=None,
            message_added_handler=None,
        ):
            _ = (prompt, tool_event_handler)
            if text_delta_handler is not None:
                text_delta_handler("你")
                text_delta_handler("好")
            session.add_message("assistant", "你好")
            if message_added_handler is not None:
                message_added_handler(len(session.messages) - 1, session.messages[-1])
            return CommandOutcome(session=session, message_added=True)

    async def collect():
        chunks = []
        async for chunk in _stream_chat_turn_live(DummyRuntime(), session, "你好"):
            chunks.append(chunk.decode("utf-8"))
        return chunks

    chunks = asyncio.run(collect())
    joined = "".join(chunks)

    assert "event: assistant_delta" in joined
    assert "event: message" in joined
    assert "event: done" in joined
    assert joined.index("event: assistant_delta") < joined.index("event: message") < joined.index("event: done")


def test_stream_permission_resolution_live_emits_assistant_delta_then_message_then_done():
    """测试权限恢复 SSE 会复用同样的事件顺序。"""
    session = SessionTranscript(session_id="s1", cwd="/tmp")

    class DummyRuntime:
        """模拟一个最小的流式权限恢复 runtime。"""

        async def resolve_pending_permission(
            self,
            session,
            *,
            approved,
            tool_event_handler=None,
            text_delta_handler=None,
            message_added_handler=None,
            _skip_turn_logging=False,
        ):
            _ = (approved, tool_event_handler, _skip_turn_logging)
            if text_delta_handler is not None:
                text_delta_handler("继")
                text_delta_handler("续")
            session.add_message("assistant", "继续执行")
            if message_added_handler is not None:
                message_added_handler(len(session.messages) - 1, session.messages[-1])
            return CommandOutcome(session=session, message_added=True)

    async def collect():
        chunks = []
        async for chunk in _stream_permission_resolution_live(DummyRuntime(), session, True):
            chunks.append(chunk.decode("utf-8"))
        return chunks

    chunks = asyncio.run(collect())
    joined = "".join(chunks)

    assert "event: assistant_delta" in joined
    assert "event: message" in joined
    assert "event: done" in joined
    assert joined.index("event: assistant_delta") < joined.index("event: message") < joined.index("event: done")
