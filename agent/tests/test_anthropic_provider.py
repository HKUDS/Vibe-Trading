"""Tests for the Anthropic Claude provider integration.

Mirrors :mod:`tests.test_openai_codex` for the OAuth-style provider: covers
env mapping, build_llm wiring, content-block normalization, stop_reason
translation, and the LANGCHAIN_REASONING_EFFORT → extended-thinking budget
mapping. No network is touched; the LangChain side is monkey-patched.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from src.providers import llm as llm_mod
from src.providers.llm import (
    _ANTHROPIC_STOP_REASON_MAP,
    _normalize_anthropic_message,
    _sync_provider_env,
    build_llm,
)


DEFAULT_CLAUDE_MODEL = "claude-sonnet-4-6"


# ---------------------------------------------------------------------------
# Provider JSON: anthropic entry shape
# ---------------------------------------------------------------------------


def test_anthropic_provider_listed_in_llm_providers_json() -> None:
    providers_path = Path(__file__).resolve().parents[1] / "src" / "providers" / "llm_providers.json"
    providers = json.loads(providers_path.read_text(encoding="utf-8"))
    entry = next((item for item in providers if item["name"] == "anthropic"), None)

    assert entry is not None, "anthropic provider missing from llm_providers.json"
    assert entry["api_key_env"] == "ANTHROPIC_API_KEY"
    assert entry["base_url_env"] == "ANTHROPIC_BASE_URL"
    assert entry["default_model"] == DEFAULT_CLAUDE_MODEL
    assert entry["api_key_required"] is True


# ---------------------------------------------------------------------------
# _sync_provider_env: Anthropic short-circuit
# ---------------------------------------------------------------------------


class TestAnthropicProviderEnv:
    """The Anthropic short-circuit must NOT project the Anthropic key into
    OPENAI_API_KEY: the standard OpenAI API key path is unrelated, and
    leaking the key there would route it to OpenAI-compatible clients on a
    later provider switch within the same process.
    """

    def _run_sync(self, env: dict[str, str]) -> dict[str, str]:
        llm_mod._dotenv_loaded = True
        clean = {k: v for k, v in os.environ.items() if not k.startswith(
            ("OPENAI_", "LANGCHAIN_", "DEEPSEEK_", "ANTHROPIC_", "GROQ_", "OLLAMA_")
        )}
        clean.update(env)
        with patch.dict(os.environ, clean, clear=True):
            _sync_provider_env()
            return {
                "OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY", ""),
                "OPENAI_API_BASE": os.environ.get("OPENAI_API_BASE", ""),
                "ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY", ""),
                "ANTHROPIC_API_URL": os.environ.get("ANTHROPIC_API_URL", ""),
            }

    def test_anthropic_provider_does_not_leak_api_key_to_openai(self) -> None:
        result = self._run_sync({
            "LANGCHAIN_PROVIDER": "anthropic",
            "ANTHROPIC_API_KEY": "sk-ant-secret",
        })
        assert result["OPENAI_API_KEY"] == ""
        assert result["ANTHROPIC_API_KEY"] == "sk-ant-secret"

    def test_claude_alias_routes_to_anthropic_branch(self) -> None:
        result = self._run_sync({
            "LANGCHAIN_PROVIDER": "claude",
            "ANTHROPIC_API_KEY": "sk-ant-secret",
        })
        # claude is an alias; key still does not leak to OPENAI_API_KEY
        assert result["OPENAI_API_KEY"] == ""

    def test_anthropic_base_url_mirrored_to_anthropic_api_url(self) -> None:
        result = self._run_sync({
            "LANGCHAIN_PROVIDER": "anthropic",
            "ANTHROPIC_API_KEY": "sk-ant-secret",
            "ANTHROPIC_BASE_URL": "https://example.test/anthropic",
        })
        assert result["ANTHROPIC_API_URL"] == "https://example.test/anthropic"


# ---------------------------------------------------------------------------
# build_llm: wiring + error paths
# ---------------------------------------------------------------------------


class _CapturedAnthropic:
    """Stand-in for ChatAnthropicWithReasoning that records kwargs."""

    last_kwargs: dict | None = None

    def __init__(self, **kwargs: object) -> None:
        type(self).last_kwargs = dict(kwargs)


class TestAnthropicBuildLlm:
    def setup_method(self) -> None:
        llm_mod._dotenv_loaded = True
        _CapturedAnthropic.last_kwargs = None

    def test_build_llm_passes_api_key_and_model(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(llm_mod, "ChatAnthropicWithReasoning", _CapturedAnthropic)
        env = {
            "LANGCHAIN_PROVIDER": "anthropic",
            "LANGCHAIN_MODEL_NAME": DEFAULT_CLAUDE_MODEL,
            "ANTHROPIC_API_KEY": "sk-ant-test",
        }
        with patch.dict(os.environ, env, clear=True):
            build_llm()

        assert _CapturedAnthropic.last_kwargs is not None
        assert _CapturedAnthropic.last_kwargs["model"] == DEFAULT_CLAUDE_MODEL
        assert _CapturedAnthropic.last_kwargs["api_key"] == "sk-ant-test"
        # No thinking enabled when LANGCHAIN_REASONING_EFFORT is unset.
        assert "thinking" not in _CapturedAnthropic.last_kwargs
        # Temperature default propagated (no clamping for Anthropic).
        assert _CapturedAnthropic.last_kwargs["temperature"] == 0.0

    def test_build_llm_forwards_optional_base_url_and_max_tokens(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(llm_mod, "ChatAnthropicWithReasoning", _CapturedAnthropic)
        env = {
            "LANGCHAIN_PROVIDER": "anthropic",
            "LANGCHAIN_MODEL_NAME": DEFAULT_CLAUDE_MODEL,
            "ANTHROPIC_API_KEY": "sk-ant-test",
            "ANTHROPIC_BASE_URL": "https://example.test/anthropic",
            "ANTHROPIC_MAX_TOKENS": "8192",
        }
        with patch.dict(os.environ, env, clear=True):
            build_llm()

        assert _CapturedAnthropic.last_kwargs["base_url"] == "https://example.test/anthropic"
        assert _CapturedAnthropic.last_kwargs["max_tokens"] == 8192

    def test_build_llm_missing_api_key_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(llm_mod, "ChatAnthropicWithReasoning", _CapturedAnthropic)
        env = {
            "LANGCHAIN_PROVIDER": "anthropic",
            "LANGCHAIN_MODEL_NAME": DEFAULT_CLAUDE_MODEL,
        }
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
                build_llm()

    def test_build_llm_missing_package_raises_install_hint(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(llm_mod, "ChatAnthropicWithReasoning", None)
        env = {
            "LANGCHAIN_PROVIDER": "anthropic",
            "LANGCHAIN_MODEL_NAME": DEFAULT_CLAUDE_MODEL,
            "ANTHROPIC_API_KEY": "sk-ant-test",
        }
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(RuntimeError, match="langchain-anthropic"):
                build_llm()

    @pytest.mark.parametrize(
        "effort,expected_budget,expected_max_tokens",
        [
            ("low", 1024, 1024 + 4096),
            ("medium", 4096, 4096 + 4096),
            ("high", 12288, 12288 + 4096),
            ("max", 24576, 24576 + 4096),
        ],
    )
    def test_reasoning_effort_enables_extended_thinking_with_budget(
        self,
        monkeypatch: pytest.MonkeyPatch,
        effort: str,
        expected_budget: int,
        expected_max_tokens: int,
    ) -> None:
        monkeypatch.setattr(llm_mod, "ChatAnthropicWithReasoning", _CapturedAnthropic)
        env = {
            "LANGCHAIN_PROVIDER": "anthropic",
            "LANGCHAIN_MODEL_NAME": DEFAULT_CLAUDE_MODEL,
            "ANTHROPIC_API_KEY": "sk-ant-test",
            "LANGCHAIN_REASONING_EFFORT": effort,
        }
        with patch.dict(os.environ, env, clear=True):
            build_llm()

        kwargs = _CapturedAnthropic.last_kwargs
        assert kwargs["thinking"] == {"type": "enabled", "budget_tokens": expected_budget}
        # Anthropic requires temperature=1.0 for extended thinking.
        assert kwargs["temperature"] == 1.0
        # max_tokens must exceed budget_tokens.
        assert kwargs["max_tokens"] == expected_max_tokens

    def test_extended_thinking_blocked_for_opus_4_7(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # docs.anthropic.com (Models overview): Claude Opus 4.7 uses adaptive
        # thinking and does NOT support the `thinking={type:enabled}` kwarg.
        # Setting LANGCHAIN_REASONING_EFFORT with claude-opus-4-7 must fail
        # at build_llm() time rather than silently misbehave at API time.
        monkeypatch.setattr(llm_mod, "ChatAnthropicWithReasoning", _CapturedAnthropic)
        env = {
            "LANGCHAIN_PROVIDER": "anthropic",
            "LANGCHAIN_MODEL_NAME": "claude-opus-4-7",
            "ANTHROPIC_API_KEY": "sk-ant-test",
            "LANGCHAIN_REASONING_EFFORT": "medium",
        }
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(RuntimeError, match="claude-opus-4-7 does not support extended thinking"):
                build_llm()

    def test_opus_4_7_without_reasoning_effort_works(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Opus 4.7 is still a valid model — just without LANGCHAIN_REASONING_EFFORT.
        monkeypatch.setattr(llm_mod, "ChatAnthropicWithReasoning", _CapturedAnthropic)
        env = {
            "LANGCHAIN_PROVIDER": "anthropic",
            "LANGCHAIN_MODEL_NAME": "claude-opus-4-7",
            "ANTHROPIC_API_KEY": "sk-ant-test",
        }
        with patch.dict(os.environ, env, clear=True):
            build_llm()
        assert _CapturedAnthropic.last_kwargs["model"] == "claude-opus-4-7"
        assert "thinking" not in _CapturedAnthropic.last_kwargs

    def test_explicit_max_tokens_overrides_thinking_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(llm_mod, "ChatAnthropicWithReasoning", _CapturedAnthropic)
        env = {
            "LANGCHAIN_PROVIDER": "anthropic",
            "LANGCHAIN_MODEL_NAME": DEFAULT_CLAUDE_MODEL,
            "ANTHROPIC_API_KEY": "sk-ant-test",
            "LANGCHAIN_REASONING_EFFORT": "medium",
            "ANTHROPIC_MAX_TOKENS": "16000",
        }
        with patch.dict(os.environ, env, clear=True):
            build_llm()

        kwargs = _CapturedAnthropic.last_kwargs
        assert kwargs["max_tokens"] == 16000
        assert kwargs["thinking"]["budget_tokens"] == 4096


# ---------------------------------------------------------------------------
# _normalize_anthropic_message: content-block flattening + stop_reason map
# ---------------------------------------------------------------------------


class _FakeMessage:
    """Minimal AIMessage stand-in supporting the attributes we read."""

    def __init__(self, content, response_metadata=None, additional_kwargs=None) -> None:
        self.content = content
        self.response_metadata = response_metadata or {}
        self.additional_kwargs = additional_kwargs or {}


class TestAnthropicMessageNormalization:
    def test_string_content_left_untouched(self) -> None:
        msg = _FakeMessage(content="Hello world", response_metadata={"stop_reason": "end_turn"})
        _normalize_anthropic_message(msg)
        assert msg.content == "Hello world"
        assert msg.response_metadata["finish_reason"] == "stop"

    def test_list_content_flattened_and_thinking_extracted(self) -> None:
        msg = _FakeMessage(
            content=[
                {"type": "thinking", "thinking": "Let me reason about this..."},
                {"type": "text", "text": "The answer is 42."},
            ],
            response_metadata={"stop_reason": "end_turn"},
        )
        _normalize_anthropic_message(msg)
        assert msg.content == "The answer is 42."
        assert msg.additional_kwargs["reasoning_content"] == "Let me reason about this..."
        assert msg.response_metadata["finish_reason"] == "stop"

    def test_redacted_thinking_recorded_as_marker(self) -> None:
        msg = _FakeMessage(
            content=[
                {"type": "redacted_thinking", "data": "encrypted-payload"},
                {"type": "text", "text": "Sorry, can't help."},
            ],
            response_metadata={"stop_reason": "refusal"},
        )
        _normalize_anthropic_message(msg)
        assert msg.content == "Sorry, can't help."
        assert "[redacted_thinking]" in msg.additional_kwargs["reasoning_content"]
        assert msg.response_metadata["finish_reason"] == "content_filter"

    def test_stop_reason_tool_use_mapped_to_tool_calls(self) -> None:
        msg = _FakeMessage(content="...", response_metadata={"stop_reason": "tool_use"})
        _normalize_anthropic_message(msg)
        assert msg.response_metadata["finish_reason"] == "tool_calls"

    def test_stop_reason_max_tokens_mapped_to_length(self) -> None:
        msg = _FakeMessage(content="...", response_metadata={"stop_reason": "max_tokens"})
        _normalize_anthropic_message(msg)
        assert msg.response_metadata["finish_reason"] == "length"

    def test_unknown_stop_reason_passes_through(self) -> None:
        msg = _FakeMessage(content="...", response_metadata={"stop_reason": "future_reason"})
        _normalize_anthropic_message(msg)
        assert msg.response_metadata["finish_reason"] == "future_reason"

    def test_finish_reason_already_present_is_preserved(self) -> None:
        msg = _FakeMessage(
            content="...",
            response_metadata={"stop_reason": "end_turn", "finish_reason": "tool_calls"},
        )
        _normalize_anthropic_message(msg)
        # Don't clobber a finish_reason set by some upstream wrapper.
        assert msg.response_metadata["finish_reason"] == "tool_calls"

    def test_reasoning_content_already_present_is_preserved(self) -> None:
        msg = _FakeMessage(
            content=[{"type": "thinking", "thinking": "fresh"}, {"type": "text", "text": "ok"}],
            additional_kwargs={"reasoning_content": "pre-existing"},
        )
        _normalize_anthropic_message(msg)
        assert msg.additional_kwargs["reasoning_content"] == "pre-existing"

    def test_anthropic_stop_reason_map_complete(self) -> None:
        # Documents the full set we translate; protects against silent drops.
        assert set(_ANTHROPIC_STOP_REASON_MAP.keys()) >= {
            "end_turn",
            "tool_use",
            "stop_sequence",
            "max_tokens",
        }

    def test_tool_calls_present_flatten_content_keep_tool_calls_intact(self) -> None:
        # When tool_use is present, ChatAnthropic._format_output has already
        # lifted the call into msg.tool_calls; the rest of Vibe-Trading
        # (e.g. swarm/worker.py:411 calls response.content.strip()) requires
        # response.content to be a string. We must flatten the list so the
        # downstream consumers don't crash. On the next ReAct turn LangChain
        # reconstructs the Anthropic content blocks from string content +
        # tool_calls — so multi-turn tool use is unaffected.
        msg = _FakeMessage(
            content=[
                {"type": "thinking", "thinking": "Plan: call tool."},
                {"type": "text", "text": "Calling tool"},
                {"type": "tool_use", "id": "tu_1", "name": "bash", "input": {}},
            ],
            response_metadata={"stop_reason": "tool_use"},
        )
        # tool_calls already extracted by LangChain's _format_output.
        msg.tool_calls = [{"id": "tu_1", "name": "bash", "args": {}}]
        _normalize_anthropic_message(msg)
        # Content flattened to text only; thinking surfaced; tool_calls intact.
        assert msg.content == "Calling tool"
        assert msg.additional_kwargs["reasoning_content"] == "Plan: call tool."
        assert msg.tool_calls == [{"id": "tu_1", "name": "bash", "args": {}}]
        assert msg.response_metadata["finish_reason"] == "tool_calls"


# ---------------------------------------------------------------------------
# End-to-end wrapper: ChatAnthropicWithReasoning._generate fires through the
# real ChatAnthropic path (proves the hook actually triggers in 0.3.x)
# ---------------------------------------------------------------------------


class TestChatAnthropicWithReasoningEndToEnd:
    """The wrapper's normalization must run when ChatAnthropic processes a
    response. langchain-anthropic 0.3.x emits messages via ``_format_output``
    inside ``_generate``; we override ``_generate`` itself to wrap that.

    We mock only the HTTP boundary (``_create``) so the full LangChain stack
    above it — including ``_format_output`` and ``_generate_with_cache``'s
    response_metadata merge — runs as in production.
    """

    def _fake_anthropic_response(self, *, content_blocks, stop_reason="end_turn"):
        """Build a stand-in for the anthropic Message object that _format_output reads."""

        class _Usage:
            input_tokens = 10
            output_tokens = 20
            cache_creation_input_tokens = 0
            cache_read_input_tokens = 0

            def model_dump(self):
                return {
                    "input_tokens": self.input_tokens,
                    "output_tokens": self.output_tokens,
                }

        class _Resp:
            def __init__(self) -> None:
                self.id = "msg_test"
                self.model = "claude-sonnet-4-6"
                self.role = "assistant"
                self.type = "message"
                self.content = content_blocks
                self.stop_reason = stop_reason
                self.stop_sequence = None
                self.usage = _Usage()

            def model_dump(self):
                return {
                    "id": self.id,
                    "model": self.model,
                    "role": self.role,
                    "type": self.type,
                    "content": self.content,
                    "stop_reason": self.stop_reason,
                    "stop_sequence": self.stop_sequence,
                    "usage": self.usage.model_dump(),
                }

        return _Resp()

    def test_invoke_returns_string_content_with_finish_reason(self, monkeypatch: pytest.MonkeyPatch) -> None:
        pytest.importorskip("langchain_anthropic")
        from src.providers.llm import ChatAnthropicWithReasoning

        assert ChatAnthropicWithReasoning is not None
        wrapper = ChatAnthropicWithReasoning(model=DEFAULT_CLAUDE_MODEL, api_key="sk-ant-test")

        fake = self._fake_anthropic_response(
            content_blocks=[
                {"type": "thinking", "thinking": "Reasoning step 1...", "signature": "sig"},
                {"type": "text", "text": "Final answer: 42."},
            ],
            stop_reason="end_turn",
        )
        monkeypatch.setattr(wrapper, "_create", lambda payload: fake)

        ai_message = wrapper.invoke("What is the meaning of life?")

        assert ai_message.content == "Final answer: 42."
        assert ai_message.additional_kwargs.get("reasoning_content") == "Reasoning step 1..."
        assert ai_message.response_metadata["finish_reason"] == "stop"
        assert ai_message.response_metadata["stop_reason"] == "end_turn"
        # Usage metadata flows through ChatAnthropic._format_output untouched.
        assert ai_message.usage_metadata is not None
        assert ai_message.usage_metadata["input_tokens"] == 10
        assert ai_message.usage_metadata["output_tokens"] == 20

    def test_invoke_with_tool_use_flattens_content_and_preserves_tool_calls(self, monkeypatch: pytest.MonkeyPatch) -> None:
        pytest.importorskip("langchain_anthropic")
        from src.providers.llm import ChatAnthropicWithReasoning

        assert ChatAnthropicWithReasoning is not None
        wrapper = ChatAnthropicWithReasoning(model=DEFAULT_CLAUDE_MODEL, api_key="sk-ant-test")

        fake = self._fake_anthropic_response(
            content_blocks=[
                {"type": "text", "text": "I will run a calculation."},
                {"type": "tool_use", "id": "toolu_01", "name": "calculator", "input": {"expr": "2+2"}},
            ],
            stop_reason="tool_use",
        )
        monkeypatch.setattr(wrapper, "_create", lambda payload: fake)

        ai_message = wrapper.invoke("Compute 2+2")

        # Content flattened to the user-visible text; downstream consumers
        # (swarm/worker.py:411 calls .content.strip()) need a string.
        assert ai_message.content == "I will run a calculation."
        # tool_calls survives via msg.tool_calls — that's the field the
        # ReAct loop uses to drive the next iteration.
        assert ai_message.tool_calls and ai_message.tool_calls[0]["name"] == "calculator"
        assert ai_message.tool_calls[0]["args"] == {"expr": "2+2"}
        assert ai_message.response_metadata["finish_reason"] == "tool_calls"
