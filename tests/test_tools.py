import asyncio

from claude_code_thy.models import SessionTranscript
from claude_code_thy.mcp.client import _ManagedConnection
from claude_code_thy.mcp.config import add_project_mcp_server
from claude_code_thy.mcp.types import McpResourceDefinition, McpToolDefinition
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


def test_read_tool_supports_utf8_non_ascii_text(tmp_path):
    runtime = build_runtime()
    session = SessionTranscript(session_id="test", cwd=str(tmp_path))
    path = tmp_path / "README.md"
    path.write_text("你好，世界\n这是一个 UTF-8 文本文件。\n", encoding="utf-8")

    result = runtime.execute("read", "README.md", session)

    assert result.ok is True
    assert "你好，世界" in result.output


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


def test_dynamic_mcp_tools_remain_visible_across_repeated_async_reads(tmp_path):
    add_project_mcp_server(
        tmp_path,
        "xiaohongshu-mcp",
        {"type": "http", "url": "http://localhost:18060/mcp"},
    )
    runtime = build_runtime()
    session = SessionTranscript(session_id="test", cwd=str(tmp_path))
    manager = runtime.services_for(session).mcp_manager

    class DummyStack:
        async def aclose(self) -> None:
            return None

    class DummyTool:
        def __init__(self, name: str) -> None:
            self.name = name
            self.description = f"tool:{name}"
            self.inputSchema = {"type": "object", "properties": {}}
            self.annotations = {"readOnlyHint": True}

    class DummyToolListResult:
        def __init__(self) -> None:
            self.tools = [DummyTool("check_login_status")]

    class DummyPromptListResult:
        def __init__(self) -> None:
            self.prompts = []

    class DummyResourceListResult:
        def __init__(self) -> None:
            self.resources = []

    class DummySession:
        def __init__(self) -> None:
            self._loop_id = id(asyncio.get_running_loop())

        async def list_tools(self):
            if id(asyncio.get_running_loop()) != self._loop_id:
                raise RuntimeError("session used from different event loop")
            return DummyToolListResult()

        async def list_prompts(self):
            if id(asyncio.get_running_loop()) != self._loop_id:
                raise RuntimeError("session used from different event loop")
            return DummyPromptListResult()

        async def list_resources(self):
            if id(asyncio.get_running_loop()) != self._loop_id:
                raise RuntimeError("session used from different event loop")
            return DummyResourceListResult()

    async def fake_open_connection(config):
        return _ManagedConnection(
            config=config,
            stack=DummyStack(),
            session=DummySession(),
        )

    manager._open_connection = fake_open_connection  # type: ignore[method-assign]

    async def run_twice():
        first = [
            tool.name
            for tool in runtime.list_tools_for_session(session)
            if tool.name.startswith("mcp__")
        ]
        second = [
            tool.name
            for tool in runtime.list_tools_for_session(session)
            if tool.name.startswith("mcp__")
        ]
        return first, second

    first, second = asyncio.run(run_twice())

    assert first == ["mcp__xiaohongshu_mcp__check_login_status"]
    assert second == first


def test_dynamic_mcp_tools_refresh_once_then_reuse_cache(tmp_path):
    runtime = build_runtime()
    session = SessionTranscript(session_id="test", cwd=str(tmp_path))
    services = runtime.services_for(session)

    class DummyMgr:
        def __init__(self) -> None:
            self.refresh_calls = 0
            self.loaded = False

        async def refresh_all(self):
            self.refresh_calls += 1
            self.loaded = True
            return []

        def cached_tools(self):
            if not self.loaded:
                return {}
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
            return {}

        def cached_resources(self):
            return {}

    manager = DummyMgr()
    services.mcp_manager = manager

    first = [
        tool.name
        for tool in runtime.list_tools_for_session(session)
        if tool.name.startswith("mcp__")
    ]
    second = [
        tool.name
        for tool in runtime.list_tools_for_session(session)
        if tool.name.startswith("mcp__")
    ]

    assert first == ["mcp__xiaohongshu_mcp__check_login_status"]
    assert second == first
    assert manager.refresh_calls == 1


