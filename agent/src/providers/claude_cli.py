"""Claude Code CLI provider: the local ``claude -p`` as a decision-only chat model.

Each call starts one headless ``claude -p`` process with every built-in tool and
MCP server disabled, and constrains its output with ``--json-schema`` to either
"call these tools" or "final answer". Vibe-Trading executes the tools itself, so
the ReAct loop, the grounding ledger and the swarm deliverable checks see every
tool result exactly as they would with an API provider.

Authentication is whatever the local Claude Code login provides; no API key is
read or required.
"""

from __future__ import annotations

import asyncio
import json
import os
import queue
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

from langchain_core.messages import AIMessage, AIMessageChunk

from src.config.accessor import get_env_config
from src.providers.claude_cli_policy import (
    bash_policy,
    offered_tools,
    screen_calls,
    tool_name,
)

DEFAULT_MODEL = "claude-opus-5-5"
_TIMEOUT_FLOOR_S = 600
_AUTH_STATUS_TIMEOUT_S = 15
_MAX_RETRIES = 3
_POLL_INTERVAL_S = 0.5
_HEARTBEAT_S = 1.0

# The union of the levels any model accepts as ``--effort``. Anything outside it
# (``""``, a ``none`` saved for another provider) is never passed. The CLI does
# not reject a level the chosen model lacks, so narrowing to the selected
# model's own levels happens in the settings form.
CLAUDE_CLI_EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")

# The flags that keep a child away from user settings, hooks, MCP servers and
# built-in tools. Model discovery uses them too, so the list matches what a turn
# can actually run.
ISOLATION_ARGS = (
    "--restricted",
    "--strict-mcp-config",
    "--tools",
    "",
    "--no-session-persistence",
)

# The child process must authenticate with the local login, never with a key
# meant for the in-process Anthropic provider.
_STRIPPED_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL")


def child_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k not in _STRIPPED_ENV}


_PROTOCOL = (
    "\n\n## Tool-calling protocol\n"
    "You cannot execute tools yourself; the host executes them and returns the "
    "results in the next turn. Respond with action=tool_calls and the calls you "
    "want (name + arguments that match the tool's JSON schema), or action=final "
    "with your complete answer in content once you have what you need.\n"
    "Available tools (OpenAI function format):\n"
)
_FINAL_ONLY = (
    "\n\n## Output protocol\n"
    "No tools are available in this turn. Respond with action=final and your "
    "complete answer in content."
)

# Where the native Claude Code installer puts the executable; checked last.
_FALLBACK_CLI_PATH = Path.home() / ".local" / "bin" / "claude"


def resolve_claude_cli() -> str:
    """Return the ``claude`` executable: ``CLAUDE_CLI_PATH``, PATH, then ``~/.local/bin``.

    Returns:
        Path or command name of the executable to run.

    Raises:
        RuntimeError: No executable was found.
    """
    explicit = get_env_config().llm.claude_cli_path.strip()
    if explicit:
        return explicit
    found = shutil.which("claude")
    if found:
        return found
    if _FALLBACK_CLI_PATH.is_file():
        return str(_FALLBACK_CLI_PATH)
    raise RuntimeError(
        "claude-cli provider requires the Claude Code CLI. Install it and run "
        "`claude auth login`, or set CLAUDE_CLI_PATH to the executable."
    )


def get_claude_cli_auth_status() -> tuple[bool, str]:
    """Report the local Claude Code login, as a turn would see it; never raises.

    Runs with the same environment as a turn: an ``ANTHROPIC_API_KEY`` meant for
    the in-process Anthropic provider would otherwise report ``api_key`` as
    logged in while every turn, which strips it, fails.

    Returns:
        ``(logged_in, auth_method)``; on failure ``(False, "unavailable: ...")``.
    """
    try:
        result = subprocess.run(
            [resolve_claude_cli(), "auth", "status"],
            capture_output=True,
            text=True,
            timeout=_AUTH_STATUS_TIMEOUT_S,
            env=child_env(),
        )
        payload = json.loads(result.stdout or "{}")
    except (RuntimeError, OSError, subprocess.SubprocessError, ValueError) as exc:
        return False, f"unavailable: {type(exc).__name__}"
    logged_in = bool(payload.get("loggedIn"))
    return logged_in, str(
        payload.get("authMethod") or ("logged in" if logged_in else "not logged in")
    )


