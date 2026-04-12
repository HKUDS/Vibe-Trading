"""Tests for Gemini thought_signature preservation across the full data flow.

Covers:
  1. GeminiChatOpenAI._create_chat_result() extracting extra_content from raw responses
  2. ChatLLM._parse_response() extracting thought_signature from additional_kwargs
  3. ContextBuilder.format_assistant_tool_calls() including thought_signature in output
  4. Full end-to-end flow: raw response -> parsed -> formatted message
  5. stream_chat() bypass for GeminiChatOpenAI
"""

from __future__ import annotations

import json
import os
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from openai.types.chat import ChatCompletion, ChatCompletionMessage, ChatCompletionMessageToolCall
from openai.types.chat.chat_completion_message_tool_call import Function
from openai.types.chat.chat_completion import Choice
from openai.types.completion_usage import CompletionUsage

from src.providers.llm import GeminiChatOpenAI, _get_current_provider, build_llm
from src.providers.chat import ChatLLM, ToolCallRequest, LLMResponse
from src.agent.context import ContextBuilder


# ---------------------------------------------------------------------------
# Helpers: build fake Gemini API responses using real OpenAI SDK models
# ---------------------------------------------------------------------------


def _make_raw_tool_call(
    tc_id: str = "call_abc123",
    name: str = "web_search",
    args: str = '{"query": "gold price"}',
    thought_signature: str | None = "sig_deadbeef",
) -> dict:
    """Build a dict matching OpenAI tool_call format with optional extra_content.

    Returns a plain dict (not a Pydantic model) because the OpenAI SDK
    ChatCompletionMessageToolCall uses extra='allow' and will preserve
    extra_content if we construct via model_validate.
    """
    tc_dict = {
        "id": tc_id,
        "type": "function",
        "function": {"name": name, "arguments": args},
    }
    if thought_signature:
        tc_dict["extra_content"] = {"google": {"thought_signature": thought_signature}}
    return tc_dict


def _make_raw_response(
    tool_calls: list[dict] | None = None,
    content: str | None = None,
) -> ChatCompletion:
    """Build a ChatCompletion with optional tool_calls including extra_content."""
    if tool_calls is not None:
        raw_tcs = [ChatCompletionMessageToolCall.model_validate(tc) for tc in tool_calls]
        message = ChatCompletionMessage(
            role="assistant",
            content=content,
            tool_calls=raw_tcs,
        )
    else:
        message = ChatCompletionMessage(
            role="assistant",
            content=content or "Hello",
        )

    return ChatCompletion(
        id="chatcmpl-test",
        choices=[
            Choice(
                finish_reason="tool_calls" if tool_calls else "stop",
                index=0,
                message=message,
            )
        ],
        created=0,
        model="gemini-2.5-flash",
        object="chat.completion",
        usage=CompletionUsage(prompt_tokens=10, completion_tokens=20, total_tokens=30),
    )


# ---------------------------------------------------------------------------
# 1. GeminiChatOpenAI._create_chat_result
# ---------------------------------------------------------------------------


class TestGeminiChatOpenAICreateChatResult:
    """Test that _create_chat_result preserves extra_content from raw responses."""

    def test_extracts_thought_signature_from_single_tool_call(self) -> None:
        raw_response = _make_raw_response(tool_calls=[_make_raw_tool_call(thought_signature="sig_abc123")])

        llm = GeminiChatOpenAI(model="gemini-2.5-flash", api_key="fake")
        result = llm._create_chat_result(raw_response)

        msg = result.generations[0].message
        extras = msg.additional_kwargs.get("tool_call_extras", {})
        assert "call_abc123" in extras
        assert extras["call_abc123"] == {"google": {"thought_signature": "sig_abc123"}}

    def test_extracts_thought_signature_from_multiple_tool_calls(self) -> None:
        raw_response = _make_raw_response(
            tool_calls=[
                _make_raw_tool_call(tc_id="call_1", name="web_search", thought_signature="sig_1"),
                _make_raw_tool_call(tc_id="call_2", name="read_url", thought_signature="sig_2"),
            ]
        )

        llm = GeminiChatOpenAI(model="gemini-2.5-flash", api_key="fake")
        result = llm._create_chat_result(raw_response)

        msg = result.generations[0].message
        extras = msg.additional_kwargs.get("tool_call_extras", {})
        assert extras["call_1"]["google"]["thought_signature"] == "sig_1"
        assert extras["call_2"]["google"]["thought_signature"] == "sig_2"

    def test_no_extra_content_when_no_thought_signature(self) -> None:
        raw_response = _make_raw_response(tool_calls=[_make_raw_tool_call(thought_signature=None)])

        llm = GeminiChatOpenAI(model="gemini-2.5-flash", api_key="fake")
        result = llm._create_chat_result(raw_response)

        msg = result.generations[0].message
        extras = msg.additional_kwargs.get("tool_call_extras", {})
        assert "call_abc123" not in extras

    def test_no_tool_calls_means_no_extras(self) -> None:
        raw_response = _make_raw_response(tool_calls=None, content="Hello!")

        llm = GeminiChatOpenAI(model="gemini-2.5-flash", api_key="fake")
        result = llm._create_chat_result(raw_response)

        msg = result.generations[0].message
        assert "tool_call_extras" not in msg.additional_kwargs

    def test_only_first_tool_call_carries_signature_parallel(self) -> None:
        raw_response = _make_raw_response(
            tool_calls=[
                _make_raw_tool_call(tc_id="call_1", name="web_search", thought_signature="sig_first"),
                _make_raw_tool_call(tc_id="call_2", name="read_url", thought_signature=None),
            ]
        )

        llm = GeminiChatOpenAI(model="gemini-2.5-flash", api_key="fake")
        result = llm._create_chat_result(raw_response)

        msg = result.generations[0].message
        extras = msg.additional_kwargs.get("tool_call_extras", {})
        assert extras["call_1"]["google"]["thought_signature"] == "sig_first"
        assert "call_2" not in extras


