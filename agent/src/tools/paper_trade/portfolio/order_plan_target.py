"""Target-weight validation, whole-lot decisions, cash plans and weight rows."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal

from ..rules import MarketRules
from .order_plan_models import (
    BucketCashPlan,
    PlannedOrder,
    Side,
    WeightReconciliation,
    _BucketSpec,
    _Decision,
)
from .order_plan_primitives import (
    _MARKET_ORDER,
    _exact_product,
    _finite_decimal,
    _generated_id,
    _lot_size,
    _money,
    _nonnegative_decimal,
    _nonnegative_quantity,
    _positive_decimal,
    _ratio,
    _reject,
    _side,
    _weight,
)
from .planner import PlannerLine, TargetWeightAllocation


def _validate_target_lines(
    allocation: TargetWeightAllocation,
    specs: Sequence[_BucketSpec],
) -> dict[tuple[str, str], PlannerLine]:
    by_bucket = {spec.bucket_id: spec for spec in specs}
    lines: dict[tuple[str, str], PlannerLine] = {}
    symbol_owner: dict[str, str] = {}
    for index, line in enumerate(allocation.lines):
        path = f"target_weight_allocation.lines[{index}]"
        if not isinstance(line, PlannerLine):
            _reject("invalid_plan_line", path)
        if not isinstance(line.bucket_id, str) or line.bucket_id not in by_bucket:
            _reject("unknown_bucket", f"{path}.bucket_id", bucket_id=line.bucket_id)
        spec = by_bucket[line.bucket_id]
        if not isinstance(line.symbol, str) or not line.symbol:
            _reject("invalid_instrument", f"{path}.symbol", bucket_id=line.bucket_id)
        if line.currency != spec.currency:
            _reject("instrument_currency_mismatch", f"{path}.currency", bucket_id=line.bucket_id)
        price = _positive_decimal(line.price, f"{path}.price")
        base_price = _positive_decimal(line.base_price, f"{path}.base_price")
        if base_price != _exact_product(price, spec.fx_rate):
            _reject(
                "planning_mark_rate_mismatch",
                f"{path}.base_price",
                bucket_id=line.bucket_id,
                detail="line base price does not equal the bucket's direct-pair mark",
            )
        _nonnegative_quantity(line.current_qty, f"{path}.current_qty")
        _nonnegative_quantity(line.target_quantity, f"{path}.target_quantity")
        _nonnegative_decimal(line.current_weight, f"{path}.current_weight")
        target_weight = _nonnegative_decimal(line.target_weight, f"{path}.target_weight")
        if target_weight > 1:
            _reject("invalid_target_weight", f"{path}.target_weight", bucket_id=line.bucket_id)
        _finite_decimal(line.weight_gap, f"{path}.weight_gap")
        if not isinstance(line.within_band, bool):
            _reject("invalid_plan_line", f"{path}.within_band")
        if type(line.price_date) is not date:
            _reject("invalid_planning_mark", f"{path}.price_date")
        if line.price_date >= allocation.trade_date:
            _reject(
                "stale_planning_mark",
                f"{path}.price_date",
                bucket_id=line.bucket_id,
                detail="planning marks must be strictly before trade_date",
            )
        if (
            not isinstance(line.mark_as_of, datetime)
            or line.mark_as_of.tzinfo is None
            or line.mark_as_of.utcoffset() is None
        ):
            _reject("invalid_planning_mark", f"{path}.mark_as_of", bucket_id=line.bucket_id)
        if line.mark_as_of > allocation.planning_at:
            _reject("future_planning_mark", f"{path}.mark_as_of", bucket_id=line.bucket_id)
        if not isinstance(line.mark_source, str) or not line.mark_source:
            _reject("invalid_planning_mark", f"{path}.mark_source", bucket_id=line.bucket_id)
        if line.fx_rate_id != spec.fx_rate_id or line.fx_rate != spec.fx_rate:
            _reject("planning_mark_rate_mismatch", f"{path}.fx_rate", bucket_id=line.bucket_id)
        owner = symbol_owner.get(line.symbol)
        if owner is not None and owner != line.bucket_id:
            _reject(
                "instrument_bucket_mismatch",
                f"{path}.symbol",
                bucket_id=line.bucket_id,
                detail=f"instrument {line.symbol!r} is already owned by bucket {owner!r}",
            )
        key = (line.bucket_id, line.symbol)
        if key in lines:
            _reject(
                "duplicate_plan_instrument",
                f"{path}.symbol",
                bucket_id=line.bucket_id,
                detail=f"instrument {line.symbol!r} appears more than once in the allocation",
            )
        symbol_owner[line.symbol] = line.bucket_id
        lines[key] = line
    return lines


def _make_order(
    *,
    plan_order_id: str,
    spec: _BucketSpec,
    symbol: str,
    side: Side,
    qty: int,
    lot_size: int,
    limit: Decimal | None,
    price: Decimal,
    price_date: date,
    mark_source: str,
    mark_as_of: datetime,
    rules: MarketRules,
    path: str,
) -> PlannedOrder:
    notional_local = _money(_exact_product(Decimal(qty), price), f"{path}.notional_local")
    fee_local = _money(rules.fee(side, qty, price), f"{path}.fee")
    if fee_local < 0:
        _reject("negative_fee", f"{path}.fee", bucket_id=spec.bucket_id)
    if side == "sell":
        cash_delta_local = notional_local - fee_local
        if cash_delta_local <= 0:
            _reject(
                "nonpositive_sale_proceeds",
                f"{path}.proceeds",
                bucket_id=spec.bucket_id,
                detail="net sale proceeds must be positive before planning cash",
            )
    else:
        cash_delta_local = -(notional_local + fee_local)
    return PlannedOrder(
        plan_order_id=plan_order_id,
        bucket_id=spec.bucket_id,
        market=spec.market,
        symbol=symbol,
        currency=spec.currency,
        side=side,
        qty=qty,
        lot_size=lot_size,
        limit=limit,
        price=price,
        price_date=price_date,
        mark_source=mark_source,
        mark_as_of=mark_as_of,
        fx_rate_id=spec.fx_rate_id,
        fx_rate=spec.fx_rate,
        base_price=_exact_product(price, spec.fx_rate),
        notional_local=notional_local,
        notional_base=_money(_exact_product(notional_local, spec.fx_rate), f"{path}.notional_base"),
        estimated_fee_local=fee_local,
        estimated_cash_delta_local=cash_delta_local,
        estimated_cash_delta_base=_money(
            _exact_product(cash_delta_local, spec.fx_rate),
            f"{path}.cash_delta_base",
        ),
    )


def _target_decisions(
    allocation: TargetWeightAllocation,
    lines: Mapping[tuple[str, str], PlannerLine],
    specs: Sequence[_BucketSpec],
    rules: Mapping[str, MarketRules],
) -> tuple[_Decision, ...]:
    rank = {spec.bucket_id: _MARKET_ORDER[spec.market] for spec in specs}
    decisions: list[_Decision] = []
    for bucket_id, symbol in sorted(
        lines,
        key=lambda item: (rank[item[0]], item[0], item[1]),
    ):
        line = lines[(bucket_id, symbol)]
        lot = _lot_size(
            rules[bucket_id],
            symbol,
            f"target_weight_allocation.lines.{bucket_id}.{symbol}.lot_size",
        )
        intended = line.target_quantity - line.current_qty
        side = _side(intended)
        if line.within_band:
            reason: str | None = "within_rebalance_band"
            planned_qty = 0
        elif intended == 0:
            reason = "no_target_change"
            planned_qty = 0
        else:
            planned_qty = (abs(intended) // lot) * lot
            reason = None if planned_qty else "lot_floor_rounding"
        planned_order = None
        if planned_qty and side is not None:
            planned_order = _make_order(
                plan_order_id=_generated_id(
                    allocation.trade_date,
                    bucket_id,
                    side,
                    symbol,
                ),
                spec=next(spec for spec in specs if spec.bucket_id == bucket_id),
                symbol=symbol,
                side=side,
                qty=planned_qty,
                lot_size=lot,
                limit=None,
                price=line.price,
                price_date=line.price_date,
                mark_source=line.mark_source,
                mark_as_of=line.mark_as_of,
                rules=rules[bucket_id],
                path=f"order_plan.{bucket_id}.{symbol}",
            )
        decisions.append(
            _Decision(
                line=line,
                lot_size=lot,
                intended_qty=intended,
                planned_order=planned_order,
                skip_reason=reason,
                residual_qty=abs(intended) - planned_qty,
            )
        )
    return tuple(decisions)


def _cash_plans(
    specs: Sequence[_BucketSpec],
    orders: Sequence[PlannedOrder],
    residual_cash: Mapping[str, Decimal],
    residual_position: Mapping[str, Decimal],
) -> tuple[BucketCashPlan, ...]:
    rows: list[BucketCashPlan] = []
    for spec in specs:
        bucket_orders = tuple(order for order in orders if order.bucket_id == spec.bucket_id)
        sell_proceeds = _money(
            sum(
                (order.notional_local - order.estimated_fee_local for order in bucket_orders if order.side == "sell"),
                Decimal(0),
            ),
            f"order_plan.{spec.bucket_id}.sell_proceeds",
        )
        buy_costs = _money(
            sum(
                (order.notional_local + order.estimated_fee_local for order in bucket_orders if order.side == "buy"),
                Decimal(0),
            ),
            f"order_plan.{spec.bucket_id}.buy_costs",
        )
        planned_cash = _money(
            spec.opening_cash + sell_proceeds - buy_costs,
            f"order_plan.{spec.bucket_id}.planned_cash",
        )
        if planned_cash < 0:
            _reject(
                "insufficient_planning_cash",
                f"order_plan.{spec.bucket_id}.planned_cash",
                bucket_id=spec.bucket_id,
                detail="planned buys exceed opening cash plus same-bucket sell proceeds",
            )
        opening_base = _money(
            _exact_product(spec.opening_cash, spec.fx_rate),
            f"order_plan.{spec.bucket_id}.opening_cash_base",
        )
        sell_base = _money(
            _exact_product(sell_proceeds, spec.fx_rate),
            f"order_plan.{spec.bucket_id}.sell_proceeds_base",
        )
        buy_base = _money(
            _exact_product(buy_costs, spec.fx_rate),
            f"order_plan.{spec.bucket_id}.buy_costs_base",
        )
        planned_base = _money(
            _exact_product(planned_cash, spec.fx_rate),
            f"order_plan.{spec.bucket_id}.planned_cash_base",
        )
        lot_cash = _money(
            residual_cash.get(spec.bucket_id, Decimal(0)),
            f"order_plan.{spec.bucket_id}.lot_residual_cash",
        )
        lot_position = _money(
            residual_position.get(spec.bucket_id, Decimal(0)),
            f"order_plan.{spec.bucket_id}.lot_residual_position_value",
        )
        rows.append(
            BucketCashPlan(
                bucket_id=spec.bucket_id,
                market=spec.market,
                currency=spec.currency,
                opening_cash=spec.opening_cash,
                sell_proceeds=sell_proceeds,
                buy_costs=buy_costs,
                planned_cash=planned_cash,
                lot_residual_cash=lot_cash,
                lot_residual_position_value=lot_position,
                fx_rate_id=spec.fx_rate_id,
                fx_rate=spec.fx_rate,
                opening_cash_base=opening_base,
                sell_proceeds_base=sell_base,
                buy_costs_base=buy_base,
                planned_cash_base=planned_base,
                lot_residual_cash_base=_money(
                    _exact_product(lot_cash, spec.fx_rate),
                    f"order_plan.{spec.bucket_id}.lot_residual_cash_base",
                ),
                lot_residual_position_value_base=_money(
                    _exact_product(lot_position, spec.fx_rate),
                    f"order_plan.{spec.bucket_id}.lot_residual_position_value_base",
                ),
                cash_rounding_residual_base=_money(
                    planned_base - (opening_base + sell_base - buy_base),
                    f"order_plan.{spec.bucket_id}.cash_rounding_residual_base",
                ),
            )
        )
    return tuple(rows)


def _target_weights(
    decisions: Sequence[_Decision],
    specs: Sequence[_BucketSpec],
    nav: Decimal,
) -> tuple[WeightReconciliation, ...]:
    rank = {spec.bucket_id: _MARKET_ORDER[spec.market] for spec in specs}
    rows: list[WeightReconciliation] = []
    for decision in sorted(
        decisions,
        key=lambda item: (rank[item.line.bucket_id], item.line.bucket_id, item.line.symbol),
    ):
        line = decision.line
        signed = 0
        if decision.planned_order is not None:
            signed = (
                decision.planned_order.qty
                if decision.planned_order.side == "buy"
                else -decision.planned_order.qty
            )
        planned_qty = line.current_qty + signed
        planned_value = _money(
            _exact_product(Decimal(planned_qty), line.base_price),
            f"order_plan.weights.{line.bucket_id}.{line.symbol}.planned_value",
        )
        planned_weight = _ratio(planned_value, nav)
        rows.append(
            WeightReconciliation(
                bucket_id=line.bucket_id,
                symbol=line.symbol,
                currency=line.currency,
                current_qty=line.current_qty,
                planned_qty=planned_qty,
                current_weight=line.current_weight,
                target_weight=line.target_weight,
                planned_weight=planned_weight,
                realized_weight=None,
                target_gap=line.weight_gap,
                planned_gap=_weight(planned_weight - line.target_weight),
                realized_gap=None,
            )
        )
    return tuple(rows)


def _lot_warnings(
    specs: Sequence[_BucketSpec],
    rules: Mapping[str, MarketRules],
) -> tuple[str, ...]:
    messages: list[str] = []
    for spec in specs:
        for symbol, lot in sorted(rules[spec.bucket_id].lot_assumptions.items()):
            messages.append(
                f"{spec.bucket_id}: lot assumption: {symbol} sized on the default "
                f"{lot}-share board lot (no lot table entry)"
            )
    return tuple(messages)
