"""Fill replay, fee recomputation and plan-outcome linkage checks."""

from __future__ import annotations

from collections import Counter
from decimal import Decimal
from typing import Any

from ..rules import MarketRules, quantize_money
from .models import ExplicitOrdersPlan, PortfolioResult, TargetWeightsPlan
from .reconcile_primitives import (
    _GENERATED_ORDER_ID,
    _exact,
    _issue,
    _money_even,
    _money_text,
    _ratio,
)


def _replay_fills(
    issues: list[dict[str, Any]],
    document: PortfolioResult,
    buckets: dict[str, Any],
    fee_rules: dict[str, MarketRules],
    cash: dict[str, Decimal],
    positions: dict[tuple[str, str], dict[str, Any]],
    *,
    unverified_cash_buckets: set[str],
) -> None:
    for index, fill in enumerate(document.fills):
        path = f"fills[{index}]"
        bucket = buckets.get(fill.bucket_id)
        if bucket is None:
            _issue(issues, "unknown_fill_bucket", f"{path}.bucket_id", "declared bucket", fill.bucket_id)
            continue
        if fill.currency != bucket.currency:
            _issue(
                issues,
                "fill_currency_mismatch",
                f"{path}.currency",
                bucket.currency,
                fill.currency,
            )
        if fill.trade_date != document.trade_date:
            _issue(
                issues,
                "fill_trade_date_mismatch",
                f"{path}.trade_date",
                document.trade_date.isoformat(),
                fill.trade_date.isoformat(),
            )
        price = Decimal(fill.price)
        fee = Decimal(fill.fee)
        if price <= 0:
            _issue(issues, "invalid_fill_price", f"{path}.price", "> 0", fill.price)
            continue
        rules = fee_rules[fill.bucket_id]
        try:
            expected_fee = rules.fee(fill.side, fill.qty, price)
        except (ArithmeticError, TypeError, ValueError) as exc:
            raise ValueError(f"{path}.fee cannot be replayed: {exc}") from exc
        if fee != expected_fee:
            _issue(
                issues,
                "fill_fee_mismatch",
                f"{path}.fee",
                _money_text(expected_fee),
                _money_text(fee),
            )
        notional = quantize_money(_exact(Decimal(fill.qty), price))
        key = (fill.bucket_id, fill.symbol)
        position = positions.get(key)
        if fill.side == "buy":
            cash[fill.bucket_id] -= notional + fee
            existing_qty = position["qty"] if position else 0
            new_qty = existing_qty + fill.qty
            if existing_qty == 0 or position is None:
                basis = price
            else:
                basis = _ratio(
                    _exact(Decimal(existing_qty), position["avg_cost"])
                    + _exact(Decimal(fill.qty), price),
                    Decimal(new_qty),
                )
            positions[key] = {
                "qty": new_qty,
                "avg_cost": _money_even(basis),
                "currency": bucket.currency,
            }
        else:
            available = position["qty"] if position else 0
            if fill.qty > available:
                _issue(
                    issues,
                    "insufficient_position",
                    f"{path}.qty",
                    available,
                    fill.qty,
                )
            cash[fill.bucket_id] += notional - fee
            if position is None:
                continue
            new_qty = available - fill.qty
            if new_qty <= 0:
                positions.pop(key, None)
            else:
                positions[key]["qty"] = new_qty
        if (
            cash[fill.bucket_id] < 0
            and fill.bucket_id not in unverified_cash_buckets
        ):
            _issue(
                issues,
                "negative_cash",
                path,
                ">= 0",
                _money_text(cash[fill.bucket_id]),
            )


def _check_plan_outcomes(
    issues: list[dict[str, Any]],
    document: PortfolioResult,
) -> None:
    rows: list[tuple[str, int, Any]] = []
    rows.extend(("fills", index, row) for index, row in enumerate(document.fills))
    rows.extend(
        ("rejected_orders", index, row)
        for index, row in enumerate(document.rejected_orders)
    )
    rows.extend(
        ("canceled_orders", index, row)
        for index, row in enumerate(document.canceled_orders)
    )
    counts = Counter(row.plan_order_id for _, _, row in rows)
    seen: set[str] = set()
    for kind, index, row in rows:
        if row.plan_order_id in seen:
            code = "duplicate_fill" if kind == "fills" else "duplicate_order_outcome"
            _issue(
                issues,
                code,
                f"{kind}[{index}].plan_order_id",
                "one terminal outcome per plan order",
                counts[row.plan_order_id],
            )
        seen.add(row.plan_order_id)

    plan = document.plan
    if isinstance(plan, ExplicitOrdersPlan):
        plan_rows: dict[str, Any] = {}
        for index, order in enumerate(plan.orders):
            if order.order_id in plan_rows:
                _issue(
                    issues,
                    "duplicate_plan_order_id",
                    f"plan.orders[{index}].order_id",
                    "unique order_id",
                    order.order_id,
                )
            plan_rows[order.order_id] = order
        for kind, index, row in rows:
            order = plan_rows.get(row.plan_order_id)
            path = f"{kind}[{index}]"
            if order is None:
                _issue(
                    issues,
                    "unknown_plan_order_id",
                    f"{path}.plan_order_id",
                    "declared plan order",
                    row.plan_order_id,
                )
                continue
            fields = {
                "bucket_id": order.bucket_id,
                "symbol": order.symbol,
                "currency": order.currency,
                "side": order.side,
                "qty": order.qty,
            }
            actual = {name: getattr(row, name) for name in fields}
            if actual != fields:
                _issue(
                    issues,
                    "order_outcome_mismatch",
                    path,
                    fields,
                    actual,
                )
        for plan_order_id in plan_rows:
            if plan_order_id not in seen:
                _issue(
                    issues,
                    "missing_order_outcome",
                    f"plan.orders[{plan_order_id}]",
                    "exactly one terminal outcome",
                    None,
                )
    elif isinstance(plan, TargetWeightsPlan):
        target_keys = {(row.bucket_id, row.symbol) for row in plan.target_weights}
        expected_date = document.trade_date.strftime("%Y%m%d")
        for kind, index, row in rows:
            path = f"{kind}[{index}]"
            match = _GENERATED_ORDER_ID.match(row.plan_order_id)
            if match is None:
                _issue(
                    issues,
                    "generated_order_id_mismatch",
                    f"{path}.plan_order_id",
                    "pt2-YYYYMMDD-<bucket>-<side>-<symbol>",
                    row.plan_order_id,
                )
                continue
            day, bucket_id, side, symbol = match.groups()
            actual = {
                "trade_date": day,
                "bucket_id": bucket_id,
                "side": side,
                "symbol": symbol,
            }
            expected = {
                "trade_date": expected_date,
                "bucket_id": row.bucket_id,
                "side": row.side,
                "symbol": row.symbol,
            }
            if actual != expected:
                _issue(
                    issues,
                    "generated_order_id_mismatch",
                    f"{path}.plan_order_id",
                    expected,
                    actual,
                )
            if (row.bucket_id, row.symbol) not in target_keys:
                _issue(
                    issues,
                    "unexpected_plan_order",
                    path,
                    "declared target",
                    {"bucket_id": row.bucket_id, "symbol": row.symbol},
                )

    expected_complete = not document.rejected_orders and not document.canceled_orders
    if document.complete != expected_complete:
        _issue(
            issues,
            "complete_mismatch",
            "complete",
            expected_complete,
            document.complete,
        )
