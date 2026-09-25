"""Regression tests for provider-scoped HTTP header isolation."""

from __future__ import annotations

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
        "model": "deepseek/deepseek-v4.1-flash",
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


@pytest.mark.skipif(
    ChatOpenAIWithReasoning is None,
    reason="langchain-openai is not installed",
)
def test_openrouter_ignores_non_ascii_ambient_openai_headers() -> None:
    """OpenRouter must not inherit OpenAI-only headers from the host process."""
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["headers"] = dict(request.headers)
        seen["body"] = request.content.decode("utf-8")
        return _stream_response("résultat")

    env = {
        "OPENAI_CUSTOM_HEADERS": (
            f"X-Debug: {'x' * 3069}à\nauthorization: stale-à\nX-Explicit: ambient-value\nx-case: ambient-à"
        ),
        "OPENAI_ORG_ID": "org-à",
        "OPENAI_PROJECT_ID": "project-à",
    }
    with patch.dict(os.environ, env, clear=True):
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            llm = ChatOpenAIWithReasoning(
                model="deepseek/deepseek-v4.1-flash",
                api_key="sk-or-test",
                base_url="https://openrouter.invalid/api/v1",
                default_headers={
                    "X-Explicit": "provider-value",
                    "X-Case": "provider-value",
                },
                http_client=client,
                vibe_provider="openrouter",
                vibe_api_key="sk-or-test",
            )
            result = "".join(chunk.content for chunk in llm.stream("entrée"))

    headers = seen["headers"]
    assert isinstance(headers, dict)
    assert result == "résultat"
    assert "entrée" in str(seen["body"])
    assert "x-debug" not in headers
    assert "openai-organization" not in headers
    assert "openai-project" not in headers
    assert headers["authorization"] == "Bearer sk-or-test"
    assert headers["x-explicit"] == "provider-value"
    assert headers["x-case"] == "provider-value"


@pytest.mark.skipif(
    ChatOpenAIWithReasoning is None,
    reason="langchain-openai is not installed",
)
def test_direct_openai_preserves_ambient_headers() -> None:
    """Header isolation must not change explicit direct-OpenAI behavior."""
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.headers))
        return _stream_response("ok")

    env = {
        "OPENAI_CUSTOM_HEADERS": "X-Debug: keep-me",
        "OPENAI_ORG_ID": "org-test",
        "OPENAI_PROJECT_ID": "project-test",
    }
    with patch.dict(os.environ, env, clear=True):
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            llm = ChatOpenAIWithReasoning(
                model="gpt-test",
                api_key="sk-test",
                base_url="https://api.openai.invalid/v1",
                http_client=client,
                vibe_provider="openai",
                vibe_api_key="sk-test",
            )
            list(llm.stream("hello"))

    assert seen["x-debug"] == "keep-me"
    assert seen["openai-organization"] == "org-test"
    assert seen["openai-project"] == "project-test"


@pytest.mark.skipif(
    ChatOpenAIWithReasoning is None,
    reason="langchain-openai is not installed",
)
def test_openrouter_async_stream_ignores_non_ascii_ambient_headers() -> None:
    """The async provider path used by API sessions must apply the same isolation."""
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.headers))
        return _stream_response("异步 résultat")

    async def scenario() -> str:
        with patch.dict(
            os.environ,
            {"OPENAI_CUSTOM_HEADERS": "X-Bad: ambient-à"},
            clear=True,
        ):
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                llm = ChatOpenAIWithReasoning(
                    model="deepseek/deepseek-v4.1-flash",
                    api_key="sk-or-test",
                    base_url="https://openrouter.invalid/api/v1",
                    http_async_client=client,
                    vibe_provider="openrouter",
                    vibe_api_key="sk-or-test",
                )
                parts: list[str] = []
                async for chunk in llm.astream("异步 entrée"):
                    parts.append(str(chunk.content))
                return "".join(parts)

    assert asyncio.run(scenario()) == "异步 résultat"
    assert "x-bad" not in seen
    assert seen["authorization"] == "Bearer sk-or-test"


