"""GitHub Copilot SDK adapter.

Authentication and transport are delegated to GitHub's supported SDK. The SDK
resolves ``COPILOT_GITHUB_TOKEN``, stored Copilot CLI credentials, and ``gh``
credentials without Vibe-Trading borrowing an OAuth client or editor identity.
"""

from __future__ import annotations

import asyncio
import json
import os
import queue
import shutil
import subprocess
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, Optional

from langchain_core.messages import AIMessage, AIMessageChunk

COPILOT_TOKEN_ENV = "COPILOT_GITHUB_TOKEN"
_SUPPORTED_TOKEN_PREFIXES = ("gho_", "ghu_", "github_pat_")


def is_supported_token(token: str) -> bool:
    """Return whether ``token`` is accepted by the Copilot SDK."""
    return bool(token) and token.startswith(_SUPPORTED_TOKEN_PREFIXES)


def gh_cli_token() -> str:
    """Return a supported token from ``gh auth token``, if available."""
    executable = shutil.which("gh")
    if not executable:
        return ""
    try:
        result = subprocess.run(
            [executable, "auth", "token"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    token = result.stdout.strip()
    return token if result.returncode == 0 and is_supported_token(token) else ""


def resolve_copilot_token() -> tuple[str, str]:
    """Resolve explicit credentials; the SDK handles stored CLI credentials."""
    for name in (COPILOT_TOKEN_ENV, "GH_TOKEN", "GITHUB_TOKEN"):
        token = os.getenv(name, "").strip()  # noqa: env-gate - provider credential
        if is_supported_token(token):
            return token, name
    token = gh_cli_token()
    return (token, "gh auth token") if token else ("", "")


def get_copilot_login_status() -> Optional[str]:
    """Return an explicit token, or None when the SDK must resolve login."""
    token, _source = resolve_copilot_token()
    return token or None


def _client_options() -> dict[str, str]:
    """Return explicit SDK options without disabling stored CLI credentials."""
    token, _source = resolve_copilot_token()
    return {"github_token": token} if token else {}


def get_copilot_auth_status() -> tuple[bool, str]:
    """Return the official SDK's authentication status."""
    result: queue.Queue[Any] = queue.Queue(maxsize=1)

    async def check() -> tuple[bool, str]:
        try:
            from copilot import CopilotClient
        except ImportError:
            return False, "github-copilot-sdk is not installed"

        async with CopilotClient(**_client_options()) as client:
            status = await client.get_auth_status()
            return bool(status.isAuthenticated), str(
                status.statusMessage or status.login or "not authenticated"
            )

    def run() -> None:
        try:
            result.put(asyncio.run(check()))
        except Exception as exc:
            result.put((False, f"{type(exc).__name__}: {exc}"))

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join()
    return result.get()


@dataclass
class _CopilotResult:
    content: str = ""
    model: str | None = None
    tool_calls: list[dict[str, Any]] | None = None


def _message_value(message: Any, key: str, default: Any = None) -> Any:
    if isinstance(message, dict):
        return message.get(key, default)
    return getattr(message, key, default)


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(item.get("text", ""))
            for item in content
            if isinstance(item, dict) and item.get("type") == "text"
        )
    return str(content or "")


def _convert_messages(messages: list[Any]) -> tuple[str, str]:
    """Convert chat history into one SDK turn while preserving role boundaries."""
    system: list[str] = []
    transcript: list[dict[str, Any]] = []
    for message in messages:
        role = str(_message_value(message, "role", "") or "")
        if not role:
            message_type = str(_message_value(message, "type", "") or "")
            role = {
                "human": "user",
                "ai": "assistant",
                "system": "system",
                "tool": "tool",
            }.get(message_type, message_type or "user")
        content = _content_text(_message_value(message, "content", ""))
        if role == "system":
            if content:
                system.append(content)
            continue
        item: dict[str, Any] = {"role": role, "content": content}
        tool_call_id = _message_value(message, "tool_call_id")
        if tool_call_id:
            item["tool_call_id"] = str(tool_call_id)
        tool_calls = _message_value(message, "tool_calls")
        if tool_calls:
            item["tool_calls"] = tool_calls
        transcript.append(item)

    prompt = (
        "Continue the following conversation and produce only the next assistant "
        "response. Preserve tool-call behavior.\n\n"
        + json.dumps(transcript, ensure_ascii=False, default=str)
    )
    return "\n\n".join(system), prompt


def _convert_tools(tools: list[dict[str, Any]]) -> list[Any]:
    try:
        from copilot.tools import Tool
    except ImportError as exc:
        raise RuntimeError(
            "GitHub Copilot requires github-copilot-sdk. Install project dependencies."
        ) from exc

    converted = []
    for entry in tools:
        function = entry.get("function", entry)
        name = str(function.get("name", "")).strip()
        if not name:
            continue
        parameters = function.get("parameters")
        converted.append(
            Tool(
                name=name,
                description=str(function.get("description", "") or ""),
                parameters=parameters if isinstance(parameters, dict) else {},
                overrides_built_in_tool=True,
                defer="never",
            )
        )
    return converted


async def _run_copilot(
    *,
    model: str,
    messages: list[Any],
    tools: list[dict[str, Any]],
    timeout: float,
    emit: Callable[[str, str], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> _CopilotResult:
    try:
        from copilot import CopilotClient, ToolSet
        from copilot.session_events import (
            AssistantMessageData,
            AssistantMessageDeltaData,
            AssistantReasoningDeltaData,
            ExternalToolRequestedData,
            SessionErrorData,
            SessionIdleData,
        )
    except ImportError as exc:
        raise RuntimeError(
            "GitHub Copilot requires github-copilot-sdk. Install project dependencies."
        ) from exc

    system_message, prompt = _convert_messages(messages)
    result = _CopilotResult(tool_calls=[])
    finished = asyncio.Event()
    tool_requested = asyncio.Event()
    error: list[Exception] = []

    def add_tool_call(tool_call_id: str, name: str, arguments: Any) -> None:
        assert result.tool_calls is not None
        if any(item["id"] == tool_call_id for item in result.tool_calls):
            return
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = {}
        result.tool_calls.append(
            {
                "id": tool_call_id,
                "name": name,
                "args": arguments if isinstance(arguments, dict) else {},
                "type": "tool_call",
            }
        )

    def on_event(event: Any) -> None:
        data = event.data
        if isinstance(data, AssistantMessageDeltaData):
            if emit and data.delta_content:
                emit("text", data.delta_content)
        elif isinstance(data, AssistantReasoningDeltaData):
            if emit and data.delta_content:
                emit("reasoning", data.delta_content)
        elif isinstance(data, AssistantMessageData):
            result.content = data.content or result.content
            result.model = data.model or result.model
            for request in data.tool_requests or []:
                add_tool_call(request.tool_call_id, request.name, request.arguments)
            if data.tool_requests:
                tool_requested.set()
        elif isinstance(data, ExternalToolRequestedData):
            add_tool_call(data.tool_call_id, data.tool_name, data.arguments)
            tool_requested.set()
        elif isinstance(data, SessionErrorData):
            error.append(RuntimeError(f"GitHub Copilot SDK error: {data.message}"))
            finished.set()
        elif isinstance(data, SessionIdleData):
            finished.set()

    # ponytail: one runtime per call keeps lifecycle simple; pool it if startup
    # latency becomes material in profiling.
    async with CopilotClient(**_client_options()) as client:
        sdk_tools = _convert_tools(tools)
        available_tools = ToolSet()
        for tool in sdk_tools:
            available_tools.add_custom(tool.name)
        session_options: dict[str, Any] = {
            "model": model,
            "tools": sdk_tools,
            "available_tools": available_tools,
            "streaming": emit is not None,
            "enable_config_discovery": False,
            "enable_session_store": False,
            "enable_skills": False,
            "skip_custom_instructions": True,
            "on_event": on_event,
        }
        if system_message:
            session_options["system_message"] = {
                "mode": "append",
                "content": system_message,
            }
        async with await client.create_session(**session_options) as session:
            await session.send(prompt)
            finish_task = asyncio.create_task(finished.wait())
            tool_task = asyncio.create_task(tool_requested.wait())

            async def watch_cancel() -> None:
                if cancel_event is None:
                    return
                while not cancel_event.is_set():
                    await asyncio.sleep(0.05)
                await session.abort()
                finished.set()

            cancel_task = asyncio.create_task(watch_cancel())
            try:
                done, _pending = await asyncio.wait_for(
                    asyncio.wait(
                        {finish_task, tool_task},
                        return_when=asyncio.FIRST_COMPLETED,
                    ),
                    timeout=timeout,
                )
                if tool_task in done:
                    # ponytail: 100 ms debounce collects parallel tool events;
                    # replace it if the SDK exposes an explicit batch-complete event.
                    await asyncio.sleep(0.1)
            finally:
                for task in (finish_task, tool_task, cancel_task):
                    task.cancel()
                await asyncio.gather(
                    finish_task,
                    tool_task,
                    cancel_task,
                    return_exceptions=True,
                )
            if result.tool_calls and not (cancel_event and cancel_event.is_set()):
                await session.abort()

    if error:
        raise error[0]
    return result


class CopilotSDKLLM:
    """Minimal LangChain-compatible wrapper around the official Copilot SDK."""

    def __init__(
        self,
        *,
        model: str,
        timeout: int = 120,
        tools: list[dict[str, Any]] | None = None,
    ) -> None:
        self.model = model
        self.timeout = timeout
        self.tools = tools or []

    def bind_tools(self, tools: list[dict[str, Any]]) -> "CopilotSDKLLM":
        return CopilotSDKLLM(model=self.model, timeout=self.timeout, tools=tools)

    def invoke(
        self,
        messages: list[Any],
        config: Optional[dict[str, Any]] = None,
    ) -> AIMessage:
        timeout = float((config or {}).get("timeout") or self.timeout)
        result = asyncio.run(
            _run_copilot(
                model=self.model,
                messages=messages,
                tools=self.tools,
                timeout=timeout,
            )
        )
        return AIMessage(
            content=result.content,
            tool_calls=result.tool_calls or [],
            response_metadata={
                "finish_reason": "tool_calls" if result.tool_calls else "stop",
                "model_name": result.model or self.model,
            },
        )

    def stream(
        self,
        messages: list[Any],
        config: Optional[dict[str, Any]] = None,
    ) -> Iterable[AIMessageChunk]:
        timeout = float((config or {}).get("timeout") or self.timeout)
        chunks: queue.Queue[Any] = queue.Queue()
        sentinel = object()
        cancel_event = threading.Event()

        def run() -> None:
            emitted_text = False

            def emit(kind: str, value: str) -> None:
                nonlocal emitted_text
                emitted_text = emitted_text or kind == "text"
                chunks.put(
                    AIMessageChunk(
                        content=value if kind == "text" else "",
                        additional_kwargs=(
                            {"reasoning_content": value} if kind == "reasoning" else {}
                        ),
                    )
                )

            try:
                result = asyncio.run(
                    _run_copilot(
                        model=self.model,
                        messages=messages,
                        tools=self.tools,
                        timeout=timeout,
                        emit=emit,
                        cancel_event=cancel_event,
                    )
                )
                if result.content and not emitted_text:
                    chunks.put(AIMessageChunk(content=result.content))
                if result.tool_calls:
                    chunks.put(
                        AIMessageChunk(
                            content="",
                            tool_call_chunks=[
                                {
                                    "id": call["id"],
                                    "name": call["name"],
                                    "args": json.dumps(call["args"]),
                                    "index": index,
                                    "type": "tool_call_chunk",
                                }
                                for index, call in enumerate(result.tool_calls)
                            ],
                            response_metadata={"finish_reason": "tool_calls"},
                        )
                    )
                else:
                    chunks.put(
                        AIMessageChunk(
                            content="",
                            response_metadata={
                                "finish_reason": "stop",
                                "model_name": result.model or self.model,
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
                chunk = chunks.get()
                if chunk is sentinel:
                    return
                if isinstance(chunk, Exception):
                    raise chunk
                yield chunk
        finally:
            cancel_event.set()

    async def ainvoke(
        self,
        messages: list[Any],
        config: Optional[dict[str, Any]] = None,
    ) -> AIMessage:
        return await asyncio.to_thread(self.invoke, messages, config)
