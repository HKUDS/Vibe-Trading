"""Claude Code (claude-agent-sdk) provider.

This provider routes LLM calls through the user's Claude Code subscription
(Pro / Max plan) instead of an Anthropic API key. It is intentionally
separate from a regular Anthropic API integration because Claude Code's auth
is OAuth-based (managed by ``claude login``) and its billing draws on the
subscription's monthly credit pool, not on per-token API charges. Direct
OAuth-token-as-API-bearer-key reuse is prohibited by Anthropic's Feb-2026
ToS update; ``claude-agent-sdk`` is the supported path.

Architecturally this is closest to the existing ``openai-codex`` provider
(also OAuth-backed, also a separate code path because the auth flow is
unrelated to the standard API-key path).

**v1 scope (this module)**: text completion only. ``bind_tools`` raises a
clear error pointing at the limitation — adding tool calling requires
inverting Vibe-Trading's ReAct loop to fit Claude Agent SDK's auto-execute
model, which is deferred to a follow-up PR. Single-turn, no streaming
fan-out, no MCP wiring.

Requires ``pip install claude-agent-sdk`` and a prior ``claude login``.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

try:
    import claude_agent_sdk as _cas
except ImportError:
    _cas = None  # type: ignore


SUPPORTS_TOOL_CALLS_HINT = (
    "The claude-code provider does not yet support tool calling — Claude Agent "
    "SDK auto-executes tools in its own agent loop, which clashes with "
    "Vibe-Trading's ReAct loop. Use LANGCHAIN_PROVIDER=anthropic or "
    "LANGCHAIN_PROVIDER=openrouter for tool-using workflows. Tracking issue: TBD."
)


@dataclass
class ClaudeCodeMessage:
    """Minimal LangChain-like message returned by :class:`ClaudeCodeLLM`.

    Matches the shape ``ChatLLM._parse_response`` reads from: ``content`` is a
    string, ``tool_calls`` is a list, ``additional_kwargs`` carries reasoning
    content (Claude Agent SDK exposes thinking blocks the same way the
    Anthropic API does), ``response_metadata`` carries ``finish_reason``, and
    ``usage_metadata`` is the per-turn usage dict the SDK reports.
    """

    content: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    additional_kwargs: dict[str, Any] = field(default_factory=dict)
    response_metadata: dict[str, Any] = field(default_factory=lambda: {"finish_reason": "stop"})
    usage_metadata: Optional[dict[str, int]] = None

    def __add__(self, other: "ClaudeCodeMessage") -> "ClaudeCodeMessage":
        # Stream chunks aggregate via __add__ in chat.py; mirror the
        # ChatOpenAI semantics so the rest of the codebase Just Works.
        finish_reason = other.response_metadata.get(
            "finish_reason",
            self.response_metadata.get("finish_reason", "stop"),
        )
        reasoning = (
            (self.additional_kwargs.get("reasoning_content") or "")
            + (other.additional_kwargs.get("reasoning_content") or "")
        )
        usage = other.usage_metadata or self.usage_metadata
        merged_kwargs = {**self.additional_kwargs, **other.additional_kwargs}
        if reasoning:
            merged_kwargs["reasoning_content"] = reasoning
        return ClaudeCodeMessage(
            content=(self.content or "") + (other.content or ""),
            tool_calls=[*self.tool_calls, *other.tool_calls],
            additional_kwargs=merged_kwargs,
            response_metadata={"finish_reason": finish_reason},
            usage_metadata=usage,
        )


_STOP_REASON_MAP = {
    "end_turn": "stop",
    "tool_use": "tool_calls",
    "stop_sequence": "stop",
    "max_tokens": "length",
    "pause_turn": "stop",
    "refusal": "content_filter",
}


def _flatten_messages_to_prompt(messages: list[dict[str, Any]]) -> tuple[str, str]:
    """Split an OpenAI-style message list into (system_prompt, user_prompt).

    Claude Agent SDK takes a single ``prompt`` string plus an optional
    ``system_prompt`` override. We hoist any ``system`` role messages into
    the system prompt and concatenate the rest with role markers so multi-turn
    history is preserved as plain text. This is a v1 simplification —
    multi-turn fidelity is best-effort because the SDK is not designed as a
    drop-in single-turn LLM surface.
    """
    system_parts: list[str] = []
    body_parts: list[str] = []
    for msg in messages:
        role = msg.get("role")
        raw_content = msg.get("content")
        if isinstance(raw_content, list):
            # Best-effort: extract text segments from a structured content list.
            text_parts: list[str] = []
            for block in raw_content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
                elif isinstance(block, str):
                    text_parts.append(block)
            content = "\n".join(text_parts)
        else:
            content = str(raw_content or "")
        if role == "system":
            system_parts.append(content)
        elif role == "user":
            body_parts.append(f"[USER]\n{content}")
        elif role == "assistant":
            body_parts.append(f"[ASSISTANT]\n{content}")
        elif role == "tool":
            body_parts.append(f"[TOOL_RESULT]\n{content}")
    system_prompt = "\n\n".join(p for p in system_parts if p)
    user_prompt = "\n\n".join(body_parts) if body_parts else ""
    return system_prompt, user_prompt


def _extract_usage(usage: dict[str, Any] | None) -> Optional[dict[str, int]]:
    """Normalise the SDK's usage dict to LangChain's ``UsageMetadata`` shape."""
    if not usage:
        return None
    try:
        return {
            "input_tokens": int(usage.get("input_tokens", 0) or 0),
            "output_tokens": int(usage.get("output_tokens", 0) or 0),
            "total_tokens": int(
                (usage.get("input_tokens", 0) or 0) + (usage.get("output_tokens", 0) or 0)
            ),
        }
    except (TypeError, ValueError):
        return None


class ClaudeCodeLLM:
    """Adapter for ``claude-agent-sdk``.

    Mirrors the small ``invoke`` / ``ainvoke`` / ``stream`` / ``bind_tools``
    surface :class:`OpenAICodexLLM` exposes — enough for Vibe-Trading's
    :class:`ChatLLM` to drive without changes.

    Args:
        model: Claude model identifier. ``None`` keeps Claude Code's CLI
            default (whatever the user has set).
        temperature: Forwarded as a hint via ``extra_args`` (the SDK does not
            currently expose a typed ``temperature`` knob — but Claude itself
            still honours sampling parameters when present).
        timeout: Per-call wall clock cap, seconds.
        max_turns: Hard cap on the SDK's internal agent loop. Defaults to 1
            so this acts as a single-turn LLM call.
        cwd: Working directory the SDK runs in. Defaults to a fresh temp dir
            so the user's project-level ``CLAUDE.md`` / CogniLayer hooks do
            not bleed into agent responses.
    """

    def __init__(
        self,
        *,
        model: Optional[str] = None,
        temperature: float = 0.0,
        timeout: int = 120,
        max_turns: int = 1,
        cwd: Optional[str] = None,
    ) -> None:
        if _cas is None:
            raise RuntimeError(
                "claude-agent-sdk is not installed. Run: pip install claude-agent-sdk "
                "(or pip install 'vibe-trading-ai[claude-code]'). Also requires a prior "
                "`claude login` so the SDK can use your Claude Pro/Max subscription."
            )
        self.model = model
        self.temperature = temperature
        self.timeout = timeout
        self.max_turns = max_turns
        # An isolated cwd avoids the user's project CLAUDE.md / plugin hooks
        # bleeding into the system prompt the SDK builds.
        self._cwd = cwd or tempfile.gettempdir()

    def bind_tools(self, tools: list[dict[str, Any]]) -> "ClaudeCodeLLM":
        """Refuse tool binding in v1 with a clear pointer.

        Claude Agent SDK auto-executes tools inside its own agent loop, which
        does not compose with Vibe-Trading's ReAct loop. A follow-up PR will
        intercept tool calls via the SDK's PreToolUse hook + custom MCP server
        to surface them to ``ChatLLM`` as ``response.tool_calls``.
        """
        if tools:
            raise NotImplementedError(SUPPORTS_TOOL_CALLS_HINT)
        return self

    def _build_options(self, system_prompt: str) -> Any:
        options = _cas.ClaudeAgentOptions(
            tools=[],  # disable every built-in Claude Code tool (Read/Write/Bash/...)
            allowed_tools=[],
            mcp_servers={},
            strict_mcp_config=True,
            permission_mode="dontAsk",
            max_turns=self.max_turns,
            cwd=self._cwd,
            include_partial_messages=False,
            include_hook_events=False,
        )
        if self.model:
            options.model = self.model
        if system_prompt:
            options.system_prompt = system_prompt
        return options

    async def _ainvoke_impl(self, messages: list[dict[str, Any]]) -> ClaudeCodeMessage:
        system_prompt, user_prompt = _flatten_messages_to_prompt(messages)
        if not user_prompt:
            # Nothing to ask — return an empty response rather than calling out.
            return ClaudeCodeMessage(content="")

        options = self._build_options(system_prompt)
        text_parts: list[str] = []
        thinking_parts: list[str] = []
        usage: Optional[dict[str, int]] = None
        finish_reason = "stop"

        async def _collect() -> None:
            nonlocal usage, finish_reason
            async for message in _cas.query(prompt=user_prompt, options=options):
                if isinstance(message, _cas.AssistantMessage):
                    for block in message.content or []:
                        if isinstance(block, _cas.TextBlock):
                            text_parts.append(block.text)
                        elif isinstance(block, _cas.ThinkingBlock):
                            thinking_parts.append(block.thinking or "")
                    if message.usage:
                        normalized = _extract_usage(message.usage)
                        if normalized is not None:
                            usage = normalized
                elif isinstance(message, _cas.ResultMessage):
                    stop_reason = message.stop_reason or ""
                    finish_reason = _STOP_REASON_MAP.get(stop_reason, stop_reason or "stop")
                    if message.usage:
                        normalized = _extract_usage(message.usage)
                        if normalized is not None:
                            usage = normalized

        await asyncio.wait_for(_collect(), timeout=self.timeout)

        msg = ClaudeCodeMessage(
            content="".join(text_parts),
            response_metadata={"finish_reason": finish_reason},
            usage_metadata=usage,
        )
        if thinking_parts:
            msg.additional_kwargs["reasoning_content"] = "".join(thinking_parts)
        return msg

    def invoke(
        self,
        messages: list[dict[str, Any]],
        config: Optional[dict[str, Any]] = None,
    ) -> ClaudeCodeMessage:
        return asyncio.run(self._ainvoke_impl(messages))

    async def ainvoke(
        self,
        messages: list[dict[str, Any]],
        config: Optional[dict[str, Any]] = None,
    ) -> ClaudeCodeMessage:
        return await self._ainvoke_impl(messages)

    def stream(
        self,
        messages: list[dict[str, Any]],
        config: Optional[dict[str, Any]] = None,
    ) -> Iterable[ClaudeCodeMessage]:
        # v1: emit the single completed message as one chunk so the existing
        # stream-then-aggregate path in chat.py works without special-casing.
        # Real token-level streaming via include_partial_messages=True is a
        # follow-up — chunk shape needs additional careful handling.
        yield self.invoke(messages, config=config)
