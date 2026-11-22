"""Independent weight tie-out recomputation for a published attribution.

Rebuilds every planned/realized weight, gap and total from the published raw
rows; a mismatch becomes an issue, never a fitted residual.
"""

from __future__ import annotations

from decimal import Decimal

from .analytics_common import (
    _attr_decimal,
    _attribution_issue,
    _exact_difference,
    _exact_product,
    _exact_sum,
    _money,
    _ratio,
    _signed_weight,
    _signed_weight_value,
    _weight,
    _weight_rounding_tolerance,
    _weight_sum,
)
from .models import (
    AnalyticsAttribution,
    AnalyticsCashFxEffect,
    AnalyticsSymbolContribution,
    PortfolioIssue,
)


def _reconcile_weights(
    attribution: AnalyticsAttribution,
    cash_rows: dict[str, AnalyticsCashFxEffect],
    symbol_by_key: dict[tuple[str, str], AnalyticsSymbolContribution],
    issues: list[PortfolioIssue],
) -> None:
    weights = attribution.weights
    nav = _attr_decimal(attribution.nav.end_nav_base)
    planning_nav = _attr_decimal(weights.planning_nav_base)
    position_values = _exact_sum(
        (
            _money(
                _attr_decimal(symbol.ending_value_base),
                "attribution.weights.position_value",
            )
            for symbol in symbol_by_key.values()
        )
    )
    for row in weights.rows:
        key = (row.bucket_id, row.symbol)
        symbol = symbol_by_key.get(key)
        realized_value = (
            _money(
                _attr_decimal(symbol.ending_value_base),
                f"attribution.weights.{row.bucket_id}.{row.symbol}.realized_value",
            )
            if symbol is not None
            else Decimal(0)
        )
        if _attr_decimal(row.realized_value_base) != realized_value:
            issues.append(
                _attribution_issue(
                    "attribution_realized_value_mismatch",
                    f"attribution.weights.{row.bucket_id}.{row.symbol}.realized_value_base",
                    "realized value must equal the published ending position money value",
                    bucket_id=row.bucket_id,
                )
            )
        realized_weight = (
            _weight(_ratio(realized_value, nav), "attribution.weights.realized_weight") if nav > 0 else Decimal(0)
        )
        if row.realized_weight != _weight_sum(
            realized_weight,
            "attribution.weights.realized_weight",
        ):
            issues.append(
                _attribution_issue(
                    "attribution_realized_weight_mismatch",
                    f"attribution.weights.{row.bucket_id}.{row.symbol}.realized_weight",
                    "realized weight must equal realized value over end NAV",
                    bucket_id=row.bucket_id,
                )
            )
        planned_at_end_value = (
            _money(
                _exact_product(
                    Decimal(row.planned_qty),
                    _exact_product(
                        _attr_decimal(symbol.ending_price),
                        _attr_decimal(symbol.ending_fx.rate),
                    ),
                ),
                f"attribution.weights.{row.bucket_id}.{row.symbol}.planned_at_end",
            )
            if symbol is not None
            else Decimal(0)
        )
        if _attr_decimal(row.planned_at_end_value_base) != planned_at_end_value:
            issues.append(
                _attribution_issue(
                    "attribution_weight_math_mismatch",
                    f"attribution.weights.{row.bucket_id}.{row.symbol}.planned_at_end_value_base",
                    "planned-at-end value must equal planned quantity at the ending mark",
                    bucket_id=row.bucket_id,
                )
            )
        planned_at_end_weight = (
            _weight(_ratio(planned_at_end_value, nav), "attribution.weights.planned_at_end_weight") if nav > 0 else Decimal(0)
        )
        if row.planned_at_end_weight != _weight_sum(
            planned_at_end_weight,
            "attribution.weights.planned_at_end_weight",
        ):
            issues.append(
                _attribution_issue(
                    "attribution_weight_math_mismatch",
                    f"attribution.weights.{row.bucket_id}.{row.symbol}.planned_at_end_weight",
                    "planned-at-end weight must equal planned-at-end value over end NAV",
                    bucket_id=row.bucket_id,
                )
            )
        expected_planned_weight = (
            _weight(
                _ratio(_attr_decimal(row.planned_value_base), planning_nav),
                "attribution.weights.planned_weight",
            )
            if planning_nav > 0
            else Decimal(0)
        )
        if row.planned_weight != _weight_sum(
            expected_planned_weight,
            "attribution.weights.planned_weight",
        ):
            issues.append(
                _attribution_issue(
                    "attribution_planned_weight_mismatch",
                    f"attribution.weights.{row.bucket_id}.{row.symbol}.planned_weight",
                    "planned weight must equal planned value over planning NAV",
                    bucket_id=row.bucket_id,
                )
            )
        target = (
            _attr_decimal(row.target_weight)
            if row.target_weight is not None
            else None
        )
        expected_target_gap = (
            _signed_weight(
                _attr_decimal(row.realized_weight) - target,
                "attribution.weights.target_gap",
            )
            if target is not None
            else None
        )
        if row.target_gap != expected_target_gap:
            issues.append(
                _attribution_issue(
                    "attribution_weight_math_mismatch",
                    f"attribution.weights.{row.bucket_id}.{row.symbol}.target_gap",
                    "target gap must be realized minus target weight",
                    bucket_id=row.bucket_id,
                )
            )
        expected_lot_gap = (
            _signed_weight(
                _attr_decimal(row.planned_weight) - target,
                "attribution.weights.lot_gap",
            )
            if target is not None
            else "0"
        )
        if row.lot_gap != expected_lot_gap:
            issues.append(
                _attribution_issue(
                    "attribution_weight_math_mismatch",
                    f"attribution.weights.{row.bucket_id}.{row.symbol}.lot_gap",
                    "lot gap must be planned minus target weight",
                    bucket_id=row.bucket_id,
                )
            )
        expected_price_gap = _signed_weight(
            _attr_decimal(row.planned_at_end_weight)
            - _attr_decimal(row.planned_weight),
            "attribution.weights.price_gap",
        )
        if row.price_gap != expected_price_gap:
            issues.append(
                _attribution_issue(
                    "attribution_weight_math_mismatch",
                    f"attribution.weights.{row.bucket_id}.{row.symbol}.price_gap",
                    "price gap must be planned-at-end minus planned weight",
                    bucket_id=row.bucket_id,
                )
            )
        expected_reject_gap = _signed_weight(
            _attr_decimal(row.realized_weight)
            - _attr_decimal(row.planned_at_end_weight),
            "attribution.weights.reject_gap",
        )
        if row.reject_gap != expected_reject_gap:
            issues.append(
                _attribution_issue(
                    "attribution_weight_math_mismatch",
                    f"attribution.weights.{row.bucket_id}.{row.symbol}.reject_gap",
                    "reject gap must be realized minus planned-at-end weight",
                    bucket_id=row.bucket_id,
                )
            )
        if row.qty_gap != row.realized_qty - row.planned_qty:
            issues.append(
                _attribution_issue(
                    "attribution_weight_math_mismatch",
                    f"attribution.weights.{row.bucket_id}.{row.symbol}.qty_gap",
                    "quantity gap must be realized minus planned quantity",
                    bucket_id=row.bucket_id,
                )
            )

    cash_total = Decimal(0)
    for row in cash_rows.values():
        cash_total = _exact_sum(
            (
                cash_total,
                _money(
                    _exact_product(
                        _attr_decimal(row.ending_cash),
                        _attr_decimal(row.ending_fx.rate),
                    ),
                    "attribution.weights.cash",
                ),
            )
        )
    bucket_reported = Decimal(0)
    for bucket_id, row in cash_rows.items():
        ending_cash = _attr_decimal(row.ending_cash)
        ending_local_money = Decimal(0)
        for symbol in symbol_by_key.values():
            if symbol.bucket_id == bucket_id:
                ending_local_money = _exact_sum(
                    (
                        ending_local_money,
                        _money(
                            _attr_decimal(symbol.ending_local_value),
                            "attribution.weights.ending_local",
                        ),
                    )
                )
        bucket_reported = _exact_sum(
            (
                bucket_reported,
                _money(
                    _exact_product(
                        _exact_sum((ending_cash, ending_local_money)),
                        _attr_decimal(row.ending_fx.rate),
                    ),
                    "attribution.weights.bucket_reported",
                ),
            )
        )
    if _attr_decimal(attribution.nav.end_nav_base) != bucket_reported:
        issues.append(
            _attribution_issue(
                "attribution_nav_mismatch",
                "attribution.nav.end_nav_base",
                "the reported end NAV must equal the per-bucket reported NAV sum",
            )
        )
    valuation_rounding = _exact_difference(
        _attr_decimal(attribution.nav.end_nav_base),
        _exact_sum((cash_total, position_values)),
    )
    realized_cash = _weight(_ratio(cash_total, nav), "attribution.weights.realized_cash") if nav > 0 else Decimal(0)
    valuation_weight = (
        _signed_weight_value(
            _ratio(valuation_rounding, nav),
            "attribution.weights.valuation_rounding",
        )
        if nav > 0
        else Decimal(0)
    )
    if weights.realized_cash_weight != _weight_sum(
        realized_cash,
        "attribution.weights.realized_cash",
    ):
        issues.append(
            _attribution_issue(
                "attribution_weight_math_mismatch",
                "attribution.weights.realized_cash_weight",
                "realized cash weight must equal ending cash over end NAV",
            )
        )
    if weights.valuation_rounding_weight != _weight_sum(
        valuation_weight,
        "attribution.weights.valuation_rounding",
    ):
        issues.append(
            _attribution_issue(
                "attribution_weight_math_mismatch",
                "attribution.weights.valuation_rounding_weight",
                "valuation rounding weight must equal NAV rounding over end NAV",
            )
        )
    target_total = _exact_sum(
        (
            _attr_decimal(row.target_weight)
            for row in weights.rows
            if row.target_weight is not None
        )
    )
    has_targets = any(row.target_weight is not None for row in weights.rows)
    if has_targets:
        if weights.target_weight_total != _weight_sum(
            target_total,
            "attribution.weights.target_total",
        ):
            issues.append(
                _attribution_issue(
                    "attribution_weight_math_mismatch",
                    "attribution.weights.target_weight_total",
                    "target total must equal the published target weights",
                )
            )
        target_cash = _exact_difference(Decimal(1), target_total)
        if weights.target_cash_weight != _weight_sum(
            target_cash,
            "attribution.weights.target_cash",
        ):
            issues.append(
                _attribution_issue(
                    "attribution_weight_math_mismatch",
                    "attribution.weights.target_cash_weight",
                    "target cash weight must be one minus target total",
                )
            )
    else:
        if weights.target_weight_total is not None or weights.target_cash_weight is not None:
            issues.append(
                _attribution_issue(
                    "attribution_weight_math_mismatch",
                    "attribution.weights.target_weight_total",
                    "explicit-order documents must not publish target weights",
                )
            )
        target_cash = None
    planned_total = _exact_sum(
        _attr_decimal(row.planned_weight) for row in weights.rows
    )
    realized_total = _exact_sum(
        _attr_decimal(row.realized_weight) for row in weights.rows
    )
    if weights.planned_weight_total != _weight_sum(
        planned_total,
        "attribution.weights.planned_total",
    ):
        issues.append(
            _attribution_issue(
                "attribution_weight_math_mismatch",
                "attribution.weights.planned_weight_total",
                "planned total must equal the published planned weights",
            )
        )
    if weights.planned_cash_weight != _weight_sum(
        _exact_difference(Decimal(1), planned_total),
        "attribution.weights.planned_cash",
    ):
        issues.append(
            _attribution_issue(
                "attribution_weight_math_mismatch",
                "attribution.weights.planned_cash_weight",
                "planned cash weight must be one minus planned total",
            )
        )
    if weights.realized_weight_total != _weight_sum(
        realized_total,
        "attribution.weights.realized_total",
    ):
        issues.append(
            _attribution_issue(
                "attribution_weight_math_mismatch",
                "attribution.weights.realized_weight_total",
                "realized total must equal the published realized weights",
            )
        )
    cash_basis = target_cash if target_cash is not None else _exact_difference(
        Decimal(1), planned_total
    )
    cash_gap = _exact_difference(realized_cash, cash_basis)
    if weights.cash_gap != _weight_sum(
        cash_gap,
        "attribution.weights.cash_gap",
    ):
        issues.append(
            _attribution_issue(
                "attribution_weight_math_mismatch",
                "attribution.weights.cash_gap",
                "cash gap must be realized cash minus the target or planned cash basis",
            )
        )
    lot_total = _exact_sum(
        _attr_decimal(row.lot_gap) for row in weights.rows
    )
    price_total = _exact_sum(
        _attr_decimal(row.price_gap) for row in weights.rows
    )
    reject_total = _exact_sum(
        _attr_decimal(row.reject_gap) for row in weights.rows
    )
    for name, expected in (
        ("lot_gap_total", lot_total),
        ("price_gap_total", price_total),
        ("reject_gap_total", reject_total),
    ):
        if getattr(weights, name) != _weight_sum(
            expected,
            f"attribution.weights.{name}",
        ):
            issues.append(
                _attribution_issue(
                    "attribution_weight_math_mismatch",
                    f"attribution.weights.{name}",
                    f"{name} must equal the published row sum",
                )
            )
    residual = _exact_sum(
        (
            lot_total,
            price_total,
            reject_total,
            cash_gap,
            valuation_weight,
        )
    )
    if weights.weight_rounding_residual != _weight_sum(
        residual,
        "attribution.weights.residual",
    ):
        issues.append(
            _attribution_issue(
                "attribution_weight_rounding_mismatch",
                "attribution.weights.weight_rounding_residual",
                "the weight residual must be the unfitted gap sum",
            )
        )
    tolerance = _weight_rounding_tolerance(len(weights.rows))
    if weights.weight_rounding_tolerance != _weight_sum(
        tolerance,
        "attribution.weights.tolerance",
    ):
        issues.append(
            _attribution_issue(
                "attribution_weight_rounding_mismatch",
                "attribution.weights.weight_rounding_tolerance",
                "the declared tolerance must be the row-count rounding bound",
            )
        )
    if abs(residual) > tolerance:
        issues.append(
            _attribution_issue(
                "attribution_weight_identity_mismatch",
                "attribution.weights",
                "weight gaps exceed the declared rounding tolerance",
            )
        )
    if weights.reconciled and abs(residual) > tolerance:
        issues.append(
            _attribution_issue(
                "attribution_weight_rounding_mismatch",
                "attribution.weights.reconciled",
                "a reconciled verdict cannot carry an out-of-bound residual",
            )
        )
