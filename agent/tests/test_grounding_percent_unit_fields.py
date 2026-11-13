"""Percent-unit evidence fields: a percent figure meets the formula's own unit.

Regression coverage for HKUDS/Vibe-Trading#1820: A-share rows carry fields
literally named ``changepercent`` whose values are already percentage points
(0.52 means 0.52%). A derived figure over such fields needs no trailing
``*100``, so the result is in points — but the gate compared percent figures
only against ``result * 100``. A correct claim was rejected, and the 100x
wrong claim passed; the model learned to write the wrong number.

The gate now follows the evidence: when every data operand anchors only to
percent-named fields, the result is read as points. Anything less certain
(mixed fields, a magnitude that also appears under a plain field) keeps the
fraction reading, so the fix never widens acceptance for ambiguous units.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.grounding import GroundingLedger


def _ledger_with_rows(tmp_path: Path, rows: list[dict]) -> GroundingLedger:
    ledger = GroundingLedger(run_dir=tmp_path, user_message="Analyze 600519.SH")
    ledger.ingest_tool_result(
        tool_name="get_market_data",
        arguments={"codes": ["600519.SH"]},
        result=json.dumps({"600519.SH": rows}),
        call_id="quote",
        success=True,
    )
    return ledger


def _verdict(ledger: GroundingLedger, value: str, expression: str) -> tuple[bool, set[str]]:
    result = ledger.validate_final_answer(
        f"600519.SH (CNY) move check: {value}.\n\n"
        f"```figures\n{value} | derived | scenario result: {expression} | quote\n```"
    )
    return result.valid, {issue.get("reason") for issue in result.issues}


def test_percent_unit_fields_accept_the_correct_claim(tmp_path: Path) -> None:
    """changepercent 0.52 vs 1.41: the spread is -0.89 points, no *100 needed."""
    ledger = _ledger_with_rows(
        tmp_path,
        [
            {"trade_date": "2026-08-03", "changepercent": 0.52},
            {"trade_date": "2026-08-04", "changepercent": 1.41},
        ],
    )
    valid, reasons = _verdict(ledger, "-0.89%", "0.52 - 1.41")
    assert valid, reasons


def test_percent_unit_fields_reject_the_hundredfold_wrong_claim(tmp_path: Path) -> None:
    """The claim the old code taught: -89% for a -0.89-point spread."""
    ledger = _ledger_with_rows(
        tmp_path,
        [
            {"trade_date": "2026-08-03", "changepercent": 0.52},
            {"trade_date": "2026-08-04", "changepercent": 1.41},
        ],
    )
    valid, reasons = _verdict(ledger, "-89%", "0.52 - 1.41")
    assert not valid
    assert "derivation_result_mismatch" in reasons


def test_fraction_evidence_still_rejects_the_colliding_tiny_percent(tmp_path: Path) -> None:
    """Prices give a fraction (0.124); declaring 0.124% must stay refused.

    Symmetric matching would accept it and re-open the 100x hole from the
    other side; the unit is resolved from field names, not by trying both.
    """
    ledger = _ledger_with_rows(
        tmp_path,
        [
            {"trade_date": "2026-08-03", "close": 100.0},
            {"trade_date": "2026-09-02", "close": 112.4},
        ],
    )
    valid, reasons = _verdict(ledger, "0.124%", "(112.4 - 100.0) / 100.0")
    assert not valid
    assert "derivation_result_mismatch" in reasons


def test_fraction_evidence_still_accepts_the_honest_percent(tmp_path: Path) -> None:
    ledger = _ledger_with_rows(
        tmp_path,
        [
            {"trade_date": "2026-08-03", "close": 100.0},
            {"trade_date": "2026-09-02", "close": 112.4},
        ],
    )
    valid, reasons = _verdict(ledger, "12.4%", "(112.4 - 100.0) / 100.0")
    assert valid, reasons


def test_explicit_trailing_x100_still_normalizes(tmp_path: Path) -> None:
    """The pre-existing path: the note spells the unit conversion itself."""
    ledger = _ledger_with_rows(
        tmp_path,
        [
            {"trade_date": "2026-08-03", "close": 100.0},
            {"trade_date": "2026-09-02", "close": 112.4},
        ],
    )
    valid, reasons = _verdict(ledger, "12.4%", "(112.4 - 100.0) / 100.0 * 100")
    assert valid, reasons


def test_mixed_fields_keep_the_fraction_reading(tmp_path: Path) -> None:
    """One percent field and one plain price: the unit is undecidable, so a
    points-shaped claim is refused exactly as before the fix."""
    ledger = _ledger_with_rows(
        tmp_path,
        [
            {"trade_date": "2026-08-03", "changepercent": 0.52, "close": 1.41},
        ],
    )
    valid, reasons = _verdict(ledger, "1.93%", "0.52 + 1.41")
    assert not valid
    assert "derivation_result_mismatch" in reasons


@pytest.mark.parametrize(
    "expression,correct,wrong",
    [
        ("0.52 / 1.41", "36.88%", "0.37%"),
        ("0.52 / 1.41 * 100", "36.88%", "0.37%"),
        ("(0.52 - 1.41) / 1.41", "-63.12%", "-0.63%"),
        ("0.52 * 1.41", "0.007332%", "0.7332%"),
        ("(1 + 0.52) * (1 + 1.41)", "101.937332%", "366.32%"),
    ],
)
def test_percent_operand_units_follow_the_formula(
    tmp_path: Path, expression: str, correct: str, wrong: str
) -> None:
    """Percentage-point inputs are converted before arithmetic, not after it."""
    ledger = _ledger_with_rows(
        tmp_path,
        [
            {"trade_date": "2026-08-03", "changepercent": 0.52},
            {"trade_date": "2026-08-04", "changepercent": 1.41},
        ],
    )
    valid, reasons = _verdict(ledger, correct, expression)
    assert valid, reasons
    valid, reasons = _verdict(ledger, wrong, expression)
    assert not valid
    assert "derivation_result_mismatch" in reasons


def test_one_point_is_data_in_an_additive_sum(tmp_path):
    ledger = _ledger_with_rows(tmp_path, [
        {"trade_date": "2026-08-03", "changepercent": 1.0},
        {"trade_date": "2026-08-04", "changepercent": 2.0},
    ])
    assert _verdict(ledger, "3%", "1 + 2")[0]
    assert not _verdict(ledger, "102%", "1 + 2")[0]
