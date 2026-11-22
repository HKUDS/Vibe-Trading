"""One-day attribution identity checks over the published document."""

from __future__ import annotations

from collections import Counter
from decimal import Decimal
from typing import Any

from ..rules import quantize_money
from .analytics import reconcile_attribution
from .models import PortfolioResult
from .reconcile_primitives import _exact, _issue, _money_text, _text
from .reconcile_state import _state_maps


def _check_attribution(
    issues: list[dict[str, Any]],
    document: PortfolioResult,
    cash: dict[str, Decimal],
    positions: dict[tuple[str, str], dict[str, Any]],
    not_verified: list[str],
) -> None:
    analytics = document.analytics
    if analytics is None or analytics.attribution is None:
        not_verified.append(
            "analytics.attribution is absent; one-day contribution and weight identities were not recomputed."
        )
        return
    attribution = analytics.attribution
    try:
        recomputed = reconcile_attribution(attribution)
    except (ArithmeticError, TypeError, ValueError) as exc:
        _issue(
            issues,
            "attribution_unverifiable",
            "analytics.attribution",
            "recomputable rows",
            str(exc),
        )
        return
    for item in recomputed:
        _issue(
            issues,
            item.reason,
            f"analytics.{item.path}",
            "recomputed attribution row",
            item.detail,
        )
    if not attribution.reconciliation.reconciled:
        _issue(
            issues,
            "attribution_reconciliation_failed",
            "analytics.attribution.reconciliation.reconciled",
            True,
            False,
        )
    if attribution.reconciliation.issues:
        _issue(
            issues,
            "attribution_reconciliation_failed",
            "analytics.attribution.reconciliation.issues",
            "empty",
            len(attribution.reconciliation.issues),
        )
    if not attribution.weights.reconciled:
        _issue(
            issues,
            "attribution_weights_mismatch",
            "analytics.attribution.weights.reconciled",
            True,
            False,
        )
    if Decimal(attribution.rounding_residual) != Decimal(
        attribution.expected_rounding_residual
    ):
        _issue(
            issues,
            "attribution_rounding_residual_mismatch",
            "analytics.attribution.rounding_residual",
            attribution.expected_rounding_residual,
            attribution.rounding_residual,
        )
    if Decimal(attribution.nav.end_nav_base) != Decimal(analytics.nav_base):
        _issue(
            issues,
            "attribution_nav_mismatch",
            "analytics.attribution.nav.end_nav_base",
            analytics.nav_base,
            attribution.nav.end_nav_base,
        )
    if Decimal(attribution.nav.end_exact_nav_base) != Decimal(
        analytics.nav_bridge.exact_nav_base
    ):
        _issue(
            issues,
            "attribution_nav_mismatch",
            "analytics.attribution.nav.end_exact_nav_base",
            analytics.nav_bridge.exact_nav_base,
            attribution.nav.end_exact_nav_base,
        )
    if attribution.nav.start_at != document.planning_at:
        _issue(
            issues,
            "attribution_nav_mismatch",
            "analytics.attribution.nav.start_at",
            document.planning_at.isoformat(),
            attribution.nav.start_at.isoformat(),
        )
    if attribution.nav.end_at != document.valuation_at:
        _issue(
            issues,
            "attribution_nav_mismatch",
            "analytics.attribution.nav.end_at",
            document.valuation_at.isoformat(),
            attribution.nav.end_at.isoformat(),
        )

    fills = {fill.plan_order_id: fill for fill in document.fills}
    fee_ids = Counter(row.plan_order_id for row in attribution.fee_effects)
    if fee_ids != Counter(fills.keys()):
        _issue(
            issues,
            "attribution_fill_mismatch",
            "analytics.attribution.fee_effects",
            sorted(fills),
            sorted(fee_ids),
        )
    for index, row in enumerate(attribution.fee_effects):
        fill = fills.get(row.plan_order_id)
        path = f"analytics.attribution.fee_effects[{index}]"
        if fill is None:
            continue
        expected = {
            "bucket_id": fill.bucket_id,
            "symbol": fill.symbol,
            "side": fill.side,
            "qty": fill.qty,
            "execution_price": fill.price,
            "fee_local": fill.fee,
        }
        actual = {
            "bucket_id": row.bucket_id,
            "symbol": row.symbol,
            "side": row.side,
            "qty": row.qty,
            "execution_price": row.execution_price,
            "fee_local": row.fee_local,
        }
        if Decimal(row.execution_price) != Decimal(fill.price):
            actual["execution_price"] = row.execution_price
        if Decimal(row.fee_local) != Decimal(fill.fee):
            actual["fee_local"] = row.fee_local
        if actual != expected:
            _issue(
                issues,
                "attribution_fill_mismatch",
                path,
                expected,
                actual,
            )

    rounding_ids = Counter(
        row.plan_order_id for row in attribution.execution_rounding
    )
    if rounding_ids != Counter(fills.keys()):
        _issue(
            issues,
            "attribution_fill_mismatch",
            "analytics.attribution.execution_rounding",
            sorted(fills),
            sorted(rounding_ids),
        )
    for index, row in enumerate(attribution.execution_rounding):
        fill = fills.get(row.plan_order_id)
        if fill is None:
            continue
        path = f"analytics.attribution.execution_rounding[{index}]"
        exact_notional = _exact(Decimal(fill.qty), Decimal(fill.price))
        notional = quantize_money(exact_notional)
        if Decimal(row.exact_notional_local) != exact_notional:
            _issue(
                issues,
                "attribution_execution_rounding_mismatch",
                f"{path}.exact_notional_local",
                _text(exact_notional),
                row.exact_notional_local,
            )
        if Decimal(row.notional_local) != notional:
            _issue(
                issues,
                "attribution_execution_rounding_mismatch",
                f"{path}.notional_local",
                _money_text(notional),
                row.notional_local,
            )
        if Decimal(row.rounding_local) != exact_notional - notional:
            _issue(
                issues,
                "attribution_execution_rounding_mismatch",
                f"{path}.rounding_local",
                _text(exact_notional - notional),
                row.rounding_local,
            )

    _, opening_positions = _state_maps(document.opening_portfolio)
    traded: dict[tuple[str, str], int] = {}
    for fill in document.fills:
        key = (fill.bucket_id, fill.symbol)
        sign = fill.qty if fill.side == "buy" else -fill.qty
        traded[key] = traded.get(key, 0) + sign
    for index, row in enumerate(attribution.symbol_contributions):
        path = f"analytics.attribution.symbol_contributions[{index}]"
        key = (row.bucket_id, row.symbol)
        opening = opening_positions.get(key)
        ending = positions.get(key)
        expected_opening = opening["qty"] if opening else 0
        expected_ending = ending["qty"] if ending else 0
        if row.opening_qty != expected_opening:
            _issue(
                issues,
                "attribution_position_mismatch",
                f"{path}.opening_qty",
                expected_opening,
                row.opening_qty,
            )
        if row.ending_qty != expected_ending:
            _issue(
                issues,
                "attribution_position_mismatch",
                f"{path}.ending_qty",
                expected_ending,
                row.ending_qty,
            )
        if row.traded_qty != traded.get(key, 0):
            _issue(
                issues,
                "attribution_position_mismatch",
                f"{path}.traded_qty",
                traded.get(key, 0),
                row.traded_qty,
            )
    covered = {
        (row.bucket_id, row.symbol) for row in attribution.symbol_contributions
    }
    for key in sorted(set(opening_positions) | set(positions)):
        if key not in covered:
            _issue(
                issues,
                "attribution_position_mismatch",
                f"analytics.attribution.symbol_contributions[{key[0]}.{key[1]}]",
                "one row per instrument",
                None,
            )
