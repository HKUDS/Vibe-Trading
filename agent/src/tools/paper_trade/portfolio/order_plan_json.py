"""Deterministic JSON-native rendering of pt-v2.0 order plans for audit evidence."""

from __future__ import annotations

from decimal import Decimal

from .models import JsonObject
from .numeric import (
    FX_RATE_SPEC,
    MONEY_SPEC,
    PRICE_SPEC,
    WEIGHT_SPEC,
    canonical_decimal,
)
from .order_plan_models import OrderPlan
from .order_plan_primitives import _BASE_PRICE_SPEC, _GAP_SPEC


def _money_text(value: Decimal) -> str:
    return canonical_decimal(value, MONEY_SPEC)


def _price_text(value: Decimal) -> str:
    return canonical_decimal(value, PRICE_SPEC)


def _base_price_text(value: Decimal) -> str:
    return canonical_decimal(value, _BASE_PRICE_SPEC)


def _weight_text(value: Decimal) -> str:
    return canonical_decimal(value, WEIGHT_SPEC)


def _gap_text(value: Decimal) -> str:
    return canonical_decimal(value, _GAP_SPEC)


def _fx_text(value: Decimal) -> str:
    return canonical_decimal(value, FX_RATE_SPEC)


def order_plan_to_json(plan: OrderPlan) -> JsonObject:
    """Render the plan as deterministic JSON-native values for audit evidence.

    Money stays at two decimals, prices at six, weights/gaps at twelve and FX
    rates at twelve. Quantities stay integers and no value is ever a float.
    """
    return {
        "plan_version": plan.plan_version,
        "mode": plan.mode,
        "trade_date": plan.trade_date.isoformat(),
        "planning_at": plan.planning_at.isoformat(),
        "base_currency": plan.base_currency,
        "weight_basis": plan.weight_basis,
        "realized_weight_status": plan.realized_weight_status,
        "orders": [
            {
                "plan_order_id": order.plan_order_id,
                "bucket_id": order.bucket_id,
                "market": order.market,
                "symbol": order.symbol,
                "currency": order.currency,
                "side": order.side,
                "qty": order.qty,
                "lot_size": order.lot_size,
                "limit": None if order.limit is None else _price_text(order.limit),
                "price": _price_text(order.price),
                "price_date": order.price_date.isoformat(),
                "mark_source": order.mark_source,
                "mark_as_of": order.mark_as_of.isoformat(),
                "fx_rate_id": order.fx_rate_id,
                "fx_rate": _fx_text(order.fx_rate),
                "base_price": _base_price_text(order.base_price),
                "notional_local": _money_text(order.notional_local),
                "notional_base": _money_text(order.notional_base),
                "estimated_fee_local": _money_text(order.estimated_fee_local),
                "estimated_cash_delta_local": _money_text(order.estimated_cash_delta_local),
                "estimated_cash_delta_base": _money_text(order.estimated_cash_delta_base),
            }
            for order in plan.orders
        ],
        "skipped": [
            {
                "bucket_id": line.bucket_id,
                "market": line.market,
                "symbol": line.symbol,
                "currency": line.currency,
                "side": line.side,
                "reason": line.reason,
                "current_qty": line.current_qty,
                "target_qty": line.target_qty,
                "intended_qty": line.intended_qty,
                "residual_qty": line.residual_qty,
                "lot_size": line.lot_size,
                "price": _price_text(line.price),
                "base_price": _base_price_text(line.base_price),
                "target_weight": None if line.target_weight is None else _weight_text(line.target_weight),
                "current_weight": None if line.current_weight is None else _weight_text(line.current_weight),
            }
            for line in plan.skipped
        ],
        "buckets": [
            {
                "bucket_id": row.bucket_id,
                "market": row.market,
                "currency": row.currency,
                "opening_cash": _money_text(row.opening_cash),
                "sell_proceeds": _money_text(row.sell_proceeds),
                "buy_costs": _money_text(row.buy_costs),
                "planned_cash": _money_text(row.planned_cash),
                "lot_residual_cash": _money_text(row.lot_residual_cash),
                "lot_residual_position_value": _money_text(row.lot_residual_position_value),
                "fx_rate_id": row.fx_rate_id,
                "fx_rate": _fx_text(row.fx_rate),
                "opening_cash_base": _money_text(row.opening_cash_base),
                "sell_proceeds_base": _money_text(row.sell_proceeds_base),
                "buy_costs_base": _money_text(row.buy_costs_base),
                "planned_cash_base": _money_text(row.planned_cash_base),
                "lot_residual_cash_base": _money_text(row.lot_residual_cash_base),
                "lot_residual_position_value_base": _money_text(
                    row.lot_residual_position_value_base
                ),
                "cash_rounding_residual_base": _money_text(
                    row.cash_rounding_residual_base
                ),
            }
            for row in plan.buckets
        ],
        "weights": [
            {
                "bucket_id": row.bucket_id,
                "symbol": row.symbol,
                "currency": row.currency,
                "current_qty": row.current_qty,
                "planned_qty": row.planned_qty,
                "current_weight": _weight_text(row.current_weight),
                "target_weight": None
                if row.target_weight is None
                else _weight_text(row.target_weight),
                "planned_weight": _weight_text(row.planned_weight),
                "realized_weight": None
                if row.realized_weight is None
                else _weight_text(row.realized_weight),
                "target_gap": None if row.target_gap is None else _gap_text(row.target_gap),
                "planned_gap": None if row.planned_gap is None else _gap_text(row.planned_gap),
                "realized_gap": None
                if row.realized_gap is None
                else _gap_text(row.realized_gap),
            }
            for row in plan.weights
        ],
        "total_planned_cash_base": _money_text(plan.total_planned_cash_base),
        "total_lot_residual_cash_base": _money_text(plan.total_lot_residual_cash_base),
        "total_lot_residual_position_value_base": _money_text(
            plan.total_lot_residual_position_value_base
        ),
        "warnings": list(plan.warnings),
    }