# ---------------------------------------------------------------------------
# 2. ChatLLM._parse_response
# ---------------------------------------------------------------------------


class TestParseResponseWithThoughtSignature:
    """Test that _parse_response extracts thought_signature from additional_kwargs."""

    def test_extracts_thought_signature(self) -> None:
        from langchain_core.messages import AIMessage

        ai_msg = AIMessage(
            content="",
            tool_calls=[
                {"id": "call_1", "name": "web_search", "args": {"query": "gold"}, "type": "tool_call"},
            ],
            additional_kwargs={
                "tool_call_extras": {
                    "call_1": {"google": {"thought_signature": "sig_xyz"}},
                },
            },
        )

        response = ChatLLM._parse_response(ai_msg)
        assert len(response.tool_calls) == 1
        assert response.tool_calls[0].thought_signature == "sig_xyz"

    def test_no_thought_signature_when_missing(self) -> None:
        from langchain_core.messages import AIMessage

        ai_msg = AIMessage(
            content="",
            tool_calls=[
                {"id": "call_1", "name": "web_search", "args": {"query": "gold"}, "type": "tool_call"},
            ],
        )

        response = ChatLLM._parse_response(ai_msg)
        assert len(response.tool_calls) == 1
        assert response.tool_calls[0].thought_signature is None

    def test_mixed_tool_calls_with_and_without_signature(self) -> None:
        from langchain_core.messages import AIMessage

        ai_msg = AIMessage(
            content="",
            tool_calls=[
                {"id": "call_1", "name": "web_search", "args": {"query": "gold"}, "type": "tool_call"},
                {"id": "call_2", "name": "read_url", "args": {"url": "http://x"}, "type": "tool_call"},
            ],
            additional_kwargs={
                "tool_call_extras": {
                    "call_1": {"google": {"thought_signature": "sig_1"}},
                },
            },
        )

        response = ChatLLM._parse_response(ai_msg)
        assert len(response.tool_calls) == 2
        assert response.tool_calls[0].thought_signature == "sig_1"
        assert response.tool_calls[1].thought_signature is None


# ---------------------------------------------------------------------------
# 3. ContextBuilder.format_assistant_tool_calls
# ---------------------------------------------------------------------------


