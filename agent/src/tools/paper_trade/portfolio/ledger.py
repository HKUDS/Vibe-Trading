"""Immutable per-bucket Decimal ledgers, conversion replay and NAV bridges.

Each account is isolated by ``bucket_id`` and settles in exactly one canonical
currency. Conversion replay can debit only the named source account's opening
cash, so neither another bucket nor an earlier conversion's proceeds can fund a
later conversion. Valuation translates each bucket's reported local NAV through
its own direct FX pair and keeps every rounding residual explicit.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal, localcontext
from types import MappingProxyType
from typing import Literal, Mapping, Sequence, TypeAlias

from .fx import (
    FxConversionEvent,
    FxConversionPlan,
    FxRateBook,
    NavBridgeEvent,
    NavBridgeTotal,
    value_in_base_currency,
)
from .models import Currency, Market, PortfolioBucket, PortfolioRequest, PortfolioState
from .numeric import (
    FX_RATE_SPEC,
    MONEY_SPEC,
    PRICE_SPEC,
    _CANONICAL_CURRENCIES,
    _EXACT_PRECISION,
    _exact_product,
    _reject,
    canonical_decimal,
    parse_fx_rate,
    parse_money,
    parse_price,
    parse_quantity,
)
from .schema import PortfolioRequestError

__all__ = [
    "BucketLedger",
    "BucketValuation",
    "CashMovement",
    "ConversionReplay",
    "LedgerEvent",
    "LedgerNavBridge",
    "LedgerPosition",
    "PortfolioLedger",
    "PositionMovement",
    "apply_conversions",
    "value_ledger",
]

ConversionStage: TypeAlias = Literal["pre_fill", "post_fill"]
DecimalLike: TypeAlias = Decimal | str


def _typed_decimal(value: DecimalLike, parser, spec, path: str) -> Decimal:
    if isinstance(value, str):
        return parser(value, path)
    if not isinstance(value, Decimal):
        _reject("invalid_decimal", path, detail="expected a fixed-point string or Decimal")
    quantized = Decimal(canonical_decimal(value, spec, path))
    if quantized != value:
        _reject("invalid_decimal", path, detail="value does not fit the canonical scale")
    return quantized


def _money(value: DecimalLike, path: str) -> Decimal:
    return _typed_decimal(value, parse_money, MONEY_SPEC, path)


def _price(value: DecimalLike, path: str) -> Decimal:
    return _typed_decimal(value, parse_price, PRICE_SPEC, path)


def _fx_rate(value: DecimalLike, path: str) -> Decimal:
    return _typed_decimal(value, parse_fx_rate, FX_RATE_SPEC, path)


def _exact_decimal(value: Decimal, path: str) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        _reject("invalid_decimal", path, detail="exact value must be a finite Decimal")
    if value.is_zero() and value.is_signed():
        _reject("negative_zero", path)
    return value


def _quantize_money(value: Decimal, path: str) -> Decimal:
    return Decimal(canonical_decimal(value, MONEY_SPEC, path))


def _validate_market_currency(
    market: Market,
    currency: Currency,
    path: str,
    bucket_id: str,
) -> None:
    expected = _CANONICAL_CURRENCIES.get(market) if isinstance(market, str) else None
    if expected is None:
        _reject("invalid_bucket_market", f"{path}.market", bucket_id=bucket_id)
    if market == "hk" and currency != "HKD":
        _reject(
            "non_hkd_hk_counter",
            f"{path}.currency",
            bucket_id=bucket_id,
            detail="an HK account must settle in HKD",
        )
    if currency != expected:
        _reject("invalid_bucket_currency", f"{path}.currency", bucket_id=bucket_id)


def _validate_position_qty(qty: int, path: str, bucket_id: str) -> int:
    if type(qty) is not int or qty < 0:
        _reject("invalid_quantity", path, bucket_id=bucket_id)
    return parse_quantity(qty, path, allow_zero=True)


@dataclass(frozen=True, slots=True)
class LedgerPosition:
    """One unique instrument row owned by exactly one bucket."""

    symbol: str
    qty: int
    avg_cost: Decimal
    market: Market
    currency: Currency


@dataclass(frozen=True, slots=True)
class BucketLedger:
    """One isolated cash/position account; no cross-market cash is shared."""

    bucket_id: str
    market: Market
    currency: Currency
    cash: Decimal
    positions: tuple[LedgerPosition, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.bucket_id, str) or not self.bucket_id:
            _reject("invalid_bucket_id", "ledger.bucket_id")
        _validate_market_currency(self.market, self.currency, "ledger", self.bucket_id)
        _money(self.cash, "ledger.cash")
        if not isinstance(self.positions, tuple):
            _reject("invalid_positions", "ledger.positions", bucket_id=self.bucket_id)
        seen: set[str] = set()
        for index, position in enumerate(self.positions):
            _validate_position(position, self, f"ledger.positions[{index}]")
            if position.symbol in seen:
                _reject(
                    "duplicate_instrument",
                    f"ledger.positions[{index}].symbol",
                    bucket_id=self.bucket_id,
                    detail=f"instrument {position.symbol!r} is declared more than once",
                )
            seen.add(position.symbol)

    @classmethod
    def from_model(cls, bucket: PortfolioBucket, path: str) -> BucketLedger:
        """Parse one wire bucket, tagging every failure with its identity."""
        try:
            _validate_market_currency(bucket.market, bucket.currency, path, bucket.bucket_id)
            cash = _money(bucket.cash, f"{path}.cash")
            positions: list[LedgerPosition] = []
            for index, position in enumerate(bucket.positions):
                position_path = f"{path}.positions[{index}]"
                qty = _validate_position_qty(position.qty, f"{position_path}.qty", bucket.bucket_id)
                avg_cost = _money(position.avg_cost, f"{position_path}.avg_cost")
                positions.append(
                    LedgerPosition(
                        symbol=position.symbol,
                        qty=qty,
                        avg_cost=avg_cost,
                        market=bucket.market,
                        currency=position.currency,
                    )
                )
            return cls(
                bucket_id=bucket.bucket_id,
                market=bucket.market,
                currency=bucket.currency,
                cash=cash,
                positions=tuple(positions),
            )
        except PortfolioRequestError as exc:
            if exc.bucket_id is not None:
                raise
            raise PortfolioRequestError(
                reason=exc.reason,
                path=exc.path,
                bucket_id=bucket.bucket_id,
                detail=exc.detail,
            ) from None


def _validate_position(position: LedgerPosition, bucket: BucketLedger, path: str) -> None:
    if not isinstance(position, LedgerPosition):
        _reject("invalid_position", path, bucket_id=bucket.bucket_id)
    if not isinstance(position.symbol, str) or not position.symbol:
        _reject("invalid_instrument", f"{path}.symbol", bucket_id=bucket.bucket_id)
    if position.market != bucket.market:
        _reject("instrument_market_mismatch", f"{path}.market", bucket_id=bucket.bucket_id)
    if bucket.market == "hk" and position.currency != "HKD":
        _reject(
            "non_hkd_hk_counter",
            f"{path}.currency",
            bucket_id=bucket.bucket_id,
            detail="an HK instrument counter must be HKD",
        )
    if position.currency != bucket.currency:
        _reject("instrument_currency_mismatch", f"{path}.currency", bucket_id=bucket.bucket_id)
    _validate_position_qty(position.qty, f"{path}.qty", bucket.bucket_id)
    _money(position.avg_cost, f"{path}.avg_cost")


@dataclass(frozen=True, slots=True)
class PortfolioLedger:
    """One immutable set of isolated bucket accounts and unique instruments."""

    buckets: tuple[BucketLedger, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.buckets, tuple):
            _reject("invalid_buckets", "ledger.buckets")
        seen_buckets: dict[str, int] = {}
        seen_instruments: dict[str, str] = {}
        for index, bucket in enumerate(self.buckets):
            if not isinstance(bucket, BucketLedger):
                _reject("invalid_bucket", f"ledger.buckets[{index}]")
            if bucket.bucket_id in seen_buckets:
                _reject(
                    "duplicate_bucket",
                    f"ledger.buckets[{index}].bucket_id",
                    bucket_id=bucket.bucket_id,
                    detail="bucket ids must be unique because FX cash is keyed by bucket_id",
                )
            seen_buckets[bucket.bucket_id] = index
            for position_index, position in enumerate(bucket.positions):
                owner = seen_instruments.get(position.symbol)
                if owner is not None:
                    _reject(
                        "duplicate_instrument",
                        f"ledger.buckets[{index}].positions[{position_index}].symbol",
                        bucket_id=bucket.bucket_id,
                        detail=f"instrument {position.symbol!r} is already declared in bucket {owner!r}",
                    )
                seen_instruments[position.symbol] = bucket.bucket_id

    @classmethod
    def from_state(cls, state: PortfolioState, path: str = "portfolio_state") -> PortfolioLedger:
        """Build a ledger from the parsed opening portfolio state."""
        return cls(
            buckets=tuple(
                BucketLedger.from_model(bucket, f"{path}.buckets[{index}]")
                for index, bucket in enumerate(state.buckets)
            )
        )

    @classmethod
    def from_request(cls, request: PortfolioRequest) -> PortfolioLedger:
        """Build the opening ledger from a parsed pt-v2.0 request."""
        return cls.from_state(request.portfolio_state)

    def bucket(self, bucket_id: str, path: str = "bucket_id") -> BucketLedger:
        """Return one named account or reject without inventing a default."""
        for bucket in self.buckets:
            if bucket.bucket_id == bucket_id:
                return bucket
        _reject("unknown_bucket", path, bucket_id=bucket_id)

    def cash_map(self) -> Mapping[str, Decimal]:
        """Return a read-only view of each isolated bucket's cash."""
        return MappingProxyType({bucket.bucket_id: bucket.cash for bucket in self.buckets})

    def positions(self) -> tuple[LedgerPosition, ...]:
        """Return every unique instrument row with its bucket identity."""
        return tuple(position for bucket in self.buckets for position in bucket.positions)

    def apply(self, events: Sequence[LedgerEvent]) -> PortfolioLedger:
        """Apply caller events one isolated bucket at a time, or return nothing."""
        balances = {bucket.bucket_id: bucket.cash for bucket in self.buckets}
        positions = {bucket.bucket_id: list(bucket.positions) for bucket in self.buckets}
        symbol_bucket = {
            position.symbol: bucket.bucket_id
            for bucket in self.buckets
            for position in bucket.positions
        }
        for index, event in enumerate(events):
            path = f"ledger_events[{index}]"
            if isinstance(event, CashMovement):
                self._apply_cash(balances, event, path)
            elif isinstance(event, PositionMovement):
                self._apply_position(
                    balances,
                    positions,
                    symbol_bucket,
                    event,
                    path,
                )
            else:
                _reject("invalid_ledger_event", path)
        return PortfolioLedger(
            buckets=tuple(
                BucketLedger(
                    bucket_id=bucket.bucket_id,
                    market=bucket.market,
                    currency=bucket.currency,
                    cash=balances[bucket.bucket_id],
                    positions=tuple(positions[bucket.bucket_id]),
                )
                for bucket in self.buckets
            )
        )

    def _apply_cash(
        self,
        balances: dict[str, Decimal],
        event: CashMovement,
        path: str,
    ) -> None:
        if event.bucket_id not in balances:
            _reject("unknown_bucket", f"{path}.bucket_id", bucket_id=event.bucket_id)
        amount = _money(event.amount, f"{path}.amount")
        with localcontext() as context:
            context.prec = _EXACT_PRECISION
            balances[event.bucket_id] += amount

    def _apply_position(
        self,
        balances: dict[str, Decimal],
        positions: dict[str, list[LedgerPosition]],
        symbol_bucket: dict[str, str],
        event: PositionMovement,
        path: str,
    ) -> None:
        if event.bucket_id not in balances:
            _reject("unknown_bucket", f"{path}.bucket_id", bucket_id=event.bucket_id)
        bucket = self.bucket(event.bucket_id, f"{path}.bucket_id")
        if not isinstance(event.symbol, str) or not event.symbol:
            _reject("invalid_instrument", f"{path}.symbol", bucket_id=bucket.bucket_id)
        owner = symbol_bucket.get(event.symbol)
        if owner is not None and owner != bucket.bucket_id:
            _reject(
                "instrument_bucket_mismatch",
                f"{path}.symbol",
                bucket_id=bucket.bucket_id,
                detail=f"instrument {event.symbol!r} is already owned by bucket {owner!r}",
            )
        if type(event.qty_delta) is not int or event.qty_delta == 0:
            _reject("invalid_quantity", f"{path}.qty_delta", bucket_id=bucket.bucket_id)
        current = next(
            (
                (index, position)
                for index, position in enumerate(positions[bucket.bucket_id])
                if position.symbol == event.symbol
            ),
            None,
        )
        if current is None:
            if event.qty_delta < 0:
                _reject("position_not_found", f"{path}.symbol", bucket_id=bucket.bucket_id)
            if event.avg_cost is None:
                _reject("missing_avg_cost", f"{path}.avg_cost", bucket_id=bucket.bucket_id)
            positions[bucket.bucket_id].append(
                LedgerPosition(
                    symbol=event.symbol,
                    qty=event.qty_delta,
                    avg_cost=_money(event.avg_cost, f"{path}.avg_cost"),
                    market=bucket.market,
                    currency=bucket.currency,
                )
            )
            symbol_bucket[event.symbol] = bucket.bucket_id
            return
        position_index, position = current
        new_qty = position.qty + event.qty_delta
        if new_qty < 0:
            _reject("negative_position", f"{path}.qty_delta", bucket_id=bucket.bucket_id)
        avg_cost = (
            _money(event.avg_cost, f"{path}.avg_cost")
            if event.avg_cost is not None
            else position.avg_cost
        )
        if new_qty == 0:
            positions[bucket.bucket_id].pop(position_index)
            symbol_bucket.pop(event.symbol, None)
        else:
            positions[bucket.bucket_id][position_index] = LedgerPosition(
                symbol=event.symbol,
                qty=new_qty,
                avg_cost=avg_cost,
                market=bucket.market,
                currency=bucket.currency,
            )


