"""Weight tie-out cluster of the one-day attribution.

Publishes each instrument's caller target, order-plan planned weight and
end-ledger realized weight with the lot/price/reject/cash gaps, and checks the
unfitted weight identity against the declared rounding tolerance. The
computation body is byte-identical to the pre-split ``_attribution`` weight
section.
"""

from __future__ import annotations

from decimal import Decimal

from .analytics_attribution_bridge import _AttributionState, _BridgeResult
from .analytics_attribution_replay import _ReplayResult
from .analytics_common import (
    _attribution_issue,
    _exact_difference,
    _exact_product,
    _exact_sum,
    _exact_text,
    _money,
    _position_quantities,
    _ratio,
    _signed_weight,
    _signed_weight_value,
    _weight,
    _weight_rounding_tolerance,
    _weight_sum,
)
from .models import (
    AnalyticsReconciliationCheck,
    AnalyticsWeightReconciliation,
    AnalyticsWeightRow,
    PortfolioIssue,
)
from .numeric import MONEY_SPEC, canonical_decimal


def _attribution_weights(
    state: _AttributionState, bridge: _BridgeResult, replay: _ReplayResult
) -> AnalyticsWeightReconciliation:
    """Build the target/planned/realized weight tie-out and its checks."""
    plan = state.plan
    fills = state.fills
    rejected_orders = state.rejected_orders
    canceled_orders = state.canceled_orders
    end_ledger = state.end_ledger
    position_rows = state.position_rows
    cash_rows = state.cash_rows
    nav_base = state.nav_base
    valuation_rounding = state.valuation_rounding
    issues = state.issues
    checks = state.checks
    end_buckets = bridge.end_buckets
    planning_marks = bridge.planning_marks
    planning_rates = bridge.planning_rates
    planning_nav = bridge.planning_nav
    planning_exact = bridge.planning_exact
    symbol_by_key = replay.symbol_by_key
    position_values = {
        (row.bucket_id, row.symbol): Decimal(row.value_base) for row in position_rows
    }
    end_qty = _position_quantities(end_ledger)
    fill_by_key = {
        (fill.bucket_id, fill.symbol): fill for fill in fills
    }
    rejected_by_key = {
        (row.bucket_id, row.symbol): row for row in rejected_orders
    }
    canceled_by_key = {
        (row.bucket_id, row.symbol): row for row in canceled_orders
    }
    weight_rows: list[AnalyticsWeightRow] = []
    weight_issues: list[PortfolioIssue] = []
    plan_keys: set[tuple[str, str]] = set()
    for index, row in enumerate(plan.weights):
        bucket_id = row.bucket_id
        symbol = row.symbol
        key = (bucket_id, symbol)
        plan_keys.add(key)
        path = f"attribution.weights.rows[{index}]"
        bucket = end_buckets.get(bucket_id)
        if bucket is None:
            weight_issues.append(
                _attribution_issue(
                    "attribution_plan_bucket_mismatch",
                    path,
                    "a plan weight names an undeclared ending bucket",
                    bucket_id=bucket_id,
                )
            )
            continue
        mark = planning_marks.get(symbol)
        rate_pair = planning_rates.get(bucket_id)
        if mark is None or rate_pair is None:
            weight_issues.append(
                _attribution_issue(
                    "attribution_planned_weight_mismatch",
                    f"{path}.planned_weight",
                    "the plan weight has no planning mark/rate to audit",
                    bucket_id=bucket_id,
                )
            )
            planned_value = Decimal(0)
        else:
            planned_value = _money(
                _exact_product(
                    Decimal(row.planned_qty),
                    _exact_product(mark.price, rate_pair[1]),
                ),
                f"{path}.planned_value",
            )
            expected = (
                _weight(_ratio(planned_value, planning_nav), f"{path}.planned_weight")
                if planning_nav > 0
                else Decimal(0)
            )
            if expected != row.planned_weight:
                weight_issues.append(
                    _attribution_issue(
                        "attribution_planned_weight_mismatch",
                        f"{path}.planned_weight",
                        "the plan weight does not equal planned quantity times the "
                        "planning mark and direct-pair FX",
                        bucket_id=bucket_id,
                    )
                )
        symbol_row = symbol_by_key.get(key)
        realized_value = position_values.get(key, Decimal(0))
        realized_units = end_qty.get(key, 0)
        if symbol_row is None:
            planned_at_end_value = Decimal(0)
            if row.planned_qty:
                weight_issues.append(
                    _attribution_issue(
                        "attribution_missing_end_mark",
                        f"{path}.planned_at_end_weight",
                        "a nonzero planned quantity has no ending mark",
                        bucket_id=bucket_id,
                    )
                )
        else:
            planned_at_end_value = _money(
                _exact_product(
                    Decimal(row.planned_qty),
                    _exact_product(
                        Decimal(symbol_row.ending_price),
                        Decimal(symbol_row.ending_fx.rate),
                    ),
                ),
                f"{path}.planned_at_end_value",
            )
        planned_at_end_weight = (
            _weight(_ratio(planned_at_end_value, nav_base), f"{path}.planned_at_end_weight")
            if nav_base > 0
            else Decimal(0)
        )
        realized_weight = (
            _weight(_ratio(realized_value, nav_base), f"{path}.realized_weight") if nav_base > 0 else Decimal(0)
        )
        planned_weight = row.planned_weight
        target = row.target_weight
        target_gap = (
            _signed_weight(realized_weight - target, f"{path}.target_gap")
            if target is not None
            else None
        )
        lot_gap = (
            _signed_weight(planned_weight - target, f"{path}.lot_gap")
            if target is not None
            else "0"
        )
        price_gap = _signed_weight(
            planned_at_end_weight - planned_weight,
            f"{path}.price_gap",
        )
        reject_gap = _signed_weight(
            realized_weight - planned_at_end_weight,
            f"{path}.reject_gap",
        )
        if key in fill_by_key:
            outcome = "filled"
        elif key in rejected_by_key:
            outcome = "rejected"
        elif key in canceled_by_key:
            outcome = "canceled"
        else:
            outcome = "not_ordered"
        weight_rows.append(
            AnalyticsWeightRow(
                bucket_id=bucket_id,
                market=bucket.market,
                currency=bucket.currency,
                symbol=symbol,
                target_weight=(
                    _signed_weight(target, f"{path}.target")
                    if target is not None
                    else None
                ),
                planned_weight=_weight_sum(
                    planned_weight,
                    f"{path}.planned_weight",
                ),
                planned_at_end_weight=_weight_sum(
                    planned_at_end_weight,
                    f"{path}.planned_at_end_weight",
                ),
                realized_weight=_weight_sum(
                    realized_weight,
                    f"{path}.realized_weight",
                ),
                target_gap=target_gap,
                lot_gap=lot_gap,
                price_gap=price_gap,
                reject_gap=reject_gap,
                planned_value_base=_exact_text(
                    planned_value,
                    f"{path}.planned_value",
                ),
                planned_at_end_value_base=_exact_text(
                    planned_at_end_value,
                    f"{path}.planned_at_end_value",
                ),
                realized_value_base=canonical_decimal(
                    realized_value,
                    MONEY_SPEC,
                    f"{path}.realized_value",
                ),
                planned_qty=row.planned_qty,
                realized_qty=realized_units,
                qty_gap=realized_units - row.planned_qty,
                outcome=outcome,
            )
        )
    for key in sorted(set(end_qty) - plan_keys):
        weight_issues.append(
            _attribution_issue(
                "attribution_missing_plan_weight",
                f"attribution.weights.{key[0]}.{key[1]}",
                "an ending position has no plan weight row",
                bucket_id=key[0],
            )
        )

    target_mode = plan.mode == "target_weights"
    target_total = (
        _weight_sum(
            _exact_sum(
                (
                    Decimal(row.target_weight)
                    for row in weight_rows
                    if row.target_weight is not None
                )
            ),
            "attribution.weights.target_total",
        )
        if target_mode
        else None
    )
    planned_total_value = _exact_sum(
        Decimal(row.planned_weight) for row in weight_rows
    )
    realized_total_value = _exact_sum(
        Decimal(row.realized_weight) for row in weight_rows
    )
    lot_total_value = _exact_sum(Decimal(row.lot_gap) for row in weight_rows)
    price_total_value = _exact_sum(Decimal(row.price_gap) for row in weight_rows)
    reject_total_value = _exact_sum(Decimal(row.reject_gap) for row in weight_rows)
    planned_cash = _exact_difference(Decimal(1), planned_total_value)
    target_cash = (
        _exact_difference(Decimal(1), Decimal(target_total))
        if target_total is not None
        else None
    )
    realized_cash = (
        _weight(
            _ratio(_exact_sum(Decimal(row.value_base) for row in cash_rows), nav_base),
            "attribution.weights.realized_cash",
        )
        if nav_base > 0
        else Decimal(0)
    )
    valuation_weight = (
        _signed_weight_value(
            _ratio(valuation_rounding, nav_base),
            "attribution.weights.valuation_rounding",
        )
        if nav_base > 0
        else Decimal(0)
    )
    cash_basis = target_cash if target_cash is not None else planned_cash
    cash_gap = _exact_difference(realized_cash, cash_basis)
    weight_rounding = _exact_sum(
        (
            lot_total_value,
            price_total_value,
            reject_total_value,
            cash_gap,
            valuation_weight,
        )
    )
    tolerance = _weight_rounding_tolerance(len(weight_rows))
    weight_identity_ok = abs(weight_rounding) <= tolerance
    weights_reconciled = weight_identity_ok and not weight_issues
    issues.extend(weight_issues)
    if not weight_identity_ok:
        issues.append(
            _attribution_issue(
                "attribution_weight_identity_mismatch",
                "attribution.weights",
                "target/planned/realized weight gaps exceed the declared rounding "
                "tolerance",
            )
        )
    checks.append(
        AnalyticsReconciliationCheck(
            name="weight_gap_identity",
            passed=weight_identity_ok,
            detail=(
                "lot + price + reject + cash gap + valuation rounding equals the "
                "declared weight rounding residual"
            ),
        )
    )

    weights = AnalyticsWeightReconciliation(
        planning_nav_base=canonical_decimal(
            planning_nav,
            MONEY_SPEC,
            "attribution.weights.planning_nav_base",
        ),
        planning_exact_nav_base=_exact_text(
            planning_exact,
            "attribution.weights.planning_exact_nav_base",
        ),
        planning_rounding_residual=_exact_text(
            _exact_difference(planning_exact, planning_nav),
            "attribution.weights.planning_rounding_residual",
        ),
        target_weight_total=target_total,
        target_cash_weight=(
            _weight_sum(target_cash, "attribution.weights.target_cash_weight")
            if target_cash is not None
            else None
        ),
        planned_weight_total=_weight_sum(
            planned_total_value,
            "attribution.weights.planned_total",
        ),
        planned_cash_weight=_weight_sum(
            planned_cash,
            "attribution.weights.planned_cash",
        ),
        realized_weight_total=_weight_sum(
            realized_total_value,
            "attribution.weights.realized_total",
        ),
        realized_cash_weight=_weight_sum(
            realized_cash,
            "attribution.weights.realized_cash",
        ),
        valuation_rounding_weight=_weight_sum(
            valuation_weight,
            "attribution.weights.valuation_rounding",
        ),
        lot_gap_total=_weight_sum(
            lot_total_value,
            "attribution.weights.lot_total",
        ),
        price_gap_total=_weight_sum(
            price_total_value,
            "attribution.weights.price_total",
        ),
        reject_gap_total=_weight_sum(
            reject_total_value,
            "attribution.weights.reject_total",
        ),
        cash_gap=_weight_sum(cash_gap, "attribution.weights.cash_gap"),
        weight_rounding_residual=_weight_sum(
            weight_rounding,
            "attribution.weights.residual",
        ),
        weight_rounding_tolerance=_weight_sum(
            tolerance,
            "attribution.weights.tolerance",
        ),
        reconciled=weights_reconciled,
        rows=tuple(weight_rows),
    )
    return weights
