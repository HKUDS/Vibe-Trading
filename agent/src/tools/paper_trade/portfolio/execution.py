"""Decimal reconstruct-and-check execution adapter for pt-v2.0 portfolios.

The legacy single-day ``all_or_none`` matcher is used only as an ordered
producer of fill/reject/cancel terminal rows. Portfolio accounting never reads
its float ``Fill`` values as money, its ``end_state`` or its ``NavPoint`` rows:
every fill quantity comes from the source integer plan order, every execution
price from the prepared target-day close snapshot, and every fee from the same
:class:`~..rules.MarketRules` used by the plan. The legacy float fill is a
consistency guard only; any disagreement, nonfinite value, duplicate/missing
terminal outcome, nonpositive sale proceeds, negative fee or negative cash
aborts before an :class:`~.orchestrator.ExecutionOutcome` can be returned.

Only cash and position movements leave this module. FX conversions settle
before matching (task 11), volume-share/5m and strategy execution are out of
scope, and each planned order gets exactly one terminal outcome.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation, localcontext
from typing import Final, NoReturn

import pandas as pd

from .. import engine
from ..rules import MarketRules, quantize_money
from ..schema import AccountState, Order, Position
from .data import BucketPreflight, PreparedBucketData, PreparedPortfolioData
from .ledger import (
    BucketLedger,
    CashMovement,
    LedgerEvent,
    PortfolioLedger,
    PositionMovement,
)
from .models import PortfolioRequest
from .numeric import (
    MONEY_SPEC,
    EffectiveFeeModel,
    canonical_decimal,
    parse_effective_fee_model,
)
from .orchestrator import (
    ExecutionCancellation,
    ExecutionFill,
    ExecutionOutcome,
    ExecutionRejection,
)
from .order_plan import OrderPlan, PlannedOrder
from .schema import PortfolioRequestError

__all__ = ["DecimalExecutionAdapter", "ExecutionAdapterError"]

_EXACT_PRECISION: Final = 60


@dataclass(frozen=True, slots=True)
class ExecutionAdapterError(ValueError):
    """One stable execution-stage rejection with no partial outcome attached."""

    reason: str
    path: str
    bucket_id: str | None = None
    detail: str = ""

    def __str__(self) -> str:
        return f"EXECUTION_MISMATCH:{self.reason}:{self.path}"


def _abort(
    reason: str,
    path: str,
    *,
    bucket_id: str | None = None,
    detail: str = "",
) -> NoReturn:
    raise ExecutionAdapterError(
        reason=reason,
        path=path,
        bucket_id=bucket_id,
        detail=detail,
    )


def _exact_product(left: Decimal, right: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = _EXACT_PRECISION
        return left * right


def _finite_decimal(value: object, path: str, bucket_id: str | None = None) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        _abort("nonfinite_decimal", path, bucket_id=bucket_id)
    return value


def _legacy_decimal(value: object, path: str, bucket_id: str) -> Decimal:
    """Read one legacy float as an exact Decimal, or abort on any lossiness."""
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        _abort("invalid_legacy_value", path, bucket_id=bucket_id)
    if isinstance(value, float) and not math.isfinite(value):
        _abort("nonfinite_legacy_value", path, bucket_id=bucket_id)
    if isinstance(value, Decimal) and not value.is_finite():
        _abort("nonfinite_legacy_value", path, bucket_id=bucket_id)
    try:
        return Decimal(str(value))
    except InvalidOperation:
        _abort("invalid_legacy_value", path, bucket_id=bucket_id)


def _price_decimal(value: object, path: str, bucket_id: str) -> Decimal:
    if not isinstance(value, str):
        _abort("invalid_execution_price", path, bucket_id=bucket_id)
    try:
        price = Decimal(value)
    except InvalidOperation:
        _abort("invalid_execution_price", path, bucket_id=bucket_id)
    if not price.is_finite() or price <= 0:
        _abort("invalid_execution_price", path, bucket_id=bucket_id)
    return price


def _fee_for(
    rules: MarketRules,
    side: str,
    qty: int,
    price: Decimal,
) -> Decimal:
    """One fee from the exact fee primitive shared with planning and legacy."""
    try:
        return rules.fee(side, qty, price)
    except (ArithmeticError, ValueError, TypeError):
        _abort("invalid_execution_fee", "execution.fee")


@dataclass(frozen=True, slots=True)
class _PreparedDayCalendar:
    """Replays the preflight day plan through the engine's calendar seam."""

    open_days: frozenset[str]

    def get_trade_calendar(self, start_date: str, end_date: str) -> pd.DataFrame:
        rows = [
            {
                "exchange": "SSE",
                "cal_date": day.strftime("%Y-%m-%d"),
                "is_open": int(day.strftime("%Y-%m-%d") in self.open_days),
                "pretrade_date": "",
            }
            for day in pd.date_range(start_date, end_date)
        ]
        return pd.DataFrame(
            rows,
            columns=["exchange", "cal_date", "is_open", "pretrade_date"],
        )