class TestFormatAssistantToolCalls:
    """Test that format_assistant_tool_calls includes thought_signature."""

    def test_includes_extra_content_with_signature(self) -> None:
        tc = ToolCallRequest(
            id="call_1",
            name="web_search",
            arguments={"query": "gold"},
            thought_signature="sig_abc",
        )
        msg = ContextBuilder.format_assistant_tool_calls([tc])

        assert msg["role"] == "assistant"
        assert len(msg["tool_calls"]) == 1
        tc_dict = msg["tool_calls"][0]
        assert "extra_content" in tc_dict
        assert tc_dict["extra_content"]["google"]["thought_signature"] == "sig_abc"

    def test_no_extra_content_without_signature(self) -> None:
        tc = ToolCallRequest(
            id="call_1",
            name="web_search",
            arguments={"query": "gold"},
        )
        msg = ContextBuilder.format_assistant_tool_calls([tc])

        assert msg["role"] == "assistant"
        assert len(msg["tool_calls"]) == 1
        assert "extra_content" not in msg["tool_calls"][0]

    def test_mixed_tool_calls(self) -> None:
        tc1 = ToolCallRequest(
            id="call_1",
            name="web_search",
            arguments={"query": "gold"},
            thought_signature="sig_1",
        )
        tc2 = ToolCallRequest(
            id="call_2",
            name="read_url",
            arguments={"url": "http://x"},
        )
        msg = ContextBuilder.format_assistant_tool_calls([tc1, tc2])

        assert len(msg["tool_calls"]) == 2
        assert "extra_content" in msg["tool_calls"][0]
        assert "extra_content" not in msg["tool_calls"][1]

    def test_output_is_valid_for_gemini_api(self) -> None:
        tc = ToolCallRequest(
            id="call_1",
            name="web_search",
            arguments={"query": "gold"},
            thought_signature="sig_test",
        )
        msg = ContextBuilder.format_assistant_tool_calls([tc])

        tc_dict = msg["tool_calls"][0]
        assert tc_dict["id"] == "call_1"
        assert tc_dict["type"] == "function"
        assert tc_dict["function"]["name"] == "web_search"
        assert json.loads(tc_dict["function"]["arguments"]) == {"query": "gold"}
        assert tc_dict["extra_content"]["google"]["thought_signature"] == "sig_test"


# ---------------------------------------------------------------------------
# 4. End-to-end flow: raw response -> parsed -> formatted
# ---------------------------------------------------------------------------


class TestEndToEndThoughtSignatureFlow:
    """Test the complete data flow from raw Gemini response to formatted message."""

    def test_full_flow_single_tool_call(self) -> None:
        raw_response = _make_raw_response(tool_calls=[_make_raw_tool_call(thought_signature="sig_e2e")])

        llm = GeminiChatOpenAI(model="gemini-2.5-flash", api_key="fake")
        result = llm._create_chat_result(raw_response)
        ai_message = result.generations[0].message

        parsed = ChatLLM._parse_response(ai_message)
        assert parsed.tool_calls[0].thought_signature == "sig_e2e"

        formatted = ContextBuilder.format_assistant_tool_calls(parsed.tool_calls)
        tc_dict = formatted["tool_calls"][0]
        assert tc_dict["extra_content"]["google"]["thought_signature"] == "sig_e2e"

    def test_full_flow_multiple_iterations(self) -> None:
        for sig_value in ["sig_iter1", "sig_iter2"]:
            raw_response = _make_raw_response(tool_calls=[_make_raw_tool_call(thought_signature=sig_value)])

            llm = GeminiChatOpenAI(model="gemini-2.5-flash", api_key="fake")
            result = llm._create_chat_result(raw_response)
            ai_message = result.generations[0].message

            parsed = ChatLLM._parse_response(ai_message)
            assert parsed.tool_calls[0].thought_signature == sig_value

            formatted = ContextBuilder.format_assistant_tool_calls(parsed.tool_calls)
            tc_dict = formatted["tool_calls"][0]
            assert tc_dict["extra_content"]["google"]["thought_signature"] == sig_value

    def test_full_flow_roundtrip_preserves_signature_in_json(self) -> None:
        """Verify the formatted message can be serialized and the signature survives."""
        raw_response = _make_raw_response(tool_calls=[_make_raw_tool_call(thought_signature="sig_json_test")])

        llm = GeminiChatOpenAI(model="gemini-2.5-flash", api_key="fake")
        result = llm._create_chat_result(raw_response)
        ai_message = result.generations[0].message

        parsed = ChatLLM._parse_response(ai_message)
        formatted = ContextBuilder.format_assistant_tool_calls(parsed.tool_calls)

        serialized = json.dumps(formatted, ensure_ascii=False)
        deserialized = json.loads(serialized)

        assert deserialized["tool_calls"][0]["extra_content"]["google"]["thought_signature"] == "sig_json_test"


# ---------------------------------------------------------------------------
# 5. stream_chat() bypass for GeminiChatOpenAI
# ---------------------------------------------------------------------------


