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
                model="deepseek/deepseek-v4-pro",
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
                    model="deepseek/deepseek-v4-pro",
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


def test_build_rejects_non_ascii_openrouter_api_key_before_transport() -> None:
    """A malformed Bearer credential should name its setting without leaking it."""
    import src.providers.llm as llm_mod

    env = {
        "LANGCHAIN_PROVIDER": "openrouter",
        "LANGCHAIN_MODEL_NAME": "deepseek/deepseek-v4-pro",
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
        "LANGCHAIN_MODEL_NAME": "deepseek/deepseek-v4-pro",
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
        "LANGCHAIN_MODEL_NAME": "deepseek/deepseek-v4-pro",
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
