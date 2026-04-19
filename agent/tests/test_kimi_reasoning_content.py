"""Regression tests for provider reasoning_content preservation.

Invariant: ``ai_message.additional_kwargs["reasoning_content"]`` is the
single source of truth. ``ChatOpenAIWithReasoning`` populates it from both
the non-streaming response path and the streaming delta path.
"""

from __future__ import annotations

import os
from types import SimpleNamespace
from typing import Any

from src.agent.context import ContextBuilder
from src.providers.chat import ChatLLM, ToolCallRequest, _dedupe_finish_reason
from src.providers.llm import ChatOpenAIWithReasoning


class TestParseResponseSingleSource:
    """_parse_response reads reasoning_content from exactly one place."""

    def test_reads_from_additional_kwargs(self) -> None:
        ai_message = SimpleNamespace(
            content="",
            tool_calls=[],
            additional_kwargs={"reasoning_content": "step-by-step reasoning"},
            response_metadata={"finish_reason": "stop"},
        )

        response = ChatLLM._parse_response(ai_message)

        assert response.reasoning_content == "step-by-step reasoning"

    def test_absent_reasoning_content_yields_none(self) -> None:
        """Non-thinking providers leave reasoning_content unset."""
        ai_message = SimpleNamespace(
            content="hello",
            tool_calls=[],
            additional_kwargs={},
            response_metadata={"finish_reason": "stop"},
        )

        response = ChatLLM._parse_response(ai_message)

        assert response.reasoning_content is None
        assert response.content == "hello"

    def test_tool_calls_are_preserved_alongside_reasoning(self) -> None:
        ai_message = SimpleNamespace(
            content="",
            tool_calls=[{"id": "tc_1", "name": "bash", "args": {"command": "pwd"}}],
            additional_kwargs={"reasoning_content": "think then call"},
            response_metadata={"finish_reason": "tool_calls"},
        )

        response = ChatLLM._parse_response(ai_message)

        assert response.reasoning_content == "think then call"
        assert response.finish_reason == "tool_calls"
        assert response.tool_calls[0].id == "tc_1"
        assert response.tool_calls[0].arguments == {"command": "pwd"}


class TestDedupeFinishReason:
    """OpenRouter-style relays emit finish_reason on every stream chunk;
    AIMessageChunk.__add__ concatenates them into 'stopstop', etc. ReAct
    loop uses finish_reason for exit decisions, so equality must survive."""

    def test_clean_values_unchanged(self) -> None:
        assert _dedupe_finish_reason("stop") == "stop"
        assert _dedupe_finish_reason("tool_calls") == "tool_calls"

    def test_duplicated_dedupes(self) -> None:
        assert _dedupe_finish_reason("stopstop") == "stop"
        assert _dedupe_finish_reason("stopstopstop") == "stop"
        assert _dedupe_finish_reason("tool_callstool_calls") == "tool_calls"

    def test_suffix_match_picks_longest_valid_marker(self) -> None:
        # endswith — "stoptool_calls" ends with "tool_calls"
        assert _dedupe_finish_reason("stoptool_calls") == "tool_calls"

    def test_empty_returns_empty(self) -> None:
        # No marker matches; raw is returned. Callers supply a default upstream.
        assert _dedupe_finish_reason("") == ""

    def test_unknown_marker_passed_through(self) -> None:
        assert _dedupe_finish_reason("custom_reason") == "custom_reason"


class TestContextBuilderToolCallReplay:
    """reasoning_content flows back into the next request's assistant message."""

    def test_format_assistant_tool_calls_preserves_reasoning_content(self) -> None:
        message = ContextBuilder.format_assistant_tool_calls(
            [ToolCallRequest(id="tc_1", name="bash", arguments={"command": "pwd"})],
            content="",
            reasoning_content="step-by-step reasoning",
        )

        assert message["role"] == "assistant"
        assert message["reasoning_content"] == "step-by-step reasoning"
        assert message["tool_calls"][0]["id"] == "tc_1"

    def test_format_assistant_tool_calls_omits_reasoning_when_absent(self) -> None:
        message = ContextBuilder.format_assistant_tool_calls(
            [ToolCallRequest(id="tc_1", name="bash", arguments={"command": "pwd"})],
            content="",
        )

        assert "reasoning_content" not in message