def test_mcp_tool_execute_from_worker_thread_uses_same_runner_loop(tmp_path):
    add_project_mcp_server(
        tmp_path,
        "xiaohongshu-mcp",
        {"type": "http", "url": "http://localhost:18060/mcp"},
    )
    runtime = build_runtime()
    session = SessionTranscript(session_id="test", cwd=str(tmp_path))
    manager = runtime.services_for(session).mcp_manager

    class DummyStack:
        async def aclose(self) -> None:
            return None

    class DummyTool:
        def __init__(self, name: str) -> None:
            self.name = name
            self.description = f"tool:{name}"
            self.inputSchema = {"type": "object", "properties": {}, "required": []}
            self.annotations = {"readOnlyHint": True}

    class DummyToolListResult:
        def __init__(self) -> None:
            self.tools = [DummyTool("check_login_status")]

    class DummyPromptListResult:
        def __init__(self) -> None:
            self.prompts = []

    class DummyResourceListResult:
        def __init__(self) -> None:
            self.resources = []

    class DummyCallToolResult:
        def __init__(self) -> None:
            self.content = "logged-in"

    class DummySession:
        def __init__(self) -> None:
            self._loop_id = id(asyncio.get_running_loop())

        async def list_tools(self):
            if id(asyncio.get_running_loop()) != self._loop_id:
                raise RuntimeError("session used from different event loop")
            return DummyToolListResult()

        async def list_prompts(self):
            if id(asyncio.get_running_loop()) != self._loop_id:
                raise RuntimeError("session used from different event loop")
            return DummyPromptListResult()

        async def list_resources(self):
            if id(asyncio.get_running_loop()) != self._loop_id:
                raise RuntimeError("session used from different event loop")
            return DummyResourceListResult()

        async def call_tool(self, tool_name, arguments=None):
            if id(asyncio.get_running_loop()) != self._loop_id:
                raise RuntimeError("call_tool used from different event loop")
            return DummyCallToolResult()

    async def fake_open_connection(config):
        return _ManagedConnection(
            config=config,
            stack=DummyStack(),
            session=DummySession(),
        )

    manager._open_connection = fake_open_connection  # type: ignore[method-assign]

    async def run():
        names = [
            tool.name
            for tool in runtime.list_tools_for_session(session)
            if tool.name.startswith("mcp__")
        ]
        assert names == ["mcp__xiaohongshu_mcp__check_login_status"]
        return await asyncio.to_thread(
            runtime.execute_input,
            "mcp__xiaohongshu_mcp__check_login_status",
            {},
            session,
        )

    result = asyncio.run(run())

    assert result.ok is True
    assert "logged-in" in result.output


def test_mcp_tool_result_is_json_serializable_for_session_save(tmp_path):
    runtime = build_runtime()
    session = SessionTranscript(session_id="test", cwd=str(tmp_path))
    services = runtime.services_for(session)

    class DummyTextContent:
        def __init__(self, text: str) -> None:
            self.type = "text"
            self.text = text
            self.annotations = None
            self.meta = None

    class DummyMcpResult:
        def __init__(self) -> None:
            self.content = [DummyTextContent('{"status":"ok"}')]

    class DummyMgr:
        async def refresh_all(self):
            return []

        def cached_tools(self):
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
            return {}

        def cached_resources(self):
            return {}

        async def call_tool(self, server_name, tool_name, arguments=None):
            return DummyMcpResult()

    services.mcp_manager = DummyMgr()

    result = runtime.execute_input(
        "mcp__xiaohongshu_mcp__check_login_status",
        {},
        session,
    )
    session.add_message(
        "tool",
        result.render(),
        content_blocks=[
            {
                "type": "tool_result",
                "tool_use_id": "toolu_test",
                "is_error": False,
                "content": result.content_for_model(),
            }
        ],
        metadata=result.message_metadata(tool_use_id="toolu_test"),
    )

    import json

    encoded = json.dumps(session.to_dict(), ensure_ascii=False)
    assert '"status":"ok"' in encoded


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


def test_runtime_merges_dynamic_mcp_tools(tmp_path):
    runtime = build_runtime()
    session = SessionTranscript(session_id="test", cwd=str(tmp_path), model="dummy")
    services = runtime.services_for(session)

    class DummyMgr:
        async def refresh_all(self):
            return []

        def cached_tools(self):
            return {
                "demo": [
                    McpToolDefinition(
                        name="search_posts",
                        description="demo tool",
                        input_schema={
                            "type": "object",
                            "properties": {"q": {"type": "string"}},
                            "required": ["q"],
                        },
                        annotations={"readOnlyHint": True, "original_name": "search_posts"},
                    )
                ]
            }

        def cached_prompts(self):
            return {}

        def cached_resources(self):
            return {"demo": [McpResourceDefinition(uri="res://1", name="r1", server="demo")]}

        async def call_tool(self, server_name, tool_name, arguments=None):
            return {"content": f"{server_name}:{tool_name}:{arguments}"}

        async def read_resource(self, server_name, uri):
            class Result:
                contents = [{"uri": uri, "text": "hello resource"}]

            return Result()

    services.mcp_manager = DummyMgr()

    names = [tool.name for tool in runtime.list_tools_for_session(session)]
    assert "mcp__demo__search_posts" in names
    assert "list_mcp_resources" in names

    result = runtime.execute_input("mcp__demo__search_posts", {"q": "abc"}, session)
    assert result.ok is True
    assert "search_posts" in result.output

    resource_result = runtime.execute_input(
        "read_mcp_resource",
        {"server": "demo", "uri": "res://1"},
        session,
    )
    assert resource_result.ok is True
    assert "hello resource" in resource_result.output
