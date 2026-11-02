"""LLMTR provider registration and OpenAI-compatible request contract."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import patch

import httpx
import pytest

import src.providers.llm as llm_mod
from src.providers.capabilities import get_llm_credentials, get_provider_capabilities
from src.providers.llm import build_llm, uses_responses_api

_PROVIDERS_JSON = Path(__file__).resolve().parents[1] / "src" / "providers" / "llm_providers.json"
_DEFAULT_MODEL = "qwen/qwen3.8-27b-free"
_PREFIXED_MODEL = "llmtr/qwen3-8-27b"
_BASE_URL = "https://llmtr.com/v1"


@pytest.fixture(autouse=True)
def _pin_dotenv_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep build_llm from reading a developer's real provider configuration."""
    monkeypatch.setattr(llm_mod, "_dotenv_loaded", True)


def test_catalog_lists_llmtr_models_and_credentials() -> None:
    catalog = {item["name"]: item for item in json.loads(_PROVIDERS_JSON.read_text(encoding="utf-8"))}

    entry = catalog["llmtr"]
    assert entry["label"] == "LLMTR"
    assert entry["api_key_env"] == "LLMTR_API_KEY"
    assert entry["base_url_env"] == "LLMTR_BASE_URL"
    assert entry["default_model"] == _DEFAULT_MODEL
    assert entry["model_options"] == [_DEFAULT_MODEL, _PREFIXED_MODEL]
    assert entry["default_base_url"] == _BASE_URL
    assert entry["api_key_required"] is True


def test_capabilities_use_generic_chat_without_reasoning_effort() -> None:
    caps = get_provider_capabilities("llmtr", _PREFIXED_MODEL)

    assert caps.name == "llmtr"
    assert (caps.api_key_env, caps.base_url_env) == ("LLMTR_API_KEY", "LLMTR_BASE_URL")
    assert caps.capture_reasoning is True
    assert caps.top_level_reasoning_effort is False
    assert caps.openrouter_reasoning_body is False
    assert uses_responses_api("llmtr", True) is False


def test_credentials_use_the_llmtr_endpoint_and_preserve_model_id() -> None:
    env = {
        "LLMTR_API_KEY": "sk-llmtr-test",
        "LANGCHAIN_PROVIDER": "llmtr",
        "LANGCHAIN_MODEL_NAME": _PREFIXED_MODEL,
    }
    with patch.dict(os.environ, env, clear=True):
        creds = get_llm_credentials("llmtr", _PREFIXED_MODEL)

    assert creds == {
        "provider": "llmtr",
        "api_key": "sk-llmtr-test",
        "base_url": _BASE_URL,
        "model": _PREFIXED_MODEL,
    }


def test_swarm_and_both_cli_onboarding_surfaces_include_llmtr() -> None:
    import cli
    from cli.onboard import PROVIDERS
    from src.swarm.models import _PUBLIC_PROVIDERS

    assert "llmtr" in _PUBLIC_PROVIDERS
    onboard = next(provider for provider in PROVIDERS if provider.key == "llmtr")
    legacy = next(item for item in cli._PROVIDER_CHOICES if item["provider"] == "llmtr")
    assert onboard.key_env == legacy["key_env"] == "LLMTR_API_KEY"
    assert onboard.base_env == legacy["base_env"] == "LLMTR_BASE_URL"
    assert onboard.base_url == legacy["base_url"] == _BASE_URL
    assert onboard.default_model == legacy["model"] == _DEFAULT_MODEL
    assert onboard.suggested_models == (_DEFAULT_MODEL, _PREFIXED_MODEL)
    assert onboard.key_prefix is None
    assert legacy["key_prefix"] is None


def _completion_body(model: str) -> dict[str, Any]:
    return {
        "id": "chatcmpl-llmtr-test",
        "object": "chat.completion",
        "created": 0,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "ok"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


@pytest.mark.skipif(llm_mod.ChatOpenAIWithReasoning is None, reason="langchain-openai is not installed")
def test_build_llm_sends_unchanged_model_without_openai_reasoning_fields() -> None:
    """An ambient effort or Responses preference must not change LLMTR's wire contract."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_completion_body(_PREFIXED_MODEL))

    env = {
        "LANGCHAIN_PROVIDER": "llmtr",
        "LANGCHAIN_MODEL_NAME": _PREFIXED_MODEL,
        "LANGCHAIN_REASONING_EFFORT": "high",
        "LANGCHAIN_USE_RESPONSES_API": "true",
        "LLMTR_API_KEY": "sk-llmtr-test",
    }
    real_adapter = llm_mod.ChatOpenAIWithReasoning
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with patch.dict(os.environ, env, clear=True):
            with patch.object(
                llm_mod,
                "ChatOpenAIWithReasoning",
                lambda **kwargs: real_adapter(**kwargs, http_client=client),
            ):
                llm = build_llm()
                assert llm.invoke("hello").content == "ok"

    assert len(requests) == 1
    assert requests[0].url.path == "/v1/chat/completions"
    payload = json.loads(requests[0].content)
    assert payload["model"] == _PREFIXED_MODEL
    assert "reasoning" not in payload
    assert "reasoning_effort" not in payload
