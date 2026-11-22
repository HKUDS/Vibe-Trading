"""Direct-pair FX snapshots, conversion planning and exact NAV bridge events.

A snapshot declares ``1 unit of from == rate units of to``. The module never
inverts, triangulates, refreshes or caches a rate: every conversion and every
base-currency valuation must resolve its own direct pair. Conversions settle
against pre-fill opening cash only, so no conversion can be auto-funded by a
fill, by another bucket or by an earlier conversion's proceeds.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, localcontext
from types import MappingProxyType
from typing import Literal, Mapping, Sequence, TypeAlias

from .models import Currency, FxSnapshot, PortfolioRequest
from .numeric import (MONEY_SPEC, _EXACT_PRECISION, _exact_product, _reject,
                      canonical_decimal, parse_fx_rate, parse_money)

__all__ = [
    "ConversionStage",
    "FxConversionEvent",
    "FxConversionPlan",
    "FxRate",
    "FxRateBook",
    "NavBridgeEvent",
    "NavBridgeTotal",
    "plan_conversions",
    "total_nav_bridge",
    "value_in_base_currency",
]

ConversionStage: TypeAlias = Literal["pre_fill", "post_fill"]
DecimalLike: TypeAlias = Decimal | str


def _quantize_money(value: Decimal, path: str) -> Decimal:
    """Reuse the single pt-v2.0 money scale and ROUND_HALF_EVEN policy."""
    return Decimal(canonical_decimal(value, MONEY_SPEC, path))


def _money(value: DecimalLike, path: str) -> Decimal:
    if isinstance(value, str):
        return parse_money(value, path)
    return _quantize_money(value, path)


def _residual(exact: Decimal, reported: Decimal) -> Decimal:
    residual = exact - reported
    return Decimal(0) if residual.is_zero() else residual


@dataclass(frozen=True, slots=True)
class FxRate:
    """One typed direct pair: ``1 from_currency == rate to_currency``."""

    rate_id: str
    from_currency: Currency
    to_currency: Currency
    rate: Decimal
    as_of: datetime
    source: str

    @classmethod
    def from_snapshot(cls, snapshot: FxSnapshot, path: str) -> FxRate:
        rate = parse_fx_rate(snapshot.rate, f"{path}.rate")
        if snapshot.from_currency == snapshot.to_currency:
            _reject(
                "degenerate_fx_pair",
                f"{path}.to",
                detail="a conversion pair must name two different currencies",
            )
        return cls(
            rate_id=snapshot.rate_id,
            from_currency=snapshot.from_currency,
            to_currency=snapshot.to_currency,
            rate=rate,
            as_of=snapshot.as_of,
            source=snapshot.source,
        )


@dataclass(frozen=True, slots=True)
class FxRateBook:
    """Exact rate-id and direct-pair lookup over caller-supplied snapshots."""

    rates: tuple[FxRate, ...] = ()
    at: datetime | None = None
    max_age: timedelta | None = None

    @classmethod
    def from_snapshots(
        cls,
        snapshots: Sequence[FxSnapshot],
        *,
        at: datetime | None = None,
        max_age: timedelta | None = None,
    ) -> FxRateBook:
        rates: list[FxRate] = []
        seen: set[str] = set()
        for index, snapshot in enumerate(snapshots):
            if snapshot.rate_id in seen:
                _reject(
                    "duplicate_fx_rate",
                    f"fx_snapshots[{index}].rate_id",
                    detail="rate ids must be unique",
                )
            seen.add(snapshot.rate_id)
            rates.append(FxRate.from_snapshot(snapshot, f"fx_snapshots[{index}]"))
        return cls(rates=tuple(rates), at=at, max_age=max_age)

    @classmethod
    def from_request(cls, request: PortfolioRequest, *, max_age: timedelta | None = None) -> FxRateBook:
        """Bind caller snapshots to the request valuation instant."""
        return cls.from_snapshots(request.fx_snapshots, at=request.valuation_at, max_age=max_age)

    def by_id(self, rate_id: str, path: str = "fx_snapshots") -> FxRate:
        for rate in self.rates:
            if rate.rate_id == rate_id:
                return rate
        _reject("unknown_fx_rate", path, detail=f"rate_id {rate_id!r} is not declared")

    def require_direct(
        self,
        from_currency: Currency,
        to_currency: Currency,
        *,
        path: str = "fx_snapshots",
        rate_id: str | None = None,
    ) -> FxRate:
        """Return the one direct pair, never an inverse or a composed path."""
        if from_currency == to_currency:
            _reject("identity_fx_pair", path, detail="a conversion pair must name two currencies")
        if rate_id is not None:
            rate = self.by_id(rate_id, path)
            if (rate.from_currency, rate.to_currency) == (from_currency, to_currency):
                return self._checked(rate, path)
            if (rate.from_currency, rate.to_currency) == (to_currency, from_currency):
                _reject(
                    "inverse_fx_rate_only",
                    path,
                    detail=f"rate_id {rate_id!r} declares the inverse direction",
                )
            _reject("fx_pair_mismatch", path, detail=f"rate_id {rate_id!r} names another pair")
        direct = tuple(
            rate
            for rate in self.rates
            if rate.from_currency == from_currency and rate.to_currency == to_currency
        )
        if len(direct) > 1:
            _reject(
                "ambiguous_direct_fx_pair",
                path,
                detail="several direct pairs match; name one rate_id",
            )
        if direct:
            return self._checked(direct[0], path)
        if any(
            rate.from_currency == to_currency and rate.to_currency == from_currency
            for rate in self.rates
        ):
            _reject("inverse_fx_rate_only", path, detail="only the inverse pair is declared")
        if self._has_two_hop(from_currency, to_currency):
            _reject("triangulation_not_supported", path, detail="a composed path is not a direct pair")
        _reject("missing_direct_fx_pair", path, detail="declare the direct pair explicitly")

    def _has_two_hop(self, from_currency: Currency, to_currency: Currency) -> bool:
        reachable = {rate.to_currency for rate in self.rates if rate.from_currency == from_currency}
        return any(
            rate.from_currency in reachable and rate.to_currency == to_currency
            for rate in self.rates
        )

    def _checked(self, rate: FxRate, path: str) -> FxRate:
        if self.at is None:
            return rate
        if rate.as_of > self.at:
            _reject("future_fx_rate", path, detail="snapshot is later than the valuation instant")
        if self.max_age is not None and self.at - rate.as_of > self.max_age:
            _reject("stale_fx_rate", path, detail="snapshot is older than the allowed age")
        return rate


@dataclass(frozen=True, slots=True)
class FxConversionEvent:
    """One settled pre-fill conversion with its exact rounding residual."""

    rate_id: str
    from_bucket_id: str
    to_bucket_id: str
    from_currency: Currency
    to_currency: Currency
    source_amount: Decimal
    rate: Decimal
    exact_converted: Decimal
    converted_amount: Decimal
    residual: Decimal


@dataclass(frozen=True, slots=True)
class FxConversionPlan:
    """Immutable conversion events plus every bucket's post-conversion cash."""

    events: tuple[FxConversionEvent, ...] = ()
    cash: tuple[tuple[str, Decimal], ...] = ()

    def cash_map(self) -> Mapping[str, Decimal]:
        return MappingProxyType(dict(self.cash))


