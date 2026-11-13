"""Derived claims can reference two observed calls without losing either."""
import json

import pytest

from evals.grounding import GroundingLedger

pytestmark = pytest.mark.unit


def _ledger(tmp_path):
    ledger = GroundingLedger(run_dir=tmp_path, user_message="Analyze AAPL.US")
    for call_id, date, close in (
        ("before", "2026-08-03", 100.0),
        ("after", "2026-09-02", 112.4),
    ):
        ledger.ingest_tool_result(
            tool_name="get_market_data",
            arguments={"codes": ["AAPL.US"]},
            result=json.dumps({
                "AAPL.US": [{"trade_date": date, "close": close}]
            }),
            call_id=call_id,
            success=True,
        )
    return ledger


def _answer(ref):
    return (
        "AAPL.US (USD) cumulative return: 12.4%.\n\n"
        "```figures\n"
        f"12.4% | derived | (112.4 - 100.0) / 100.0 | {ref}\n"
        "```"
    )


def test_derived_multi_call_refs_ground_both_operands(tmp_path):
    result = _ledger(tmp_path).validate_final_answer(_answer("before; after"))
    assert result.valid, result.issues


@pytest.mark.parametrize("ref", [
    "before; unknown",
    "unknown; after",
    "before; ",
    "; after",
])
def test_derived_multi_refs_fail_closed_on_unknown_or_empty_source(tmp_path, ref):
    result = _ledger(tmp_path).validate_final_answer(_answer(ref))
    assert not result.valid
    assert any(issue.get("reason") == "no_evidence" for issue in result.issues)


@pytest.mark.parametrize("ref", [
    "before; ghost::close",
    "before::AAPL.US[0].close; ghost::close",
    "before; after::missing_field",
])
def test_unknown_exact_field_never_borrows_a_valid_call(tmp_path, ref):
    result = _ledger(tmp_path).validate_final_answer(_answer(ref))
    assert not result.valid
    assert any(issue.get("reason") == "no_evidence" for issue in result.issues)


def test_single_call_ref_contract_unchanged(tmp_path):
    ledger = GroundingLedger(run_dir=tmp_path, user_message="Analyze AAPL.US")
    ledger.ingest_tool_result(
        tool_name="get_market_data",
        arguments={"codes": ["AAPL.US"]},
        result=json.dumps({
            "AAPL.US": [
                {"trade_date": "2026-08-03", "close": 100.0},
                {"trade_date": "2026-09-02", "close": 112.4},
            ]
        }),
        call_id="quote",
        success=True,
    )
    result = ledger.validate_final_answer(_answer("quote"))
    assert result.valid, result.issues