def _message_value(message: Any, key: str, default: Any = None) -> Any:
    if isinstance(message, dict):
        return message.get(key, default)
    return getattr(message, key, default)


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts: list[str] = []
        for part in content:
            if isinstance(part, dict):
                if part.get("type", "text") != "text":
                    # Dropping an image silently would let the model answer a
                    # question about a picture it never saw.
                    raise RuntimeError(
                        f"claude-cli supports text input only, not {part.get('type')!r}"
                    )
                texts.append(str(part.get("text", "")))
            else:
                texts.append(str(part))
        return "".join(texts)
    return "" if content is None else str(content)


def _role(message: Any) -> str:
    return str(
        _message_value(message, "role", "") or _message_value(message, "type", "")
    )


def _render(messages: list[Any]) -> tuple[str, str]:
    """Split messages into the system prompt and the stdin transcript.

    A lone user message is passed through verbatim so a swarm worker's prompt
    reaches the model byte-for-byte; longer histories keep role boundaries and
    tool results in a fixed text layout.
    """
    system: list[str] = []
    rest: list[Any] = []
    for message in messages:
        role = _role(message)
        if role == "system":
            system.append(_content_text(_message_value(message, "content", "")))
        else:
            rest.append(message)
    if len(rest) == 1 and _role(rest[0]) in {"user", "human"}:
        return "\n\n".join(system), _content_text(
            _message_value(rest[0], "content", "")
        )
    parts: list[str] = []
    for message in rest:
        role = _role(message)
        content = _content_text(_message_value(message, "content", ""))
        tool_calls = _message_value(message, "tool_calls")
        if role in {"assistant", "ai"} and tool_calls:
            calls = [
                {
                    "id": _message_value(tc, "id"),
                    "name": (_message_value(tc, "function") or {}).get("name")
                    or _message_value(tc, "name"),
                    "arguments": (_message_value(tc, "function") or {}).get("arguments")
                    or _message_value(tc, "args"),
                }
                for tc in tool_calls
            ]
            parts.append(
                f"[assistant]\n{content}\n[assistant tool_calls]\n{json.dumps(calls, ensure_ascii=False, default=str)}"
            )
        elif role == "tool":
            parts.append(
                f"[tool result: {_message_value(message, 'name')} id={_message_value(message, 'tool_call_id')}]\n{content}"
            )
        else:
            parts.append(f"[{role}]\n{content}")
    return "\n\n".join(system), "\n\n".join(parts)


def _schema(allow_tools: bool) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["tool_calls", "final"] if allow_tools else ["final"],
            },
            "content": {"type": "string"},
            "tool_calls": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "arguments": {"type": "object"},
                    },
                    "required": ["name", "arguments"],
                },
            },
        },
        "required": ["action"],
    }


@dataclass
class _Decision:
    content: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, int] = field(
        default_factory=lambda: {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
        }
    )


def _run_cli(
    *,
    system: str,
    user_input: str,
    allow_tools: bool,
    model: str,
    effort: str = "",
    timeout: float,
    cancel_event: threading.Event,
) -> dict[str, Any]:
    """Run one ``claude -p`` turn and return its parsed JSON result."""
    fd, system_path = tempfile.mkstemp(prefix="vibe-claude-cli-", suffix=".md")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(system)
        # An empty or foreign level (``none`` saved for another provider) leaves
        # the model's own default in place.
        effort_args = ["--effort", effort] if effort in CLAUDE_CLI_EFFORT_LEVELS else []
        cmd = [
            resolve_claude_cli(),
            "-p",
            *ISOLATION_ARGS,
            "--output-format",
            "json",
            "--model",
            model,
            *effort_args,
            "--system-prompt-file",
            system_path,
            "--json-schema",
            json.dumps(_schema(allow_tools)),
        ]
        env = child_env()
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            env=env,
        )
        result: dict[str, Any] = {}

        def communicate() -> None:
            result["out"], result["err"] = proc.communicate(user_input)

        worker = threading.Thread(target=communicate, daemon=True)
        worker.start()
        waited = 0.0
        while worker.is_alive():
            worker.join(_POLL_INTERVAL_S)
            waited += _POLL_INTERVAL_S
            if cancel_event.is_set() or waited > timeout:
                proc.kill()
                worker.join(5)
                if cancel_event.is_set():
                    return {"cancelled": True}
                raise RuntimeError(f"claude -p exceeded {timeout:.0f}s")
    finally:
        try:
            os.unlink(system_path)
        except OSError:
            pass
    try:
        payload = json.loads(result.get("out") or "")
    except ValueError:
        raise RuntimeError(
            f"claude -p produced no JSON (exit {proc.returncode}): {(result.get('err') or '')[:300]}"
        ) from None
    if payload.get("is_error"):
        raise RuntimeError(
            f"claude -p failed: {payload.get('subtype')} {str(payload.get('result'))[:300]}"
        )
    if not isinstance(payload.get("structured_output"), dict):
        raise RuntimeError("claude -p returned no structured_output")
    return payload


