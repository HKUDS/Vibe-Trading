"""Opening-state maps and field-by-field ledger comparison."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from .models import PortfolioState
from .reconcile_primitives import _issue, _money_text


def _state_maps(state: PortfolioState) -> tuple[dict[str, Decimal], dict[tuple[str, str], dict[str, Any]]]:
    cash: dict[str, Decimal] = {}
    positions: dict[tuple[str, str], dict[str, Any]] = {}
    for bucket in state.buckets:
        cash[bucket.bucket_id] = Decimal(bucket.cash)
        for position in bucket.positions:
            positions[(bucket.bucket_id, position.symbol)] = {
                "qty": position.qty,
                "avg_cost": Decimal(position.avg_cost),
                "currency": position.currency,
            }
    return cash, positions


def _check_duplicate_buckets(
    issues: list[dict[str, Any]], state: PortfolioState, path: str
) -> None:
    seen: set[str] = set()
    for index, bucket in enumerate(state.buckets):
        if bucket.bucket_id in seen:
            _issue(
                issues,
                "duplicate_bucket",
                f"{path}[{index}].bucket_id",
                "one row per bucket",
                bucket.bucket_id,
            )
        seen.add(bucket.bucket_id)


def _compare_states(
    issues: list[dict[str, Any]],
    expected: PortfolioState,
    actual: PortfolioState,
    path: str,
) -> None:
    """Report every field where the caller ledger disagrees with the document."""
    expected_cash, expected_positions = _state_maps(expected)
    actual_cash, actual_positions = _state_maps(actual)
    expected_buckets = {bucket.bucket_id: bucket for bucket in expected.buckets}
    actual_buckets = {bucket.bucket_id: bucket for bucket in actual.buckets}
    for bucket_id in sorted(set(expected_cash) | set(actual_cash)):
        bucket_path = f"{path}.buckets.{bucket_id}"
        if bucket_id not in actual_cash:
            _issue(issues, "opening_portfolio_mismatch", bucket_path, "present", None)
            continue
        if bucket_id not in expected_cash:
            _issue(
                issues,
                "opening_portfolio_mismatch",
                bucket_path,
                None,
                "unexpected bucket",
            )
            continue
        expected_bucket = expected_buckets[bucket_id]
        actual_bucket = actual_buckets[bucket_id]
        if expected_bucket.market != actual_bucket.market:
            _issue(
                issues,
                "opening_portfolio_mismatch",
                f"{bucket_path}.market",
                expected_bucket.market,
                actual_bucket.market,
            )
        if expected_bucket.currency != actual_bucket.currency:
            _issue(
                issues,
                "opening_portfolio_mismatch",
                f"{bucket_path}.currency",
                expected_bucket.currency,
                actual_bucket.currency,
            )
        if expected_bucket.fee_model != actual_bucket.fee_model:
            _issue(
                issues,
                "opening_portfolio_mismatch",
                f"{bucket_path}.fee_model",
                "caller-declared fee model",
                "different fee model",
            )
        if expected_cash[bucket_id] != actual_cash[bucket_id]:
            _issue(
                issues,
                "opening_portfolio_mismatch",
                f"{bucket_path}.cash",
                _money_text(expected_cash[bucket_id]),
                _money_text(actual_cash[bucket_id]),
            )
    for key in sorted(set(expected_positions) | set(actual_positions)):
        bucket_id, symbol = key
        position_path = f"{path}.buckets.{bucket_id}.positions[{symbol}]"
        expected_position = expected_positions.get(key)
        actual_position = actual_positions.get(key)
        if expected_position is None:
            _issue(
                issues,
                "opening_portfolio_mismatch",
                position_path,
                None,
                "unexpected position",
            )
            continue
        if actual_position is None:
            _issue(
                issues,
                "opening_portfolio_mismatch",
                position_path,
                expected_position["qty"],
                None,
            )
            continue
        if expected_position["qty"] != actual_position["qty"]:
            _issue(
                issues,
                "opening_portfolio_mismatch",
                f"{position_path}.qty",
                expected_position["qty"],
                actual_position["qty"],
            )
        if expected_position["avg_cost"] != actual_position["avg_cost"]:
            _issue(
                issues,
                "opening_portfolio_mismatch",
                f"{position_path}.avg_cost",
                _money_text(expected_position["avg_cost"]),
                _money_text(actual_position["avg_cost"]),
            )
        if expected_position["currency"] != actual_position["currency"]:
            _issue(
                issues,
                "opening_portfolio_mismatch",
                f"{position_path}.currency",
                expected_position["currency"],
                actual_position["currency"],
            )