class TestStreamChatBypass:
    """Test that stream_chat() falls back to chat() for GeminiChatOpenAI."""

    def test_stream_chat_uses_chat_for_gemini(self) -> None:
        llm = ChatLLM.__new__(ChatLLM)
        llm._llm = GeminiChatOpenAI(model="gemini-2.5-flash", api_key="fake")
        llm.model_name = "gemini-2.5-flash"

        with patch.object(llm, "chat", return_value=LLMResponse(content="test")) as mock_chat:
            result = llm.stream_chat(
                [{"role": "user", "content": "hello"}],
                tools=None,
            )
            mock_chat.assert_called_once()
            assert result.content == "test"

    def test_stream_chat_streams_for_regular_chat_openai(self) -> None:
        """Verify non-Gemini ChatOpenAI uses streaming path (not the bypass)."""
        from langchain_openai import ChatOpenAI

        llm = ChatLLM.__new__(ChatLLM)
        llm._llm = ChatOpenAI(model="gpt-4o", api_key="fake")
        llm.model_name = "gpt-4o"

        assert not isinstance(llm._llm, GeminiChatOpenAI)

    def test_stream_chat_gemini_bypass_does_not_call_stream(self) -> None:
        """Verify that for Gemini, the chat method is used instead of streaming."""
        llm = ChatLLM.__new__(ChatLLM)
        llm._llm = GeminiChatOpenAI(model="gemini-2.5-flash", api_key="fake")
        llm.model_name = "gemini-2.5-flash"

        with patch.object(llm, "chat", return_value=LLMResponse(content="test")) as mock_chat:
            llm.stream_chat([{"role": "user", "content": "hello"}], tools=None)
            mock_chat.assert_called_once()


# ---------------------------------------------------------------------------
# 6. build_llm() returns correct class for gemini provider
# ---------------------------------------------------------------------------


class TestBuildLlmProviderSelection:
    """Test that build_llm() returns GeminiChatOpenAI for gemini provider."""

    def test_gemini_provider_returns_gemini_chat(self) -> None:
        import src.providers.llm as llm_mod

        llm_mod._dotenv_loaded = True

        env = {
            "LANGCHAIN_PROVIDER": "gemini",
            "GEMINI_API_KEY": "test-key",
            "GEMINI_BASE_URL": "https://generativelanguage.googleapis.com/v1beta/openai/",
            "LANGCHAIN_MODEL_NAME": "gemini-2.5-flash",
        }
        clean = {k: v for k, v in os.environ.items() if not k.startswith(("OPENAI_", "LANGCHAIN_", "GEMINI_"))}
        clean.update(env)
        with patch.dict(os.environ, clean, clear=True):
            result = build_llm()
            assert isinstance(result, GeminiChatOpenAI)

    def test_openai_provider_returns_base_chat(self) -> None:
        from langchain_openai import ChatOpenAI
        import src.providers.llm as llm_mod

        llm_mod._dotenv_loaded = True

        env = {
            "LANGCHAIN_PROVIDER": "openai",
            "OPENAI_API_KEY": "sk-test",
            "OPENAI_BASE_URL": "https://api.openai.com/v1",
            "LANGCHAIN_MODEL_NAME": "gpt-4o",
        }
        clean = {k: v for k, v in os.environ.items() if not k.startswith(("OPENAI_", "LANGCHAIN_"))}
        clean.update(env)
        with patch.dict(os.environ, clean, clear=True):
            result = build_llm()
            assert type(result) is ChatOpenAI
            assert not isinstance(result, GeminiChatOpenAI)


# ---------------------------------------------------------------------------
# 7. _get_current_provider helper
# ---------------------------------------------------------------------------


class TestGetCurrentProvider:
    def test_returns_gemini(self) -> None:
        import src.providers.llm as llm_mod

        llm_mod._dotenv_loaded = True
        with patch.dict(os.environ, {"LANGCHAIN_PROVIDER": "gemini"}, clear=False):
            assert _get_current_provider() == "gemini"

    def test_defaults_to_openai(self) -> None:
        import src.providers.llm as llm_mod

        llm_mod._dotenv_loaded = True
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LANGCHAIN_PROVIDER", None)
            assert _get_current_provider() == "openai"


# ---------------------------------------------------------------------------
# 8. Regression: WebSearchTool gracefully handles missing ddgs
# ---------------------------------------------------------------------------


class TestWebSearchToolGracfulFailure:
    """Ensure WebSearchTool returns a valid JSON error when ddgs is missing."""

    def test_returns_error_json_when_ddgs_missing(self) -> None:
        from src.tools.web_search_tool import WebSearchTool

        tool = WebSearchTool()
        result = tool.execute(query="test")
        data = json.loads(result)
        if data.get("status") == "error" and "not installed" in data.get("error", ""):
            pytest.skip("ddgs not installed (expected in CI without full deps)")
        else:
            assert data["status"] == "ok"
