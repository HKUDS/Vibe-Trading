"""Formatting may change units, but cannot change the referenced observation."""

import json

import pytest

from src.agent.grounding import GroundingLedger
from src.agent.grounding.figures import magnitude_suffix


@pytest.mark.parametrize("prose", ["96.22B", "96.22 billion", "96.22 Billion", "962.21亿"])
@pytest.mark.parametrize("declaration", ["96221000000", "96.221B", "96.221 billion"])
def test_scaled_prose_matches_precise_declared_observation(tmp_path, prose, declaration):
    ledger = GroundingLedger(run_dir=tmp_path, user_message="Report revenue")
    ledger.ingest_tool_result(tool_name="financial_data", arguments={}, call_id="c1", success=True,
                             result=json.dumps({"revenue": 96221000000, "earnings": 18775000000}))
    answer = f"Revenue was {prose}.\n```figures\n{declaration} | observed | Revenue | c1::revenue\n```"
    result = ledger.validate_final_answer(answer)
    assert result.valid, result.issues
    assert not ledger.validate_final_answer(answer.replace("c1::revenue", "c1::earnings")).valid


@pytest.mark.parametrize("factor", [1.02, 1.05, 1.10, 0.98, 0.95, 0.90])
@pytest.mark.parametrize("unit", ["B", " billion", " million"])
def test_wrong_magnitude_values_still_fail(tmp_path, factor, unit):
    ledger = GroundingLedger(run_dir=tmp_path, user_message="Report revenue")
    ledger.ingest_tool_result(tool_name="financial_data", arguments={}, call_id="c1", success=True,
                             result=json.dumps({"revenue": 96221000000}))
    value = f"{96.221 * factor:.3f}{unit}"
    answer = f"Revenue was {value}.\n```figures\n{value} | observed | Revenue | c1::revenue\n```"
    assert not ledger.validate_final_answer(answer).valid


def test_scale_does_not_supply_a_missing_declaration(tmp_path):
    ledger = GroundingLedger(run_dir=tmp_path, user_message="Report revenue")
    ledger.ingest_tool_result(tool_name="financial_data", arguments={}, call_id="c1", success=True,
                             result=json.dumps({"revenue": 96221000000}))
    assert not ledger.validate_final_answer("Revenue was 96.22 billion.").valid


@pytest.mark.parametrize("text", [" billionaires", " millionth", " MB", " March", "\nbillion"])
def test_magnitude_unit_has_a_word_and_line_boundary(text):
    assert magnitude_suffix(text, 0) == (1.0, 0)
