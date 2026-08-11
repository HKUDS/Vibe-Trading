"""Regression test: auto-compaction must not silently drop head content.

Issue #1055. ``AgentLoop._auto_compact`` used to serialize the head with a
hard ``json.dumps(head)[:80000]`` slice. Once the head exceeded the slice,
everything past the cut was neither fed to the summarization LLM nor kept in
the preserved tail — silent information loss, contradicting the method's own
"zero info decay" contract.

The fix folds the head through the summarization LLM in budget-sized,
message-boundary chunks. Every head message must reach the summarization
prompt exactly once, so no marker may end up in neither the summarization
prompts nor the reconstructed conversation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.agent.loop import (
    COMPACT_HEAD_CHAR_BUDGET,
    AgentLoop,
    _chunk_messages_for_summary,
)
from src.agent.trace import TraceWriter


class _RecordingLLM:
    """Records every summarization prompt _auto_compact sends."""

    model_name = "stub"

    def __init__(self) -> None:
        self.prompts: list[str] = []

    class _Resp:
        content = "STUB_SUMMARY"
        tool_calls: list[Any] = []
        reasoning_content = None
        has_tool_calls = False

    def chat(self, messages: list[dict[str, Any]], **_: Any) -> Any:
        self.prompts.append(messages[0]["content"])
        return self._Resp()


def _build_agent(llm: Any, tmp_run_dir: Path) -> AgentLoop:
    from src.memory.persistent import PersistentMemory
    from src.tools import build_registry

    pm = PersistentMemory()
    agent = AgentLoop(
        registry=build_registry(persistent_memory=pm, include_shell_tools=False),
        llm=llm,
        event_callback=None,
        max_iterations=1,
        persistent_memory=pm,
    )
    tmp_run_dir.mkdir(parents=True, exist_ok=True)
    agent.memory.run_dir = str(tmp_run_dir)
    return agent


def test_auto_compact_does_not_drop_head_content_beyond_slice(tmp_path: Path) -> None:
    """Reproduces issue #1055: an oversized head must not lose any message."""
    llm = _RecordingLLM()
    agent = _build_agent(llm, tmp_path / "run")
    trace = TraceWriter(tmp_path / "trace")

    # 20 tagged messages sized so the head (everything outside the ~20K-token
    # tail) serializes past the old 80,000-character slice.
    messages: list[dict[str, str]] = [{"role": "system", "content": "system prompt"}]
    messages += [
        {"role": "user", "content": f"MARKER_{i} " + ("alpha " * 2000)}
        for i in range(20)
    ]

    try:
        agent._auto_compact(messages, tmp_path / "run", trace, iteration=1)
    finally:
        trace.close()

    all_prompts = "\n".join(llm.prompts)
    final_transcript = json.dumps(messages, default=str)

    lost = [
        i
        for i in range(20)
        if f"MARKER_{i} " not in all_prompts and f"MARKER_{i} " not in final_transcript
    ]
    assert lost == [], f"messages dropped by auto-compaction: {lost}"
    # The oversized head must have been folded through more than one pass.
    assert len(llm.prompts) >= 2


def test_chunk_messages_for_summary_covers_every_message_exactly_once() -> None:
    messages = [{"role": "user", "content": f"msg-{i} " + ("x" * 500)} for i in range(30)]
    chunks = _chunk_messages_for_summary(messages, 8000)

    flattened = [msg for chunk in chunks for msg in chunk]
    assert flattened == messages
    for chunk in chunks:
        assert len(json.dumps(chunk, default=str, ensure_ascii=False)) <= 8000


def test_chunk_messages_for_summary_keeps_oversized_single_message() -> None:
    big = {"role": "user", "content": "y" * (COMPACT_HEAD_CHAR_BUDGET + 1000)}
    chunks = _chunk_messages_for_summary([big], COMPACT_HEAD_CHAR_BUDGET)

    assert chunks == [[big]]


def test_chunk_messages_for_summary_empty_input() -> None:
    assert _chunk_messages_for_summary([], COMPACT_HEAD_CHAR_BUDGET) == []
