"""Local numeric guards and bucket/spec primitives for the pt-v2.0 order-plan layers.

The precision, quantum and market/currency tables below are deliberate local
duplicates of the numeric canonical helpers; the order-plan boundary keeps its
own frozen copies so rejection bytes never drift with upstream numeric edits.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from typing import Final, NoReturn

from ..rules import MarketRules
from .ledger import PortfolioLedger
from .models import Currency, Market
from .numeric import (
    MONEY_SPEC,
    PRICE_SPEC,
    WEIGHT_SPEC,
    DecimalSpec,
    EffectiveFeeModel,
    canonical_decimal,
    parse_lot_size,
    parse_price,
)
from .order_plan_models import PlannedOrder, Side, _BucketSpec
from .planner import PlannerBucketNav, TargetWeightAllocation
from .schema import PortfolioRequestError

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
