"""Regression coverage for generic portfolio derivations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.agent.grounding import GroundingLedger
from src.agent.grounding.evidence import _currency_code
from src.portfolio.iso4217 import is_iso_currency

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
            {"data": {"volatility": {"annualized_vol": 0.24}}},
            "risk-call",
        ),
    )

    result = ledger.validate_final_answer(
        "Annualized volatility is 24%."
        + _figures(
            "24% | derived | 0.24 × 100 | portfolio_risk"
        )
    )

    assert result.valid is True, result.issues


def test_negative_derived_operand_keeps_its_sign_for_grounding(tmp_path: Path) -> None:
    ledger = _ledger(
        tmp_path,
        (
            "portfolio_risk",
            {"data": {"drawdown": {"max_drawdown": -0.093}}},
            "risk-call",
        ),
    )

    result = ledger.validate_final_answer(
        "Maximum drawdown is -9.3%."
        + _figures(
            "-9.3% | derived | -0.093 × 100 | portfolio_risk"
        )
    )

    assert result.valid is True, result.issues


def test_derived_formula_can_scope_operands_to_multiple_refs(tmp_path: Path) -> None:
    ledger = _ledger(
        tmp_path,
        ("portfolio_scope", {"totals": {"value": 350.0}}, "scope-call"),
        ("portfolio_summary", {"totals": {"value": 1000.0}}, "summary-call"),
    )

    result = ledger.validate_final_answer(
        "The scoped portfolio is 35%."
        + _figures(
            "35% | derived | 350.0 / 1000.0 × 100 | "
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


@pytest.mark.parametrize("code", ["ARS", "EUR", "USD", "KRW"])
def test_iso_currency_contract_accepts_supported_codes(code: str) -> None:
    assert is_iso_currency(code) is True
    assert _currency_code(code.lower()) == code


@pytest.mark.parametrize("code", ["NAV", "PNL", "AVG", "ABC"])
def test_iso_currency_contract_rejects_non_currency_identifiers(code: str) -> None:
    assert is_iso_currency(code) is False
    assert _currency_code(code) is None


def test_currency_keyed_totals_ground_an_ars_amount(tmp_path: Path) -> None:
    ledger = _ledger(
        tmp_path,
        (
            "portfolio_summary",
            {"totals": {"native_by_currency": {"ARS": 1234.5}}},
            "summary-call",
        ),
    )

    result = ledger.validate_final_answer(
        "The portfolio value is ARS 1234.5."
        + _figures(
            "1234.5 | observed | totals.native_by_currency.ARS | "
            "portfolio_summary"
        )
    )

    assert result.valid is True, result.issues


def test_nav_path_does_not_infer_nav_as_a_currency(tmp_path: Path) -> None:
    ledger = _ledger(
        tmp_path,
        ("portfolio_summary", {"data": {"nav": {"total": 1234.5}}}, "summary-call"),
    )

    assert [record.currency for record in ledger._evidence] == [None]

    result = ledger.validate_final_answer(
        "The NAV total is 1234.5."
        + _figures("1234.5 | observed | data.nav.total | portfolio_summary")
    )

    assert result.valid is True, result.issues

@pytest.mark.parametrize(
    ("claim", "formula", "scope_payload", "calc_value"),
    [
        (
            "37.5%",
            "375.0 / 1000.0 × 100",
            {
                "meta": {
                    "scope_value_ars": 375.0,
                    "total_value_ars": 1000.0,
                }
            },
            37.5,
        ),
        (
            "15%",
            "600.0 × 0.25 / 1000.0 × 100",
            {
                "meta": {
                    "scope_value_ars": 600.0,
                    "total_value_ars": 1000.0,
                },
                "portfolio_positions": [
                    {"ticker": "YPFD", "weight_scope": 0.30},
                    {"ticker": "PAMP", "weight_scope": 0.25},
                ],
            },
            15.0,
        ),
        (
            "7.5%",
            "600.0 × 0.125 / 1000.0 × 100",
            {
                "meta": {
                    "scope_value_ars": 600.0,
                    "total_value_ars": 1000.0,
                },
                "portfolio_positions": [
                    {"ticker": "GGAL", "weight_scope": 0.125},
                ],
            },
            7.5,
        ),
        (
            "6%",
            "600.0 × 0.10 / 1000.0 × 100",
            {
                "meta": {
                    "scope_value_ars": 600.0,
                    "total_value_ars": 1000.0,
                },
                "portfolio_positions": [
                    {"ticker": "TGSU2", "weight_scope": 0.10},
                ],
            },
            6.0,
        ),
    ],
)
def test_real_xray_derivations_require_refs_for_all_operand_sources(
    tmp_path: Path,
    claim: str,
    formula: str,
    scope_payload: dict[str, Any],
    calc_value: float,
) -> None:
    ledger = _ledger(
        tmp_path,
        ("asistente_casa_portfolio_risk_xray", scope_payload, "xray-call"),
        ("financial_rigor", {"result": calc_value}, "calc-call"),
    )

    incomplete = ledger.validate_final_answer(
        f"Derived figure: {claim}."
        + _figures(f"{claim} | derived | {formula} | financial_rigor")
    )
    assert incomplete.valid is False
    assert any(
        issue.get("reason") == "formula_not_anchored"
        or issue.get("code") == "formula_not_anchored"
        for issue in incomplete.issues
    ), incomplete.issues

    complete = ledger.validate_final_answer(
        f"Derived figure: {claim}."
        + _figures(
            f"{claim} | derived | {formula} | "
            "financial_rigor; asistente_casa_portfolio_risk_xray"
        )
    )
    assert complete.valid is True, complete.issues

def test_observed_ref_must_match_exact_session_tool_or_call_id(tmp_path: Path) -> None:
    ledger = _ledger(
        tmp_path,
        (
            "asistente_casa_portfolio_risk_xray",
            {"meta": {"total_value_ars": 123456789.125}},
            "xray-call",
        ),
    )

    valid_tool = ledger.validate_final_answer(
        "Portfolio value is ARS 123456789.125."
        + _figures(
            "123456789.125 | observed | meta.total_value_ars | "
            "asistente_casa_portfolio_risk_xray"
        )
    )
    valid_call = ledger.validate_final_answer(
        "Portfolio value is ARS 123456789.125."
        + _figures("123456789.125 | observed | meta.total_value_ars | xray-call")
    )
    missing = ledger.validate_final_answer(
        "Portfolio value is ARS 123456789.125."
        + _figures("123456789.125 | observed | meta.total_value_ars | missing-call")
    )
    decorated = ledger.validate_final_answer(
        "Portfolio value is ARS 123456789.125."
        + _figures(
            "123456789.125 | observed | meta.total_value_ars | "
            "asistente_casa_portfolio_risk_xray (ACCIONES)"
        )
    )

    assert valid_tool.valid is True, valid_tool.issues
    assert valid_call.valid is True, valid_call.issues
    for rejected in (missing, decorated):
        assert rejected.valid is False
        assert any(
            issue.get("reason") == "not_in_referenced_call"
            for issue in rejected.issues
        ), rejected.issues


def test_derived_ref_rejects_unknown_or_decorated_sources_even_when_value_exists_globally(
    tmp_path: Path,
) -> None:
    ledger = _ledger(
        tmp_path,
        (
            "asistente_casa_portfolio_risk_xray",
            {
                "meta": {
                    "scope_value_ars": 375.0,
                    "total_value_ars": 1000.0,
                }
            },
            "xray-call",
        ),
        ("financial_rigor", {"result": 37.5}, "calc-call"),
    )
    formula = "375.0 / 1000.0 × 100"

    valid = ledger.validate_final_answer(
        "CEDEAR weight is 37.5%."
        + _figures(
            "37.5% | derived | "
            + formula
            + " | financial_rigor; asistente_casa_portfolio_risk_xray"
        )
    )
    missing = ledger.validate_final_answer(
        "CEDEAR weight is 37.5%."
        + _figures(
            "37.5% | derived | "
            + formula
            + " | financial_rigor; missing-call"
        )
    )
    decorated = ledger.validate_final_answer(
        "CEDEAR weight is 37.5%."
        + _figures(
            "37.5% | derived | "
            + formula
            + " | financial_rigor; asistente_casa_portfolio_risk_xray (CEDEARS)"
        )
    )

    assert valid.valid is True, valid.issues
    for rejected in (missing, decorated):
        assert rejected.valid is False
        assert any(
            issue.get("reason") == "no_evidence"
            for issue in rejected.issues
        ), rejected.issues
