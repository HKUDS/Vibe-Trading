"""Explicit-order mark, header, row and weight validation for pt-v2.0 plans."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal

from .ledger import PortfolioLedger
from .models import PortfolioOrder
from .order_plan_models import (
    PlannedOrder,
    WeightReconciliation,
    _BucketSpec,
    _ExplicitRow,
)
from .order_plan_primitives import (
    _MARKET_ORDER,
    _exact_product,
    _mark_price,
    _money,
    _ratio,
    _reject,
)
from .planner import PlanningMark


def _validate_marks(
    marks: Sequence[PlanningMark],
    *,
    trade_date: date,
    planning_at: datetime,
) -> dict[str, tuple[PlanningMark, Decimal]]:
    if isinstance(marks, (str, bytes, dict)) or not isinstance(marks, Sequence):
        _reject("invalid_planning_marks", "planning_marks")
    supplied: dict[str, tuple[PlanningMark, Decimal]] = {}
    for index, mark in enumerate(marks):
        path = f"planning_marks[{index}]"
        if not isinstance(mark, PlanningMark):
            _reject("invalid_planning_mark", path)
        if not isinstance(mark.symbol, str) or not mark.symbol:
            _reject("invalid_planning_mark", f"{path}.symbol")
        if type(mark.price_date) is not date:
            _reject("invalid_planning_mark", f"{path}.price_date")
        if not isinstance(mark.source, str) or not mark.source:
            _reject("invalid_planning_mark", f"{path}.source")
        if (
            not isinstance(mark.as_of, datetime)
            or mark.as_of.tzinfo is None
            or mark.as_of.utcoffset() is None
        ):
            _reject("invalid_planning_mark", f"{path}.as_of", detail="timestamp must be aware")
        price = _mark_price(mark.close, f"{path}.close")
        if mark.symbol in supplied:
            _reject(
                "duplicate_planning_mark",
                f"{path}.symbol",
                detail=f"instrument {mark.symbol!r} has more than one planning mark",
            )
        if mark.as_of > planning_at:
            _reject("future_planning_mark", f"{path}.as_of")
        if mark.price_date > trade_date:
            _reject("future_planning_mark", f"{path}.price_date")
        if mark.price_date == trade_date:
            _reject("stale_planning_mark", f"{path}.price_date")
        supplied[mark.symbol] = (mark, price)
    return supplied


def _validate_explicit_header(
    orders: Sequence[PortfolioOrder],
    specs: Sequence[_BucketSpec],
    ledger: PortfolioLedger,
) -> tuple[PortfolioOrder, ...]:
    if isinstance(orders, (str, bytes, dict)) or not isinstance(orders, Sequence):
        _reject("invalid_orders", "orders")
    by_bucket = {spec.bucket_id: spec for spec in specs}
    position_owner = {
        position.symbol: bucket.bucket_id
        for bucket in ledger.buckets
        for position in bucket.positions
    }
    seen_ids: set[str] = set()
    seen_instruments: dict[str, str] = {}
    raw: list[PortfolioOrder] = []
    for index, order in enumerate(orders):
        path = f"orders[{index}]"
        if not isinstance(order, PortfolioOrder):
            _reject("invalid_portfolio_order", path, detail="expected a typed PortfolioOrder")
        if not isinstance(order.order_id, str) or not order.order_id:
            _reject("invalid_order_id", f"{path}.order_id")
        if order.order_id in seen_ids:
            _reject(
                "duplicate_order_id",
                f"{path}.order_id",
                bucket_id=order.bucket_id,
                detail=f"order id {order.order_id!r} is used more than once",
            )
        seen_ids.add(order.order_id)
        spec = by_bucket.get(order.bucket_id)
        if spec is None:
            _reject("unknown_bucket", f"{path}.bucket_id", bucket_id=order.bucket_id)
        if not isinstance(order.symbol, str) or not order.symbol:
            _reject("invalid_instrument", f"{path}.symbol", bucket_id=order.bucket_id)
        if order.currency != spec.currency:
            if spec.market == "hk" and order.currency != "HKD":
                _reject("non_hkd_hk_counter", f"{path}.currency", bucket_id=order.bucket_id)
            _reject(
                "instrument_currency_mismatch",
                f"{path}.currency",
                bucket_id=order.bucket_id,
            )
        if order.side not in ("buy", "sell"):
            _reject("invalid_order_side", f"{path}.side", bucket_id=order.bucket_id)
        if type(order.qty) is not int or order.qty <= 0:
            _reject("invalid_order_quantity", f"{path}.qty", bucket_id=order.bucket_id)
        owner = position_owner.get(order.symbol)
        if owner is not None and owner != order.bucket_id:
            _reject(
                "instrument_bucket_mismatch",
                f"{path}.symbol",
                bucket_id=order.bucket_id,
                detail=f"instrument {order.symbol!r} is already owned by bucket {owner!r}",
            )
        seen_owner = seen_instruments.get(order.symbol)
        if seen_owner is not None:
            if seen_owner == order.bucket_id:
                _reject(
                    "duplicate_order_instrument",
                    f"{path}.symbol",
                    bucket_id=order.bucket_id,
                    detail=f"instrument {order.symbol!r} has more than one explicit order",
                )
            _reject(
                "instrument_bucket_mismatch",
                f"{path}.symbol",
                bucket_id=order.bucket_id,
                detail=f"instrument {order.symbol!r} is already ordered in bucket {seen_owner!r}",
            )
        seen_instruments[order.symbol] = order.bucket_id
        raw.append(order)
    return tuple(raw)


def _explicit_rows(
    raw_orders: Sequence[PortfolioOrder],
    specs: Sequence[_BucketSpec],
    supplied_marks: Mapping[str, tuple[PlanningMark, Decimal]],
) -> tuple[_ExplicitRow, ...]:
    by_bucket = {spec.bucket_id: spec for spec in specs}
    rows: list[_ExplicitRow] = []
    for index, order in enumerate(raw_orders):
        path = f"orders[{index}]"
        mark, price = supplied_marks[order.symbol]
        limit = None
        if order.limit is not None:
            limit = _mark_price(order.limit, f"{path}.limit")
        rows.append(
            _ExplicitRow(
                order=order,
                spec=by_bucket[order.bucket_id],
                mark=mark,
                price=price,
                limit=limit,
            )
        )
    return tuple(rows)


def _explicit_weights(
    ledger: PortfolioLedger,
    specs: Sequence[_BucketSpec],
    orders: Sequence[PlannedOrder],
    supplied_marks: Mapping[str, tuple[PlanningMark, Decimal]],
    nav: Decimal,
) -> tuple[WeightReconciliation, ...]:
    by_bucket = {spec.bucket_id: spec for spec in specs}
    position_qty = {
        position.symbol: (bucket.bucket_id, position.qty)
        for bucket in ledger.buckets
        for position in bucket.positions
    }
    signed_by_symbol = {
        order.symbol: (order.qty if order.side == "buy" else -order.qty) for order in orders
    }
    symbols = set(position_qty) | set(signed_by_symbol)
    rank = {spec.bucket_id: _MARKET_ORDER[spec.market] for spec in specs}
    keys: list[tuple[str, str]] = []
    for symbol in symbols:
        owner = position_qty.get(symbol)
        if owner is not None:
            keys.append((owner[0], symbol))
        else:
            order = next(order for order in orders if order.symbol == symbol)
            keys.append((order.bucket_id, symbol))
    rows: list[WeightReconciliation] = []
    for bucket_id, symbol in sorted(keys, key=lambda item: (rank[item[0]], item[0], item[1])):
        spec = by_bucket[bucket_id]
        _, price = supplied_marks[symbol]
        base_price = _exact_product(price, spec.fx_rate)
        held = position_qty.get(symbol)
        current_qty = held[1] if held is not None else 0
        planned_qty = current_qty + signed_by_symbol.get(symbol, 0)
        current_value = _money(
            _exact_product(Decimal(current_qty), base_price),
            f"order_plan.weights.{bucket_id}.{symbol}.current_value",
        )
        planned_value = _money(
            _exact_product(Decimal(planned_qty), base_price),
            f"order_plan.weights.{bucket_id}.{symbol}.planned_value",
        )
        rows.append(
            WeightReconciliation(
                bucket_id=bucket_id,
                symbol=symbol,
                currency=spec.currency,
                current_qty=current_qty,
                planned_qty=planned_qty,
                current_weight=_ratio(current_value, nav),
                target_weight=None,
                planned_weight=_ratio(planned_value, nav),
                realized_weight=None,
                target_gap=None,
                planned_gap=None,
                realized_gap=None,
            )
        )
    return tuple(rows)
