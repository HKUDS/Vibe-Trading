"""Pure prior-mark target-weight planner for pt-v2.0 portfolio accounts.

The planner is deliberately separated from matching and execution data. It
accepts the post-conversion opening ledger, caller-supplied planning marks and
direct-pair FX snapshots, long-only target weights and a rebalance band. It
values each bucket through its own direct FX pair, uses only marks strictly
before ``trade_date`` and returns typed plan lines for the later order-plan
layer. It never reads execution bars, generates conversions, redistributes
residual cash, allows leverage or fetches live sector/benchmark data.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_FLOOR, ROUND_HALF_EVEN, Decimal, localcontext
from typing import Final, NoReturn, Sequence

from .fx import FxRateBook
from .ledger import PortfolioLedger, value_ledger
from .models import Currency, FxSnapshot, TargetWeight
from .numeric import (
    MONEY_SPEC,
    PRICE_SPEC,
    WEIGHT_SPEC,
    canonical_decimal,
    parse_price,
    parse_quantity,
    parse_weight,
)
from .schema import PortfolioRequestError

__all__ = [
    "PLANNER_VERSION",
    "PlanningMark",
    "PlanningNav",
    "PlannerBucketNav",
    "PlannerLine",
    "TargetWeightAllocation",
    "plan_target_weights",
]

PLANNER_VERSION: Final = "pt-planner-v1"
_EXACT_PRECISION: Final = 60
_WEIGHT_QUANTUM: Final = Decimal(1).scaleb(-WEIGHT_SPEC.scale)
_CANONICAL_CURRENCIES: Final = frozenset({"CNY", "HKD", "USD"})


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


def _price(value: Decimal | str, path: str) -> Decimal:
    if isinstance(value, Decimal):
        return Decimal(canonical_decimal(value, PRICE_SPEC, path))
    return parse_price(value, path)


def _money(value: Decimal, path: str) -> Decimal:
    return Decimal(canonical_decimal(value, MONEY_SPEC, path))


def _weight(value: Decimal) -> Decimal:
    quantized = value.quantize(_WEIGHT_QUANTUM, rounding=ROUND_HALF_EVEN)
    return Decimal(0) if quantized.is_zero() else quantized


def _typed_weight(value: str | Decimal, path: str) -> Decimal:
    if isinstance(value, Decimal):
        return Decimal(canonical_decimal(value, WEIGHT_SPEC, path))
    return parse_weight(value, path)


def _floor_quantity(value: Decimal, price: Decimal, path: str) -> int:
    with localcontext() as context:
        context.prec = _EXACT_PRECISION
        quotient = value / price
    return parse_quantity(
        int(quotient.to_integral_value(rounding=ROUND_FLOOR)),
        path,
        allow_zero=True,
    )


@dataclass(frozen=True, slots=True)
class PlanningMark:
    """One explicit planning close with its own price date and provenance."""

    symbol: str
    price_date: date
    close: Decimal
    source: str
    as_of: datetime


@dataclass(frozen=True, slots=True)
class PlannerBucketNav:
    """One bucket's local planning NAV and its direct-pair base bridge."""

    bucket_id: str
    currency: Currency
    cash: Decimal
    position_value: Decimal
    local_nav: Decimal
    fx_rate_id: str | None
    fx_rate: Decimal
    nav_base: Decimal
    exact_nav_base: Decimal
    residual: Decimal


@dataclass(frozen=True, slots=True)
class PlanningNav:
    """The exact and reported planning NAV in the account base currency."""

    base_currency: Currency
    reported_nav: Decimal
    exact_nav: Decimal
    residual: Decimal


@dataclass(frozen=True, slots=True)
class PlannerLine:
    """One instrument's prior-mark value, target and deterministic quantity.

    ``target_quantity`` is whole-share flooring before market lot rounding and
    is not yet an order. Order IDs, lot residuals and realized-weight
    reconciliation belong to the later order-plan layer.
    """

    bucket_id: str
    symbol: str
    currency: Currency
    price: Decimal
    price_date: date
    mark_source: str
    mark_as_of: datetime
    fx_rate_id: str | None
    fx_rate: Decimal
    base_price: Decimal
    current_qty: int
    current_value_base: Decimal
    current_weight: Decimal
    target_weight: Decimal
    target_value_base: Decimal
    target_quantity: int
    weight_gap: Decimal
    within_band: bool


@dataclass(frozen=True, slots=True)
class TargetWeightAllocation:
    """The pure allocation result consumed by the order-plan layer."""

    trade_date: date
    planning_at: datetime
    base_currency: Currency
    rebalance_band: Decimal
    target_weight_total: Decimal
    cash_weight: Decimal
    nav: PlanningNav
    buckets: tuple[PlannerBucketNav, ...]
    lines: tuple[PlannerLine, ...]


