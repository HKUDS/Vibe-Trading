"""Document-level orchestration of the independent portfolio replay."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from .ledger import PortfolioLedger
from .models import PortfolioResult
from .reconcile_analytics import _analytics_checks, _check_end_state
from .reconcile_conversions import _apply_conversions, _check_post_conversion
from .reconcile_fills import _check_plan_outcomes, _replay_fills
from .reconcile_parse import _fee_rules, _parse_account_state, _parse_result
from .reconcile_primitives import _issue, _money_text
from .reconcile_state import _check_duplicate_buckets, _compare_states, _state_maps
from .schema import PortfolioRequestError


def _expected_end_portfolio(
    document: PortfolioResult,
    cash: dict[str, Decimal],
    positions: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any]:
    rows = []
    for bucket in document.opening_portfolio.buckets:
        bucket_id = bucket.bucket_id
        bucket_positions = []
        for (position_bucket, symbol), position in sorted(positions.items()):
            if position_bucket != bucket_id or position["qty"] == 0:
                continue
            bucket_positions.append(
                {
                    "symbol": symbol,
                    "qty": position["qty"],
                    "avg_cost": _money_text(position["avg_cost"]),
                    "currency": position["currency"],
                }
            )
        rows.append(
            {
                "bucket_id": bucket_id,
                "cash": _money_text(cash[bucket_id]),
                "positions": bucket_positions,
            }
        )
    return {"buckets": rows}


def reconcile_portfolio_document(
    account_state: Any, result: Any
) -> dict[str, Any]:
    """Replay one pt-v2.0 portfolio document against its opening portfolio."""
    document = _parse_result(result)
    opening_state = _parse_account_state(account_state)
    issues: list[dict[str, Any]] = []
    not_verified: list[str] = [
        "Caller-declared valuation marks and direct FX pairs were replayed from the document only; they were not re-fetched or compared with an independent market source.",
        "plan_hash, planning_data_hash, execution_data_fingerprint and document_hash were not recomputed because the raw request bars, sessions and fee snapshots are absent.",
        "This is a ledger and document-internal arithmetic audit, not a broker, venue or live-account verification.",
    ]

    _check_duplicate_buckets(issues, opening_state, "opening_portfolio.buckets")
    _check_duplicate_buckets(
        issues, document.opening_portfolio, "result.opening_portfolio.buckets"
    )
    _compare_states(
        issues,
        opening_state,
        document.opening_portfolio,
        "opening_portfolio",
    )
    try:
        PortfolioLedger.from_state(document.opening_portfolio)
    except PortfolioRequestError as exc:
        raise ValueError(
            f"result.opening_portfolio is invalid: {exc.reason} at {exc.path}"
        ) from exc
    fee_rules, buckets = _fee_rules(document.opening_portfolio)
    cash, positions = _state_maps(document.opening_portfolio)

    conversions_replayed, unverified_cash_buckets = _apply_conversions(
        issues, document, buckets, cash, not_verified
    )
    _check_post_conversion(
        issues, document, cash, positions, conversions_replayed
    )
    _check_plan_outcomes(issues, document)
    _replay_fills(
        issues,
        document,
        buckets,
        fee_rules,
        cash,
        positions,
        unverified_cash_buckets=unverified_cash_buckets,
    )
    _check_end_state(
        issues,
        document,
        cash,
        positions,
        unverified_cash_buckets=unverified_cash_buckets,
    )

    for index, row in enumerate(document.bucket_results):
        path = f"bucket_results[{index}]"
        bucket = buckets.get(row.bucket_id)
        if bucket is None:
            _issue(issues, "bucket_row_mismatch", path, "declared bucket", row.bucket_id)
            continue
        if row.cash != _money_text(cash[row.bucket_id]) and row.bucket_id not in unverified_cash_buckets:
            _issue(
                issues,
                "bucket_cash_mismatch",
                f"{path}.cash",
                _money_text(cash[row.bucket_id]),
                row.cash,
            )
        if row.session.market != row.market:
            _issue(
                issues,
                "bucket_row_mismatch",
                f"{path}.session.market",
                row.market,
                row.session.market,
            )
    reported_buckets = {row.bucket_id for row in document.bucket_results}
    for bucket_id in sorted(set(cash) - reported_buckets):
        _issue(
            issues,
            "bucket_row_mismatch",
            f"bucket_results[{bucket_id}]",
            "one row per bucket",
            None,
        )

    _analytics_checks(issues, document, cash, positions, not_verified)

    return {
        "status": "ok",
        "tool": "paper_trade_reconcile",
        "reconciled": not issues,
        "summary": {
            "fills_checked": len(document.fills),
            "bucket_rows_checked": len(document.bucket_results),
            "conversions_checked": len(document.conversions),
            "nav_rows_checked": 1 if document.analytics is not None else 0,
            "issue_count": len(issues),
        },
        "expected_end_portfolio": _expected_end_portfolio(
            document, cash, positions
        ),
        "issues": issues,
        "not_verified": not_verified,
    }
