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


@pytest.mark.parametrize("ref", ["unknown", "ghost", "missing_field"])
def test_unknown_single_ref_does_not_borrow_other_evidence(tmp_path, ref):
    result = _ledger(tmp_path).validate_final_answer(_answer(ref))
    assert not result.valid
    assert any(issue.get("reason") == "no_evidence" for issue in result.issues)


@pytest.mark.parametrize("ref", ["before", "after", "get_market_data", "close", "AAPL.US"])
def test_valid_single_call_tool_field_or_observed_symbol_ref_survives(tmp_path, ref):
    result = _ledger(tmp_path).validate_final_answer(_answer(ref))
    # A single call contains only one of the two prices, so valid evidence
    # resolution does not imply the derived formula itself is supported.
    assert not any(
        issue.get("reason") == "no_evidence"
        for issue in result.issues
    ), result.issues


@pytest.mark.parametrize("ref", ["unknown", "ghost", "missing_field"])
def test_unknown_single_ref_with_surfaced_symbol_and_other_market_symbol(tmp_path, ref):
    ledger = _ledger(tmp_path)
    ledger.ingest_tool_result(
        tool_name="get_market_data",
        arguments={"codes": ["MSFT.US"]},
        result=json.dumps({
            "MSFT.US": [{"trade_date": "2026-09-02", "close": 221.0}]
        }),
        call_id="other_symbol",
        success=True,
    )
    # The prose already identifies AAPL.US and USD: do not let an unrelated
    # market bar disable fail-closed handling of this unknown declared ref.
    result = ledger.validate_final_answer(_answer(ref))
    assert not result.valid
    assert any(issue.get("reason") == "no_evidence" for issue in result.issues)
