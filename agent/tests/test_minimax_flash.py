"""MiniMax defaults and real SDK requests with an offline HTTP transport."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest
from langchain_core.messages import HumanMessage, ToolMessage

from src.providers.discovery import LLMProviderOption, _list_provider_models
from src.config.accessor import reset_env_config
from src.providers import llm, settings

FLASH = "MiniMax-M3.1-Flash"
MODELS = [FLASH, "MiniMax-M3"]
ENDPOINTS = ["https://api.minimax.io/v1", "https://api.minimaxi.com/v1"]


def _provider(name="minimax") -> LLMProviderOption:
    catalog = Path(__file__).resolve().parents[1] / "src/providers/llm_providers.json"
    return LLMProviderOption(
        **next(p for p in json.loads(catalog.read_text()) if p["name"] == name)
    )


@pytest.fixture
def requests(monkeypatch):
    """Exercise the installed SDK; replace only dotenv loading and HTTP transport."""
    captured = []

    def respond(request):
        body = json.loads(request.content)
        captured.append((request, body))
        if body.get("stream"):
            chunk = {
                "id": "offline-stream",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": body["model"],
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "content": "offline",
                            "reasoning_content": "offline thought",
                        },
                        "finish_reason": None,
                    }
                ],
            }
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                text=f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n",
            )
        message = {"role": "assistant", "content": "offline"}
        if body.get("tools"):
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_offline",
                        "type": "function",
                        "function": {
                            "name": "inspect_text",
                            "arguments": '{"text":"hello"}',
                        },
                    }
                ],
            }
        message["reasoning_content"] = "offline reasoning"
        return httpx.Response(
            200,
            json={
                "id": "offline",
                "object": "chat.completion",
                "created": 1,
                "model": body["model"],
                "choices": [
                    {
                        "index": 0,
                        "message": message,
                        "finish_reason": "tool_calls" if body.get("tools") else "stop",
                    }
                ],
            },
        )

    sync = httpx.Client(transport=httpx.MockTransport(respond), trust_env=False)
    async_client = httpx.AsyncClient(
        transport=httpx.MockTransport(respond), trust_env=False
    )
    monkeypatch.setattr(settings, "_dotenv_loaded", True)
    monkeypatch.setattr(
        llm, "_build_http_clients", lambda: (sync, async_client)
    )
    for key in (
        "OPENAI_BASE_URL",
        "OPENAI_API_BASE",
        "OPENAI_API_KEY",
        "LANGCHAIN_USE_RESPONSES_API",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("LANGCHAIN_PROVIDER", "minimax")
    monkeypatch.setenv("LANGCHAIN_MODEL_NAME", _provider().default_model)
    monkeypatch.setenv("MINIMAX_API_KEY", "test-key")
    monkeypatch.setenv("MINIMAX_BASE_URL", ENDPOINTS[0])
    monkeypatch.setenv("LANGCHAIN_TEMPERATURE", "0")
    monkeypatch.setenv("LANGCHAIN_REASONING_EFFORT", "")
    monkeypatch.setenv("VIBE_TRADING_DISABLE_HTTP_PROXY", "true")
    reset_env_config()
    yield captured
    sync.close()
    asyncio.run(async_client.aclose())
    reset_env_config()


@pytest.mark.parametrize("endpoint", ENDPOINTS)
@pytest.mark.parametrize("effort", ["", "low", "medium", "high", "xhigh", "max"])
def test_flash_real_sdk_request(requests, monkeypatch, endpoint, effort):
    monkeypatch.setenv("MINIMAX_BASE_URL", endpoint)
    monkeypatch.setenv("LANGCHAIN_REASONING_EFFORT", effort)
    model = llm.build_llm()
    assert model.invoke([HumanMessage(content="hello")]).content == "offline"
    request, body = requests[0]
    assert str(request.url) == endpoint + "/chat/completions"
    assert request.headers["authorization"] == "Bearer test-key"
    assert body["model"] == FLASH
    assert body["temperature"] == 0.01
    # Keep the existing provider allowlist: Flash uses server-default depth.
    assert "reasoning_effort" not in body
    assert "reasoning" not in body
    assert "thinking" not in body
    assert "service_tier" not in body
    assert "reasoning_split" not in body


def test_registry_endpoint_is_used_when_unset(requests, monkeypatch):
    monkeypatch.delenv("MINIMAX_BASE_URL")
    llm.build_llm().invoke("hello")
    assert str(requests[0][0].url) == ENDPOINTS[0] + "/chat/completions"
    assert requests[0][1]["model"] == FLASH


@pytest.mark.parametrize("effort", ["none", "minimal", "invalid"])
def test_flash_does_not_send_unsupported_effort(requests, monkeypatch, effort):
    monkeypatch.setenv("LANGCHAIN_REASONING_EFFORT", effort)
    llm.build_llm().invoke("hello")
    assert "reasoning_effort" not in requests[0][1]
    assert "thinking" not in requests[0][1]


@pytest.mark.parametrize(
    "model_name",
    ["MiniMax-M3", "MiniMax-M2.7", "MiniMax-M2.7-highspeed", "custom-model"],
)
def test_saved_models_are_sent_unchanged(requests, monkeypatch, model_name):
    monkeypatch.setenv("LANGCHAIN_MODEL_NAME", model_name)
    monkeypatch.setenv("LANGCHAIN_REASONING_EFFORT", "none")
    llm.build_llm().invoke("hello")
    assert requests[0][1]["model"] == model_name
    assert "reasoning_effort" not in requests[0][1]


def test_custom_gateway_keeps_its_contract(requests, monkeypatch):
    monkeypatch.setenv("MINIMAX_BASE_URL", "https://gateway.example/v1")
    monkeypatch.setenv("LANGCHAIN_REASONING_EFFORT", "none")
    llm.build_llm().invoke("hello")
    assert str(requests[0][0].url) == "https://gateway.example/v1/chat/completions"
    assert "reasoning_effort" not in requests[0][1]


def test_existing_content_blocks_are_not_rewritten(requests):
    content = [
        {"type": "text", "text": "Describe this fixture"},
        {
            "type": "image_url",
            "image_url": {"url": "https://image.example/fixture.png"},
        },
        {
            "type": "video_url",
            "video_url": {"url": "https://video.example/fixture.mp4"},
        },
    ]
    llm.build_llm().invoke([HumanMessage(content=content)])
    assert requests[0][1]["messages"][0]["content"] == content


def test_real_sdk_tool_call_and_async_stream(requests):
    model = llm.build_llm()
    tool = {
        "type": "function",
        "function": {
            "name": "inspect_text",
            "description": "Inspect text only.",
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        },
    }
    response = model.bind_tools([tool]).invoke("hello")
    assert response.tool_calls[0]["name"] == "inspect_text"
    assert response.tool_calls[0]["args"] == {"text": "hello"}
    assert response.additional_kwargs["reasoning_content"] == "offline reasoning"
    model.invoke(
        [
            HumanMessage(content="hello"),
            response,
            ToolMessage(content="inspected", tool_call_id="call_offline"),
        ]
    )
    assistant = requests[1][1]["messages"][1]
    assert assistant["reasoning_content"] == "offline reasoning"
    assert assistant["tool_calls"][0]["id"] == "call_offline"

    async def collect():
        return [chunk async for chunk in model.astream("hello")]

    chunks = asyncio.run(collect())
    assert "".join(chunk.content for chunk in chunks) == "offline"
    assert (
        "".join(
            chunk.additional_kwargs.get("reasoning_content", "") for chunk in chunks
        )
        == "offline thought"
    )
    assert requests[2][1]["stream"] is True
    assert all(body["model"] == FLASH for _, body in requests)


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_settings_picker_is_flash_first_without_live_discovery(endpoint):
    provider = _provider()
    assert provider.default_model == FLASH
    result = asyncio.run(_list_provider_models(provider, base_url=endpoint, api_key=""))
    assert result.models == MODELS
    assert result.source == "default"


def test_custom_gateway_model_discovery_is_preserved(monkeypatch):
    def respond(request):
        assert str(request.url) == "https://gateway.example/v1/models"
        return httpx.Response(
            200, json={"data": [{"id": "saved-custom-model"}, {"id": "MiniMax-M2.7"}]}
        )

    client_type = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: client_type(transport=httpx.MockTransport(respond), **kwargs),
    )
    result = asyncio.run(
        _list_provider_models(
            _provider(), base_url="https://gateway.example/v1", api_key="test-key"
        )
    )
    assert "saved-custom-model" in result.models
    assert "MiniMax-M2.7" in result.models
    assert result.source == "provider"


@pytest.mark.parametrize(
    "provider_name,endpoint,prefix,flash",
    [
        (
            "openrouter",
            "https://openrouter.ai/api/v1",
            "minimax/minimax-",
            "minimax/minimax-m3.1-flash:free",
        ),
        (
            "opencode",
            "https://opencode.ai/zen/v1",
            "minimax-",
            "minimax-m3.1-flash-free",
        ),
    ],
)
@pytest.mark.parametrize("custom_endpoint", [False, True])
def test_gateway_picker_preserves_other_models_and_custom_endpoints(
    monkeypatch, provider_name, endpoint, prefix, flash, custom_endpoint
):
    m3, legacy, media = prefix + "m3", prefix + "m2.7", prefix + "music"
    paid_flash = prefix + "m3.1-flash"
    future = prefix + "m4"
    available = [m3, legacy, flash, paid_flash, future, "other/text-model", media]
    client_type = httpx.AsyncClient
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200, json={"data": [{"id": m} for m in available]}
        )
    )
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: client_type(transport=transport, **kwargs),
    )
    result = asyncio.run(
        _list_provider_models(
            _provider(provider_name),
            base_url="https://custom.example/v1" if custom_endpoint else endpoint,
            api_key="test-key",
        )
    )
    assert "other/text-model" in result.models and media in result.models
    assert paid_flash in result.models and future in result.models
    if custom_endpoint:
        assert legacy in result.models
    else:
        assert legacy in result.models
        assert result.models.index(flash) < result.models.index(m3)


@pytest.mark.parametrize(
    "provider_name,endpoint,m3,flash",
    [
        (
            "openrouter",
            "https://openrouter.ai/api/v1",
            "minimax/minimax-m3",
            "minimax/minimax-m3.1-flash:free",
        ),
        (
            "opencode",
            "https://opencode.ai/zen/go/v1",
            "minimax-m3",
            "minimax-m3.1-flash-free",
        ),
    ],
)
def test_gateway_picker_does_not_invent_flash_availability(
    monkeypatch, provider_name, endpoint, m3, flash
):
    client_type = httpx.AsyncClient
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"data": [{"id": m3}]})
    )
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: client_type(transport=transport, **kwargs),
    )
    result = asyncio.run(
        _list_provider_models(
            _provider(provider_name), base_url=endpoint, api_key="test-key"
        )
    )
    assert m3 in result.models
    assert flash not in result.models


@pytest.mark.parametrize(
    "provider_name,endpoint,model_name",
    [
        (
            "openrouter",
            "https://openrouter.ai/api/v1",
            "minimax/minimax-m3.1-flash:free",
        ),
        ("opencode", "https://opencode.ai/zen/v1", "minimax-m3.1-flash-free"),
    ],
)
def test_gateway_real_sdk_preserves_route_id(
    requests, monkeypatch, provider_name, endpoint, model_name
):
    provider = _provider(provider_name)
    monkeypatch.setenv("LANGCHAIN_PROVIDER", provider_name)
    monkeypatch.setenv("LANGCHAIN_MODEL_NAME", model_name)
    monkeypatch.setenv(provider.api_key_env, "test-key")
    monkeypatch.setenv(provider.base_url_env, endpoint)
    llm.build_llm().invoke("hello")
    assert str(requests[0][0].url) == endpoint + "/chat/completions"
    assert requests[0][1]["model"] == model_name
