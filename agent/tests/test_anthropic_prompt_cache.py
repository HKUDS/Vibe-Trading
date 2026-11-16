"""Prompt caching for the Anthropic provider (flag, payload, usage)."""

from __future__ import annotations

from tests.provider_helpers import chat_with_adapter

from src.providers import settings as _provider_configuration

import os
from typing import Any
from unittest.mock import patch

import pytest

from src.agent.loop import _normalize_llm_usage, _record_llm_usage
from src.config.accessor import get_env_config, reset_env_config
from src.providers.chat import ChatLLM, prompt_cache_messages


@pytest.fixture(autouse=True)
def _fresh_env_config(monkeypatch):
    # _dotenv_loaded suppresses .env loading for the tests that build a real
    # adapter; monkeypatch restores it so the flag does not leak to later tests.
    monkeypatch.setattr(_provider_configuration, "_dotenv_loaded", True)
    reset_env_config()
    yield
    reset_env_config()


def test_prompt_cache_flag_defaults_on() -> None:
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("VIBE_TRADING_ANTHROPIC_PROMPT_CACHE", None)
        reset_env_config()
        assert get_env_config().llm.vibe_trading_anthropic_prompt_cache is True


def test_prompt_cache_flag_parses_off() -> None:
    with patch.dict(os.environ, {"VIBE_TRADING_ANTHROPIC_PROMPT_CACHE": "0"}, clear=False):
        reset_env_config()
        assert get_env_config().llm.vibe_trading_anthropic_prompt_cache is False


_ANTHROPIC_ENV = {
    "LANGCHAIN_PROVIDER": "anthropic",
    "LANGCHAIN_MODEL_NAME": "claude-sonnet-5",
    "LANGCHAIN_TEMPERATURE": "0",
    "LANGCHAIN_REASONING_EFFORT": "medium",
    "ANTHROPIC_API_KEY": "test-key",
    "ANTHROPIC_BASE_URL": "https://api.anthropic.com",
}


def test_prompt_cache_messages_marks_leading_system_string() -> None:
    messages = [{"role": "system", "content": "stable prefix"}, {"role": "user", "content": "hi"}]
    out = prompt_cache_messages(messages)
    assert out[0] == {
        "role": "system",
        "content": [{"type": "text", "text": "stable prefix", "cache_control": {"type": "ephemeral"}}],
    }
    assert out[1] is messages[1]
    assert messages[0] == {"role": "system", "content": "stable prefix"}


def test_prompt_cache_messages_leaves_other_shapes_alone() -> None:
    no_system = [{"role": "user", "content": "hi"}]
    assert prompt_cache_messages(no_system) is no_system
    blocks = [{"role": "system", "content": [{"type": "text", "text": "x"}]}]
    assert prompt_cache_messages(blocks) is blocks
    assert prompt_cache_messages([]) == []


class _FakeChunk:
    """Minimal AIMessageChunk stand-in, same shape tests/test_chat_llm_streaming.py uses."""

    def __init__(self, content: str = "", finish_reason: str = "stop") -> None:
        self.content = content
        self.tool_calls: list[dict[str, Any]] = []
        self.additional_kwargs: dict[str, Any] = {}
        self.response_metadata = {"finish_reason": finish_reason}
        self.usage_metadata = None

    def __add__(self, other: "_FakeChunk") -> "_FakeChunk":
        return _FakeChunk(
            content=f"{self.content}{other.content}",
            finish_reason=other.response_metadata.get("finish_reason", "stop"),
        )


class _RecordingLLM:
    """Records the messages and call kwargs each send path handed to the adapter."""

    def __init__(self) -> None:
        self.calls: list[tuple[Any, dict[str, Any]]] = []

    def bind_tools(self, tools):
        self.tools = tools
        return self

    def invoke(self, messages, config=None, **kwargs):
        self.calls.append((messages, kwargs))
        return _FakeChunk(content="ok")

    def stream(self, messages, config=None, **kwargs):
        self.calls.append((messages, kwargs))
        yield _FakeChunk(content="ok")


class _FakeAnthropicLLM(_RecordingLLM):
    _llm_type = "anthropic-chat"


