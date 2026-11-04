"""Horizontal spacing must not change the meaning of a monetary amount."""
import json

import pytest

from src.agent.grounding import GroundingLedger
from src.agent.grounding.figures import magnitude_suffix


@pytest.mark.parametrize("space", [" ", "\t", "\u00a0", "\u202f", "\u3000"])
def test_spaced_money_matches_the_same_observation(tmp_path, space):
    ledger = GroundingLedger(run_dir=tmp_path, user_message="Report revenue")
    ledger.ingest_tool_result(tool_name="financial_data", arguments={}, call_id="c1", success=True,
                              result=json.dumps({"revenue": {"amount": 1_234_000_000}}))
    answer = f"营业收入为12.34{space}亿元。\n```figures\n12.34亿元 | observed | 营业收入 | c1::revenue.amount\n```"
    result = ledger.validate_final_answer(answer)
    assert result.valid, result.issues
    wrong = ledger.validate_final_answer(answer.replace("12.34", "13.34"))
    assert not wrong.valid


@pytest.mark.parametrize("text,expected", [(" 亿", (1e8, 2)), (" M", (1e6, 2)),
                                          (" MB", (1.0, 0)), (" March", (1.0, 0)),
                                          ("\n亿", (1.0, 0)), (" ", (1.0, 0))])
def test_spacing_preserves_word_and_line_boundaries(text, expected):
    assert magnitude_suffix(text, 0) == expected
