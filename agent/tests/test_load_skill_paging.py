"""Regression: an oversized skill must be reachable, and the cut must be stated.

Skill documents are the implementation for much of this product — the bond
maths, the implied-vol solver, the impact models, the China market structure.
A tool result is capped at ``TOOL_RESULT_LIMIT`` characters and 31 of the 88
bundled skills exceed it: ``tushare`` delivered 9.7% of its ~103k characters,
``options-payoff`` 33.8%, ``credit-analysis`` 43.0%. The cut was silent, so the
agent could not tell an amputated document from a complete one and had no way
to reach the remainder.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.agent.loop import TOOL_RESULT_LIMIT
from src.agent.skills import SkillsLoader
from src.tools.load_skill_tool import LoadSkillTool

_SKILL_ROOT = Path(__file__).resolve().parents[1] / "src" / "skills"


def _skill_names() -> list[str]:
    return sorted(path.parent.name for path in _SKILL_ROOT.glob("*/SKILL.md"))


def _read_all(tool: LoadSkillTool, name: str) -> tuple[str, int, int]:
    """Page a skill to completion; return (text, page_count, longest_envelope)."""
    offset, pages, chunks, longest = 0, 0, [], 0
    while True:
        raw = tool.execute(name=name, offset=offset)
        longest = max(longest, len(raw))
        payload = json.loads(raw)
        assert payload["status"] == "ok", payload
        pages += 1
        chunks.append(payload["content"])
        if payload["complete"]:
            return "".join(chunks), pages, longest
        offset = payload["next_offset"]
        assert pages < 400, f"{name} did not converge"


@pytest.fixture(scope="module")
def tool() -> LoadSkillTool:
    return LoadSkillTool()


class TestEnvelopeStatesWhatItDelivered:
    """A partial read must never look like a whole document."""

    def test_a_long_skill_reports_that_it_is_incomplete(self, tool):
        payload = json.loads(tool.execute(name="tushare"))

        assert payload["complete"] is False
        assert payload["next_offset"] > 0
        assert payload["total_chars"] > len(payload["content"])

    def test_a_short_skill_reports_that_it_is_complete(self, tool):
        name = min(_skill_names(), key=lambda n: len(SkillsLoader().get_content(n)))
        payload = json.loads(tool.execute(name=name))

        assert payload["complete"] is True
        assert payload["next_offset"] is None

    def test_an_unknown_skill_still_errors(self, tool):
        payload = json.loads(tool.execute(name="no-such-skill-here"))

        assert payload["status"] == "error"

    def test_a_non_integer_offset_is_rejected(self, tool):
        payload = json.loads(tool.execute(name="tushare", offset="banana"))

        assert payload["status"] == "error"

    def test_an_offset_past_the_end_is_rejected(self, tool):
        payload = json.loads(tool.execute(name="tushare", offset=10_000_000))

        assert payload["status"] == "error"


class TestEverySkillIsFullyReachable:
    """Paging must reconstruct each document exactly, without breaching the cap."""

    def test_no_single_page_exceeds_the_tool_result_limit(self, tool):
        # The cap applies to the serialized envelope, and JSON escaping is
        # content-dependent — a newline-dense page costs two characters a line.
        oversized = []
        for name in _skill_names():
            _, _, longest = _read_all(tool, name)
            if longest > TOOL_RESULT_LIMIT:
                oversized.append((name, longest))

        assert oversized == []

    def test_paging_reconstructs_every_skill_byte_for_byte(self, tool):
        loader = SkillsLoader()
        mismatched = [
            name for name in _skill_names() if _read_all(tool, name)[0] != loader.get_content(name)
        ]

        assert mismatched == []

    def test_the_largest_skill_pages_in_a_sane_number_of_calls(self, tool):
        _, pages, _ = _read_all(tool, "tushare")

        assert 1 < pages <= 20
