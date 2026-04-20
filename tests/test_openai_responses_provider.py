import json

from claude_code_thy.config import AppConfig
from claude_code_thy.models import SessionTranscript
from claude_code_thy.providers.base import ProviderError
from claude_code_thy.providers.openai_responses import OpenAIResponsesProvider
from claude_code_thy.tools.base import ToolSpec


class _FakeHttpResponse:
    def __init__(self, body: dict[str, object]) -> None:
        self._body = json.dumps(body, ensure_ascii=False).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return self._body


def test_openai_responses_provider_builds_tools_and_parses_function_call(monkeypatch):
    captured: dict[str, object] = {}
    config = AppConfig(
        provider="openai-responses-compatible",
        model="gpt-5.4",
        openai_responses_api_key="test-openai-key",
        openai_responses_base_url="https://example.com",
        openai_responses_reasoning_effort="high",
        max_tokens=2048,
    )
    provider = OpenAIResponsesProvider(config)
    session = SessionTranscript(session_id="s1", cwd="/tmp", model="gpt-5.4", provider_name=provider.name)
    session.add_message("user", "请读取 README.md", content_blocks=[{"type": "text", "text": "请读取 README.md"}])
    tools = [
        ToolSpec(
            name="read",
            description="读取文件",
            input_schema={
                "type": "object",
                "properties": {"file_path": {"type": "string"}},
                "required": ["file_path"],
            },
        )
    ]

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["headers"] = dict(request.header_items())
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return _FakeHttpResponse(
            {
                "output": [
                    {
                        "type": "function_call",
                        "call_id": "call_123",
                        "name": "read",
                        "arguments": "{\"file_path\":\"README.md\"}",
                    }
                ]
            }
        )

    monkeypatch.setattr("claude_code_thy.providers.openai_responses.urlopen", fake_urlopen)

    response = provider._request(session, tools)

    assert captured["url"] == "https://example.com/v1/responses"
    assert captured["timeout"] == config.api_timeout_ms / 1000
    assert captured["headers"]["Authorization"] == "Bearer test-openai-key"
    assert captured["headers"]["User-agent"] == "python-requests/2.31.0"
    assert captured["payload"]["reasoning"] == {"effort": "high"}
    assert captured["payload"]["parallel_tool_calls"] is False
    assert captured["payload"]["max_output_tokens"] == 2048
    assert captured["payload"]["tools"][0]["type"] == "function"
    assert captured["payload"]["tools"][0]["parameters"]["required"] == ["file_path"]
    assert captured["payload"]["input"][0]["role"] == "user"
    assert response.display_text == ""
    assert response.tool_calls[0].id == "call_123"
    assert response.tool_calls[0].name == "read"
    assert response.tool_calls[0].input == {"file_path": "README.md"}


def test_openai_responses_provider_maps_tool_history_back_to_input():
    config = AppConfig(
        provider="openai-responses-compatible",
        model="gpt-5.4",
        openai_responses_api_key="test-openai-key",
    )
    provider = OpenAIResponsesProvider(config)
    session = SessionTranscript(session_id="s1", cwd="/tmp", model="gpt-5.4", provider_name=provider.name)
    session.add_message("user", "请读取 README.md", content_blocks=[{"type": "text", "text": "请读取 README.md"}])
    session.add_message(
        "assistant",
        "",
        metadata={
            "tool_calls": [
                {
                    "id": "call_123",
                    "name": "read",
                    "input": {"file_path": "README.md"},
                }
            ]
        },
    )
    session.add_message(
        "tool",
        "README 内容",
        content_blocks=[
            {
                "type": "tool_result",
                "tool_use_id": "call_123",
                "is_error": False,
                "content": "README 内容",
            }
        ],
        metadata={"tool_use_id": "call_123", "tool_name": "read"},
    )

    items = provider._build_input(session)

    assert items[0]["role"] == "user"
    assert items[1]["type"] == "function_call"
    assert items[1]["call_id"] == "call_123"
    assert json.loads(items[1]["arguments"]) == {"file_path": "README.md"}
    assert items[2] == {
        "type": "function_call_output",
        "call_id": "call_123",
        "output": "README 内容",
    }


def test_openai_responses_provider_rejects_non_object_tool_arguments():
    config = AppConfig(
        provider="openai-responses-compatible",
        model="gpt-5.4",
        openai_responses_api_key="test-openai-key",
    )
    provider = OpenAIResponsesProvider(config)

    try:
        provider._parse_json_object("[1,2,3]")
    except ProviderError as error:
        assert "JSON object" in str(error)
    else:
        raise AssertionError("Expected ProviderError")


def test_openai_responses_provider_simplifies_edit_schema_for_gateway_compat():
    config = AppConfig(
        provider="openai-responses-compatible",
        model="gpt-5.4",
        openai_responses_api_key="test-openai-key",
    )
    provider = OpenAIResponsesProvider(config)
    tool = ToolSpec(
        name="edit",
        description="按 old_string/new_string 规则精确编辑文件。",
        input_schema={
            "type": "object",
            "properties": {
                "file_path": {"type": "string"},
                "old_string": {"type": "string"},
                "new_string": {"type": "string"},
                "replace_all": {"type": "boolean"},
                "edits": {"type": "array"},
            },
            "required": ["file_path"],
        },
    )

    payload = provider._tool_to_api(tool)
    parameters = payload["parameters"]

    assert payload["name"] == "edit"
    assert parameters["required"] == ["file_path", "old_string", "new_string"]
    assert "edits" not in parameters["properties"]
    assert parameters["properties"]["replace_all"]["type"] == "boolean"


def test_openai_responses_provider_rejects_stream_mode_for_now():
    config = AppConfig(
        provider="openai-responses-compatible",
        model="gpt-5.4",
        openai_responses_api_key="test-openai-key",
        openai_responses_enable_stream=True,
    )
    provider = OpenAIResponsesProvider(config)
    session = SessionTranscript(session_id="s1", cwd="/tmp", model="gpt-5.4", provider_name=provider.name)

    try:
        provider._request(session, [])
    except ProviderError as error:
        assert "OPENAI_RESPONSES_ENABLE_STREAM=false" in str(error)
    else:
        raise AssertionError("Expected ProviderError")


def test_openai_responses_provider_ignores_null_error_field(monkeypatch):
    config = AppConfig(
        provider="openai-responses-compatible",
        model="gpt-5.4",
        openai_responses_api_key="test-openai-key",
        openai_responses_base_url="https://example.com",
    )
    provider = OpenAIResponsesProvider(config)
    session = SessionTranscript(session_id="s1", cwd="/tmp", model="gpt-5.4", provider_name=provider.name)
    session.add_message("user", "你好", content_blocks=[{"type": "text", "text": "你好"}])

    def fake_urlopen(request, timeout):
        _ = (request, timeout)
        return _FakeHttpResponse(
            {
                "error": None,
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "你好！"}],
                    }
                ],
            }
        )

    monkeypatch.setattr("claude_code_thy.providers.openai_responses.urlopen", fake_urlopen)

    response = provider._request(session, [])

    assert response.display_text == "你好！"
