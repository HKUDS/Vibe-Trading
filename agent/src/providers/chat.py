"""ChatLLM: raw LLM message interface with function calling support.

ChatLLM is designed specifically for the AgentLoop ReAct cycle.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.providers.llm import build_llm


@dataclass
class ToolCallRequest:
    """Tool call request returned by the LLM.

    Attributes:
        id: Tool call ID (used to match tool_result messages).
        name: Tool name.
        arguments: Tool argument dict.
    """

    id: str
    name: str
    arguments: Dict[str, Any]


@dataclass
class LLMResponse:
    """LLM response.

    Attributes:
        content: Text content (final answer or thinking text).
        tool_calls: List of tool call requests.
        finish_reason: Finish reason string.
    """

    content: Optional[str] = None
    tool_calls: List[ToolCallRequest] = field(default_factory=list)
    reasoning_content: Optional[str] = None
    finish_reason: str = "stop"

    @property
    def has_tool_calls(self) -> bool:
        """Return True if the response contains tool calls."""
        return len(self.tool_calls) > 0


class ChatLLM:
    """LLM chat client with function calling support.

    Uses build_llm() to obtain a ChatOpenAI instance and bind_tools() to attach tool definitions.

    Attributes:
        model_name: Model name.
    """

    def __init__(self, model_name: Optional[str] = None) -> None:
        """Initialize ChatLLM.

        Args:
            model_name: Model name; defaults to the environment variable value.
        """
        self.model_name = model_name
        self._llm = build_llm(model_name=model_name)

    def chat(self, messages: List[Dict[str, Any]], tools: Optional[List[Dict[str, Any]]] = None, timeout: Optional[int] = None) -> LLMResponse:
        """Call the LLM synchronously.

        Args:
            messages: Message list (OpenAI format).
            tools: Tool definition list (OpenAI function calling format).
            timeout: Optional per-call timeout in seconds.

        Returns:
            LLMResponse.
        """
        llm = self._llm.bind_tools(tools) if tools else self._llm
        config = {"timeout": timeout} if timeout else {}
        ai_message = llm.invoke(messages, config=config)
        return self._parse_response(ai_message)

    def stream_chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        on_text_chunk: Optional[Any] = None,
        timeout: Optional[int] = None,
    ) -> LLMResponse:
        """Stream the LLM and optionally forward text deltas (e.g. thinking).

        Iterates AIMessageChunk; each text delta invokes ``on_text_chunk``.
        Aggregates chunks into one response; on failure falls back to ``chat()``.

        Args:
            messages: Messages in OpenAI format.
            tools: Tool definitions for function calling.
            on_text_chunk: Optional callback ``(delta: str) -> None``.
            timeout: Optional per-call timeout in seconds.

        Returns:
            Parsed ``LLMResponse``.
        """
        try:
            llm = self._llm.bind_tools(tools) if tools else self._llm
            config = {"timeout": timeout} if timeout else {}
            accumulated = None
            for chunk in llm.stream(messages, config=config):
                if chunk.content and on_text_chunk:
                    on_text_chunk(chunk.content)
                accumulated = chunk if accumulated is None else accumulated + chunk
            if accumulated is None:
                return LLMResponse(content="", tool_calls=[], finish_reason="stop")
            return self._parse_response(accumulated)
        except Exception:
            return self.chat(messages, tools=tools, timeout=timeout)

    async def achat(self, messages: List[Dict[str, Any]], tools: Optional[List[Dict[str, Any]]] = None, timeout: Optional[int] = None) -> LLMResponse:
        """Async LLM invocation.

        Args:
            messages: Messages in OpenAI format.
            tools: Tool definitions (OpenAI function-calling format).
            timeout: Optional per-call timeout in seconds.

        Returns:
            ``LLMResponse``.
        """
        llm = self._llm.bind_tools(tools) if tools else self._llm
        config = {"timeout": timeout} if timeout else {}
        ai_message = await llm.ainvoke(messages, config=config)
        return self._parse_response(ai_message)

    @staticmethod
    def _parse_response(ai_message: Any) -> LLMResponse:
        """Convert a LangChain AIMessage to ``LLMResponse``.

        Args:
            ai_message: LangChain AIMessage instance.

        Returns:
            ``LLMResponse``.
        """
        content = ai_message.content if hasattr(ai_message, "content") else None
        reasoning_content = (
            getattr(ai_message, "reasoning_content", None)
            or getattr(ai_message, "additional_kwargs", {}).get("reasoning_content")
            or getattr(ai_message, "response_metadata", {}).get("reasoning_content")
        )
        raw_calls = getattr(ai_message, "tool_calls", None) or []
        tool_calls = []
        for tc in raw_calls:
            tool_calls.append(ToolCallRequest(
                id=tc.get("id", ""),
                name=tc.get("name", ""),
                arguments=tc.get("args", {}),
            ))
        finish = getattr(ai_message, "response_metadata", {}).get("finish_reason", "stop")
        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            reasoning_content=reasoning_content,
            finish_reason=finish,
        )