def _bucket_map(ledger: PortfolioLedger) -> dict[str, BucketLedger]:
    return {bucket.bucket_id: bucket for bucket in ledger.buckets}


def _effective_models(
    request: PortfolioRequest,
    supplied: Sequence[EffectiveFeeModel],
) -> dict[str, EffectiveFeeModel]:
    buckets = {bucket.bucket_id: bucket for bucket in request.portfolio_state.buckets}
    if supplied:
        if isinstance(supplied, (str, bytes, dict)):
            _abort("invalid_effective_fee_models", "fee_models")
        models: dict[str, EffectiveFeeModel] = {}
        for index, model in enumerate(supplied):
            path = f"fee_models[{index}]"
            if not isinstance(model, EffectiveFeeModel):
                _abort("invalid_effective_fee_model", path)
            bucket = buckets.get(model.bucket_id)
            if bucket is None:
                _abort("unknown_fee_bucket", f"{path}.bucket_id", bucket_id=model.bucket_id)
            if model.bucket_id in models:
                _abort("duplicate_effective_fee_model", f"{path}.bucket_id", bucket_id=model.bucket_id)
            if model.market != bucket.market or model.currency != bucket.currency:
                _abort("fee_bucket_mismatch", path, bucket_id=model.bucket_id)
            models[model.bucket_id] = model
    else:
        try:
            models = {
                bucket.bucket_id: parse_effective_fee_model(bucket)
                for bucket in request.portfolio_state.buckets
            }
        except PortfolioRequestError as exc:
            _abort(
                "invalid_fee_model",
                exc.path,
                bucket_id=exc.bucket_id,
                detail=exc.detail,
            )
    missing = set(buckets) - set(models)
    if missing:
        bucket_id = sorted(missing)[0]
        _abort("missing_effective_fee_model", f"fee_models.{bucket_id}", bucket_id=bucket_id)
    return models


def _market_rules(
    model: EffectiveFeeModel,
    hk_lot_sizes: Mapping[str, int] | None,
) -> MarketRules:
    try:
        return MarketRules(
            model.market,
            dict(model.parameters),
            hk_lot_sizes=hk_lot_sizes,
        )
    except (ArithmeticError, TypeError, ValueError):
        _abort("invalid_market_rules", f"fee_models.{model.bucket_id}", bucket_id=model.bucket_id)


