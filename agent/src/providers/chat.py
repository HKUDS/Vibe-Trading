"""ChatLLM: raw LLM message interface with function calling support.

ChatLLM is designed specifically for the AgentLoop ReAct cycle.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.providers.llm import GeminiChatOpenAI, build_llm


@dataclass
class ToolCallRequest:
    """Tool call request returned by the LLM.

    Attributes:
        id: Tool call ID (used to match tool_result messages).
        name: Tool name.
        arguments: Tool argument dict.
        thought_signature: Gemini thought_signature for this tool call (if any).
    """

    id: str
    name: str
    arguments: Dict[str, Any]
    thought_signature: Optional[str] = None


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

    def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        timeout: Optional[int] = None,
    ) -> LLMResponse:
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

        For Gemini (GeminiChatOpenAI), streaming is bypassed in favor of
        ``chat()`` because the streaming path does not preserve
        ``extra_content.google.thought_signature`` from the raw response.

        Args:
            messages: Messages in OpenAI format.
            tools: Tool definitions for function calling.
            on_text_chunk: Optional callback ``(delta: str) -> None``.
            timeout: Optional per-call timeout in seconds.

        Returns:
            Parsed ``LLMResponse``.
        """
        if isinstance(self._llm, GeminiChatOpenAI):
            return self.chat(messages, tools=tools, timeout=timeout)

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

    async def achat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        timeout: Optional[int] = None,
    ) -> LLMResponse:
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
        raw_calls = getattr(ai_message, "tool_calls", None) or []
        tool_call_extras: Dict[str, Any] = {}
        if hasattr(ai_message, "additional_kwargs"):
            tool_call_extras = ai_message.additional_kwargs.get("tool_call_extras", {})
        tool_calls = []
        for tc in raw_calls:
            tc_id = tc.get("id", "")
            thought_signature = None
            if tc_id and tc_id in tool_call_extras:
                extra = tool_call_extras[tc_id]
                if isinstance(extra, dict):
                    google_extra = extra.get("google", {})
                    thought_signature = google_extra.get("thought_signature")
            tool_calls.append(
                ToolCallRequest(
                    id=tc_id,
                    name=tc.get("name", ""),
                    arguments=tc.get("args", {}),
                    thought_signature=thought_signature,
                )
            )
        finish = getattr(ai_message, "response_metadata", {}).get("finish_reason", "stop")
        return LLMResponse(content=content, tool_calls=tool_calls, finish_reason=finish)
