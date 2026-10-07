"""Regression tests for lossless, chunked auto-compaction summaries."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from src.agent.loop import AgentLoop, _summary_chunks
from src.agent.tools import ToolRegistry
from src.agent.trace import TraceWriter


class _CompactionLLM:
    """Stub LLM that records compaction prompts and returns queued summaries."""

    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.prompts: list[str] = []

    def chat(self, messages: list[dict[str, Any]], **_: Any) -> Any:
        self.prompts.append(messages[0]["content"])
        return SimpleNamespace(content=self.responses.pop(0))


def _build_agent(llm: Any) -> AgentLoop:
    """Build an AgentLoop with the same lightweight registry pattern as loop tests."""
    return AgentLoop(registry=ToolRegistry(), llm=llm, max_iterations=1)


def test_replayed_payload_and_call_pair_survive_collapse_and_summary_until_request(tmp_path):
    from src.agent import loop as loop_mod
    payload = "replayed evidence " + "x" * 9000
    call = {"role": "assistant", "content": "", "tool_calls": [
        {"id": "leased", "type": "function", "function": {"name": "probe", "arguments": "{}"}}]}
    result = {"role": "tool", "tool_call_id": "leased", "name": "probe", "content": payload}
    messages = [{"role": "system", "content": "system"}, {"role": "user", "content": "old goal"},
                call, result, *[{"role": "user", "content": "tail" + "t" * 30000} for _ in range(4)]]
    agent = _build_agent(_CompactionLLM(["Earlier work summarized."] * 10))
    agent._readonly_replay_visibility_pending = {"leased"}
    loop_mod._context_collapse(messages, preserve_tool_call_ids={"leased"})
    assert result["content"] == payload
    with_trace = TraceWriter(tmp_path / "trace")
    try:
        agent._auto_compact(messages, tmp_path, with_trace)
        assert any(message.get("content") == payload for message in messages)
        assert any(any(tc.get("id") == "leased" for tc in message.get("tool_calls", [])) for message in messages)
        assert agent._readonly_replay_visibility_pending == {"leased"}
        agent._consume_readonly_replay_visibility(messages, with_trace, 1)
        assert agent._readonly_replay_visibility_pending == set()
    finally:
        with_trace.close()


def test_summary_chunks_single_chunk_matches_json_dumps() -> None:
    """The common one-chunk path must preserve the original prompt bytes."""
    messages = [
        {"role": "user", "content": "请保留 unicode、emoji 🚀 和 punctuation"},
        {"role": "assistant", "content": "ack", "metadata": {"n": 1}},
    ]

    chunks = _summary_chunks(messages)

    assert len(chunks) == 1
    assert chunks[0] == json.dumps(messages, default=str, ensure_ascii=False)


def test_summary_chunks_cover_every_message_at_message_boundaries() -> None:
    """Multiple ordinary chunks contain every whole message exactly once."""
    messages = [
        {
            "role": "user",
            "content": f"__CHUNK_MESSAGE_{index}__ " + ("x" * 80),
        }
        for index in range(5)
    ]

    chunks = _summary_chunks(messages, limit=220)

    assert len(chunks) >= 3
    assert all(len(chunk) <= 220 for chunk in chunks)
    for index in range(5):
        marker = f"__CHUNK_MESSAGE_{index}__"
        assert sum(chunk.count(marker) for chunk in chunks) == 1
    decoded = [message for chunk in chunks for message in json.loads(chunk)]
    assert decoded == messages


def test_summary_chunks_preserve_oversized_message_as_labeled_fragments() -> None:
    """Fragment bodies concatenate back to the exact oversized raw JSON."""
    message = {"role": "user", "content": "__OVERSIZED__" + ("z" * 500)}
    raw = json.dumps(message, default=str, ensure_ascii=False)

    chunks = _summary_chunks([message], limit=180)

    assert len(chunks) > 1
    assert all(len(chunk) <= 180 for chunk in chunks)
    fragments: list[str] = []
    for index, chunk in enumerate(chunks, start=1):
        prefix, fragment = chunk.split("\n", 1)
        assert f"fragment {index}/{len(chunks)}" in prefix
        assert "raw JSON slice, not valid JSON on its own" in prefix
        fragments.append(fragment)
    assert "".join(fragments) == raw


def test_auto_compact_folds_all_head_chunks_and_preserves_empty_update(
    tmp_path: Path,
) -> None:
    """Every head marker reaches a summary call and empty updates keep state."""
    markers = [f"__HEAD_MESSAGE_{index:02d}__" for index in range(6)]
    head_messages = [
        {
            "role": "user",
            "content": marker + " " + ("x" * 29_900),
        }
        for marker in markers
    ]
    # These two messages occupy the token-budget tail; all markers are in the
    # six-message head and therefore must reach the folding calls.
    tail_messages = [
        {"role": "user", "content": "tail filler " + ("t" * 29_900)},
        {"role": "assistant", "content": "tail filler " + ("u" * 29_900)},
    ]
    messages = [{"role": "system", "content": "system prompt"}, *head_messages, *tail_messages]
    llm = _CompactionLLM(["summary-0", "", "summary-2"])
    agent = _build_agent(llm)
    trace = TraceWriter(tmp_path / "trace")

    try:
        agent._auto_compact(messages, tmp_path / "run", trace, iteration=7)
    finally:
        trace.close()

    assert len(llm.prompts) == 3
    assert "Summarize this conversation for handoff" in llm.prompts[0]
    assert llm.prompts[1].startswith("Update the existing summary")
    assert llm.prompts[2].startswith("Update the existing summary")
    assert "summary-0" in llm.prompts[1]
    # The second response was empty; its predecessor must still be supplied to
    # the third fold and remain available after compaction.
    assert "summary-0" in llm.prompts[2]
    assert agent._previous_summary == "summary-2"

    for marker in markers:
        assert sum(prompt.count(marker) for prompt in llm.prompts) == 1

    compact_entries = [
        entry for entry in TraceWriter.read(tmp_path / "trace") if entry.get("type") == "compact"
    ]
    assert len(compact_entries) == 1
    assert compact_entries[0]["summary_chunks"] == len(llm.prompts)
