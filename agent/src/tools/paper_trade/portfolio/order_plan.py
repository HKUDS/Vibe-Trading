"""Deterministic, auditable pt-v2.0 order plans.

This module is the boundary between the pure target-weight planner and the
matching/execution adapter. It consumes typed :class:`TargetWeightAllocation`
lines or caller-declared explicit orders and emits canonical whole-lot orders:
buckets are ordered canonically, sells precede buys inside every bucket, every
line has a stable ``plan_order_id``, and every bucket keeps its own planned cash
and lot residue. It never matches, fills, fetches data or promises exact
post-trade weights: ``planned_weight`` is only an estimate at planning marks and
``realized_weight`` stays ``None`` until a later execution layer reconciles it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from typing import Final, Literal, NoReturn

from ..rules import MarketRules
from .fx import FxRateBook
from .ledger import PortfolioLedger, value_ledger
from .models import Currency, FxSnapshot, JsonObject, Market, PortfolioOrder
from .numeric import (
    FX_RATE_SPEC,
    MONEY_SPEC,
    PRICE_SPEC,
    WEIGHT_SPEC,
    DecimalSpec,
    EffectiveFeeModel,
    canonical_decimal,
    parse_lot_size,
    parse_price,
)
from .planner import PlannerBucketNav, PlannerLine, PlanningMark, TargetWeightAllocation
from .schema import PortfolioRequestError

__all__ = [
    "ORDER_PLAN_VERSION",
    "BucketCashPlan",
    "OrderPlan",
    "PlannedOrder",
    "SkippedPlanLine",
    "WeightReconciliation",
    "build_explicit_order_plan",
    "build_target_weight_order_plan",
    "order_plan_to_json",
]

ORDER_PLAN_VERSION: Final = "pt-order-plan-v1"
WEIGHT_BASIS: Final = "planning_marks"
REALIZED_WEIGHT_STATUS: Final = "pending_execution"
Side = Literal["buy", "sell"]
PlanMode = Literal["target_weights", "explicit_orders"]

_EXACT_PRECISION: Final = 60
_WEIGHT_QUANTUM: Final = Decimal(1).scaleb(-WEIGHT_SPEC.scale)
_GAP_SPEC: Final = DecimalSpec(
    scale=WEIGHT_SPEC.scale,
    minimum=Decimal(-1),
    maximum=Decimal(1),
)
_BASE_PRICE_SPEC: Final = DecimalSpec(
    scale=12,
    minimum=Decimal(0),
    minimum_inclusive=False,
)
_MARKET_ORDER: Final[dict[str, int]] = {"cn_a": 0, "hk": 1, "us": 2}
_MARKET_BY_CURRENCY: Final[dict[str, Market]] = {
    "CNY": "cn_a",
    "HKD": "hk",
    "USD": "us",
}
_CANONICAL_CURRENCIES: Final = frozenset(_MARKET_BY_CURRENCY)


def _reject(
    reason: str,
    path: str,
    *,
    bucket_id: str | None = None,
    detail: str = "",
) -> NoReturn:
    raise PortfolioRequestError(reason=reason, path=path, bucket_id=bucket_id, detail=detail)


def _exact_product(left: Decimal, right: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = _EXACT_PRECISION
        return left * right


def _money(value: Decimal, path: str) -> Decimal:
    normalized = Decimal(0) if value.is_zero() else value
    return Decimal(canonical_decimal(normalized, MONEY_SPEC, path))


def _weight(value: Decimal) -> Decimal:
    quantized = value.quantize(_WEIGHT_QUANTUM, rounding=ROUND_HALF_EVEN)
    return Decimal(0) if quantized.is_zero() else quantized


def _ratio(value: Decimal, denominator: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = _EXACT_PRECISION
        return _weight(value / denominator)


def _finite_decimal(value: object, path: str) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        _reject("invalid_plan_value", path, detail="expected a finite Decimal")
    return value


def _positive_decimal(value: object, path: str) -> Decimal:
    parsed = _finite_decimal(value, path)
    if parsed <= 0:
        _reject("invalid_plan_value", path, detail="expected a positive Decimal")
    return parsed


def _nonnegative_decimal(value: object, path: str) -> Decimal:
    parsed = _finite_decimal(value, path)
    if parsed < 0:
        _reject("invalid_plan_value", path, detail="expected a nonnegative Decimal")
    return parsed


def _nonnegative_quantity(value: object, path: str) -> int:
    if type(value) is not int or value < 0:
        _reject("invalid_plan_quantity", path, detail="expected a nonnegative integer")
    return value


def _mark_price(value: Decimal | str, path: str) -> Decimal:
    if isinstance(value, Decimal):
        return Decimal(canonical_decimal(value, PRICE_SPEC, path))
    return parse_price(value, path)


def _rate(value: object, path: str) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
        _reject("invalid_fx_rate", path)
    return value


def _validate_identity(
    trade_date: date,
    planning_at: datetime,
    base_currency: Currency,
) -> None:
    if not isinstance(trade_date, date) or isinstance(trade_date, datetime):
        _reject("invalid_trade_date", "trade_date")
    if (
        not isinstance(planning_at, datetime)
        or planning_at.tzinfo is None
        or planning_at.utcoffset() is None
    ):
        _reject("invalid_planning_at", "planning_at")
    if not isinstance(base_currency, str) or base_currency not in _CANONICAL_CURRENCIES:
        _reject("invalid_base_currency", "base_currency")


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


def _bucket_key(spec: _BucketSpec) -> tuple[int, str]:
    return (_MARKET_ORDER[spec.market], spec.bucket_id)


def _order_key(order: PlannedOrder) -> tuple[int, str, int, str]:
    return (
        _MARKET_ORDER[order.market],
        order.bucket_id,
        0 if order.side == "sell" else 1,
        order.symbol,
    )


def _validate_allocation(allocation: TargetWeightAllocation) -> None:
    if not isinstance(allocation, TargetWeightAllocation):
        _reject("invalid_target_allocation", "target_weight_allocation")
    if not allocation.buckets:
        _reject("empty_portfolio", "target_weight_allocation.buckets")
    if not isinstance(allocation.nav.reported_nav, Decimal) or allocation.nav.reported_nav <= 0:
        _reject("nonpositive_planning_nav", "planning_nav")
    _validate_identity(allocation.trade_date, allocation.planning_at, allocation.base_currency)


def _target_buckets(allocation: TargetWeightAllocation) -> tuple[_BucketSpec, ...]:
    specs: list[_BucketSpec] = []
    seen: set[str] = set()
    for index, row in enumerate(allocation.buckets):
        path = f"target_weight_allocation.buckets[{index}]"
        if not isinstance(row, PlannerBucketNav):
            _reject("invalid_plan_bucket", path)
        if not isinstance(row.bucket_id, str) or not row.bucket_id:
            _reject("invalid_bucket_id", f"{path}.bucket_id")
        if row.bucket_id in seen:
            _reject("duplicate_plan_bucket", f"{path}.bucket_id", bucket_id=row.bucket_id)
        seen.add(row.bucket_id)
        market = _MARKET_BY_CURRENCY.get(row.currency)
        if market is None:
            _reject("invalid_bucket_currency", f"{path}.currency", bucket_id=row.bucket_id)
        cash = _nonnegative_decimal(row.cash, f"{path}.cash")
        rate = _rate(row.fx_rate, f"{path}.fx_rate")
        if row.currency == allocation.base_currency:
            if row.fx_rate_id is not None or rate != Decimal(1):
                _reject("invalid_identity_fx_rate", f"{path}.fx_rate", bucket_id=row.bucket_id)
        elif not isinstance(row.fx_rate_id, str) or not row.fx_rate_id:
            _reject("missing_direct_fx_pair", f"{path}.fx_rate_id", bucket_id=row.bucket_id)
        specs.append(
            _BucketSpec(
                bucket_id=row.bucket_id,
                market=market,
                currency=row.currency,
                opening_cash=cash,
                fx_rate_id=row.fx_rate_id,
                fx_rate=rate,
            )
        )
    return tuple(sorted(specs, key=_bucket_key))


def _ledger_buckets(ledger: PortfolioLedger) -> tuple[_BucketSpec, ...]:
    if not isinstance(ledger, PortfolioLedger):
        _reject("invalid_portfolio_ledger", "portfolio_ledger")
    if not ledger.buckets:
        _reject("empty_portfolio", "portfolio_ledger.buckets")
    specs: list[_BucketSpec] = []
    for index, bucket in enumerate(ledger.buckets):
        path = f"portfolio_ledger.buckets[{index}]"
        if bucket.cash < 0:
            _reject(
                "infeasible_post_conversion_cash",
                f"{path}.cash",
                bucket_id=bucket.bucket_id,
                detail="post-conversion cash cannot be negative",
            )
        specs.append(
            _BucketSpec(
                bucket_id=bucket.bucket_id,
                market=bucket.market,
                currency=bucket.currency,
                opening_cash=bucket.cash,
                fx_rate_id=None,
                fx_rate=Decimal(1),
            )
        )
    return tuple(sorted(specs, key=_bucket_key))


def _lot_table(value: Mapping[str, int] | None) -> dict[str, int] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        _reject("invalid_hk_lot_sizes", "hk_lot_sizes")
    table: dict[str, int] = {}
    for symbol, lot in value.items():
        if not isinstance(symbol, str) or not symbol:
            _reject("invalid_hk_lot_sizes", "hk_lot_sizes.symbol")
        table[symbol] = parse_lot_size(lot, f"hk_lot_sizes.{symbol}")
    return table


def _fee_models(
    models: Sequence[EffectiveFeeModel],
    specs: Sequence[_BucketSpec],
) -> dict[str, EffectiveFeeModel]:
    if isinstance(models, (str, bytes, dict)) or not isinstance(models, Sequence):
        _reject("invalid_effective_fee_models", "fee_models")
    by_bucket = {spec.bucket_id: spec for spec in specs}
    found: dict[str, EffectiveFeeModel] = {}
    for index, model in enumerate(models):
        path = f"fee_models[{index}]"
        if not isinstance(model, EffectiveFeeModel):
            _reject("invalid_effective_fee_model", path)
        spec = by_bucket.get(model.bucket_id)
        if spec is None:
            _reject("unknown_fee_bucket", f"{path}.bucket_id", bucket_id=model.bucket_id)
        if model.bucket_id in found:
            _reject("duplicate_effective_fee_model", f"{path}.bucket_id", bucket_id=model.bucket_id)
        if model.market != spec.market:
            _reject("fee_market_mismatch", f"{path}.market", bucket_id=model.bucket_id)
        if model.currency != spec.currency:
            _reject("fee_currency_mismatch", f"{path}.currency", bucket_id=model.bucket_id)
        found[model.bucket_id] = model
    for spec in specs:
        if spec.bucket_id not in found:
            _reject(
                "missing_effective_fee_model",
                f"fee_models.{spec.bucket_id}",
                bucket_id=spec.bucket_id,
                detail="every bucket needs its effective fee model before an order plan",
            )
    return found


def _market_rules(
    spec: _BucketSpec,
    fee_model: EffectiveFeeModel,
    hk_lot_sizes: Mapping[str, int] | None,
) -> MarketRules:
    try:
        return MarketRules(
            spec.market,
            dict(fee_model.parameters),
            hk_lot_sizes=hk_lot_sizes,
        )
    except (ValueError, TypeError, ArithmeticError) as exc:
        _reject(
            "invalid_market_rules",
            f"fee_models.{spec.bucket_id}",
            bucket_id=spec.bucket_id,
            detail=str(exc)[:200],
        )


def _lot_size(rules: MarketRules, symbol: str, path: str) -> int:
    return parse_lot_size(rules.lot_size(symbol), path)


def _side(intended_qty: int) -> Side | None:
    if intended_qty > 0:
        return "buy"
    if intended_qty < 0:
        return "sell"
    return None


def _generated_id(trade_date: date, bucket_id: str, side: Side, symbol: str) -> str:
    return f"pt2-{trade_date:%Y%m%d}-{bucket_id}-{side}-{symbol}"


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