def _usage(payload: dict[str, Any]) -> dict[str, int]:
    usage = payload.get("usage") or {}
    tokens_in = sum(
        int(usage.get(k) or 0)
        for k in (
            "input_tokens",
            "cache_creation_input_tokens",
            "cache_read_input_tokens",
        )
    )
    tokens_out = int(usage.get("output_tokens") or 0)
    return {
        "input_tokens": tokens_in,
        "output_tokens": tokens_out,
        "total_tokens": tokens_in + tokens_out,
    }


def _decide(
    *,
    model: str,
    effort: str = "",
    messages: list[Any],
    tools: list[dict[str, Any]],
    timeout: float,
    cancel_event: threading.Event,
) -> Optional[_Decision]:
    """Ask the CLI for the next step; refused calls are fed back for a new choice.

    Every attempt shares one deadline, so feedback retries cannot stretch a
    decision past ``timeout``.
    """
    deadline = time.monotonic() + timeout
    offered = offered_tools(tools)
    offered_names = {tool_name(t) for t in offered}
    system, user_input = _render(messages)
    allow_tools = bool(offered)
    system += (
        (_PROTOCOL + json.dumps(offered, ensure_ascii=False))
        if allow_tools
        else _FINAL_ONLY
    )
    decision = _Decision()
    for _ in range(_MAX_RETRIES + 1):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError(f"claude-cli: decision exceeded {timeout:.0f}s")
        payload = _run_cli(
            system=system,
            user_input=user_input,
            allow_tools=allow_tools,
            model=model,
            effort=effort,
            timeout=remaining,
            cancel_event=cancel_event,
        )
        if payload.get("cancelled"):
            return None
        # The loop reads input_tokens as the current context size; summing the
        # re-sent prompt over feedback retries would double it and compact early.
        attempt = _usage(payload)
        decision.usage["input_tokens"] = attempt["input_tokens"]
        decision.usage["output_tokens"] += attempt["output_tokens"]
        decision.usage["total_tokens"] = (
            decision.usage["input_tokens"] + decision.usage["output_tokens"]
        )
        output = payload["structured_output"]
        calls = (
            (output.get("tool_calls") or [])
            if allow_tools and output.get("action") == "tool_calls"
            else []
        )
        if not calls:
            # Under --json-schema, payload["result"] is the structured output as text, so
            # an empty content must not fall back to it: the user would see raw JSON.
            content = str(output.get("content") or "")
            if content.strip():
                decision.content = content
                return decision
            user_input += (
                "\n\n[host] Your reply had no tool calls and no content, so the user saw nothing. "
                "Reply again with action=final and the complete answer in content."
            )
            failure = "final answers kept arriving without content"
            continue
        accepted, notes = screen_calls(calls, offered_names)
        if not notes:
            decision.content = str(output.get("content") or "")
            decision.tool_calls = [
                {
                    "id": f"ccli_{uuid.uuid4().hex[:8]}_{i}",
                    "name": c["name"],
                    "args": c["arguments"],
                }
                for i, c in enumerate(accepted)
            ]
            return decision
        user_input += (
            "\n\n[host] These tool calls were rejected and NOT executed:\n"
            + "\n".join(notes)
            + "\nChoose different calls or answer with what you have."
        )
        failure = "tool calls kept violating the host policy: " + "; ".join(notes)
    raise RuntimeError(f"claude-cli: {failure}")