@dataclass(frozen=True, slots=True)
class CashMovement:
    """One signed cash delta confined to a single named bucket."""

    bucket_id: str
    amount: Decimal


@dataclass(frozen=True, slots=True)
class PositionMovement:
    """One signed quantity delta; ``avg_cost`` is the post-move average cost."""

    bucket_id: str
    symbol: str
    qty_delta: int
    avg_cost: Decimal | None = None


LedgerEvent: TypeAlias = CashMovement | PositionMovement


@dataclass(frozen=True, slots=True)
class ConversionReplay:
    """The exact opening and post-conversion ledgers around one settled plan."""

    opening: PortfolioLedger
    events: tuple[FxConversionEvent, ...]
    post_conversion: PortfolioLedger
    opening_cash: tuple[tuple[str, Decimal], ...]
    post_conversion_cash: tuple[tuple[str, Decimal], ...]
    total_residual: Decimal

    def opening_cash_map(self) -> Mapping[str, Decimal]:
        return MappingProxyType(dict(self.opening_cash))

    def post_conversion_cash_map(self) -> Mapping[str, Decimal]:
        return MappingProxyType(dict(self.post_conversion_cash))


def apply_conversions(
    ledger: PortfolioLedger,
    plan: FxConversionPlan,
    *,
    stage: ConversionStage = "pre_fill",
) -> ConversionReplay:
    """Replay a verified pre-fill plan against each source bucket's opening cash."""
    if stage != "pre_fill":
        _reject(
            "post_fill_fx_conversion",
            "fx_conversions",
            detail="conversions settle before fills; post-fill conversion is not supported",
        )
    opening_cash = ledger.cash_map()
    plan_cash = plan.cash_map()
    if len(plan.cash) != len(plan_cash):
        _reject(
            "duplicate_plan_cash",
            "fx_conversions.cash",
            detail="the plan's post-conversion cash must name each bucket exactly once",
        )
    if not plan.events and not plan.cash:
        frozen = tuple(opening_cash.items())
        return ConversionReplay(
            opening=ledger,
            events=(),
            post_conversion=ledger,
            opening_cash=frozen,
            post_conversion_cash=frozen,
            total_residual=Decimal(0),
        )
    if set(plan_cash) != set(opening_cash):
        _reject(
            "fx_plan_cash_mismatch",
            "fx_conversions",
            detail="the conversion plan and ledger must name the same buckets",
        )
    available = dict(opening_cash)
    balances = dict(opening_cash)
    total_residual = Decimal(0)
    for index, event in enumerate(plan.events):
        path = f"fx_conversions[{index}]"
        if event.from_bucket_id == event.to_bucket_id:
            _reject("identity_fx_conversion", f"{path}.to_bucket_id", bucket_id=event.from_bucket_id)
        if event.from_currency == event.to_currency:
            _reject(
                "identity_fx_conversion",
                f"{path}.to_currency",
                bucket_id=event.from_bucket_id,
                detail="a conversion pair must name two different currencies",
            )
        source = ledger.bucket(event.from_bucket_id, f"{path}.from_bucket_id")
        target = ledger.bucket(event.to_bucket_id, f"{path}.to_bucket_id")
        if source.currency != event.from_currency:
            _reject("fx_pair_mismatch", f"{path}.from_currency", bucket_id=source.bucket_id)
        if target.currency != event.to_currency:
            _reject("fx_pair_mismatch", f"{path}.to_currency", bucket_id=target.bucket_id)
        amount = _money(event.source_amount, f"{path}.source_amount")
        if amount <= 0:
            _reject(
                "invalid_fx_amount",
                f"{path}.source_amount",
                bucket_id=source.bucket_id,
                detail="a conversion amount must be positive",
            )
        converted = _money(event.converted_amount, f"{path}.converted_amount")
        rate = _fx_rate(event.rate, f"{path}.rate")
        exact = _exact_decimal(event.exact_converted, f"{path}.exact_converted")
        expected_exact = _exact_product(amount, rate)
        if exact != expected_exact:
            _reject(
                "fx_event_mismatch",
                f"{path}.exact_converted",
                bucket_id=source.bucket_id,
                detail="the event's exact amount does not equal source_amount * rate",
            )
        expected_converted = _quantize_money(expected_exact, f"{path}.converted_amount")
        if converted != expected_converted:
            _reject(
                "fx_event_mismatch",
                f"{path}.converted_amount",
                bucket_id=source.bucket_id,
                detail="the event's converted amount does not equal the quantized exact amount",
            )
        with localcontext() as context:
            context.prec = _EXACT_PRECISION
            expected_residual = expected_exact - expected_converted
        if expected_residual.is_zero():
            expected_residual = Decimal(0)
        if _exact_decimal(event.residual, f"{path}.residual") != expected_residual:
            _reject(
                "fx_event_mismatch",
                f"{path}.residual",
                bucket_id=source.bucket_id,
                detail="the event residual does not tie exact to converted",
            )
        if available[source.bucket_id] < amount:
            _reject(
                "insufficient_fx_cash",
                f"{path}.source_amount",
                bucket_id=source.bucket_id,
                detail="opening source cash cannot fund the conversion",
            )
        with localcontext() as context:
            context.prec = _EXACT_PRECISION
            available[source.bucket_id] -= amount
            balances[source.bucket_id] -= amount
            balances[target.bucket_id] += converted
            total_residual += expected_residual
    for bucket_id, expected in plan_cash.items():
        if balances[bucket_id] != expected:
            _reject(
                "fx_plan_cash_mismatch",
                "fx_conversions",
                bucket_id=bucket_id,
                detail="replayed cash does not equal the plan's post-conversion cash",
            )
    post_conversion = PortfolioLedger(
        buckets=tuple(
            replace(bucket, cash=balances[bucket.bucket_id])
            for bucket in ledger.buckets
        )
    )
    return ConversionReplay(
        opening=ledger,
        events=tuple(plan.events),
        post_conversion=post_conversion,
        opening_cash=tuple(opening_cash.items()),
        post_conversion_cash=tuple(balances.items()),
        total_residual=total_residual,
    )