def plan_conversions(
    request: PortfolioRequest,
    *,
    stage: ConversionStage = "pre_fill",
    max_age: timedelta | None = None,
) -> FxConversionPlan:
    """Settle declared conversions against opening cash, never after a fill."""
    if stage != "pre_fill":
        _reject(
            "post_fill_fx_conversion",
            "fx_conversions",
            detail="conversions settle before fills; post-fill conversion is not supported",
        )
    book = FxRateBook.from_snapshots(
        request.fx_snapshots,
        at=request.planning_at,
        max_age=max_age,
    )
    buckets = {bucket.bucket_id: bucket for bucket in request.portfolio_state.buckets}
    balances: dict[str, Decimal] = {
        bucket.bucket_id: parse_money(bucket.cash, f"portfolio_state.buckets[{index}].cash")
        for index, bucket in enumerate(request.portfolio_state.buckets)
    }
    available = dict(balances)
    events: list[FxConversionEvent] = []
    for index, conversion in enumerate(request.fx_conversions):
        source = buckets.get(conversion.from_bucket_id)
        target = buckets.get(conversion.to_bucket_id)
        if source is None:
            _reject("unknown_bucket", f"fx_conversions[{index}].from_bucket_id", bucket_id=conversion.from_bucket_id)
        if target is None:
            _reject("unknown_bucket", f"fx_conversions[{index}].to_bucket_id", bucket_id=conversion.to_bucket_id)
        if source.bucket_id == target.bucket_id:
            _reject(
                "identity_fx_conversion",
                f"fx_conversions[{index}].to_bucket_id",
                bucket_id=source.bucket_id,
            )
        amount = parse_money(conversion.amount, f"fx_conversions[{index}].amount")
        if amount <= 0:
            _reject(
                "invalid_fx_amount",
                f"fx_conversions[{index}].amount",
                bucket_id=source.bucket_id,
                detail="a conversion amount must be positive",
            )
        rate = book.require_direct(
            source.currency,
            target.currency,
            path=f"fx_conversions[{index}].rate_id",
            rate_id=conversion.rate_id,
        )
        if available[source.bucket_id] < amount:
            _reject(
                "insufficient_fx_cash",
                f"fx_conversions[{index}].amount",
                bucket_id=source.bucket_id,
                detail="opening source cash cannot fund the conversion",
            )
        exact = _exact_product(amount, rate.rate)
        converted = _quantize_money(exact, f"fx_conversions[{index}].amount")
        residual = _residual(exact, converted)
        available[source.bucket_id] -= amount
        balances[source.bucket_id] -= amount
        balances[target.bucket_id] += converted
        events.append(
            FxConversionEvent(
                rate_id=rate.rate_id,
                from_bucket_id=source.bucket_id,
                to_bucket_id=target.bucket_id,
                from_currency=source.currency,
                to_currency=target.currency,
                source_amount=amount,
                rate=rate.rate,
                exact_converted=exact,
                converted_amount=converted,
                residual=residual,
            )
        )
    return FxConversionPlan(events=tuple(events), cash=tuple(balances.items()))


