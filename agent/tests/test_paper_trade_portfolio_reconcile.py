"""Offline reconciliation of pt-v2.0 portfolio documents by dispatch.

The existing ``paper_trade_reconcile`` tool keeps its name, signature and
legacy single-market output. A portfolio document is dispatched only when the
result declares ``paper_trade_step`` + ``mode=portfolio`` +
``schema_version=pt-v2.0``; every legacy document still follows the original
ledger-only path byte for byte.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

GOLDEN = Path(__file__).parent / "fixtures" / "paper_trade" / "golden"
PORTFOLIO_GOLDENS = (
    "portfolio_explicit_cn_hk_us.json",
    "portfolio_target_weights_conversion.json",
    "portfolio_cn_open_hk_closed_us_open.json",
    "portfolio_per_order_rejection.json",
)
LEGACY_GOLDENS = {
    "cn_a_orders_single_day.json": (
        {"cash": 200000.0, "positions": []},
        "a432f5d494f2b7c2ca1d802bb1c3997fd9144891da88421861bd3a93cfcd2800",
    ),
    "hk_orders_single_day.json": (
        {"cash": 100000.0, "positions": []},
        "78d703cb2ef83cc80896694304a5f8e438e91c4aaeb06615c0900066195add53",
    ),
    "us_orders_single_day.json": (
        {"cash": 50000.0, "positions": []},
        "1b62cbc37e121ff343bbfc2be0e6d0820a876b505811f751deeb26769633437a",
    ),
}


def _tool():
    from src.tools.paper_trade_reconcile_tool import PaperTradeReconcileTool

    return PaperTradeReconcileTool()


def _document(name: str) -> dict:
    return json.loads((GOLDEN / name).read_text())


def _execute(document: dict, account_state: dict | None = None) -> dict:
    state = copy.deepcopy(account_state or document["opening_portfolio"])
    return json.loads(_tool().execute(account_state=state, result=document))


@pytest.mark.parametrize("name", PORTFOLIO_GOLDENS)
def test_valid_portfolio_documents_reconcile_exactly(name: str) -> None:
    document = _document(name)

    payload = _execute(document)

    assert payload["status"] == "ok"
    assert payload["tool"] == "paper_trade_reconcile"
    assert payload["reconciled"] is True
    assert payload["issues"] == []
    assert payload["summary"]["issue_count"] == 0
    assert payload["summary"]["fills_checked"] == len(document["fills"])
    assert payload["summary"]["conversions_checked"] == len(document["conversions"])
    assert payload["not_verified"]


def test_incomplete_but_valid_document_still_reconciles() -> None:
    document = _document("portfolio_per_order_rejection.json")

    payload = _execute(document)

    assert document["complete"] is False
    assert payload["reconciled"] is True
    assert payload["issues"] == []


def test_mutated_opening_bucket_is_reported_at_its_field() -> None:
    document = _document("portfolio_explicit_cn_hk_us.json")
    state = copy.deepcopy(document["opening_portfolio"])
    state["buckets"][0]["cash"] = "99999.99"

    payload = _execute(document, state)

    assert payload["reconciled"] is False
    assert "opening_portfolio_mismatch" in {issue["code"] for issue in payload["issues"]}
    assert any(
        issue["path"] == "opening_portfolio.buckets.cn.cash"
        for issue in payload["issues"]
    )


def test_duplicate_plan_order_id_fill_is_detected() -> None:
    document = _document("portfolio_explicit_cn_hk_us.json")
    document["fills"].append(copy.deepcopy(document["fills"][0]))

    payload = _execute(document)

    assert payload["reconciled"] is False
    codes = {issue["code"] for issue in payload["issues"]}
    assert "duplicate_fill" in codes
    assert any(issue["path"].endswith("plan_order_id") for issue in payload["issues"])


def test_altered_conversion_arithmetic_is_detected() -> None:
    document = _document("portfolio_target_weights_conversion.json")
    document["analytics"]["conversion_rows"][0]["converted_amount"] = "141.00"

    payload = _execute(document)

    assert payload["reconciled"] is False
    codes = {issue["code"] for issue in payload["issues"]}
    assert "conversion_arithmetic_mismatch" in codes
    assert any(
        issue["path"].startswith("conversions[0]") for issue in payload["issues"]
    )


def test_converted_bucket_end_and_bucket_cash_mutation_is_detected() -> None:
    document = _document("portfolio_target_weights_conversion.json")
    document["end_portfolio"]["buckets"][2]["cash"] = "11058.15"
    document["bucket_results"][2]["cash"] = "11058.15"

    payload = _execute(document)

    assert payload["reconciled"] is False
    issues = {(issue["code"], issue["path"]) for issue in payload["issues"]}
    assert (
        "end_cash_mismatch",
        "end_portfolio.buckets.us.cash",
    ) in issues
    assert ("bucket_cash_mismatch", "bucket_results[2].cash") in issues


def test_negative_cash_after_conversion_replay_is_detected() -> None:
    document = _document("portfolio_target_weights_conversion.json")
    fill = document["fills"][2]
    assert fill["bucket_id"] == "us" and fill["side"] == "buy"
    fill["qty"] = 100

    payload = _execute(document)

    assert payload["reconciled"] is False
    assert any(
        issue["code"] == "negative_cash"
        and issue["path"] == "fills[2]"
        and issue["actual"] == "-9206.99"
        for issue in payload["issues"]
    )


@pytest.mark.parametrize(
    ("state_path", "index", "field", "value", "code", "issue_path"),
    [
        (
            "post_conversion_portfolio",
            2,
            "market",
            "hk",
            "conversion_bucket_mismatch",
            "post_conversion_portfolio.buckets.us.market",
        ),
        (
            "post_conversion_portfolio",
            2,
            "currency",
            "HKD",
            "conversion_bucket_mismatch",
            "post_conversion_portfolio.buckets.us.currency",
        ),
        (
            "end_portfolio",
            2,
            "market",
            "hk",
            "end_bucket_mismatch",
            "end_portfolio.buckets.us.market",
        ),
        (
            "end_portfolio",
            2,
            "currency",
            "HKD",
            "end_bucket_mismatch",
            "end_portfolio.buckets.us.currency",
        ),
    ],
)
def test_post_conversion_and_end_bucket_identity_mutation_is_detected(
    state_path: str,
    index: int,
    field: str,
    value: str,
    code: str,
    issue_path: str,
) -> None:
    document = _document("portfolio_target_weights_conversion.json")
    document[state_path]["buckets"][index][field] = value

    payload = _execute(document)

    assert payload["reconciled"] is False
    assert any(
        issue["code"] == code and issue["path"] == issue_path
        for issue in payload["issues"]
    )


@pytest.mark.parametrize(
    ("state_path", "index", "value", "issue_path", "code"),
    [
        (
            "post_conversion_portfolio",
            1,
            "USD",
            "post_conversion_portfolio.buckets.hk.positions[00700.HK].currency",
            "conversion_position_mismatch",
        ),
        (
            "end_portfolio",
            2,
            "HKD",
            "end_portfolio.buckets.us.positions[AAPL.US].currency",
            "end_position_currency_mismatch",
        ),
    ],
)
def test_converted_position_currency_mutation_is_detected(
    state_path: str, index: int, value: str, issue_path: str, code: str
) -> None:
    document = _document("portfolio_target_weights_conversion.json")
    document[state_path]["buckets"][index]["positions"][0]["currency"] = value

    payload = _execute(document)

    assert payload["reconciled"] is False
    assert any(
        issue["code"] == code and issue["path"] == issue_path
        for issue in payload["issues"]
    )


def test_wrong_fill_bucket_is_detected_against_the_plan() -> None:
    document = _document("portfolio_explicit_cn_hk_us.json")
    document["fills"][0]["bucket_id"] = "us"

    payload = _execute(document)

    assert payload["reconciled"] is False
    codes = {issue["code"] for issue in payload["issues"]}
    assert "order_outcome_mismatch" in codes
    assert "end_cash_mismatch" in codes


def test_forged_nav_is_detected_at_the_bucket_and_bridge() -> None:
    document = _document("portfolio_explicit_cn_hk_us.json")
    document["bucket_results"][0]["nav_base"] = "47888.84"
    document["analytics"]["nav_base"] = "84627.59"

    payload = _execute(document)

    assert payload["reconciled"] is False
    codes = {issue["code"] for issue in payload["issues"]}
    assert "bucket_nav_mismatch" in codes
    assert "analytics_nav_mismatch" in codes


def test_forged_market_exposure_is_detected() -> None:
    document = _document("portfolio_explicit_cn_hk_us.json")
    document["analytics"]["market_exposures"][0]["value_base"] = "47889.83"

    payload = _execute(document)

    assert payload["reconciled"] is False
    assert "analytics_exposure_mismatch" in {
        issue["code"] for issue in payload["issues"]
    }


def test_forged_attribution_row_is_detected() -> None:
    document = _document("portfolio_explicit_cn_hk_us.json")
    contribution = document["analytics"]["attribution"]["symbol_contributions"][0]
    contribution["total_contribution_base"] = "43.00"

    payload = _execute(document)

    assert payload["reconciled"] is False
    codes = {issue["code"] for issue in payload["issues"]}
    assert any("attribution" in code for code in codes)


def test_nonzero_unexplained_attribution_residual_is_an_issue() -> None:
    document = _document("portfolio_explicit_cn_hk_us.json")
    document["analytics"]["attribution"]["rounding_residual"] = "0.01"

    payload = _execute(document)

    assert payload["reconciled"] is False
    codes = {issue["code"] for issue in payload["issues"]}
    assert "attribution_rounding_residual_mismatch" in codes


def test_malformed_portfolio_result_returns_a_stable_error() -> None:
    document = _document("portfolio_explicit_cn_hk_us.json")
    document["status"] = "error"

    payload = _execute(document)

    assert payload["status"] == "error"
    assert payload["tool"] == "paper_trade_reconcile"
    assert "successful pt-v2.0 portfolio document" in payload["error"]


def test_legacy_scalar_account_state_is_not_accepted_for_portfolio() -> None:
    document = _document("portfolio_explicit_cn_hk_us.json")

    payload = _execute(document, {"cash": 100.0, "positions": []})

    assert payload["status"] == "error"
    assert "account_state" in payload["error"]


def test_mcp_wrapper_accepts_both_account_state_shapes() -> None:
    import mcp_server

    portfolio = _document("portfolio_explicit_cn_hk_us.json")
    portfolio_payload = json.loads(
        mcp_server.paper_trade_reconcile(
            account_state=copy.deepcopy(portfolio["opening_portfolio"]),
            result=portfolio,
        )
    )
    legacy = _document("cn_a_orders_single_day.json")
    legacy_payload = json.loads(
        mcp_server.paper_trade_reconcile(
            account_state={"cash": 200000.0, "positions": []},
            result=legacy,
        )
    )

    assert portfolio_payload["reconciled"] is True
    assert legacy_payload["reconciled"] is True


@pytest.mark.parametrize("name", sorted(LEGACY_GOLDENS))
def test_legacy_reconcile_output_remains_byte_identical(name: str) -> None:
    account_state, expected_sha256 = LEGACY_GOLDENS[name]
    document = _document(name)

    raw = _tool().execute(account_state=account_state, result=document)

    assert hashlib.sha256(raw.encode()).hexdigest() == expected_sha256