def _validate_plan(
    request: PortfolioRequest,
    ledger: PortfolioLedger,
    plan: OrderPlan,
    prepared: PreparedPortfolioData,
) -> None:
    if not isinstance(request, PortfolioRequest):
        _abort("invalid_request", "$")
    if not isinstance(ledger, PortfolioLedger):
        _abort("invalid_ledger", "portfolio_ledger")
    if not isinstance(plan, OrderPlan):
        _abort("invalid_order_plan", "order_plan")
    if not isinstance(prepared, PreparedPortfolioData):
        _abort("invalid_prepared_data", "prepared_data")
    if request.interval != "1d" or request.fill_model != "all_or_none":
        _abort("unsupported_execution_mode", "request", detail="only single-day all_or_none")
    expected_mode = "explicit_orders" if request.orders is not None else "target_weights"
    if plan.mode != expected_mode:
        _abort("plan_mode_mismatch", "order_plan.mode")
    if (
        plan.trade_date != request.trade_date
        or plan.planning_at != request.planning_at
        or plan.base_currency != request.base_currency
    ):
        _abort("plan_identity_mismatch", "order_plan")

    ledger_by_id = _bucket_map(ledger)
    plan_ids = [bucket.bucket_id for bucket in plan.buckets]
    if len(plan_ids) != len(set(plan_ids)) or set(plan_ids) != set(ledger_by_id):
        _abort("plan_ledger_bucket_mismatch", "order_plan.buckets")
    for bucket_plan in plan.buckets:
        bucket = ledger_by_id[bucket_plan.bucket_id]
        if (
            bucket_plan.market != bucket.market
            or bucket_plan.currency != bucket.currency
        ):
            _abort(
                "plan_ledger_identity_mismatch",
                f"order_plan.buckets.{bucket_plan.bucket_id}",
                bucket_id=bucket_plan.bucket_id,
            )
        if bucket_plan.opening_cash != bucket.cash:
            _abort(
                "plan_ledger_cash_mismatch",
                f"order_plan.buckets.{bucket_plan.bucket_id}.opening_cash",
                bucket_id=bucket_plan.bucket_id,
                detail="the plan must be built from this post-conversion ledger",
            )

    prepared_ids = [bucket.bucket_id for bucket in prepared.buckets]
    if len(prepared_ids) != len(set(prepared_ids)) or set(prepared_ids) != set(ledger_by_id):
        _abort("prepared_bucket_mismatch", "prepared_data.buckets")
    for bucket in prepared.buckets:
        ledger_bucket = ledger_by_id[bucket.bucket_id]
        if (
            bucket.session.bucket_id != bucket.bucket_id
            or bucket.session.market != ledger_bucket.market
            or bucket.session.price_date != request.trade_date
        ):
            _abort(
                "prepared_session_mismatch",
                f"prepared_data.buckets.{bucket.bucket_id}.session",
                bucket_id=bucket.bucket_id,
            )

    if not prepared.preflight:
        _abort(
            "missing_preflight_journal",
            "prepared_data.preflight",
            detail="the Decimal adapter needs the raw preflight market-data journal",
        )
    journal_ids = [entry.bucket_id for entry in prepared.preflight]
    if len(journal_ids) != len(set(journal_ids)) or set(journal_ids) != set(ledger_by_id):
        _abort("incomplete_preflight_journal", "prepared_data.preflight")

    seen_orders: set[str] = set()
    seen_instruments: set[tuple[str, str]] = set()
    for order in plan.orders:
        if not isinstance(order, PlannedOrder):
            _abort("invalid_planned_order", "order_plan.orders")
        if order.plan_order_id in seen_orders:
            _abort(
                "duplicate_plan_order_id",
                f"order_plan.orders.{order.plan_order_id}",
                bucket_id=order.bucket_id,
            )
        seen_orders.add(order.plan_order_id)
        bucket = ledger_by_id.get(order.bucket_id)
        if bucket is None:
            _abort("unknown_plan_bucket", f"order_plan.orders.{order.plan_order_id}.bucket_id")
        if (
            order.market != bucket.market
            or order.currency != bucket.currency
            or order.side not in ("buy", "sell")
            or type(order.qty) is not int
            or order.qty <= 0
            or not isinstance(order.symbol, str)
            or not order.symbol
        ):
            _abort(
                "invalid_planned_order",
                f"order_plan.orders.{order.plan_order_id}",
                bucket_id=order.bucket_id,
            )
        key = (order.bucket_id, order.symbol)
        if key in seen_instruments:
            _abort(
                "duplicate_plan_instrument",
                f"order_plan.orders.{order.plan_order_id}.symbol",
                bucket_id=order.bucket_id,
            )
        seen_instruments.add(key)