def _validate_identity(
    ledger: PortfolioLedger,
    trade_date: date,
    planning_at: datetime,
    base_currency: Currency,
) -> None:
    if not isinstance(ledger, PortfolioLedger):
        _reject("invalid_portfolio_ledger", "portfolio_ledger")
    if not ledger.buckets:
        _reject("empty_portfolio", "portfolio_ledger.buckets")
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
    for bucket in ledger.buckets:
        if bucket.cash < 0:
            _reject(
                "infeasible_post_conversion_cash",
                f"portfolio_ledger.{bucket.bucket_id}.cash",
                bucket_id=bucket.bucket_id,
                detail="post-conversion cash cannot be negative",
            )


def _validate_targets(
    ledger: PortfolioLedger,
    target_weights: Sequence[TargetWeight],
) -> tuple[dict[str, tuple[TargetWeight, Decimal]], Decimal]:
    buckets = {bucket.bucket_id: bucket for bucket in ledger.buckets}
    owner_by_symbol = {
        position.symbol: bucket.bucket_id
        for bucket in ledger.buckets
        for position in bucket.positions
    }
    targets: dict[str, tuple[TargetWeight, Decimal]] = {}
    total = Decimal(0)
    for index, target in enumerate(target_weights):
        path = f"target_weights[{index}]"
        if not isinstance(target, TargetWeight):
            _reject("invalid_target_weight", path, detail="expected a typed TargetWeight")
        bucket = buckets.get(target.bucket_id)
        if bucket is None:
            _reject("unknown_bucket", f"{path}.bucket_id", bucket_id=target.bucket_id)
        if not isinstance(target.symbol, str) or not target.symbol:
            _reject("invalid_instrument", f"{path}.symbol", bucket_id=bucket.bucket_id)
        if target.symbol in targets:
            _reject(
                "duplicate_target_instrument",
                f"{path}.symbol",
                bucket_id=bucket.bucket_id,
                detail=f"instrument {target.symbol!r} is targeted more than once",
            )
        if target.currency != bucket.currency:
            if bucket.market == "hk" and target.currency != "HKD":
                _reject("non_hkd_hk_counter", f"{path}.currency", bucket_id=bucket.bucket_id)
            _reject(
                "instrument_currency_mismatch",
                f"{path}.currency",
                bucket_id=bucket.bucket_id,
                detail="target currency must equal its canonical bucket currency",
            )
        owner = owner_by_symbol.get(target.symbol)
        if owner is not None and owner != bucket.bucket_id:
            _reject(
                "instrument_bucket_mismatch",
                f"{path}.symbol",
                bucket_id=bucket.bucket_id,
                detail=f"instrument {target.symbol!r} is already owned by bucket {owner!r}",
            )
        try:
            weight = _typed_weight(target.weight, f"{path}.weight")
        except PortfolioRequestError as exc:
            raise PortfolioRequestError(
                reason="invalid_target_weight",
                path=exc.path,
                bucket_id=bucket.bucket_id,
                detail=exc.reason,
            ) from None
        targets[target.symbol] = (target, weight)
        total += weight
    if total > 1:
        _reject(
            "target_weights_exceed_one",
            "target_weights",
            detail="long-only target weights must sum to at most one",
        )
    return targets, total


def _validate_marks(
    marks: Sequence[PlanningMark],
    *,
    trade_date: date,
    planning_at: datetime,
) -> dict[str, tuple[PlanningMark, Decimal]]:
    supplied: dict[str, tuple[PlanningMark, Decimal]] = {}
    for index, mark in enumerate(marks):
        path = f"planning_marks[{index}]"
        if not isinstance(mark, PlanningMark):
            _reject("invalid_planning_mark", path, detail="expected a typed PlanningMark")
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
        try:
            price = _price(mark.close, f"{path}.close")
        except PortfolioRequestError as exc:
            raise PortfolioRequestError(
                reason="invalid_planning_mark",
                path=exc.path,
                detail=exc.reason,
            ) from None
        if mark.symbol in supplied:
            _reject(
                "duplicate_planning_mark",
                f"{path}.symbol",
                detail=f"instrument {mark.symbol!r} has more than one planning mark",
            )
        if mark.as_of > planning_at:
            _reject(
                "future_planning_mark",
                f"{path}.as_of",
                detail="mark provenance is later than the planning instant",
            )
        if mark.price_date > trade_date:
            _reject(
                "future_planning_mark",
                f"{path}.price_date",
                detail="planning mark is dated after trade_date",
            )
        if mark.price_date == trade_date:
            _reject(
                "stale_planning_mark",
                f"{path}.price_date",
                detail="planning marks must be strictly before trade_date",
            )
        supplied[mark.symbol] = (mark, price)
    return supplied


