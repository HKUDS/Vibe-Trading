"""Regression coverage for generic portfolio derivations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.agent.grounding import GroundingLedger

pytestmark = pytest.mark.unit


def _ledger(tmp_path: Path, *calls: tuple[str, Any, str]) -> GroundingLedger:
    ledger = GroundingLedger(run_dir=tmp_path, user_message="Analyze the portfolio risk")
    for tool, payload, call_id in calls:
        ledger.ingest_tool_result(
            tool_name=tool,
            arguments={},
            result=json.dumps(payload),
            call_id=call_id,
            success=True,
        )
    return ledger


def _figures(*rows: str) -> str:
    return "\n\n```figures\n" + "\n".join(rows) + "\n```"


def test_derived_percent_already_scaled_by_100_is_not_scaled_twice(tmp_path: Path) -> None:
    ledger = _ledger(
        tmp_path,
        (
            "portfolio_risk",
            {"data": {"volatility": {"annualized_vol": 0.240791109055723}}},
            "risk-call",
        ),
    )

    result = ledger.validate_final_answer(
        "Annualized volatility is 24.079111%."
        + _figures(
            "24.079111% | derived | 0.240791109055723 × 100 | portfolio_risk"
        )
    )

    assert result.valid is True, result.issues


def test_negative_derived_operand_keeps_its_sign_for_grounding(tmp_path: Path) -> None:
    ledger = _ledger(
        tmp_path,
        (
            "portfolio_risk",
            {"data": {"drawdown": {"max_drawdown": -0.09310091567275514}}},
            "risk-call",
        ),
    )

    result = ledger.validate_final_answer(
        "Maximum drawdown is -9.310092%."
        + _figures(
            "-9.310092% | derived | -0.09310091567275514 × 100 | portfolio_risk"
        )
    )

    assert result.valid is True, result.issues


def test_derived_formula_can_scope_operands_to_multiple_refs(tmp_path: Path) -> None:
    ledger = _ledger(
        tmp_path,
        ("portfolio_scope", {"totals": {"value": 78_894_720.0}}, "scope-call"),
        ("portfolio_summary", {"totals": {"value": 224_780_341.158}}, "summary-call"),
    )

    result = ledger.validate_final_answer(
        "The scoped portfolio is 35.098576%."
        + _figures(
            "35.098576% | derived | 78894720.0 / 224780341.158 × 100 | "
            "portfolio_scope; portfolio_summary"
        )
    )

    assert result.valid is True, result.issues


def test_generic_structured_money_uses_currency_context_for_observed_claims(
    tmp_path: Path,
) -> None:
    ledger = _ledger(
        tmp_path,
        (
            "portfolio_summary",
            {"currency": "EUR", "totals": {"value": 1234.5}},
            "summary-call",
        ),
    )

    result = ledger.validate_final_answer(
        "The portfolio value is EUR 1234.5."
        + _figures("1234.5 | observed | totals.value | portfolio_summary")
    )

    assert result.valid is True, result.issues
