"""Regression tests for provider-scoped HTTP header isolation."""

from __future__ import annotations

from src.providers import llm as _provider_adapters
from src.providers import settings as _provider_configuration

import asyncio
import json
import os
from unittest.mock import patch

import httpx
import pytest

from src.config.accessor import reset_env_config
from src.providers.llm import ChatOpenAIWithReasoning, build_llm, provider_diagnostics


def _stream_response(text: str) -> httpx.Response:
    """Build a minimal OpenAI-compatible SSE response."""
    chunk = {
        "id": "chatcmpl-header-test",
        "object": "chat.completion.chunk",
        "created": 0,
        "model": "deepseek/deepseek-v4-pro",
        "choices": [
            {
                "index": 0,
                "delta": {"content": text},
                "finish_reason": "stop",
            }
        ],
    }
    body = (f"data: {json.dumps(chunk, ensure_ascii=False)}\n\ndata: [DONE]\n\n").encode("utf-8")
    return httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        content=body,
    )


@pytest.mark.skipif(ChatOpenAIWithReasoning is None, reason="langchain-openai is not installed")
@pytest.mark.parametrize("provider,with_explicit_headers", [
    ("openai", False), ("openrouter", False), ("openrouter", True), ("kimi-coding", True),
], ids=["direct-openai", "relay-default-headers", "relay-explicit-headers", "kimi-explicit-headers"])
@pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])
def test_stream_headers_stay_provider_scoped(provider, with_explicit_headers, asynchronous):
    """Direct OpenAI keeps its headers; relays isolate them on both stream paths."""
    seen = []

    def handler(request):
        seen.append(request)
        return _stream_response("异步 résultat")

    direct = provider == "openai"
    env = {
        "OPENAI_CUSTOM_HEADERS": "X-Debug: keep-me" if direct else (
            f"X-Debug: {'x' * 3069}à\nauthorization: stale-à\n"
            "X-Other: ambient\nX-Explicit: ambient-value\nx-case: ambient-à\nuser-agent: ambient"
        ),
        "OPENAI_ORG_ID": "org-test" if direct else "org-à",
        "OPENAI_PROJECT_ID": "project-test" if direct else "project-à",
    }
    explicit = {
        "X-Explicit": "provider-value", "X-Case": "provider-value", "User-Agent": "provider-value",
    } if with_explicit_headers else None

    async def scenario():
        with httpx.Client(transport=httpx.MockTransport(handler)) as sync_client:
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as async_client:
                adapter = ChatOpenAIWithReasoning(
                    model="header-test", api_key="sk-test", base_url="https://relay.invalid/v1",
                    default_headers=explicit, http_client=sync_client, http_async_client=async_client,
                    vibe_provider=provider, vibe_api_key="sk-test",
                )
                if asynchronous:
                    chunks = [chunk async for chunk in adapter.astream("异步 entrée")]
                else:
                    chunks = list(adapter.stream("异步 entrée"))
                return "".join(chunk.content for chunk in chunks), adapter

    with patch.dict(os.environ, env, clear=True):
        result, adapter = asyncio.run(scenario())

    assert result == "异步 résultat"
    assert len(seen) == 1
    assert "异步 entrée" in seen[0].content.decode("utf-8")
    headers = seen[0].headers
    assert headers.get_list("authorization") == ["Bearer sk-test"]
    if direct:
        assert headers["x-debug"] == "keep-me"
        assert headers["openai-organization"] == "org-test"
        assert headers["openai-project"] == "project-test"
    else:
        assert not {"x-debug", "x-other", "openai-organization", "openai-project"}.intersection(headers)
        # SDK 2.x merges by spelling; 3.x applies Omit case-insensitively.
        # Pin both the wire and override ordering so either SDK stays covered.
        overrides = adapter._provider_scoped_extra_headers()
        assert type(overrides["user-agent"]).__name__ == "Omit"
        if explicit:
            for name in explicit:
                assert headers.get_list(name) == ["provider-value"]
            assert overrides["User-Agent"] == "provider-value"
            names = list(overrides)
            assert names.index("User-Agent") > names.index("user-agent")
        else:
            assert not {"x-explicit", "x-case"}.intersection(headers)
            assert headers.get("user-agent") != "ambient"


def test_build_rejects_non_ascii_openrouter_api_key_before_transport() -> None:
    """A malformed Bearer credential should name its setting without leaking it."""

    env = {
        "LANGCHAIN_PROVIDER": "openrouter",
        "LANGCHAIN_MODEL_NAME": "deepseek/deepseek-v4-pro",
        "OPENROUTER_API_KEY": f"{'x' * 3062}à",
        "OPENROUTER_BASE_URL": "https://openrouter.ai/api/v1",
    }
    try:
        with patch.object(_provider_configuration, "_dotenv_loaded", True):
            with patch.dict(os.environ, env, clear=True):
                with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY.*non-ASCII") as excinfo:
                    build_llm()
    finally:
        reset_env_config()

    assert "x" * 20 not in str(excinfo.value)


def test_build_passes_openrouter_credentials_explicitly() -> None:
    """The relay client should retain the selected key for header restoration."""

    captured: dict[str, object] = {}

    class _FakeChatOpenAI:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    env = {
        "LANGCHAIN_PROVIDER": "openrouter",
        "LANGCHAIN_MODEL_NAME": "deepseek/deepseek-v4-pro",
        "OPENROUTER_API_KEY": "sk-or-test",
        "OPENROUTER_BASE_URL": "https://openrouter.ai/api/v1",
    }
    try:
        with patch.object(_provider_configuration, "_dotenv_loaded", True):
            with patch.dict(os.environ, env, clear=True):
                with patch.object(_provider_adapters, "ChatOpenAIWithReasoning", _FakeChatOpenAI):
                    build_llm()
    finally:
        reset_env_config()

    assert captured["api_key"] == "sk-or-test"
    assert captured["base_url"] == "https://openrouter.ai/api/v1"
    assert captured["vibe_provider"] == "openrouter"
    assert captured["vibe_api_key"] == "sk-or-test"


