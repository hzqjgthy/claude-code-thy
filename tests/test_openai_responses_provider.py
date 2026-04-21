import json
from io import BytesIO
from urllib.error import HTTPError

from claude_code_thy.config import AppConfig
from claude_code_thy.models import SessionTranscript
from claude_code_thy.providers.base import ProviderError
from claude_code_thy.providers.openai_responses import OPENAI_RESPONSES_STATE_KEY, OpenAIResponsesProvider
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


def test_openai_responses_provider_rewrites_assistant_text_history_as_user_context():
    config = AppConfig(
        provider="openai-responses-compatible",
        model="gpt-5.4",
        openai_responses_api_key="test-openai-key",
    )
    provider = OpenAIResponsesProvider(config)
    session = SessionTranscript(session_id="s1", cwd="/tmp", model="gpt-5.4", provider_name=provider.name)
    session.add_message("user", "你好", content_blocks=[{"type": "text", "text": "你好"}])
    session.add_message("assistant", "你好！有什么我可以帮你的吗？")
    session.add_message("user", "你是什么模型", content_blocks=[{"type": "text", "text": "你是什么模型"}])

    items = provider._build_input(session)

    assert items[0]["role"] == "user"
    assert items[1]["role"] == "user"
    assert "上一轮助手回复" in items[1]["content"][0]["text"]
    assert "你好！有什么我可以帮你的吗？" in items[1]["content"][0]["text"]
    assert items[2]["role"] == "user"


def test_openai_responses_provider_stores_response_id_state(monkeypatch):
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
                "id": "resp_123",
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
    state = session.runtime_state[OPENAI_RESPONSES_STATE_KEY]
    assert state["last_response_id"] == "resp_123"
    assert state["last_response_message_count"] == 2


def test_openai_responses_provider_uses_previous_response_id_for_incremental_turns(monkeypatch):
    captured: dict[str, object] = {}
    config = AppConfig(
        provider="openai-responses-compatible",
        model="gpt-5.4",
        openai_responses_api_key="test-openai-key",
        openai_responses_base_url="https://example.com",
        openai_responses_use_previous_response_id=True,
    )
    provider = OpenAIResponsesProvider(config)
    session = SessionTranscript(session_id="s1", cwd="/tmp", model="gpt-5.4", provider_name=provider.name)
    session.runtime_state[OPENAI_RESPONSES_STATE_KEY] = {
        "last_response_id": "resp_prev",
        "last_response_message_count": 2,
    }
    session.add_message("user", "你好", content_blocks=[{"type": "text", "text": "你好"}])
    session.add_message("assistant", "你好！有什么我可以帮你的吗？")
    session.add_message("user", "你是什么模型", content_blocks=[{"type": "text", "text": "你是什么模型"}])

    def fake_urlopen(request, timeout):
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        _ = timeout
        return _FakeHttpResponse(
            {
                "id": "resp_next",
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "我是一个模型。"}],
                    }
                ],
            }
        )

    monkeypatch.setattr("claude_code_thy.providers.openai_responses.urlopen", fake_urlopen)

    provider._request(session, [])

    payload = captured["payload"]
    assert payload["previous_response_id"] == "resp_prev"
    assert payload["input"] == [
        {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": "你是什么模型"}],
        }
    ]