def _preflight_for_bucket(
    bucket: BucketLedger,
    request: PortfolioRequest,
    prepared: PreparedPortfolioData,
) -> BucketPreflight:
    entry = next(
        (row for row in prepared.preflight if row.bucket_id == bucket.bucket_id),
        None,
    )
    if entry is None:
        _abort("missing_bucket_preflight", "prepared_data.preflight", bucket_id=bucket.bucket_id)
    if entry.market != bucket.market:
        _abort("prepared_market_mismatch", "prepared_data.preflight", bucket_id=bucket.bucket_id)
    bucket_data = entry.prepared
    if (
        bucket_data.session.bucket_id != bucket.bucket_id
        or bucket_data.session.market != bucket.market
        or bucket_data.session.price_date != request.trade_date
        or not bucket_data.session.matchable
    ):
        _abort("bucket_not_matchable", "prepared_data.buckets", bucket_id=bucket.bucket_id)
    if bucket_data.execution is None:
        _abort("missing_execution_snapshot", "prepared_data.buckets", bucket_id=bucket.bucket_id)
    if bucket_data.execution.price_date != request.trade_date:
        _abort(
            "execution_date_mismatch",
            f"prepared_data.buckets.{bucket.bucket_id}.execution",
            bucket_id=bucket.bucket_id,
        )
    if (
        entry.market_data.market != bucket.market
        or entry.market_data.interval != "1d"
        or entry.market_data.from_date != request.trade_date.isoformat()
        or entry.market_data.to_date != request.trade_date.isoformat()
    ):
        _abort(
            "prepared_market_data_mismatch",
            f"prepared_data.buckets.{bucket.bucket_id}.market_data",
            bucket_id=bucket.bucket_id,
        )
    if not entry.readiness.ready:
        _abort("target_bar_not_ready", "prepared_data.preflight", bucket_id=bucket.bucket_id)
    day = request.trade_date.isoformat()
    day_entries = tuple(row for row in entry.day_plan if row.date == day)
    if len(day_entries) != 1:
        _abort("missing_day_plan", f"prepared_data.buckets.{bucket.bucket_id}.day_plan", bucket_id=bucket.bucket_id)
    if day_entries[0].skip_reason is not None:
        _abort("closed_target_day", "prepared_data.buckets", bucket_id=bucket.bucket_id)
    if day in entry.corporate_actions.clean_by_day or day in entry.corporate_actions.unresolved_by_day:
        _abort(
            "corporate_action_at_execution",
            f"prepared_data.buckets.{bucket.bucket_id}.corporate_actions",
            bucket_id=bucket.bucket_id,
        )
    return entry


def _target_closes(
    bucket: BucketLedger,
    entry: BucketPreflight,
) -> dict[str, Decimal]:
    bucket_data: PreparedBucketData = entry.prepared
    execution = bucket_data.execution
    if execution is None:
        _abort("missing_execution_snapshot", "prepared_data.buckets", bucket_id=bucket.bucket_id)
    closes: dict[str, Decimal] = {}
    for bar in execution.bars:
        if bar.symbol in closes:
            _abort(
                "duplicate_execution_price",
                f"prepared_data.buckets.{bucket.bucket_id}.execution.{bar.symbol}",
                bucket_id=bucket.bucket_id,
            )
        closes[bar.symbol] = _price_decimal(
            bar.close,
            f"prepared_data.buckets.{bucket.bucket_id}.execution.{bar.symbol}.close",
            bucket.bucket_id,
        )
    if not closes:
        _abort("missing_execution_prices", "prepared_data.buckets", bucket_id=bucket.bucket_id)
    return closes


def _legacy_account(bucket: BucketLedger) -> AccountState:
    # Decimal inputs cross the seam unchanged: MarketRules and the engine call
    # money()/Decimal(str(...)) themselves, so no float is introduced here.
    return AccountState(
        cash=bucket.cash,
        positions=tuple(
            Position(symbol=position.symbol, qty=position.qty, avg_cost=position.avg_cost)
            for position in bucket.positions
        ),
    )


def _legacy_orders(orders: Sequence[PlannedOrder]) -> tuple[Order, ...]:
    return tuple(
        Order(symbol=order.symbol, side=order.side, qty=order.qty, limit=order.limit)
        for order in orders
    )


