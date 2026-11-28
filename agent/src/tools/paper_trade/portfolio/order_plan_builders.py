"""Public pt-v2.0 order-plan builders: target-weight and explicit-order modes."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from decimal import Decimal

from .fx import FxRateBook
from .ledger import PortfolioLedger, value_ledger
from .models import Currency, FxSnapshot, PortfolioOrder
from .numeric import EffectiveFeeModel
from .order_plan_explicit import (
    _explicit_rows,
    _explicit_weights,
    _validate_explicit_header,
    _validate_marks,
)
from .order_plan_models import (
    ORDER_PLAN_VERSION,
    REALIZED_WEIGHT_STATUS,
    WEIGHT_BASIS,
    OrderPlan,
    PlannedOrder,
    SkippedPlanLine,
    _BucketSpec,
)
from .order_plan_primitives import (
    _exact_product,
    _fee_models,
    _ledger_buckets,
    _lot_size,
    _lot_table,
    _market_rules,
    _money,
    _order_key,
    _rate,
    _reject,
    _side,
    _target_buckets,
    _validate_allocation,
    _validate_identity,
)
from .order_plan_target import (
    _cash_plans,
    _lot_warnings,
    _make_order,
    _target_decisions,
    _target_weights,
    _validate_target_lines,
)
from .planner import PlanningMark, TargetWeightAllocation


def build_target_weight_order_plan(
    allocation: TargetWeightAllocation,
    *,
    fee_models: Sequence[EffectiveFeeModel] = (),
    hk_lot_sizes: Mapping[str, int] | None = None,
) -> OrderPlan:
    """Turn one pure target-weight allocation into canonical whole-lot orders.

    Buckets are ordered ``cn_a``, ``hk``, ``us``; inside each bucket sells come
    before buys and symbols sort lexicographically. Every target line yields
    either one whole-lot order, an explicit skipped row or a lot-floor residual.
    Residual lot cash stays in its own bucket; no cross-bucket funding exists.
    """
    _validate_allocation(allocation)
    specs = _target_buckets(allocation)
    lot_table = _lot_table(hk_lot_sizes)
    fee_map = _fee_models(fee_models, specs)
    rules = {
        spec.bucket_id: _market_rules(spec, fee_map[spec.bucket_id], lot_table)
        for spec in specs
    }
    lines = _validate_target_lines(allocation, specs)
    decisions = _target_decisions(allocation, lines, specs, rules)

    orders = tuple(
        sorted(
            (decision.planned_order for decision in decisions if decision.planned_order is not None),
            key=_order_key,
        )
    )
    seen_ids: set[str] = set()
    for order in orders:
        if order.plan_order_id in seen_ids:
            _reject(
                "duplicate_plan_order_id",
                f"order_plan.{order.bucket_id}.{order.symbol}.plan_order_id",
                bucket_id=order.bucket_id,
            )
        seen_ids.add(order.plan_order_id)

    skipped = tuple(
        SkippedPlanLine(
            bucket_id=decision.line.bucket_id,
            market=next(
                spec.market for spec in specs if spec.bucket_id == decision.line.bucket_id
            ),
            symbol=decision.line.symbol,
            currency=decision.line.currency,
            side=_side(decision.intended_qty),
            reason=decision.skip_reason or "lot_floor_rounding",
            current_qty=decision.line.current_qty,
            target_qty=decision.line.target_quantity,
            intended_qty=decision.intended_qty,
            residual_qty=decision.residual_qty,
            lot_size=decision.lot_size,
            price=decision.line.price,
            base_price=decision.line.base_price,
            target_weight=decision.line.target_weight,
            current_weight=decision.line.current_weight,
        )
        for decision in decisions
        if decision.skip_reason is not None
    )

    residual_cash: dict[str, Decimal] = {}
    residual_position: dict[str, Decimal] = {}
    for decision in decisions:
        if decision.residual_qty <= 0:
            continue
        if decision.skip_reason not in (None, "lot_floor_rounding"):
            continue
        side = _side(decision.intended_qty)
        if side is None:
            continue
        residual_value = _money(
            _exact_product(Decimal(decision.residual_qty), decision.line.price),
            f"order_plan.{decision.line.bucket_id}.{decision.line.symbol}.lot_residual",
        )
        if side == "buy":
            residual_cash[decision.line.bucket_id] = (
                residual_cash.get(decision.line.bucket_id, Decimal(0)) + residual_value
            )
        else:
            residual_position[decision.line.bucket_id] = (
                residual_position.get(decision.line.bucket_id, Decimal(0)) + residual_value
            )

    cash_rows = _cash_plans(specs, orders, residual_cash, residual_position)
    weights = _target_weights(decisions, specs, allocation.nav.reported_nav)
    return OrderPlan(
        plan_version=ORDER_PLAN_VERSION,
        mode="target_weights",
        trade_date=allocation.trade_date,
        planning_at=allocation.planning_at,
        base_currency=allocation.base_currency,
        orders=orders,
        skipped=skipped,
        buckets=cash_rows,
        weights=weights,
        total_planned_cash_base=_money(
            sum((row.planned_cash_base for row in cash_rows), Decimal(0)),
            "order_plan.total_planned_cash_base",
        ),
        total_lot_residual_cash_base=_money(
            sum((row.lot_residual_cash_base for row in cash_rows), Decimal(0)),
            "order_plan.total_lot_residual_cash_base",
        ),
        total_lot_residual_position_value_base=_money(
            sum((row.lot_residual_position_value_base for row in cash_rows), Decimal(0)),
            "order_plan.total_lot_residual_position_value_base",
        ),
        weight_basis=WEIGHT_BASIS,
        realized_weight_status=REALIZED_WEIGHT_STATUS,
        warnings=_lot_warnings(specs, rules),
    )


def build_explicit_order_plan(
    orders: Sequence[PortfolioOrder],
    *,
    ledger: PortfolioLedger,
    trade_date: date,
    planning_at: datetime,
    base_currency: Currency,
    marks: Sequence[PlanningMark],
    fx_snapshots: Sequence[FxSnapshot] = (),
    fee_models: Sequence[EffectiveFeeModel] = (),
    hk_lot_sizes: Mapping[str, int] | None = None,
    max_fx_age: timedelta | None = None,
) -> OrderPlan:
    """Normalize caller orders into canonical, sell-first whole-lot orders.

    Caller order IDs are preserved and must be unique. Submission order never
    decides priority: buckets sort canonically and each bucket emits sells
    before buys. Duplicate IDs/instruments, cross-bucket instruments, invalid
    lots, nonpositive net sale proceeds and cash-infeasible plans fail before
    any match object could exist.
    """
    _validate_identity(trade_date, planning_at, base_currency)
    initial_specs = _ledger_buckets(ledger)
    raw_orders = _validate_explicit_header(orders, initial_specs, ledger)
    lot_table = _lot_table(hk_lot_sizes)
    fee_map = _fee_models(fee_models, initial_specs)
    rules = {
        spec.bucket_id: _market_rules(spec, fee_map[spec.bucket_id], lot_table)
        for spec in initial_specs
    }
    supplied_marks = _validate_marks(marks, trade_date=trade_date, planning_at=planning_at)

    required: dict[str, str] = {
        position.symbol: bucket.bucket_id
        for bucket in ledger.buckets
        for position in bucket.positions
    }
    for order in raw_orders:
        required[order.symbol] = order.bucket_id
    for symbol, bucket_id in required.items():
        if symbol not in supplied_marks:
            _reject(
                "missing_planning_mark",
                f"planning_marks.{symbol}",
                bucket_id=bucket_id,
                detail="every held or explicitly ordered instrument needs a planning mark",
            )

    if isinstance(fx_snapshots, (str, bytes, dict)) or not isinstance(fx_snapshots, Sequence):
        _reject("invalid_fx_snapshots", "fx_snapshots")
    snapshots = tuple(fx_snapshots)
    for index, snapshot in enumerate(snapshots):
        if not isinstance(snapshot, FxSnapshot):
            _reject("invalid_fx_snapshot", f"fx_snapshots[{index}]")
    book = FxRateBook.from_snapshots(snapshots, at=planning_at, max_age=max_fx_age)
    mark_prices = {symbol: price for symbol, (_, price) in supplied_marks.items()}
    bridge = value_ledger(
        ledger,
        mark_prices,
        book,
        base_currency=base_currency,
        path="planning_marks",
    )
    nav = bridge.total.reported_base
    if nav <= 0:
        _reject(
            "nonpositive_planning_nav",
            "planning_nav",
            detail="order planning requires a positive planning NAV",
        )
    rate_by_bucket = {row.bucket_id: row for row in bridge.rows}
    specs = tuple(
        _BucketSpec(
            bucket_id=spec.bucket_id,
            market=spec.market,
            currency=spec.currency,
            opening_cash=spec.opening_cash,
            fx_rate_id=rate_by_bucket[spec.bucket_id].rate_id,
            fx_rate=_rate(
                rate_by_bucket[spec.bucket_id].rate,
                f"planning_marks.{spec.bucket_id}.fx_rate",
            ),
        )
        for spec in initial_specs
    )
    spec_by_bucket = {spec.bucket_id: spec for spec in specs}
    rows = _explicit_rows(raw_orders, specs, supplied_marks)
    position_qty = {
        position.symbol: position.qty
        for bucket in ledger.buckets
        for position in bucket.positions
    }

    pending: list[PlannedOrder] = []
    seen_ids: set[str] = set()
    for index, row in enumerate(rows):
        path = f"orders[{index}]"
        if row.order.order_id in seen_ids:
            _reject("duplicate_plan_order_id", f"{path}.order_id", bucket_id=row.spec.bucket_id)
        seen_ids.add(row.order.order_id)
        lot = _lot_size(rules[row.spec.bucket_id], row.order.symbol, f"{path}.lot_size")
        if row.order.qty % lot != 0:
            _reject(
                "invalid_lot_quantity",
                f"{path}.qty",
                bucket_id=row.spec.bucket_id,
                detail=f"quantity must be a positive multiple of the {lot}-share board lot",
            )
        if row.order.side == "sell" and row.order.qty > position_qty.get(row.order.symbol, 0):
            _reject(
                "insufficient_position",
                f"{path}.qty",
                bucket_id=row.spec.bucket_id,
                detail="an explicit sell cannot exceed the bucket's held quantity",
            )
        pending.append(
            _make_order(
                plan_order_id=row.order.order_id,
                spec=spec_by_bucket[row.order.bucket_id],
                symbol=row.order.symbol,
                side=row.order.side,
                qty=row.order.qty,
                lot_size=lot,
                limit=row.limit,
                price=row.price,
                price_date=row.mark.price_date,
                mark_source=row.mark.source,
                mark_as_of=row.mark.as_of,
                rules=rules[row.spec.bucket_id],
                path=path,
            )
        )
    order_rows = tuple(sorted(pending, key=_order_key))
    cash_rows = _cash_plans(specs, order_rows, {}, {})
    weights = _explicit_weights(ledger, specs, order_rows, supplied_marks, nav)
    return OrderPlan(
        plan_version=ORDER_PLAN_VERSION,
        mode="explicit_orders",
        trade_date=trade_date,
        planning_at=planning_at,
        base_currency=base_currency,
        orders=order_rows,
        skipped=(),
        buckets=cash_rows,
        weights=weights,
        total_planned_cash_base=_money(
            sum((row.planned_cash_base for row in cash_rows), Decimal(0)),
            "order_plan.total_planned_cash_base",
        ),
        total_lot_residual_cash_base=_money(
            sum((row.lot_residual_cash_base for row in cash_rows), Decimal(0)),
            "order_plan.total_lot_residual_cash_base",
        ),
        total_lot_residual_position_value_base=_money(
            sum((row.lot_residual_position_value_base for row in cash_rows), Decimal(0)),
            "order_plan.total_lot_residual_position_value_base",
        ),
        weight_basis=WEIGHT_BASIS,
        realized_weight_status=REALIZED_WEIGHT_STATUS,
        warnings=_lot_warnings(specs, rules),
    )
