"""Prompt regressions for grounding ref repair."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.agent.grounding import GroundingLedger

pytestmark = pytest.mark.unit


def test_correction_prompt_requires_literal_refs_and_full_figures_block(tmp_path: Path) -> None:
    ledger = GroundingLedger(run_dir=tmp_path, user_message="Analyze portfolio risk")
    validation = ledger.validate_final_answer("Portfolio value is 1234.5.")

    prompt = ledger.correction_prompt(validation)

    assert "exact literal tool names or exact call ids" in prompt
    assert "Do not append labels, scopes, parentheses or prose to a ref" in prompt
    assert "prefer exact call ids" in prompt
    assert "Return the FULL revised answer" in prompt
    assert "Preserve or rebuild the final figures block on every revision" in prompt
    assert "normalized raw number" in prompt or "normalized numeric token" in prompt
    assert "not `ARS 123.456.789,125`" in prompt
    assert "preserve ALL of those refs" in prompt
    assert "17.6351 puntos porcentuales" in prompt
    assert "17.6351 pp" in prompt
    assert "declare the bare `17.6351`" in prompt
    assert "does not change the scanner's percent shape" in prompt