def _bucket_day_calendar(entry: BucketPreflight) -> _PreparedDayCalendar:
    return _PreparedDayCalendar(
        open_days=frozenset(
            row.date for row in entry.day_plan if row.skip_reason is None
        )
    )


def _run_legacy_match(
    bucket: BucketLedger,
    request: PortfolioRequest,
    entry: BucketPreflight,
    rules: MarketRules,
    orders: Sequence[PlannedOrder],
    hk_lot_sizes: Mapping[str, int] | None,
) -> engine.MatchOutcome:
    day = request.trade_date.isoformat()
    try:
        outcome = engine.run_day_loop(
            market=bucket.market,
            account_state=_legacy_account(bucket),
            from_date=day,
            to_date=day,
            orders_by_day={day: _legacy_orders(orders)},
            market_data=entry.market_data,
            fee_model=dict(rules.effective_fee_model),
            calendar_client=_bucket_day_calendar(entry) if bucket.market == "cn_a" else None,
            limits_client=None,
            corporate_action_unresolved_by_day=entry.corporate_actions.unresolved_by_day,
            hk_lot_sizes=hk_lot_sizes,
        )
    except Exception as exc:  # noqa: BLE001 — an engine fault must abort the document
        _abort(
            "engine_execution_failed",
            f"execution.{bucket.bucket_id}",
            bucket_id=bucket.bucket_id,
            detail=f"{type(exc).__name__}: {exc}"[:200],
        )
    if outcome.error is not None:
        _abort(
            "legacy_engine_error",
            f"execution.{bucket.bucket_id}",
            bucket_id=bucket.bucket_id,
            detail=f"{outcome.error.code}: {outcome.error.message}"[:200],
        )
    if outcome.skipped_days:
        _abort(
            "unexpected_skipped_day",
            f"execution.{bucket.bucket_id}.skipped_days",
            bucket_id=bucket.bucket_id,
        )
    for attribute in ("conversions", "fx_conversions", "conversion_requests"):
        if getattr(outcome, attribute, ()):
            _abort(
                "post_fill_fx_conversion",
                f"execution.{bucket.bucket_id}.{attribute}",
                bucket_id=bucket.bucket_id,
            )
    return outcome


def _terminal_rows(
    outcome: engine.MatchOutcome,
    bucket: BucketLedger,
    orders: Sequence[PlannedOrder],
    day: str,
) -> dict[tuple[str, str], tuple[str, object]]:
    rows: dict[tuple[str, str], tuple[str, object]] = {}
    expected = {(order.symbol, order.side) for order in orders}
    sources = (
        ("fill", outcome.fills),
        ("rejected", outcome.rejected_orders),
        ("canceled", outcome.canceled_orders),
    )
    for kind, values in sources:
        for row in values:
            key = (row.symbol, row.side)
            if key in rows:
                _abort(
                    "duplicate_order_outcome",
                    f"execution.{bucket.bucket_id}.{kind}.{row.symbol}",
                    bucket_id=bucket.bucket_id,
                    detail="every planned order has exactly one terminal outcome",
                )
            if key not in expected:
                _abort(
                    "unexpected_order_outcome",
                    f"execution.{bucket.bucket_id}.{kind}.{row.symbol}",
                    bucket_id=bucket.bucket_id,
                )
            if str(row.trade_date) != day:
                _abort(
                    "outcome_date_mismatch",
                    f"execution.{bucket.bucket_id}.{kind}.{row.symbol}",
                    bucket_id=bucket.bucket_id,
                )
            rows[key] = (kind, row)
    missing = expected - set(rows)
    if missing:
        symbol, side = sorted(missing)[0]
        _abort(
            "missing_order_outcome",
            f"execution.{bucket.bucket_id}.{symbol}.{side}",
            bucket_id=bucket.bucket_id,
        )
    if len(rows) != len(orders):
        _abort(
            "inconsistent_order_outcome_count",
            f"execution.{bucket.bucket_id}",
            bucket_id=bucket.bucket_id,
        )
    return rows