class _FakeOtherLLM(_RecordingLLM):
    pass


class _FakeAnthropicNoStreamLLM(_RecordingLLM):
    """Anthropic adapter whose stream yields nothing, forcing the invoke fallback."""

    _llm_type = "anthropic-chat"

    def stream(self, messages, config=None, **kwargs):
        self.calls.append((messages, kwargs))
        return iter(())


def _chat_client(fake):
    return chat_with_adapter(fake, model="m")


_CACHE_KWARGS = {"cache_control": {"type": "ephemeral"}}


def test_prompt_cache_request_marks_only_anthropic_calls_with_a_system_prompt() -> None:
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
    no_system = [{"role": "user", "content": "u"}]
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("VIBE_TRADING_ANTHROPIC_PROMPT_CACHE", None)
        reset_env_config()
        prepared, call_kwargs = _chat_client(_FakeAnthropicLLM())._prompt_cache_request(msgs)
        assert prepared[0]["content"][0]["cache_control"] == {"type": "ephemeral"}
        assert call_kwargs == _CACHE_KWARGS
        # A one-shot call (compaction, vision) has no system prompt: sent unchanged.
        assert _chat_client(_FakeAnthropicLLM())._prompt_cache_request(no_system) == (no_system, {})
        assert _chat_client(_FakeOtherLLM())._prompt_cache_request(msgs) == (msgs, {})
    with patch.dict(os.environ, {"VIBE_TRADING_ANTHROPIC_PROMPT_CACHE": "0"}, clear=False):
        reset_env_config()
        assert _chat_client(_FakeAnthropicLLM())._prompt_cache_request(msgs) == (msgs, {})


def test_chat_and_stream_chat_send_the_marked_request() -> None:
    """The seam: both send paths must apply the gate, not just the pure helper."""
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("VIBE_TRADING_ANTHROPIC_PROMPT_CACHE", None)
        reset_env_config()
        for send in ("chat", "stream_chat"):
            msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
            fake = _FakeAnthropicLLM()
            getattr(_chat_client(fake), send)(msgs)
            sent, kwargs = fake.calls[0]
            assert sent[0]["content"] == [
                {"type": "text", "text": "s", "cache_control": {"type": "ephemeral"}}
            ]
            assert sent[1] is msgs[1]
            assert kwargs == _CACHE_KWARGS
            # The caller's list is never mutated.
            assert msgs[0] == {"role": "system", "content": "s"}

            other = _FakeOtherLLM()
            getattr(_chat_client(other), send)(msgs)
            assert other.calls[0] == (msgs, {})


def test_stream_chat_no_chunk_fallback_keeps_cache_kwargs(caplog) -> None:
    """The no-chunk invoke fallback must send the same cache markers as chat()."""
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("VIBE_TRADING_ANTHROPIC_PROMPT_CACHE", None)
        reset_env_config()
        msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
        fake = _FakeAnthropicNoStreamLLM()
        with caplog.at_level("WARNING"):
            _chat_client(fake).stream_chat(msgs)
        sent, kwargs = fake.calls[-1]
        assert sent[0]["content"] == [
            {"type": "text", "text": "s", "cache_control": {"type": "ephemeral"}}
        ]
        assert kwargs == _CACHE_KWARGS


def test_normalize_usage_keeps_cache_details() -> None:
    usage = {
        "input_tokens": 1200,
        "output_tokens": 30,
        "total_tokens": 1230,
        "input_token_details": {"cache_read": 70000, "cache_creation": 900},
    }
    assert _normalize_llm_usage(usage) == {
        "input_tokens": 1200,
        "output_tokens": 30,
        "total_tokens": 1230,
        "cache_read_tokens": 70000,
        "cache_creation_tokens": 900,
    }