@dataclass(frozen=True, slots=True)
class BucketValuation:
    """One bucket's reported local NAV and exact base-currency bridge."""

    bucket_id: str
    market: Market
    currency: Currency
    cash: Decimal
    position_value: Decimal
    exact_position_value: Decimal
    local_nav: Decimal
    exact_local_nav: Decimal
    local_residual: Decimal
    bridge: NavBridgeEvent
    exact_base: Decimal
    residual: Decimal

    @property
    def reported_base(self) -> Decimal:
        return self.bridge.reported_base

    @property
    def base_currency(self) -> Currency:
        return self.bridge.base_currency

    @property
    def rate_id(self) -> str | None:
        return self.bridge.rate_id

    @property
    def rate(self) -> Decimal:
        return self.bridge.rate


@dataclass(frozen=True, slots=True)
class LedgerNavBridge:
    """Every bucket's NAV row plus an exact, residual-carrying total."""

    base_currency: Currency
    rows: tuple[BucketValuation, ...]
    total: NavBridgeTotal

    @property
    def balanced(self) -> bool:
        return self.total.balanced

    @property
    def bridge_events(self) -> tuple[NavBridgeEvent, ...]:
        return tuple(row.bridge for row in self.rows)


def _mark(
    marks: Mapping[str, DecimalLike],
    symbol: str,
    path: str,
    bucket_id: str,
) -> Decimal:
    try:
        value = marks[symbol]
    except KeyError:
        _reject(
            "missing_valuation_mark",
            f"{path}.{symbol}",
            bucket_id=bucket_id,
            detail="every held instrument needs an explicit valuation mark",
        )
    return _price(value, f"{path}.{symbol}")


