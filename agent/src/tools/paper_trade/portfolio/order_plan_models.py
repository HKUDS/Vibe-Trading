"""Typed constants and frozen dataclasses shared by the pt-v2.0 order-plan layers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Final, Literal

from .models import Currency, Market, PortfolioOrder
from .planner import PlannerLine, PlanningMark

ORDER_PLAN_VERSION: Final = "pt-order-plan-v1"
WEIGHT_BASIS: Final = "planning_marks"
REALIZED_WEIGHT_STATUS: Final = "pending_execution"
Side = Literal["buy", "sell"]
PlanMode = Literal["target_weights", "explicit_orders"]


@dataclass(frozen=True, slots=True)
class PlannedOrder:
    """One whole-lot order with its planning mark and estimated cash effect."""

    plan_order_id: str
    bucket_id: str
    market: Market
    symbol: str
    currency: Currency
    side: Side
    qty: int
    lot_size: int
    limit: Decimal | None
    price: Decimal
    price_date: date
    mark_source: str
    mark_as_of: datetime
    fx_rate_id: str | None
    fx_rate: Decimal
    base_price: Decimal
    notional_local: Decimal
    notional_base: Decimal
    estimated_fee_local: Decimal
    estimated_cash_delta_local: Decimal
    estimated_cash_delta_base: Decimal


@dataclass(frozen=True, slots=True)
class SkippedPlanLine:
    """One planner line deliberately left unordered by band or lot flooring."""

    bucket_id: str
    market: Market
    symbol: str
    currency: Currency
    side: Side | None
    reason: str
    current_qty: int
    target_qty: int | None
    intended_qty: int
    residual_qty: int
    lot_size: int
    price: Decimal
    base_price: Decimal
    target_weight: Decimal | None
    current_weight: Decimal | None


@dataclass(frozen=True, slots=True)
class BucketCashPlan:
    """One isolated bucket's exact local cash plan and its base-currency echo."""

    bucket_id: str
    market: Market
    currency: Currency
    opening_cash: Decimal
    sell_proceeds: Decimal
    buy_costs: Decimal
    planned_cash: Decimal
    lot_residual_cash: Decimal
    lot_residual_position_value: Decimal
    fx_rate_id: str | None
    fx_rate: Decimal
    opening_cash_base: Decimal
    sell_proceeds_base: Decimal
    buy_costs_base: Decimal
    planned_cash_base: Decimal
    lot_residual_cash_base: Decimal
    lot_residual_position_value_base: Decimal
    cash_rounding_residual_base: Decimal


@dataclass(frozen=True, slots=True)
class WeightReconciliation:
    """Target/planned/realized weights for one instrument.

    ``planned_weight`` is an estimate at planning marks after whole-lot
    flooring. ``realized_weight`` and ``realized_gap`` are intentionally empty
    until the execution layer reports fills; the plan never claims exact
    post-trade weights.
    """

    bucket_id: str
    symbol: str
    currency: Currency
    current_qty: int
    planned_qty: int
    current_weight: Decimal
    target_weight: Decimal | None
    planned_weight: Decimal
    realized_weight: Decimal | None
    target_gap: Decimal | None
    planned_gap: Decimal | None
    realized_gap: Decimal | None


@dataclass(frozen=True, slots=True)
class OrderPlan:
    """Canonical order sequence plus per-bucket cash and weight reconciliation."""

    plan_version: str
    mode: PlanMode
    trade_date: date
    planning_at: datetime
    base_currency: Currency
    orders: tuple[PlannedOrder, ...]
    skipped: tuple[SkippedPlanLine, ...]
    buckets: tuple[BucketCashPlan, ...]
    weights: tuple[WeightReconciliation, ...]
    total_planned_cash_base: Decimal
    total_lot_residual_cash_base: Decimal
    total_lot_residual_position_value_base: Decimal
    weight_basis: str
    realized_weight_status: str
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _BucketSpec:
    bucket_id: str
    market: Market
    currency: Currency
    opening_cash: Decimal
    fx_rate_id: str | None
    fx_rate: Decimal


@dataclass(frozen=True, slots=True)
class _Decision:
    line: PlannerLine
    lot_size: int
    intended_qty: int
    planned_order: PlannedOrder | None
    skip_reason: str | None
    residual_qty: int


@dataclass(frozen=True, slots=True)
class _ExplicitRow:
    order: PortfolioOrder
    spec: _BucketSpec
    mark: PlanningMark
    price: Decimal
    limit: Decimal | None