@pytest.mark.skipif(
    ChatOpenAIWithReasoning is None,
    reason="langchain-openai is not installed",
)
def test_an_explicit_header_wins_over_its_ambient_twin_on_the_wire() -> None:
    """One header, the explicit value, whatever spelling the ambient env used (#1573).

    openai 2.53 (and 3.19.0) merge OPENAI_CUSTOM_HEADERS under default_headers
    with a plain dict (an ambient ``user-agent`` beside an explicit ``User-Agent``
    sent both); openai 3.19.2 merges case-insensitively and applies a per-request
    omit the same way (an omit for the ambient spelling stripped the explicit
    header). The repo's lock pins 2.53 and CI installs the newest, so both must
    hold.
    """
    seen: list[httpx.Headers] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers)
        return _stream_response("ok")

    env = {"OPENAI_CUSTOM_HEADERS": "user-agent: ambient\nX-Other: ambient"}
    with patch.dict(os.environ, env, clear=True):
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            llm = ChatOpenAIWithReasoning(
                model="kimi-for-coding",
                api_key="sk-test",
                base_url="https://relay.invalid/v1",
                default_headers={"User-Agent": "provider-value"},
                http_client=client,
                vibe_provider="kimi-coding",
                vibe_api_key="sk-test",
            )
            list(llm.stream("hello"))

    assert seen[0].get_list("user-agent") == ["provider-value"]
    assert "x-other" not in seen[0]
    # The wire above is checked against whichever openai CI installed; the
    # overrides are checked here so both merge styles are pinned on any version:
    # the ambient spelling is omitted (2.x), and the explicit value comes after
    # that omit (3.x drops every spelling of a name when it meets the omit).
    overrides = llm._provider_scoped_extra_headers()
    names = list(overrides)
    assert type(overrides["user-agent"]).__name__ == "Omit"
    assert overrides["User-Agent"] == "provider-value"
    assert names.index("User-Agent") > names.index("user-agent")


def test_build_rejects_non_ascii_openrouter_api_key_before_transport() -> None:
    """A malformed Bearer credential should name its setting without leaking it."""
    import src.providers.llm as llm_mod

    env = {
        "LANGCHAIN_PROVIDER": "openrouter",
        "LANGCHAIN_MODEL_NAME": "deepseek/deepseek-v4.1-flash",
        "OPENROUTER_API_KEY": f"{'x' * 3062}à",
        "OPENROUTER_BASE_URL": "https://openrouter.ai/api/v1",
    }
    try:
        with patch.object(llm_mod, "_dotenv_loaded", True):
            with patch.dict(os.environ, env, clear=True):
                with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY.*non-ASCII") as excinfo:
                    build_llm()
    finally:
        reset_env_config()

    assert "x" * 20 not in str(excinfo.value)


def test_build_passes_openrouter_credentials_explicitly() -> None:
    """The relay client should retain the selected key for header restoration."""
    import src.providers.llm as llm_mod

    captured: dict[str, object] = {}

    class _FakeChatOpenAI:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    env = {
        "LANGCHAIN_PROVIDER": "openrouter",
        "LANGCHAIN_MODEL_NAME": "deepseek/deepseek-v4.1-flash",
        "OPENROUTER_API_KEY": "sk-or-test",
        "OPENROUTER_BASE_URL": "https://openrouter.ai/api/v1",
    }
    try:
        with patch.object(llm_mod, "_dotenv_loaded", True):
            with patch.dict(os.environ, env, clear=True):
                with patch.object(llm_mod, "ChatOpenAIWithReasoning", _FakeChatOpenAI):
                    build_llm()
    finally:
        reset_env_config()

    assert captured["api_key"] == "sk-or-test"
    assert captured["base_url"] == "https://openrouter.ai/api/v1"
    assert captured["vibe_provider"] == "openrouter"
    assert captured["vibe_api_key"] == "sk-or-test"


def test_provider_doctor_reports_header_safety_without_values() -> None:
    """Doctor should identify a bad header source while keeping values secret."""
    import src.providers.llm as llm_mod

    env = {
        "LANGCHAIN_PROVIDER": "openrouter",
        "LANGCHAIN_MODEL_NAME": "deepseek/deepseek-v4.1-flash",
        "OPENROUTER_API_KEY": "sk-or-secret-value",
        "OPENROUTER_BASE_URL": "https://openrouter.ai/api/v1",
        "OPENAI_CUSTOM_HEADERS": "X-Debug: private-à",
    }
    try:
        with patch.object(llm_mod, "_dotenv_loaded", True):
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
    import src.providers.llm as llm_mod

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
    llm_mod._STREAM_USAGE_UNSUPPORTED.discard(model)
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
    llm_mod._STREAM_USAGE_UNSUPPORTED.discard(model)


def test_stream_usage_unsupported_error_detection() -> None:
    import src.providers.llm as llm_mod

    assert llm_mod._is_stream_usage_unsupported_error(ValueError("Unknown parameter: 'stream_options' is unsupported"))
    assert llm_mod._is_stream_usage_unsupported_error(
        ValueError("include_usage is not a valid field for this endpoint")
    )
    assert not llm_mod._is_stream_usage_unsupported_error(ValueError("model overloaded, retry later"))
    assert not llm_mod._is_stream_usage_unsupported_error(ValueError("temperature is unsupported"))