class ClaudeCliLLM:
    """LangChain-compatible wrapper around the local ``claude -p`` CLI."""

    _llm_type = "claude-cli"

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        timeout: int = 120,
        reasoning_effort: str = "",
        tools: list[dict[str, Any]] | None = None,
    ) -> None:
        """Configure one CLI-backed model.

        Args:
            model: Full model name or CLI alias, passed to ``--model``.
            timeout: Per-decision budget in seconds; never below
                ``_TIMEOUT_FLOOR_S``.
            reasoning_effort: Level passed as ``--effort``; values outside
                ``CLAUDE_CLI_EFFORT_LEVELS`` leave the model's default.
            tools: Tool definitions in OpenAI function format.

        Raises:
            RuntimeError: ``CLAUDE_CLI_BASH_POLICY`` is not a known policy, so
                the error surfaces before a paid turn rather than after one.
        """
        bash_policy()
        self.model = model
        self.timeout = timeout
        self.reasoning_effort = reasoning_effort
        self.tools = tools or []

    def bind_tools(self, tools: list[dict[str, Any]]) -> "ClaudeCliLLM":
        """Return a copy that offers *tools* to the model.

        Args:
            tools: Tool definitions in OpenAI function format.

        Returns:
            A new instance with the same model, timeout and reasoning effort.
        """
        return ClaudeCliLLM(
            model=self.model,
            timeout=self.timeout,
            reasoning_effort=self.reasoning_effort,
            tools=tools,
        )

    def _budget(self, config: Optional[dict[str, Any]]) -> float:
        # Vibe sizes timeouts for one HTTP request; one CLI turn also pays for
        # process start-up and prompt-cache creation, so keep a higher floor.
        return float(
            max((config or {}).get("timeout") or self.timeout or 0, _TIMEOUT_FLOOR_S)
        )

    def _message(self, decision: _Decision) -> AIMessage:
        return AIMessage(
            content=decision.content,
            tool_calls=decision.tool_calls,
            usage_metadata=decision.usage,
            response_metadata={
                "finish_reason": "tool_calls" if decision.tool_calls else "stop",
                "model_name": self.model,
            },
        )

    def invoke(
        self, messages: list[Any], config: Optional[dict[str, Any]] = None, **_: Any
    ) -> AIMessage:
        """Run one decision and return it as a single message.

        Args:
            messages: Conversation so far, as LangChain messages or dicts.
            config: Optional run config; its ``timeout`` raises the budget above
                the floor.

        Returns:
            The final answer, or the tool calls to execute next.
        """
        decision = _decide(
            model=self.model,
            effort=self.reasoning_effort,
            messages=messages,
            tools=self.tools,
            timeout=self._budget(config),
            cancel_event=threading.Event(),
        )
        return self._message(decision or _Decision())

    def stream(
        self, messages: list[Any], config: Optional[dict[str, Any]] = None, **_: Any
    ) -> Iterable[AIMessageChunk]:
        """Run one decision, yielding an empty chunk every second until it lands.

        Args:
            messages: Conversation so far, as LangChain messages or dicts.
            config: Optional run config; its ``timeout`` raises the budget above
                the floor.

        Yields:
            Empty keep-alive chunks while the CLI runs, then one chunk carrying
            the answer or tool calls. Closing the iterator kills the child.
        """
        chunks: queue.Queue[Any] = queue.Queue()
        sentinel = object()
        cancel_event = threading.Event()
        budget = self._budget(config)

        def run() -> None:
            try:
                decision = _decide(
                    model=self.model,
                    effort=self.reasoning_effort,
                    messages=messages,
                    tools=self.tools,
                    timeout=budget,
                    cancel_event=cancel_event,
                )
                if decision is not None:
                    chunks.put(
                        AIMessageChunk(
                            content=decision.content,
                            tool_call_chunks=[
                                {
                                    "id": call["id"],
                                    "name": call["name"],
                                    "args": json.dumps(
                                        call["args"], ensure_ascii=False
                                    ),
                                    "index": index,
                                    "type": "tool_call_chunk",
                                }
                                for index, call in enumerate(decision.tool_calls)
                            ],
                            usage_metadata=decision.usage,
                            response_metadata={
                                "finish_reason": (
                                    "tool_calls" if decision.tool_calls else "stop"
                                ),
                                "model_name": self.model,
                            },
                        )
                    )
            except Exception as exc:
                chunks.put(exc)
            finally:
                chunks.put(sentinel)

        threading.Thread(target=run, daemon=True).start()
        try:
            while True:
                try:
                    chunk = chunks.get(timeout=_HEARTBEAT_S)
                except queue.Empty:
                    # One decision is a single chunk that can take minutes. Without
                    # empty chunks meanwhile, vibe's idle timeout discards an answer
                    # that is still on its way and the stop button is never polled.
                    yield AIMessageChunk(content="")
                    continue
                if chunk is sentinel:
                    return
                if isinstance(chunk, Exception):
                    raise chunk
                yield chunk
        finally:
            # Closing the iterator (vibe's cooperative cancel) kills the child.
            cancel_event.set()

    async def ainvoke(
        self,
        messages: list[Any],
        config: Optional[dict[str, Any]] = None,
        **kwargs: Any,
    ) -> AIMessage:
        """Run :meth:`invoke` in a worker thread.

        Args:
            messages: Conversation so far, as LangChain messages or dicts.
            config: Optional run config, passed through to :meth:`invoke`.
            **kwargs: Passed through to :meth:`invoke`.

        Returns:
            The message :meth:`invoke` returns.
        """
        return await asyncio.to_thread(self.invoke, messages, config, **kwargs)