class TestChatOpenAIWithReasoningNonStreaming:
    """_create_chat_result path: invoke / ainvoke."""

    def _instance(self, model: str = "kimi-k2-thinking") -> Any:
        os.environ.setdefault("OPENAI_API_KEY", "sk-test")
        return ChatOpenAIWithReasoning(model=model, api_key="sk-test")

    def test_preserves_reasoning_on_tool_call_response(self) -> None:
        instance = self._instance()
        response = {
            "id": "chatcmpl-test",
            "model": "kimi-k2-thinking",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "reasoning_content": "step-by-step reasoning from provider",
                        "tool_calls": [
                            {
                                "id": "tc_1",
                                "type": "function",
                                "function": {
                                    "name": "bash",
                                    "arguments": '{"command":"pwd"}',
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }

        result = instance._create_chat_result(response)

        assert result.generations[0].message.additional_kwargs["reasoning_content"] == \
            "step-by-step reasoning from provider"

    def test_no_reasoning_content_when_absent(self) -> None:
        """OpenAI / Claude / Groq-style responses leave additional_kwargs clean."""
        instance = self._instance(model="gpt-4")
        response = {
            "id": "chatcmpl-test",
            "model": "gpt-4",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "hello"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
        }

        result = instance._create_chat_result(response)

        assert "reasoning_content" not in result.generations[0].message.additional_kwargs


class TestChatOpenAIWithReasoningStreaming:
    """_convert_chunk_to_generation_chunk path: stream / astream.

    This is the path swarm workers take via ChatLLM.stream_chat → llm.stream.
    PR #41 only fixed the non-streaming path; this class covers the gap.
    """

    def _instance(self, model: str = "kimi-k2-thinking") -> Any:
        os.environ.setdefault("OPENAI_API_KEY", "sk-test")
        return ChatOpenAIWithReasoning(model=model, api_key="sk-test")

    def _delta_chunk(self, delta: dict, model: str = "kimi-k2-thinking") -> dict:
        return {
            "id": "chatcmpl-test",
            "model": model,
            "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
        }

    def test_preserves_reasoning_on_streaming_delta(self) -> None:
        from langchain_core.messages import AIMessageChunk

        instance = self._instance()
        chunk = self._delta_chunk(
            {"role": "assistant", "content": "", "reasoning_content": "thinking step"}
        )

        gen_chunk = instance._convert_chunk_to_generation_chunk(chunk, AIMessageChunk, None)

        assert gen_chunk is not None
        assert gen_chunk.message.additional_kwargs["reasoning_content"] == "thinking step"

    def test_streaming_chunks_accumulate_reasoning_across_chunks(self) -> None:
        """Multiple deltas: AIMessageChunk.__add__ concatenates via merge_dicts."""
        from langchain_core.messages import AIMessageChunk

        instance = self._instance()
        chunks = [
            self._delta_chunk({"role": "assistant", "content": "", "reasoning_content": "first "}),
            self._delta_chunk({"content": "", "reasoning_content": "second "}),
            self._delta_chunk({"content": "", "reasoning_content": "third"}),
        ]

        accumulated = None
        for raw in chunks:
            gen = instance._convert_chunk_to_generation_chunk(raw, AIMessageChunk, None)
            assert gen is not None
            accumulated = gen.message if accumulated is None else accumulated + gen.message

        assert accumulated is not None
        assert accumulated.additional_kwargs["reasoning_content"] == "first second third"

    def test_streaming_delta_without_reasoning_is_unchanged(self) -> None:
        """OpenAI-style stream deltas (no reasoning_content) produce empty additional_kwargs."""
        from langchain_core.messages import AIMessageChunk

        instance = self._instance(model="gpt-4")
        chunk = self._delta_chunk({"role": "assistant", "content": "hello"}, model="gpt-4")

        gen_chunk = instance._convert_chunk_to_generation_chunk(chunk, AIMessageChunk, None)

        assert gen_chunk is not None
        assert "reasoning_content" not in gen_chunk.message.additional_kwargs

    def test_openrouter_field_name_reasoning_maps_to_reasoning_content(self) -> None:
        """OpenRouter relays Kimi/DeepSeek with delta.reasoning (not reasoning_content).

        All variants must normalize to additional_kwargs["reasoning_content"] so
        downstream reads one canonical key.
        """
        from langchain_core.messages import AIMessageChunk

        instance = self._instance(model="moonshotai/kimi-k2-thinking")
        chunk = self._delta_chunk(
            {"role": "assistant", "content": "", "reasoning": "openrouter-style reasoning"},
            model="moonshotai/kimi-k2-thinking",
        )

        gen_chunk = instance._convert_chunk_to_generation_chunk(chunk, AIMessageChunk, None)

        assert gen_chunk is not None
        # Canonical key — not "reasoning"
        assert gen_chunk.message.additional_kwargs["reasoning_content"] == \
            "openrouter-style reasoning"
        assert "reasoning" not in gen_chunk.message.additional_kwargs

    def test_reasoning_content_takes_priority_over_reasoning(self) -> None:
        """If both variants are present, reasoning_content wins (higher priority)."""
        from langchain_core.messages import AIMessageChunk

        instance = self._instance()
        chunk = self._delta_chunk(
            {
                "role": "assistant",
                "content": "",
                "reasoning_content": "canonical",
                "reasoning": "variant",
            }
        )

        gen_chunk = instance._convert_chunk_to_generation_chunk(chunk, AIMessageChunk, None)

        assert gen_chunk is not None
        assert gen_chunk.message.additional_kwargs["reasoning_content"] == "canonical"

    def test_usage_only_chunk_returns_without_modification(self) -> None:
        """Final usage-only chunks have no choices[] — must not crash."""
        from langchain_core.messages import AIMessageChunk

        instance = self._instance()
        usage_only = {
            "id": "chatcmpl-test",
            "model": "kimi-k2-thinking",
            "choices": [],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }

        gen_chunk = instance._convert_chunk_to_generation_chunk(usage_only, AIMessageChunk, None)

        # super() returns a default-content chunk for usage-only; we should
        # pass it through unchanged (no choices to read reasoning from).
        assert gen_chunk is not None
        assert "reasoning_content" not in gen_chunk.message.additional_kwargs