def _post_buy_avg_cost(
    bucket: BucketLedger,
    order: PlannedOrder,
    price: Decimal,
) -> Decimal:
    current = next(
        (position for position in bucket.positions if position.symbol == order.symbol),
        None,
    )
    if current is None:
        basis = price
    else:
        with localcontext() as context:
            context.prec = _EXACT_PRECISION
            total_qty = current.qty + order.qty
            basis = (
                Decimal(current.qty) * current.avg_cost + Decimal(order.qty) * price
            ) / Decimal(total_qty)
    # The Decimal ledger stores fee-exclusive average cost at the money scale;
    # canonical_decimal applies the ledger's ROUND_HALF_EVEN canonicalisation.
    return Decimal(
        canonical_decimal(
            basis,
            MONEY_SPEC,
            f"execution.{bucket.bucket_id}.{order.symbol}.avg_cost",
        )
    )


def _check_fee(fee: Decimal, bucket_id: str, order: PlannedOrder) -> None:
    _finite_decimal(fee, f"execution.{bucket_id}.{order.plan_order_id}.fee", bucket_id)
    if fee < 0:
        _abort(
            "negative_execution_fee",
            f"execution.{bucket_id}.{order.plan_order_id}.fee",
            bucket_id=bucket_id,
            detail="fees may not reduce a fill's cash effect",
        )


def _fill_row(
    *,
    bucket: BucketLedger,
    order: PlannedOrder,
    row: engine.Fill,
    price: Decimal,
    fee: Decimal,
    trade_date: date,
    running_cash: dict[str, Decimal],
) -> tuple[ExecutionFill, tuple[LedgerEvent, ...]]:
    day_path = f"execution.{bucket.bucket_id}.{order.plan_order_id}"
    legacy_qty = _legacy_decimal(row.qty, f"{day_path}.qty", bucket.bucket_id)
    if legacy_qty != Decimal(order.qty):
        _abort(
            "legacy_execution_mismatch",
            f"{day_path}.qty",
            bucket_id=bucket.bucket_id,
            detail=f"legacy qty {legacy_qty} != planned {order.qty}",
        )
    if order.side == "sell":
        try:
            notional = quantize_money(_exact_product(Decimal(order.qty), price))
        except ArithmeticError:
            _abort("nonfinite_execution_value", f"{day_path}.notional", bucket_id=bucket.bucket_id)
        proceeds = notional - fee
        if not proceeds.is_finite() or proceeds <= 0:
            _abort(
                "nonpositive_sale_proceeds",
                f"{day_path}.proceeds",
                bucket_id=bucket.bucket_id,
                detail=f"net proceeds {proceeds} must be positive",
            )
        cash_amount = proceeds
    else:
        try:
            notional = quantize_money(_exact_product(Decimal(order.qty), price))
        except ArithmeticError:
            _abort("nonfinite_execution_value", f"{day_path}.notional", bucket_id=bucket.bucket_id)
        cash_amount = -(notional + fee)

    legacy_price = _legacy_decimal(row.price, f"{day_path}.price", bucket.bucket_id)
    if legacy_price != price:
        _abort(
            "legacy_execution_mismatch",
            f"{day_path}.price",
            bucket_id=bucket.bucket_id,
            detail=f"legacy price {legacy_price} != target close {price}",
        )
    legacy_fee = _legacy_decimal(row.fee, f"{day_path}.fee", bucket.bucket_id)
    if legacy_fee != fee:
        _abort(
            "legacy_execution_mismatch",
            f"{day_path}.fee",
            bucket_id=bucket.bucket_id,
            detail=f"legacy fee {legacy_fee} != reconstructed {fee}",
        )

    if not cash_amount.is_finite():
        _abort("nonfinite_execution_value", f"{day_path}.cash", bucket_id=bucket.bucket_id)
    next_cash = running_cash[bucket.bucket_id] + cash_amount
    if not next_cash.is_finite():
        _abort("nonfinite_execution_value", f"{day_path}.cash", bucket_id=bucket.bucket_id)
    if next_cash < 0:
        _abort(
            "negative_execution_cash",
            f"{day_path}.cash",
            bucket_id=bucket.bucket_id,
            detail=f"cash {next_cash} would go negative",
        )
    running_cash[bucket.bucket_id] = next_cash

    events: list[LedgerEvent] = [
        CashMovement(bucket_id=bucket.bucket_id, amount=cash_amount)
    ]
    if order.side == "buy":
        events.append(
            PositionMovement(
                bucket_id=bucket.bucket_id,
                symbol=order.symbol,
                qty_delta=order.qty,
                avg_cost=_post_buy_avg_cost(bucket, order, price),
            )
        )
    else:
        events.append(
            PositionMovement(
                bucket_id=bucket.bucket_id,
                symbol=order.symbol,
                qty_delta=-order.qty,
            )
        )
    fill = ExecutionFill(
        plan_order_id=order.plan_order_id,
        bucket_id=bucket.bucket_id,
        symbol=order.symbol,
        currency=order.currency,
        side=order.side,
        qty=order.qty,
        price=price,
        fee=fee,
        trade_date=trade_date,
    )
    return fill, tuple(events)


