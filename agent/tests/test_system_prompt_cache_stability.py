"""System-prompt cache stability (issue #1707).

``WorkspaceMemory.to_summary()`` renders ``run_dir`` (a fresh
``timestamp_uuid`` directory per run) and tool ``counters`` (bumped on every
tool call). Rendering that summary into the system prompt meant the prompt
bytes changed on every turn and every tool call, invalidating the provider
prefix cache — including the ``cache_control`` block the Anthropic adapter
marks on the system message — for everything after the ``## State`` section.

The fix: the volatile summary rides the first **user** message wrapped in an
``<agent-state>`` envelope (same convention as ``<recalled-memories>``), and
the system template no longer has a ``## State`` section. The system prompt is
now byte-identical across runs as long as the registry, skills, and date
minute do not change.
"""

from __future__ import annotations

import pytest

from src.agent.context import ContextBuilder
from src.agent.memory import WorkspaceMemory
from src.agent.tools import ToolRegistry

pytestmark = pytest.mark.unit


def _builder(memory: WorkspaceMemory) -> ContextBuilder:
    return ContextBuilder(ToolRegistry(), memory)


class TestSystemPromptCacheStability:
    def test_prompt_is_byte_identical_when_run_dir_and_counters_change(self) -> None:
        """Different run_dir / counters must not change the system prompt."""
        m1 = WorkspaceMemory()
        m1.run_dir = "/runs/20260101_000000_abcdef"
        m1.increment("get_market_data")

        m2 = WorkspaceMemory()
        m2.run_dir = "/runs/20260102_111111_fedcba"
        m2.increment("get_market_data")
        m2.increment("get_market_data")
        m2.increment("backtest")

        # Freeze the clock so only run_dir/counters differ between the two.
        import src.agent.context as ctx
        from datetime import datetime, timezone

        frozen = datetime(2026, 10, 6, 12, 0, 0, tzinfo=timezone.utc)
        orig = ctx.datetime

        class _FrozenDatetime:
            @staticmethod
            def now(tz=None):
                return frozen if tz is not None else frozen.replace(tzinfo=None)

        try:
            ctx.datetime = _FrozenDatetime  # type: ignore[assignment]
            p1 = _builder(m1).build_system_prompt("hello")
            p2 = _builder(m2).build_system_prompt("hello")
        finally:
            ctx.datetime = orig

        assert p1 == p2

    def test_state_section_removed_from_system_template(self) -> None:
        assert "## State" not in _builder(WorkspaceMemory()).build_system_prompt("x")

    def test_volatile_state_rides_first_user_message(self) -> None:
        m = WorkspaceMemory()
        m.run_dir = "/runs/20260101_000000_abcdef"
        m.increment("backtest")

        messages = _builder(m).build_messages("analyze AAPL")

        assert messages[0]["role"] == "system"
        # The template's static Task Routing text may mention the literal
        # "run_dir" parameter; what must NOT appear is the volatile value.
        assert "/runs/20260101_000000_abcdef" not in messages[0]["content"]
        assert "counters:" not in messages[0]["content"]
        user = messages[-1]["content"]
        assert user.startswith("<agent-state>")
        assert "- run_dir: /runs/20260101_000000_abcdef" in user
        assert "counters: backtest=1" in user
        assert "analyze AAPL" in user

    def test_empty_state_leaves_user_message_untouched(self) -> None:
        messages = _builder(WorkspaceMemory()).build_messages("analyze AAPL")

        assert messages[-1]["content"] == "analyze AAPL"

    def test_state_envelope_sits_before_recalled_memories(self) -> None:
        class _Recall:
            title = "prefers conciseness"
            memory_type = "preference"
            body = "keep answers short"

        class _PersistentMemory:
            snapshot = None

            def find_relevant(self, query: str, max_results: int = 3):
                return [_Recall()]

        m = WorkspaceMemory()
        m.run_dir = "/runs/x"
        builder = ContextBuilder(ToolRegistry(), m, persistent_memory=_PersistentMemory())

        user = builder.build_messages("analyze AAPL")[-1]["content"]

        # Both envelopes ride the same user message; order between them does
        # not matter, but both must precede the raw user text.
        assert "<agent-state>" in user
        assert "<recalled-memories>" in user
        assert user.index("<agent-state>") < user.index("analyze AAPL")
        assert user.index("<recalled-memories>") < user.index("analyze AAPL")

    def test_state_envelope_stays_outside_user_message_tags(self) -> None:
        """loop.py may wrap the raw text in <user-message> tags (goal context).
        The state envelope must stay a sibling prefix, never nest inside —
        it must not look like user-typed input."""
        wrapped = "<goal-continuation>g</goal-continuation>\n\n<user-message>\nanalyze AAPL\n</user-message>"
        m = WorkspaceMemory()
        m.run_dir = "/runs/x"

        user = _builder(m).build_messages(wrapped)[-1]["content"]

        assert user.index("<agent-state>") < user.index("<user-message>")
        closing = user.index("</user-message>")
        opening = user.index("<user-message>")
        assert "<agent-state>" not in user[opening:closing]