def test_cache_creation_survives_langchain_ttl_breakdown() -> None:
    pytest.importorskip("langchain_anthropic")
    from anthropic.types import Usage
    from langchain_anthropic.chat_models import _create_usage_metadata

    usage = Usage(
        input_tokens=500,
        output_tokens=12,
        cache_read_input_tokens=0,
        cache_creation_input_tokens=46404,
        cache_creation={"ephemeral_5m_input_tokens": 46404, "ephemeral_1h_input_tokens": 0},
    )
    normalized = _normalize_llm_usage(_create_usage_metadata(usage))
    assert normalized["cache_creation_tokens"] == 46404
    assert normalized["cache_read_tokens"] == 0


def test_normalize_usage_without_details_is_unchanged() -> None:
    assert _normalize_llm_usage({"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}) == {
        "input_tokens": 10,
        "output_tokens": 5,
        "total_tokens": 15,
    }
    assert _normalize_llm_usage({"input_tokens": 1, "input_token_details": {"cache_read": None}}) == {
        "input_tokens": 1,
        "output_tokens": 0,
        "total_tokens": 1,
    }


def test_record_usage_accumulates_cache_totals(tmp_path) -> None:
    summary = {"provider": "anthropic", "model": "m", "totals": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "calls": 0}, "per_iteration": []}
    details = {"cache_read": 70000, "cache_creation": 0}
    _record_llm_usage(tmp_path, summary, {"input_tokens": 100, "output_tokens": 1, "input_token_details": {"cache_read": 0, "cache_creation": 70000}}, 1)
    _record_llm_usage(tmp_path, summary, {"input_tokens": 100, "output_tokens": 1, "input_token_details": details}, 2)
    assert summary["totals"]["cache_read_tokens"] == 70000
    assert summary["totals"]["cache_creation_tokens"] == 70000
    assert summary["totals"]["calls"] == 2
    assert summary["per_iteration"][1]["cache_read_tokens"] == 70000
    assert (tmp_path / "llm_usage.json").exists()


def test_real_adapter_request_payload_carries_both_breakpoints() -> None:
    pytest.importorskip("langchain_anthropic")
    with patch.dict(os.environ, _ANTHROPIC_ENV, clear=True):
        reset_env_config()
        client = ChatLLM()
        messages = [{"role": "system", "content": "S" * 5000}, {"role": "user", "content": "hi"}]
        tools = [{"type": "function", "function": {"name": "read_file", "description": "d", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}}]
        bound = client._llm.bind_tools(tools)
        prepared, call_kwargs = client._prompt_cache_request(messages)
        payload = bound._get_request_payload(prepared, **bound.kwargs, **call_kwargs)
    assert payload["cache_control"] == {"type": "ephemeral"}
    assert payload["system"] == [{"type": "text", "text": "S" * 5000, "cache_control": {"type": "ephemeral"}}]
    assert [t["name"] for t in payload["tools"]] == ["read_file"]
    assert payload["messages"] == [{"role": "user", "content": "hi"}]
    assert payload["output_config"] == {"effort": "medium"}
    assert payload.get("temperature") is None


def test_real_adapter_payload_has_no_cache_markers_when_flag_off() -> None:
    pytest.importorskip("langchain_anthropic")
    with patch.dict(os.environ, {**_ANTHROPIC_ENV, "VIBE_TRADING_ANTHROPIC_PROMPT_CACHE": "0"}, clear=True):
        reset_env_config()
        client = ChatLLM()
        messages = [{"role": "system", "content": "S" * 5000}, {"role": "user", "content": "hi"}]
        prepared, call_kwargs = client._prompt_cache_request(messages)
        payload = client._llm._get_request_payload(prepared, **call_kwargs)
    assert "cache_control" not in payload
    assert payload["system"] == "S" * 5000


def test_real_adapter_payload_has_no_cache_markers_without_a_system_prompt() -> None:
    """One-shot calls (compaction, vision) carry no system prompt and no markers."""
    pytest.importorskip("langchain_anthropic")
    with patch.dict(os.environ, _ANTHROPIC_ENV, clear=True):
        reset_env_config()
        client = ChatLLM()
        messages = [{"role": "user", "content": "summarize " + "x" * 5000}]
        prepared, call_kwargs = client._prompt_cache_request(messages)
        payload = client._llm._get_request_payload(prepared, **call_kwargs)
    assert "cache_control" not in payload
    assert payload.get("system") is None
