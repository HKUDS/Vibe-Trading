"""Regression tests for Kimi thinking/tool-call compatibility."""

from __future__ import annotations

from types import SimpleNamespace

from src.agent.context import ContextBuilder
from src.providers.chat import ChatLLM, ToolCallRequest


class TestKimiReasoningContent:
    def test_parse_response_keeps_reasoning_content(self) -> None:
        ai_message = SimpleNamespace(
            content="",
            reasoning_content="step-by-step reasoning",
            tool_calls=[
                {
                    "id": "tc_1",
                    "name": "bash",
                    "args": {"command": "pwd"},
                }
            ],
            additional_kwargs={},
            response_metadata={"finish_reason": "tool_calls"},
        )

        response = ChatLLM._parse_response(ai_message)

        assert response.reasoning_content == "step-by-step reasoning"
        assert response.finish_reason == "tool_calls"
        assert len(response.tool_calls) == 1
        assert response.tool_calls[0].arguments == {"command": "pwd"}

    def test_parse_response_falls_back_to_additional_kwargs(self) -> None:
        ai_message = SimpleNamespace(
            content="",
            tool_calls=[],
            additional_kwargs={"reasoning_content": "fallback reasoning"},
            response_metadata={"finish_reason": "stop"},
        )

        response = ChatLLM._parse_response(ai_message)

        assert response.reasoning_content == "fallback reasoning"

    def test_format_assistant_tool_calls_preserves_reasoning_content(self) -> None:
        message = ContextBuilder.format_assistant_tool_calls(
            [
                ToolCallRequest(
                    id="tc_1",
                    name="bash",
                    arguments={"command": "pwd"},
                )
            ],
            content="",
            reasoning_content="step-by-step reasoning",
        )

        assert message["role"] == "assistant"
        assert message["reasoning_content"] == "step-by-step reasoning"
        assert message["tool_calls"][0]["id"] == "tc_1"

    def test_format_assistant_tool_calls_omits_reasoning_when_absent(self) -> None:
        message = ContextBuilder.format_assistant_tool_calls(
            [
                ToolCallRequest(
                    id="tc_1",
                    name="bash",
                    arguments={"command": "pwd"},
                )
            ],
            content="",
        )

        assert "reasoning_content" not in message
