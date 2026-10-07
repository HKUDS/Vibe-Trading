"""Codex adapter: what the model sees on the next request of a run.

Event shapes follow Codex CLI's own test helpers (openai/codex
``codex-rs/core/tests/common/responses.rs``: ``ev_reasoning_item`` — a
``response.output_item.done`` whose item is ``{type: reasoning, id, summary,
encrypted_content}`` — and ``ev_function_call``, whose item carries
``call_id``/``name``/``arguments`` and no ``id``). Codex CLI replays reasoning
items as API input (``context_manager/history.rs`` ``is_api_message``) and sends
added instructions as ``developer`` messages (``context/base_instructions.rs``).
"""

from __future__ import annotations

import base64
import json

import pytest

import src.providers.openai_codex as codex_mod
from src.agent.context import ContextBuilder
from src.providers.chat import ChatLLM
from src.providers.openai_codex import (
    CodexToolCall,
    OpenAICodexLLM,
    _convert_messages,
    _events_from_lines,
    _message_chunks_from_events,
    _prompt_cache_key,
)
from src.providers.session_context import bind_llm_session_id, reset_llm_session_id

SYSTEM_PROMPT = "You are the research agent. " * 2000  # ~54K chars, like the real one


def ev_reasoning_item(item_id: str, summary: list[str], raw: str) -> dict:
    return {
        "type": "response.output_item.done",
        "item": {
            "type": "reasoning",
            "id": item_id,
            "summary": [{"type": "summary_text", "text": text} for text in summary],
            "encrypted_content": base64.b64encode(("b" * 550 + raw).encode()).decode(),
        },
    }


def ev_function_call(call_id: str, name: str, arguments: str) -> dict:
    return {
        "type": "response.output_item.done",
        "item": {"type": "function_call", "call_id": call_id, "name": name, "arguments": arguments},
    }


def ev_completed() -> dict:
    return {
        "type": "response.completed",
        "response": {"id": "resp_1", "status": "completed",
                     "usage": {"input_tokens": 90_000, "output_tokens": 40, "total_tokens": 90_040}},
    }


def _sse(*events: dict) -> list[str]:
    lines: list[str] = []
    for event in events:
        lines += [f"data: {json.dumps(event)}", ""]
    return lines


def _accumulate(lines: list[str]):
    total = None
    for chunk in _message_chunks_from_events(_events_from_lines(lines)):
        total = chunk if total is None else total + chunk
    return total


def _turn_one():
    return _accumulate(_sse(
        ev_reasoning_item("rs_1", ["Plan: fetch both"], "need 002555 and 002624 filings"),
        ev_function_call("call_a", "get_financial_statements", '{"code": "002555.SZ"}'),
        ev_function_call("call_b", "get_financial_statements", '{"code": "002624.SZ"}'),
        ev_completed(),
    ))


def _history_after_turn_one() -> list[dict]:
    """Loop messages after turn one ran, built by the loop's own helpers."""
    response = ChatLLM._parse_response(_turn_one())
    assistant = ContextBuilder.format_assistant_tool_calls(
        response.tool_calls,
        content=response.content,
        reasoning_content=response.reasoning_content,
        provider_items=response.provider_items,
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "Compare A-share game companies."},
        assistant,
        {"role": "tool", "tool_call_id": response.tool_calls[0].id, "content": '{"ok": true}'},
        {"role": "tool", "tool_call_id": response.tool_calls[1].id, "content": '{"ok": true}'},
    ]


def test_reasoning_items_travel_back_ahead_of_their_calls() -> None:
    _, items = _convert_messages(_history_after_turn_one())
    kinds = [item.get("type") or item.get("role") for item in items]

    assert kinds == ["user", "reasoning", "function_call", "function_call",
                     "function_call_output", "function_call_output"]
    reasoning = items[1]
    assert reasoning["id"] == "rs_1"
    assert reasoning["encrypted_content"]
    assert reasoning["summary"] == [{"type": "summary_text", "text": "Plan: fetch both"}]
    assert "content" not in reasoning  # plaintext never goes back


def test_replay_can_be_switched_off() -> None:
    _, items = _convert_messages(_history_after_turn_one(), replay_reasoning=False)
    assert all(item.get("type") != "reasoning" for item in items)


def test_calls_without_backend_ids_are_not_given_made_up_ones() -> None:
    """Two parallel calls used to both be sent back as id "fc_0"."""
    _, items = _convert_messages(_history_after_turn_one())
    calls = [item for item in items if item.get("type") == "function_call"]

    assert [call["call_id"] for call in calls] == ["call_a", "call_b"]
    assert all("id" not in call for call in calls)
    outputs = [item["call_id"] for item in items if item.get("type") == "function_call_output"]
    assert outputs == ["call_a", "call_b"]