def test_openai_responses_provider_skips_previous_response_id_when_disabled(monkeypatch):
    captured: dict[str, object] = {}
    config = AppConfig(
        provider="openai-responses-compatible",
        model="gpt-5.4",
        openai_responses_api_key="test-openai-key",
        openai_responses_base_url="https://example.com",
        openai_responses_use_previous_response_id=False,
    )
    provider = OpenAIResponsesProvider(config)
    session = SessionTranscript(session_id="s1", cwd="/tmp", model="gpt-5.4", provider_name=provider.name)
    session.runtime_state[OPENAI_RESPONSES_STATE_KEY] = {
        "last_response_id": "resp_prev",
        "last_response_message_count": 2,
    }
    session.add_message("user", "你好", content_blocks=[{"type": "text", "text": "你好"}])
    session.add_message("assistant", "你好！有什么我可以帮你的吗？")
    session.add_message("user", "你是什么模型", content_blocks=[{"type": "text", "text": "你是什么模型"}])

    def fake_urlopen(request, timeout):
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        _ = timeout
        return _FakeHttpResponse(
            {
                "id": "resp_next",
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "我是一个模型。"}],
                    }
                ],
            }
        )

    monkeypatch.setattr("claude_code_thy.providers.openai_responses.urlopen", fake_urlopen)

    provider._request(session, [])

    payload = captured["payload"]
    assert "previous_response_id" not in payload
    assert len(payload["input"]) == 3
    assert payload["input"][0]["role"] == "user"
    assert payload["input"][1]["role"] == "user"
    assert "上一轮助手回复" in payload["input"][1]["content"][0]["text"]
    assert payload["input"][2]["content"][0]["text"] == "你是什么模型"


def test_openai_responses_provider_falls_back_when_previous_response_id_fails(monkeypatch):
    captured_payloads: list[dict[str, object]] = []
    config = AppConfig(
        provider="openai-responses-compatible",
        model="gpt-5.4",
        openai_responses_api_key="test-openai-key",
        openai_responses_base_url="https://example.com",
        openai_responses_use_previous_response_id=True,
    )
    provider = OpenAIResponsesProvider(config)
    session = SessionTranscript(session_id="s1", cwd="/tmp", model="gpt-5.4", provider_name=provider.name)
    session.runtime_state[OPENAI_RESPONSES_STATE_KEY] = {
        "last_response_id": "resp_prev",
        "last_response_message_count": 2,
    }
    session.add_message("user", "你好", content_blocks=[{"type": "text", "text": "你好"}])
    session.add_message("assistant", "你好！有什么我可以帮你的吗？")
    session.add_message("user", "你是什么模型", content_blocks=[{"type": "text", "text": "你是什么模型"}])

    def fake_urlopen(request, timeout):
        payload = json.loads(request.data.decode("utf-8"))
        captured_payloads.append(payload)
        _ = timeout
        if len(captured_payloads) == 1:
            raise HTTPError(
                request.full_url,
                400,
                "unsupported previous_response_id",
                hdrs=None,
                fp=BytesIO(b'{"error":{"message":"unsupported previous_response_id"}}'),
            )
        return _FakeHttpResponse(
            {
                "id": "resp_fallback",
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "我是一个模型。"}],
                    }
                ],
            }
        )

    monkeypatch.setattr("claude_code_thy.providers.openai_responses.urlopen", fake_urlopen)

    response = provider._request(session, [])

    assert response.display_text == "我是一个模型。"
    assert len(captured_payloads) == 2
    assert captured_payloads[0]["previous_response_id"] == "resp_prev"
    assert "previous_response_id" not in captured_payloads[1]
    fallback_input = captured_payloads[1]["input"]
    assert fallback_input[0]["role"] == "user"
    assert fallback_input[1]["role"] == "user"
    assert "上一轮助手回复" in fallback_input[1]["content"][0]["text"]
    assert session.runtime_state[OPENAI_RESPONSES_STATE_KEY]["use_previous_response_id"] is False


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


def test_openai_responses_provider_preserves_structured_edit_schema():
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
                "edits": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "old_string": {"type": "string"},
                            "new_string": {"type": "string"},
                            "replace_all": {"type": "boolean"},
                        },
                        "required": ["old_string", "new_string"],
                    },
                },
            },
            "required": ["file_path"],
        },
    )

    payload = provider._tool_to_api(tool)
    parameters = payload["parameters"]

    assert payload["name"] == "edit"
    assert parameters["required"] == ["file_path"]
    assert "edits" in parameters["properties"]
    assert parameters["properties"]["edits"]["type"] == "array"
    assert parameters["properties"]["edits"]["items"]["type"] == "object"
    assert parameters["properties"]["edits"]["items"]["required"] == ["old_string", "new_string"]
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