@dataclass(frozen=True, slots=True)
class NavBridgeEvent:
    """One bucket's local amount valued in the base currency."""

    bucket_id: str
    currency: Currency
    base_currency: Currency
    rate_id: str | None
    rate: Decimal
    local_amount: Decimal
    exact_base: Decimal
    reported_base: Decimal
    residual: Decimal


@dataclass(frozen=True, slots=True)
class NavBridgeTotal:
    """Exact aggregate of NAV bridge rows; reported plus residual is exact."""

    reported_base: Decimal
    exact_base: Decimal
    residual: Decimal

    @property
    def balanced(self) -> bool:
        with localcontext() as context:
            context.prec = _EXACT_PRECISION
            return self.exact_base == self.reported_base + self.residual


def value_in_base_currency(
    bucket_id: str,
    currency: Currency,
    amount: DecimalLike,
    book: FxRateBook,
    *,
    base_currency: Currency,
    path: str | None = None,
) -> NavBridgeEvent:
    """Value one bucket amount in the base currency through a direct pair."""
    local_amount = _money(amount, path or f"bucket_results.{bucket_id}.cash")
    if currency == base_currency:
        return NavBridgeEvent(
            bucket_id=bucket_id,
            currency=currency,
            base_currency=base_currency,
            rate_id=None,
            rate=Decimal(1),
            local_amount=local_amount,
            exact_base=local_amount,
            reported_base=local_amount,
            residual=Decimal(0),
        )
    rate = book.require_direct(
        currency,
        base_currency,
        path=path or f"bucket_results.{bucket_id}.fx_rate_id",
    )
    exact = _exact_product(local_amount, rate.rate)
    reported = _quantize_money(exact, f"bucket_results.{bucket_id}.nav_base")
    return NavBridgeEvent(
        bucket_id=bucket_id,
        currency=currency,
        base_currency=base_currency,
        rate_id=rate.rate_id,
        rate=rate.rate,
        local_amount=local_amount,
        exact_base=exact,
        reported_base=reported,
        residual=_residual(exact, reported),
    )


def total_nav_bridge(events: Sequence[NavBridgeEvent]) -> NavBridgeTotal:
    """Sum bridge rows without re-rounding away any residual."""
    with localcontext() as context:
        context.prec = _EXACT_PRECISION
        reported = sum((event.reported_base for event in events), Decimal(0))
        exact = sum((event.exact_base for event in events), Decimal(0))
        residual = sum((event.residual for event in events), Decimal(0))
    return NavBridgeTotal(reported_base=reported, exact_base=exact, residual=residual)