def test_backend_issued_call_ids_are_kept() -> None:
    lines = _sse(
        {"type": "response.output_item.added",
         "item": {"type": "function_call", "call_id": "call_1", "id": "fc_real", "name": "bash", "arguments": ""}},
        {"type": "response.output_item.done",
         "item": {"type": "function_call", "call_id": "call_1", "id": "fc_real", "name": "bash",
                  "arguments": '{"command": "pwd"}'}},
    )
    message = _accumulate(lines)
    assert message.tool_calls == [{"id": "call_1|fc_real", "name": "bash", "args": {"command": "pwd"}}]
    _, items = _convert_messages([
        {"role": "system", "content": "s"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "call_1|fc_real", "type": "function",
             "function": {"name": "bash", "arguments": '{"command": "pwd"}'}}]},
    ])
    assert items[0]["id"] == "fc_real" and items[0]["call_id"] == "call_1"


def test_a_mid_run_system_message_does_not_replace_the_system_prompt() -> None:
    """The loop appends system messages mid-run; each one used to become
    ``instructions`` and every later request lost the whole system prompt."""
    messages = _history_after_turn_one() + [
        {"role": "system", "content": "[SYSTEM] Your previous response was empty."},
        {"role": "system", "content": "[SYSTEM] Write the pending file now."},
    ]
    instructions, items = _convert_messages(messages)

    assert instructions == SYSTEM_PROMPT
    developer = [item for item in items if item.get("role") == "developer"]
    assert [item["content"][0]["text"] for item in developer] == [
        "[SYSTEM] Your previous response was empty.",
        "[SYSTEM] Write the pending file now.",
    ]


def test_prompt_cache_key_is_stable_for_a_session_and_differs_between_sessions() -> None:
    token = bind_llm_session_id("session-a")
    try:
        first = _prompt_cache_key(SYSTEM_PROMPT)
        second = _prompt_cache_key(SYSTEM_PROMPT)
    finally:
        reset_llm_session_id(token)
    token = bind_llm_session_id("session-b")
    try:
        other = _prompt_cache_key(SYSTEM_PROMPT)
    finally:
        reset_llm_session_id(token)

    assert first == second
    assert first != other
    # Unbound: stable per system prompt, never per message list.
    assert _prompt_cache_key(SYSTEM_PROMPT) == _prompt_cache_key(SYSTEM_PROMPT)


def test_body_uses_the_session_key_across_turns() -> None:
    adapter = OpenAICodexLLM(model="openai-codex/gpt-6-sol")
    history = _history_after_turn_one()
    token = bind_llm_session_id("session-a")
    try:
        early = adapter._body(history[:2], stream=True)["prompt_cache_key"]
        late = adapter._body(history, stream=True)["prompt_cache_key"]
    finally:
        reset_llm_session_id(token)
    assert early == late


class _Response:
    def __init__(self, status_code: int, body: bytes = b"", lines: list[str] | None = None) -> None:
        self.status_code = status_code
        self._body = body
        self._lines = lines or []

    def __enter__(self):
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body

    def iter_lines(self):
        return iter(self._lines)


@pytest.fixture
def fresh_replay_state(monkeypatch):
    monkeypatch.setattr(codex_mod, "_REASONING_REPLAY_REJECTED", set())


def _client_returning(responses: list[_Response], sent: list[dict]):
    class _Client:
        def __init__(self, **kwargs: object) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def stream(self, method: str, url: str, **kwargs: object) -> _Response:
            sent.append(kwargs["json"])
            return responses.pop(0)

    return _Client


def test_a_refused_reasoning_replay_is_resent_without_it(monkeypatch, fresh_replay_state) -> None:
    sent: list[dict] = []
    ok = _Response(200, lines=_sse({"type": "response.output_text.delta", "delta": "done"}, ev_completed()))
    refused = _Response(400, b'{"error": {"message": "Invalid reasoning item rs_1: encrypted_content could not be verified"}}')
    monkeypatch.setattr(codex_mod.httpx, "Client", _client_returning([refused, ok], sent))
    adapter = OpenAICodexLLM(model="openai-codex/gpt-6-sol")
    adapter._headers = lambda **kwargs: {}

    text = "".join(chunk.content for chunk in adapter.stream(_history_after_turn_one()))

    assert text == "done"
    assert [any(i.get("type") == "reasoning" for i in body["input"]) for body in sent] == [True, False]
    assert "gpt-6-sol" in codex_mod._REASONING_REPLAY_REJECTED


def test_an_unrelated_400_is_not_retried(monkeypatch, fresh_replay_state) -> None:
    sent: list[dict] = []
    refused = _Response(400, b'{"detail": "The model is not supported when using Codex with a ChatGPT account."}')
    monkeypatch.setattr(codex_mod.httpx, "Client", _client_returning([refused], sent))
    adapter = OpenAICodexLLM(model="openai-codex/gpt-6-sol")
    adapter._headers = lambda **kwargs: {}

    with pytest.raises(codex_mod.CodexStreamError):
        list(adapter.stream(_history_after_turn_one()))
    assert len(sent) == 1
    assert codex_mod._REASONING_REPLAY_REJECTED == set()


def test_tool_call_ids_round_trip_through_the_parser() -> None:
    message = _turn_one()
    assert [call["id"] for call in message.tool_calls] == ["call_a", "call_b"]
    assert CodexToolCall(id="call_a", name="x", arguments={}).as_langchain_tool_call()["id"] == "call_a"
    assert [item["id"] for item in message.additional_kwargs["provider_items"]] == ["rs_1"]
