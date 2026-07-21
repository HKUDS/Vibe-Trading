"""Coverage for the AnyRouter.top regional Responses API provider."""

from __future__ import annotations

import json

import pytest

from src.config.accessor import reset_env_config
from src.providers import llm as llm_mod
from src.providers.anyrouter_responses import (
    AnyRouterResponsesLLM,
    anyrouter_responses_url,
    validate_anyrouter_base_url,
)
from src.providers.openai_codex import _events_from_lines, _message_chunks_from_events


def test_anyrouter_base_url_validation_and_response_path() -> None:
    assert validate_anyrouter_base_url("https://region.example/v1/") == "https://region.example/v1"
    assert anyrouter_responses_url("https://relay.example/v1") == "https://relay.example/v1/responses"
    assert anyrouter_responses_url("https://relay.example/v1/responses") == "https://relay.example/v1/responses"

    with pytest.raises(ValueError, match="requires ANYROUTER_BASE_URL"):
        validate_anyrouter_base_url("")

    for invalid in (
        "http://region.example/v1",
        "https://user:secret@region.example/v1",
        "https://region.example/v1?token=secret",
    ):
        with pytest.raises(ValueError, match="credential-free HTTPS"):
            validate_anyrouter_base_url(invalid)


def test_build_llm_returns_anyrouter_responses_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm_mod, "_dotenv_loaded", True)
    monkeypatch.setenv("LANGCHAIN_PROVIDER", "anyrouter")
    monkeypatch.setenv("LANGCHAIN_MODEL_NAME", "gpt-5.6-sol")
    monkeypatch.setenv("ANYROUTER_API_KEY", "sk-test")
    monkeypatch.setenv("ANYROUTER_BASE_URL", "https://region.example/v1")
    reset_env_config()

    adapter = llm_mod.build_llm()

    assert isinstance(adapter, AnyRouterResponsesLLM)
    assert adapter.model == "gpt-5.6-sol"
    assert adapter.responses_url == "https://region.example/v1/responses"
    assert adapter._headers()["Authorization"] == "Bearer sk-test"


def test_build_llm_requires_explicit_regional_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(llm_mod, "_dotenv_loaded", True)
    monkeypatch.setenv("LANGCHAIN_PROVIDER", "anyrouter")
    monkeypatch.setenv("LANGCHAIN_MODEL_NAME", "gpt-5.6-sol")
    monkeypatch.setenv("ANYROUTER_API_KEY", "sk-test")
    monkeypatch.delenv("ANYROUTER_BASE_URL", raising=False)
    reset_env_config()

    with pytest.raises(ValueError, match="requires ANYROUTER_BASE_URL"):
        llm_mod.build_llm()


def test_anyrouter_body_preserves_model_and_round_trips_tool_history() -> None:
    adapter = AnyRouterResponsesLLM(
        model="gpt-5.6-sol",
        api_key="sk-test",
        base_url="https://region.example/v1",
        reasoning_effort="high",
    ).bind_tools([
        {
            "type": "function",
            "function": {
                "name": "market_data",
                "description": "Read market data",
                "parameters": {
                    "type": "object",
                    "properties": {"symbol": {"type": "string"}},
                    "required": ["symbol"],
                },
            },
        }
    ])

    body = adapter._body(
        [
            {"role": "system", "content": "Use evidence."},
            {"role": "user", "content": "Check BTC."},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_1|fc_1",
                        "type": "function",
                        "function": {"name": "market_data", "arguments": '{"symbol":"BTC-USDT"}'},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_1|fc_1", "content": '{"close":60000}'},
        ],
        stream=True,
    )

    assert body["model"] == "gpt-5.6-sol"
    assert body["instructions"] == "Use evidence."
    assert body["reasoning"] == {"effort": "high"}
    assert body["tools"][0]["name"] == "market_data"
    assert body["input"][-2]["type"] == "function_call"
    assert body["input"][-1] == {
        "type": "function_call_output",
        "call_id": "call_1",
        "output": '{"close":60000}',
    }


def test_anyrouter_sse_parser_carries_reasoning_tools_and_usage() -> None:
    events = list(_events_from_lines([
        'event: response.reasoning_summary_text.delta',
        'data: {"type":"response.reasoning_summary_text.delta","delta":"checking"}',
        "",
        'data: {"type":"response.output_item.added","item":{"type":"function_call","call_id":"call_1","id":"fc_1","name":"market_data","arguments":""}}',
        "",
        'data: {"type":"response.function_call_arguments.done","call_id":"call_1","arguments":"{\\"symbol\\":\\"BTC-USDT\\"}"}',
        "",
        'data: {"type":"response.output_item.done","item":{"type":"function_call","call_id":"call_1"}}',
        "",
        'data: {"type":"response.completed","response":{"status":"completed","usage":{"input_tokens":10,"output_tokens":4,"total_tokens":14}}}',
        "",
    ]))

    chunks = list(_message_chunks_from_events(events))

    assert chunks[0].additional_kwargs["reasoning_content"] == "checking"
    assert chunks[1].tool_calls == [
        {"id": "call_1|fc_1", "name": "market_data", "args": {"symbol": "BTC-USDT"}}
    ]
    assert chunks[2].usage_metadata == {
        "input_tokens": 10,
        "output_tokens": 4,
        "total_tokens": 14,
    }


def test_anyrouter_stream_uses_api_key_without_chatgpt_oauth(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class _FakeResponse:
        status_code = 200

        def __enter__(self) -> "_FakeResponse":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def iter_lines(self):
            return iter([
                'data: {"type":"response.output_text.delta","delta":"ok"}',
                "",
                'data: {"type":"response.completed","response":{"status":"completed"}}',
                "",
            ])

    class _FakeClient:
        def __init__(self, **kwargs: object) -> None:
            captured["client"] = kwargs

        def __enter__(self) -> "_FakeClient":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def stream(self, method: str, url: str, **kwargs: object) -> _FakeResponse:
            captured.update({"method": method, "url": url, **kwargs})
            return _FakeResponse()

    import src.providers.openai_codex as responses_mod

    monkeypatch.setattr(responses_mod.httpx, "Client", _FakeClient)
    adapter = AnyRouterResponsesLLM(
        model="gpt-5.6-sol",
        api_key="sk-test",
        base_url="https://relay.example/v1",
    )

    chunks = list(adapter.stream([{"role": "user", "content": "hello"}]))

    assert chunks[0].content == "ok"
    assert captured["url"] == "https://relay.example/v1/responses"
    headers = captured["headers"]
    assert isinstance(headers, dict)
    assert headers["Authorization"] == "Bearer sk-test"
    assert "chatgpt-account-id" not in headers
    assert json.dumps(captured).count("sk-test") == 1