def plan_target_weights(
    ledger: PortfolioLedger,
    *,
    trade_date: date,
    planning_at: datetime,
    base_currency: Currency,
    marks: Sequence[PlanningMark],
    fx_snapshots: Sequence[FxSnapshot] = (),
    target_weights: Sequence[TargetWeight] = (),
    rebalance_band: str | Decimal = "0",
    max_fx_age: timedelta | None = None,
) -> TargetWeightAllocation:
    """Build a deterministic prior-mark allocation from a post-conversion ledger.

    Target weights are long-only fractions with an exact sum of at most one;
    the unallocated residual remains cash. A zero band rebalances every line,
    while a nonzero band marks a line ``within_band`` only when the absolute
    current/target weight gap is less than or equal to the band. The result is
    pure: no FX conversion, order ID, lot rounding, matching or execution data
    enters this layer.
    """
    _validate_identity(ledger, trade_date, planning_at, base_currency)
    try:
        band = _typed_weight(rebalance_band, "rebalance_band")
    except PortfolioRequestError as exc:
        _reject("invalid_rebalance_band", "rebalance_band", detail=exc.reason)
    targets, target_total = _validate_targets(ledger, target_weights)
    supplied_marks = _validate_marks(marks, trade_date=trade_date, planning_at=planning_at)

    buckets = {bucket.bucket_id: bucket for bucket in ledger.buckets}
    positions = {
        position.symbol: position
        for bucket in ledger.buckets
        for position in bucket.positions
    }
    line_keys = sorted(
        {
            (bucket.bucket_id, position.symbol)
            for bucket in ledger.buckets
            for position in bucket.positions
        }
        | {(target.bucket_id, symbol) for symbol, (target, _) in targets.items()}
    )
    for bucket_id, symbol in line_keys:
        if symbol not in supplied_marks:
            _reject(
                "missing_planning_mark",
                f"planning_marks.{symbol}",
                bucket_id=bucket_id,
                detail="every held or targeted instrument needs an explicit planning mark",
            )

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
    nav = PlanningNav(
        base_currency=base_currency,
        reported_nav=bridge.total.reported_base,
        exact_nav=bridge.total.exact_base,
        residual=bridge.total.residual,
    )
    if nav.reported_nav <= 0:
        _reject(
            "nonpositive_planning_nav",
            "planning_nav",
            detail="target weights require a positive planning NAV",
        )

    bucket_rows = tuple(
        PlannerBucketNav(
            bucket_id=row.bucket_id,
            currency=row.currency,
            cash=row.cash,
            position_value=row.position_value,
            local_nav=row.local_nav,
            fx_rate_id=row.rate_id,
            fx_rate=row.rate,
            nav_base=row.reported_base,
            exact_nav_base=row.exact_base,
            residual=row.residual,
        )
        for row in bridge.rows
    )
    rate_by_bucket = {row.bucket_id: (row.rate_id, row.rate) for row in bridge.rows}

    lines: list[PlannerLine] = []
    for bucket_id, symbol in line_keys:
        bucket = buckets[bucket_id]
        mark, price = supplied_marks[symbol]
        rate_id, rate = rate_by_bucket[bucket_id]
        base_price = _exact_product(price, rate)
        position = positions.get(symbol)
        current_qty = position.qty if position is not None else 0
        current_value = _money(
            _exact_product(Decimal(current_qty), base_price),
            f"planning_lines.{bucket_id}.{symbol}.current_value",
        )
        with localcontext() as context:
            context.prec = _EXACT_PRECISION
            current_weight = _weight(current_value / nav.reported_nav)
        targeted = targets.get(symbol)
        target_weight = targeted[1] if targeted is not None else Decimal(0)
        target_value = _money(
            _exact_product(nav.reported_nav, target_weight),
            f"planning_lines.{bucket_id}.{symbol}.target_value",
        )
        target_quantity = _floor_quantity(
            target_value,
            base_price,
            f"planning_lines.{bucket_id}.{symbol}.target_quantity",
        )
        weight_gap = _weight(target_weight - current_weight)
        within_band = band != 0 and abs(weight_gap) <= band
        lines.append(
            PlannerLine(
                bucket_id=bucket_id,
                symbol=symbol,
                currency=bucket.currency,
                price=price,
                price_date=mark.price_date,
                mark_source=mark.source,
                mark_as_of=mark.as_of,
                fx_rate_id=rate_id,
                fx_rate=rate,
                base_price=base_price,
                current_qty=current_qty,
                current_value_base=current_value,
                current_weight=current_weight,
                target_weight=target_weight,
                target_value_base=target_value,
                target_quantity=target_quantity,
                weight_gap=weight_gap,
                within_band=within_band,
            )
        )

    return TargetWeightAllocation(
        trade_date=trade_date,
        planning_at=planning_at,
        base_currency=base_currency,
        rebalance_band=band,
        target_weight_total=_weight(target_total),
        cash_weight=_weight(Decimal(1) - target_total),
        nav=nav,
        buckets=bucket_rows,
        lines=tuple(lines),
    )