def value_ledger(
    ledger: PortfolioLedger,
    marks: Mapping[str, DecimalLike],
    book: FxRateBook,
    *,
    base_currency: Currency,
    path: str = "marks",
) -> LedgerNavBridge:
    """Value every bucket in the base currency through its own direct pair."""
    if base_currency not in set(_CANONICAL_CURRENCIES.values()):
        _reject("invalid_base_currency", "base_currency")
    rows: list[BucketValuation] = []
    for bucket in ledger.buckets:
        with localcontext() as context:
            context.prec = _EXACT_PRECISION
            exact_position_value = Decimal(0)
            position_value = Decimal(0)
            for position in bucket.positions:
                price = _mark(marks, position.symbol, path, bucket.bucket_id)
                exact = _exact_product(Decimal(position.qty), price)
                exact_position_value += exact
                position_value += _quantize_money(
                    exact,
                    f"{path}.{position.symbol}.position_value",
                )
            local_nav = bucket.cash + position_value
            exact_local_nav = bucket.cash + exact_position_value
            local_residual = exact_local_nav - local_nav
        bridge = value_in_base_currency(
            bucket.bucket_id,
            bucket.currency,
            local_nav,
            book,
            base_currency=base_currency,
            path=f"{path}.{bucket.bucket_id}.fx_rate_id",
        )
        exact_base = _exact_product(exact_local_nav, bridge.rate)
        with localcontext() as context:
            context.prec = _EXACT_PRECISION
            residual = exact_base - bridge.reported_base
        rows.append(
            BucketValuation(
                bucket_id=bucket.bucket_id,
                market=bucket.market,
                currency=bucket.currency,
                cash=bucket.cash,
                position_value=position_value,
                exact_position_value=exact_position_value,
                local_nav=local_nav,
                exact_local_nav=exact_local_nav,
                local_residual=local_residual,
                bridge=bridge,
                exact_base=exact_base,
                residual=residual,
            )
        )
    with localcontext() as context:
        context.prec = _EXACT_PRECISION
        reported_base = sum((row.reported_base for row in rows), Decimal(0))
        exact_base = sum((row.exact_base for row in rows), Decimal(0))
        residual = sum((row.residual for row in rows), Decimal(0))
    with localcontext() as context:
        context.prec = _EXACT_PRECISION
        balanced = exact_base == reported_base + residual
    if not balanced:
        _reject(
            "internal_nav_bridge_mismatch",
            "nav_bridge",
            detail="exact base NAV does not equal reported base plus residual",
        )
    total = NavBridgeTotal(
        reported_base=reported_base,
        exact_base=exact_base,
        residual=residual,
    )
    return LedgerNavBridge(base_currency=base_currency, rows=tuple(rows), total=total)