def _nonfill_row(
    *,
    bucket: BucketLedger,
    order: PlannedOrder,
    kind: str,
    row: engine.RejectedOrder | engine.CanceledOrder,
    trade_date: date,
) -> ExecutionRejection | ExecutionCancellation:
    reason_code = getattr(row, "reason_code", "")
    if not isinstance(reason_code, str) or not reason_code:
        _abort(
            "missing_outcome_reason",
            f"execution.{bucket.bucket_id}.{order.plan_order_id}.reason_code",
            bucket_id=bucket.bucket_id,
        )
    legacy_qty = _legacy_decimal(
        row.qty,
        f"execution.{bucket.bucket_id}.{order.plan_order_id}.qty",
        bucket.bucket_id,
    )
    if legacy_qty != Decimal(order.qty):
        _abort(
            "outcome_quantity_mismatch",
            f"execution.{bucket.bucket_id}.{order.plan_order_id}.qty",
            bucket_id=bucket.bucket_id,
            detail="all_or_none terminal outcomes must match the planned quantity",
        )
    kwargs = {
        "plan_order_id": order.plan_order_id,
        "bucket_id": bucket.bucket_id,
        "symbol": order.symbol,
        "currency": order.currency,
        "side": order.side,
        "qty": order.qty,
        "trade_date": trade_date,
        "reason_code": reason_code,
        "detail": getattr(row, "detail", ""),
    }
    if kind == "canceled":
        return ExecutionCancellation(**kwargs)
    return ExecutionRejection(**kwargs)


def _bucket_outcome(
    *,
    bucket: BucketLedger,
    request: PortfolioRequest,
    orders: Sequence[PlannedOrder],
    entry: BucketPreflight,
    rules: MarketRules,
    hk_lot_sizes: Mapping[str, int] | None,
) -> tuple[
    tuple[ExecutionFill, ...],
    tuple[ExecutionRejection, ...],
    tuple[ExecutionCancellation, ...],
    tuple[LedgerEvent, ...],
]:
    legacy = _run_legacy_match(bucket, request, entry, rules, orders, hk_lot_sizes)
    closes = _target_closes(bucket, entry)
    rows = _terminal_rows(legacy, bucket, orders, request.trade_date.isoformat())
    running_cash = {bucket.bucket_id: bucket.cash}
    fills: list[ExecutionFill] = []
    rejected: list[ExecutionRejection] = []
    canceled: list[ExecutionCancellation] = []
    events: list[LedgerEvent] = []
    for order in orders:
        kind, row = rows[(order.symbol, order.side)]
        if kind == "fill":
            price = closes.get(order.symbol)
            if price is None:
                _abort(
                    "missing_execution_price",
                    f"execution.{bucket.bucket_id}.{order.plan_order_id}.price",
                    bucket_id=bucket.bucket_id,
                    detail="a fill needs its source target-day close",
                )
            fee = _fee_for(rules, order.side, order.qty, price)
            _check_fee(fee, bucket.bucket_id, order)
            fill, fill_events = _fill_row(
                bucket=bucket,
                order=order,
                row=row,
                price=price,
                fee=fee,
                trade_date=request.trade_date,
                running_cash=running_cash,
            )
            fills.append(fill)
            events.extend(fill_events)
            continue
        if kind == "canceled":
            canceled.append(
                _nonfill_row(
                    bucket=bucket,
                    order=order,
                    kind="canceled",
                    row=row,
                    trade_date=request.trade_date,
                )
            )
        else:
            rejected.append(
                _nonfill_row(
                    bucket=bucket,
                    order=order,
                    kind="rejected",
                    row=row,
                    trade_date=request.trade_date,
                )
            )
    return tuple(fills), tuple(rejected), tuple(canceled), tuple(events)