def test_provider_doctor_reports_header_safety_without_values() -> None:
    """Doctor should identify a bad header source while keeping values secret."""

    env = {
        "LANGCHAIN_PROVIDER": "openrouter",
        "LANGCHAIN_MODEL_NAME": "deepseek/deepseek-v4-pro",
        "OPENROUTER_API_KEY": "sk-or-secret-value",
        "OPENROUTER_BASE_URL": "https://openrouter.ai/api/v1",
        "OPENAI_CUSTOM_HEADERS": "X-Debug: private-à",
    }
    try:
        with patch.object(_provider_configuration, "_dotenv_loaded", True):
            with patch.dict(os.environ, env, clear=True):
                diagnostics = provider_diagnostics()
    finally:
        reset_env_config()

    header_env = diagnostics["http_header_env"]
    assert header_env["authorization"] == {
        "source": "OPENROUTER_API_KEY",
        "set": True,
        "length": len("sk-or-secret-value"),
        "ascii_only": True,
    }
    assert header_env["ambient_openai"]["OPENAI_CUSTOM_HEADERS"] == {
        "set": True,
        "length": len("X-Debug: private-à"),
        "ascii_only": False,
    }
    encoded = json.dumps(diagnostics, ensure_ascii=False)
    assert "sk-or-secret-value" not in encoded
    assert "private-à" not in encoded


def _sse_usage_body(text: str, output_tokens: int) -> bytes:
    """SSE payload whose final chunk carries real usage (stream include_usage)."""
    text_chunk = {
        "id": "chatcmpl-usage-test",
        "object": "chat.completion.chunk",
        "created": 0,
        "model": "gpt-usage-test",
        "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}],
    }
    usage_chunk = {
        "id": "chatcmpl-usage-test",
        "object": "chat.completion.chunk",
        "created": 0,
        "model": "gpt-usage-test",
        "choices": [],
        "usage": {
            "prompt_tokens": 28,
            "completion_tokens": output_tokens,
            "total_tokens": 28 + output_tokens,
        },
    }
    return (f"data: {json.dumps(text_chunk)}\n\ndata: {json.dumps(usage_chunk)}\n\ndata: [DONE]\n\n").encode("utf-8")


@pytest.mark.skipif(
    ChatOpenAIWithReasoning is None,
    reason="langchain-openai is not installed",
)
def test_stream_requests_usage_and_forwards_real_counts() -> None:
    """stream_usage=True must put stream_options on the wire and let the
    accumulated response carry the provider's real token counts (#1224)."""
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.content.decode("utf-8")
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_sse_usage_body("ok", 241),
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        llm = ChatOpenAIWithReasoning(
            model="gpt-usage-test",
            api_key="sk-test",
            base_url="https://api.openai.invalid/v1",
            stream_usage=True,
            http_client=client,
            vibe_provider="openai",
            vibe_api_key="sk-test",
        )
        accumulated = None
        for chunk in llm.stream("hello"):
            accumulated = chunk if accumulated is None else accumulated + chunk

    assert '"stream_options":{"include_usage":true}' in str(seen["body"])
    usage = getattr(accumulated, "usage_metadata", None)
    assert usage is not None
    assert usage["input_tokens"] == 28
    assert usage["output_tokens"] == 241


@pytest.mark.skipif(
    ChatOpenAIWithReasoning is None,
    reason="langchain-openai is not installed",
)
def test_stream_usage_rejection_self_heals_and_is_remembered() -> None:
    """An endpoint that 400s on stream_options gets one stateless retry, and
    later calls skip the doomed attempt entirely."""

    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode("utf-8")
        calls.append(body)
        if '"stream_options"' in body:
            return httpx.Response(
                400,
                json={"error": {"message": "Unknown parameter: 'stream_options' is unsupported"}},
            )
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_sse_usage_body("ok", 3),
        )

    model = "gpt-usage-reject-test"
    _provider_adapters._STREAM_USAGE_UNSUPPORTED.clear()
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        llm = ChatOpenAIWithReasoning(
            model=model,
            api_key="sk-test",
            base_url="https://api.openai.invalid/v1",
            stream_usage=True,
            http_client=client,
            vibe_provider="openai",
            vibe_api_key="sk-test",
        )
        first = "".join(chunk.content for chunk in llm.stream("hello"))
        second = "".join(chunk.content for chunk in llm.stream("hello again"))

    assert first == "ok"
    assert second == "ok"
    # First call: one rejected attempt plus the stateless retry. Second call:
    # straight to no-usage, no wasted 400.
    assert len(calls) == 3
    assert '"stream_options"' in calls[0]
    assert '"stream_options"' not in calls[1]
    assert '"stream_options"' not in calls[2]
    _provider_adapters._STREAM_USAGE_UNSUPPORTED.clear()


def test_stream_usage_unsupported_error_detection() -> None:

    assert _provider_adapters._is_stream_usage_unsupported_error(ValueError("Unknown parameter: 'stream_options' is unsupported"))
    assert _provider_adapters._is_stream_usage_unsupported_error(
        ValueError("include_usage is not a valid field for this endpoint")
    )
    assert not _provider_adapters._is_stream_usage_unsupported_error(ValueError("model overloaded, retry later"))
    assert not _provider_adapters._is_stream_usage_unsupported_error(ValueError("temperature is unsupported"))