def _validate_replayed_ledger(
    ledger: PortfolioLedger,
    events: Sequence[LedgerEvent],
) -> None:
    try:
        end = ledger.apply(events)
    except PortfolioRequestError as exc:
        _abort(
            "ledger_replay_failed",
            exc.path,
            bucket_id=exc.bucket_id,
            detail=exc.reason,
        )
    before_ids = tuple(bucket.bucket_id for bucket in ledger.buckets)
    after_ids = tuple(bucket.bucket_id for bucket in end.buckets)
    if before_ids != after_ids:
        _abort("end_ledger_bucket_mismatch", "end_ledger.buckets")
    for bucket in end.buckets:
        if not bucket.cash.is_finite() or bucket.cash < 0:
            _abort(
                "negative_execution_cash",
                f"end_ledger.{bucket.bucket_id}.cash",
                bucket_id=bucket.bucket_id,
            )


@dataclass(frozen=True, slots=True)
class DecimalExecutionAdapter:
    """Task-11 ``MatchAdapter`` replaying only cash/position ledger events."""

    fee_models: tuple[EffectiveFeeModel, ...] = ()
    hk_lot_sizes: Mapping[str, int] | None = None

    def match(
        self,
        request: PortfolioRequest,
        ledger: PortfolioLedger,
        plan: OrderPlan,
        prepared: PreparedPortfolioData,
    ) -> ExecutionOutcome:
        """Match every planned order once, or raise without a partial outcome."""
        _validate_plan(request, ledger, plan, prepared)
        models = _effective_models(request, self.fee_models)
        rules = {
            bucket_id: _market_rules(model, self.hk_lot_sizes)
            for bucket_id, model in models.items()
        }
        orders_by_bucket: dict[str, list[PlannedOrder]] = {}
        for order in plan.orders:
            orders_by_bucket.setdefault(order.bucket_id, []).append(order)

        fills: list[ExecutionFill] = []
        rejected: list[ExecutionRejection] = []
        canceled: list[ExecutionCancellation] = []
        events: list[LedgerEvent] = []
        for bucket_plan in plan.buckets:
            bucket_orders = tuple(orders_by_bucket.get(bucket_plan.bucket_id, ()))
            if not bucket_orders:
                continue
            bucket = next(
                row for row in ledger.buckets if row.bucket_id == bucket_plan.bucket_id
            )
            entry = _preflight_for_bucket(bucket, request, prepared)
            bucket_fills, bucket_rejected, bucket_canceled, bucket_events = _bucket_outcome(
                bucket=bucket,
                request=request,
                orders=bucket_orders,
                entry=entry,
                rules=rules[bucket.bucket_id],
                hk_lot_sizes=self.hk_lot_sizes,
            )
            fills.extend(bucket_fills)
            rejected.extend(bucket_rejected)
            canceled.extend(bucket_canceled)
            events.extend(bucket_events)

        seen: set[str] = set()
        for row in (*fills, *rejected, *canceled):
            if row.plan_order_id in seen:
                _abort(
                    "duplicate_order_outcome",
                    f"execution.{row.plan_order_id}",
                    bucket_id=row.bucket_id,
                )
            seen.add(row.plan_order_id)
        missing = {order.plan_order_id for order in plan.orders} - seen
        if missing:
            _abort(
                "missing_order_outcome",
                "execution",
                detail=f"no terminal outcome for {', '.join(sorted(missing))}",
            )
        _validate_replayed_ledger(ledger, events)
        return ExecutionOutcome(
            fills=tuple(fills),
            rejected_orders=tuple(rejected),
            canceled_orders=tuple(canceled),
            ledger_events=tuple(events),
        )
