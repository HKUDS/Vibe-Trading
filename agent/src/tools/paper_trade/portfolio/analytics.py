"""Exact post-valuation NAV, exposure and concentration for pt-v2.0.

The module is a pure projection over three already-validated inputs:

* the immutable Decimal :class:`~.ledger.PortfolioLedger` after fills,
* the prepared per-bucket valuation snapshots or closed-market prior marks,
* the caller-declared direct FX snapshots.

No value is fetched, inferred or taken from an engine float NAV row. A currency
is translated only through its own direct pair; a market name never implies a
currency. Every position row carries its dated mark and FX rate identity, while
cash, per-bucket, per-currency, per-market and per-sector aggregates carry the
same provenance. Caller sectors are applied verbatim and every unmapped
position is reported under the explicit ``unclassified`` bucket.

The reported NAV is the ledger's own rounded NAV. The bridge also exposes the
exact ``Σ cash×fx + Σ qty×price×fx`` identity and the resulting rounding
residual, plus the already-settled conversion rounding in both its local
currency and base value. Conversion rounding is descriptive: it is already
inside the converted cash and is never added to NAV a second time.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, localcontext
from typing import Final, NoReturn

from .data import (
    PreparedPortfolioData,
    PriorMarkValuation,
    TargetBarValuation,
)
from .fx import FxConversionEvent, FxRateBook
from .ledger import PortfolioLedger, value_ledger
from .models import (
    AnalyticsBucketExposure,
    AnalyticsCashRow,
    AnalyticsConcentration,
    AnalyticsConversionRow,
    AnalyticsCurrencyExposure,
    AnalyticsFxReference,
    AnalyticsMarketExposure,
    AnalyticsMarkReference,
    AnalyticsNavBridge,
    AnalyticsPositionRow,
    AnalyticsPositionWeight,
    AnalyticsProvenance,
    AnalyticsSectorExposure,
    Currency,
    Market,
    PortfolioAnalytics,
    PortfolioRequest,
)
from .numeric import (
    FX_RATE_SPEC,
    MONEY_SPEC,
    PRICE_SPEC,
    WEIGHT_SPEC,
    canonical_decimal,
    parse_price,
)
from .orchestrator import OrchestrationError
from .schema import PortfolioRequestError

__all__ = ["build_portfolio_analytics"]

_EXACT_PRECISION: Final = 60
_UNCLASSIFIED: Final = "unclassified"
_ZERO_WEIGHT: Final = Decimal(0)


@dataclass(frozen=True, slots=True)
class _Mark:
    price: Decimal
    price_date: date
    source: str
    as_of: datetime


@dataclass(frozen=True, slots=True)
class _PositionBuild:
    row: AnalyticsPositionRow
    exact_base: Decimal


def _reject(
    reason: str,
    path: str,
    *,
    bucket_id: str | None = None,
    detail: str = "",
) -> NoReturn:
    raise PortfolioRequestError(reason=reason, path=path, bucket_id=bucket_id, detail=detail)


def _invariant(reason: str, path: str, detail: str = "") -> NoReturn:
    raise OrchestrationError(
        stage="valuate_reconcile",
        reason=reason,
        code="INTERNAL",
        path=path,
        detail=detail,
    )


def _exact_product(left: Decimal, right: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = _EXACT_PRECISION
        return left * right


def _exact_sum(values: Iterable[Decimal]) -> Decimal:
    with localcontext() as context:
        context.prec = _EXACT_PRECISION
        return sum(values, Decimal(0))


def _money(value: Decimal, path: str) -> Decimal:
    if value.is_zero():
        value = Decimal(0)
    return Decimal(canonical_decimal(value, MONEY_SPEC, path))


def _weight(value: Decimal, path: str) -> Decimal:
    if value.is_zero():
        value = Decimal(0)
    return Decimal(canonical_decimal(value, WEIGHT_SPEC, path))


def _rate_text(value: Decimal, path: str) -> str:
    return canonical_decimal(value, FX_RATE_SPEC, path)


def _price_text(value: Decimal, path: str) -> str:
    return canonical_decimal(value, PRICE_SPEC, path)


def _exact_text(value: Decimal, path: str) -> str:
    """Render an exact Decimal without exponent spelling or trailing zeros."""
    if not isinstance(value, Decimal) or not value.is_finite():
        _invariant("invalid_analytics_decimal", path, "exact values must be finite Decimals")
    if value.is_zero():
        return "0"
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in {"-0", ""} else text


def _ratio(value: Decimal, denominator: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = _EXACT_PRECISION
        return value / denominator


def _fx_reference(
    currency: Currency,
    base_currency: Currency,
    book: FxRateBook,
    valuation_at: datetime,
    *,
    path: str,
) -> tuple[AnalyticsFxReference, Decimal]:
    """Resolve one currency's direct base pair or its explicit identity."""
    if currency == base_currency:
        rate = Decimal(1)
        return (
            AnalyticsFxReference(
                rate_id=f"identity:{base_currency}",
                from_currency=currency,
                to_currency=base_currency,
                rate=_rate_text(rate, path),
                as_of=valuation_at,
                source="base_currency_identity",
            ),
            rate,
        )
    rate = book.require_direct(currency, base_currency, path=path)
    return (
        AnalyticsFxReference(
            rate_id=rate.rate_id,
            from_currency=rate.from_currency,
            to_currency=rate.to_currency,
            rate=_rate_text(rate.rate, path),
            as_of=rate.as_of,
            source=rate.source,
        ),
        rate.rate,
    )


def _marks_by_bucket(
    prepared: PreparedPortfolioData,
) -> dict[str, dict[str, _Mark]]:
    """Index exactly the prepared marks; never fall back to another date."""
    marks: dict[str, dict[str, _Mark]] = {}
    for bucket in prepared.buckets:
        rows: dict[str, _Mark] = {}
        valuation = bucket.valuation
        if isinstance(valuation, TargetBarValuation):
            snapshot = valuation.snapshot
            for bar in snapshot.bars:
                path = f"analytics.marks.{bucket.bucket_id}.{bar.symbol}"
                if bar.symbol in rows:
                    _reject(
                        "duplicate_valuation_mark",
                        path,
                        bucket_id=bucket.bucket_id,
                        detail="a symbol may declare exactly one valuation mark",
                    )
                rows[bar.symbol] = _Mark(
                    price=parse_price(bar.close, path),
                    price_date=snapshot.price_date,
                    source=snapshot.source,
                    as_of=snapshot.as_of,
                )
        else:
            assert isinstance(valuation, PriorMarkValuation)
            for mark in valuation.marks:
                path = f"analytics.marks.{bucket.bucket_id}.{mark.symbol}"
                if mark.symbol in rows:
                    _reject(
                        "duplicate_valuation_mark",
                        path,
                        bucket_id=bucket.bucket_id,
                        detail="a symbol may declare exactly one prior mark",
                    )
                rows[mark.symbol] = _Mark(
                    price=parse_price(mark.close, path),
                    price_date=mark.price_date,
                    source=mark.source,
                    as_of=mark.as_of,
                )
        marks[bucket.bucket_id] = rows
    return marks


def _provenance(
    price_dates: Iterable[date],
    references: Iterable[AnalyticsFxReference],
) -> AnalyticsProvenance:
    dates = tuple(sorted(set(price_dates)))
    unique = {
        (reference.rate_id, reference.from_currency, reference.to_currency): reference
        for reference in references
    }
    return AnalyticsProvenance(
        price_dates=dates,
        fx=tuple(unique[key] for key in sorted(unique)),
    )


def _position_provenance(rows: Sequence[AnalyticsPositionRow]) -> AnalyticsProvenance:
    return _provenance(
        (row.mark.price_date for row in rows),
        (row.fx for row in rows),
    )


def _bucket_provenance(
    cash: AnalyticsCashRow,
    positions: Sequence[AnalyticsPositionRow],
) -> AnalyticsProvenance:
    return _provenance(
        (row.mark.price_date for row in positions),
        (cash.fx, *(row.fx for row in positions)),
    )


def _declared_sector_map(
    request: PortfolioRequest,
    ledger: PortfolioLedger,
    *,
    base_path: str = "analytics.sectors",
) -> dict[tuple[str, str], str]:
    """Validate caller sectors against the declared buckets and instruments."""
    buckets = {bucket.bucket_id: bucket for bucket in ledger.buckets}
    declared: set[tuple[str, str]] = set()
    for bucket in request.portfolio_state.buckets:
        for position in bucket.positions:
            declared.add((bucket.bucket_id, position.symbol))
    for order in request.orders or ():
        declared.add((order.bucket_id, order.symbol))
    for target in request.target_weights or ():
        declared.add((target.bucket_id, target.symbol))

    sectors: dict[tuple[str, str], str] = {}
    for index, row in enumerate(request.sectors):
        path = f"{base_path}[{index}]"
        if row.bucket_id not in buckets:
            _reject(
                "unknown_bucket",
                f"{path}.bucket_id",
                bucket_id=row.bucket_id,
                detail="the sector names a bucket that is not declared",
            )
        key = (row.bucket_id, row.symbol)
        if key not in declared:
            _reject(
                "unknown_sector_symbol",
                f"{path}.symbol",
                bucket_id=row.bucket_id,
                detail="the sector names an instrument outside the declared portfolio and plan",
            )
        if key in sectors:
            _reject(
                "duplicate_sector",
                f"{path}.symbol",
                bucket_id=row.bucket_id,
                detail="an instrument may declare exactly one caller sector",
            )
        sectors[key] = row.sector
    return sectors


def _currency_exposures(
    buckets: Sequence[AnalyticsBucketExposure],
    *,
    nav_base: Decimal,
) -> tuple[AnalyticsCurrencyExposure, ...]:
    grouped: dict[Currency, list[AnalyticsBucketExposure]] = {}
    for row in buckets:
        grouped.setdefault(row.currency, []).append(row)
    exposures: list[AnalyticsCurrencyExposure] = []
    for currency in sorted(grouped):
        rows = grouped[currency]
        cash_base = _exact_sum(Decimal(row.cash_base) for row in rows)
        position_value_base = _exact_sum(
            Decimal(row.position_value_base) for row in rows
        )
        valuation_rounding = _exact_sum(Decimal(row.valuation_rounding) for row in rows)
        value_base = _exact_sum(Decimal(row.value_base) for row in rows)
        if value_base != cash_base + position_value_base + valuation_rounding:
            _invariant(
                "currency_exposure_mismatch",
                f"analytics.currency_exposures.{currency}",
            )
        exposures.append(
            AnalyticsCurrencyExposure(
                currency=currency,
                cash_base=canonical_decimal(
                    cash_base,
                    MONEY_SPEC,
                    "analytics.currency_exposures.cash_base",
                ),
                position_value_base=canonical_decimal(
                    position_value_base,
                    MONEY_SPEC,
                    "analytics.currency_exposures.position_value_base",
                ),
                valuation_rounding=canonical_decimal(
                    valuation_rounding,
                    MONEY_SPEC,
                    "analytics.currency_exposures.valuation_rounding",
                ),
                value_base=canonical_decimal(
                    value_base,
                    MONEY_SPEC,
                    "analytics.currency_exposures.value_base",
                ),
                weight=canonical_decimal(
                    _weight(
                        _ratio(value_base, nav_base)
                        if nav_base > 0
                        else _ZERO_WEIGHT,
                        "analytics.currency_exposures.weight",
                    ),
                    WEIGHT_SPEC,
                    "analytics.currency_exposures.weight",
                ),
                bucket_ids=tuple(sorted(row.bucket_id for row in rows)),
                provenance=_provenance(
                    (date_value for row in rows for date_value in row.provenance.price_dates),
                    (reference for row in rows for reference in row.provenance.fx),
                ),
            )
        )
    return tuple(exposures)


def _market_exposures(
    buckets: Sequence[AnalyticsBucketExposure],
    *,
    nav_base: Decimal,
) -> tuple[AnalyticsMarketExposure, ...]:
    grouped: dict[Market, list[AnalyticsBucketExposure]] = {}
    for row in buckets:
        grouped.setdefault(row.market, []).append(row)
    exposures: list[AnalyticsMarketExposure] = []
    for market in sorted(grouped):
        rows = grouped[market]
        cash_base = _exact_sum(Decimal(row.cash_base) for row in rows)
        position_value_base = _exact_sum(
            Decimal(row.position_value_base) for row in rows
        )
        valuation_rounding = _exact_sum(Decimal(row.valuation_rounding) for row in rows)
        value_base = _exact_sum(Decimal(row.value_base) for row in rows)
        if value_base != cash_base + position_value_base + valuation_rounding:
            _invariant("market_exposure_mismatch", f"analytics.market_exposures.{market}")
        exposures.append(
            AnalyticsMarketExposure(
                market=market,
                cash_base=canonical_decimal(
                    cash_base,
                    MONEY_SPEC,
                    "analytics.market_exposures.cash_base",
                ),
                position_value_base=canonical_decimal(
                    position_value_base,
                    MONEY_SPEC,
                    "analytics.market_exposures.position_value_base",
                ),
                valuation_rounding=canonical_decimal(
                    valuation_rounding,
                    MONEY_SPEC,
                    "analytics.market_exposures.valuation_rounding",
                ),
                value_base=canonical_decimal(
                    value_base,
                    MONEY_SPEC,
                    "analytics.market_exposures.value_base",
                ),
                weight=canonical_decimal(
                    _weight(
                        _ratio(value_base, nav_base)
                        if nav_base > 0
                        else _ZERO_WEIGHT,
                        "analytics.market_exposures.weight",
                    ),
                    WEIGHT_SPEC,
                    "analytics.market_exposures.weight",
                ),
                bucket_ids=tuple(sorted(row.bucket_id for row in rows)),
                provenance=_provenance(
                    (date_value for row in rows for date_value in row.provenance.price_dates),
                    (reference for row in rows for reference in row.provenance.fx),
                ),
            )
        )
    return tuple(exposures)


def _sector_exposures(
    request: PortfolioRequest,
    ledger: PortfolioLedger,
    positions: Sequence[AnalyticsPositionRow],
    *,
    position_value_base: Decimal,
) -> tuple[AnalyticsSectorExposure, ...]:
    sectors = _declared_sector_map(request, ledger)
    grouped: dict[str, list[AnalyticsPositionRow]] = {}
    for row in positions:
        sector = sectors.get((row.bucket_id, row.symbol), _UNCLASSIFIED)
        grouped.setdefault(sector, []).append(row)

    exposures: list[AnalyticsSectorExposure] = []
    for sector, rows in grouped.items():
        value_base = _exact_sum(Decimal(row.value_base) for row in rows)
        exposures.append(
            AnalyticsSectorExposure(
                sector=sector,
                value_base=canonical_decimal(
                    value_base,
                    MONEY_SPEC,
                    f"analytics.sector_exposures.{sector}",
                ),
                weight_of_positions=canonical_decimal(
                    _weight(
                        _ratio(value_base, position_value_base)
                        if position_value_base > 0
                        else _ZERO_WEIGHT,
                        f"analytics.sector_exposures.{sector}.weight_of_positions",
                    ),
                    WEIGHT_SPEC,
                    f"analytics.sector_exposures.{sector}.weight_of_positions",
                ),
                bucket_ids=tuple(sorted({row.bucket_id for row in rows})),
                symbols=tuple(sorted(row.symbol for row in rows)),
                provenance=_position_provenance(rows),
            )
        )
    return tuple(
        sorted(exposures, key=lambda row: (-Decimal(row.value_base), row.sector))
    )


def _concentration(
    positions: Sequence[AnalyticsPositionRow],
    *,
    nav_base: Decimal,
) -> AnalyticsConcentration:
    sorted_rows = sorted(
        positions,
        key=lambda row: (-Decimal(row.value_base), row.bucket_id, row.symbol),
    )
    weights = [
        _ratio(Decimal(row.value_base), nav_base) if nav_base > 0 else _ZERO_WEIGHT
        for row in sorted_rows
    ]
    ordered = sorted(weights, reverse=True)
    top_1 = ordered[0] if ordered else _ZERO_WEIGHT
    top_5 = _exact_sum(ordered[:5])
    hhi = _exact_sum(weight * weight for weight in ordered)
    return AnalyticsConcentration(
        position_count=len(sorted_rows),
        top_1=canonical_decimal(
            _weight(top_1, "analytics.concentration.top_1"),
            WEIGHT_SPEC,
            "analytics.concentration.top_1",
        ),
        top_5=canonical_decimal(
            _weight(top_5, "analytics.concentration.top_5"),
            WEIGHT_SPEC,
            "analytics.concentration.top_5",
        ),
        hhi=canonical_decimal(
            _weight(hhi, "analytics.concentration.hhi"),
            WEIGHT_SPEC,
            "analytics.concentration.hhi",
        ),
        position_weights=tuple(
            AnalyticsPositionWeight(
                bucket_id=row.bucket_id,
                symbol=row.symbol,
                value_base=row.value_base,
                weight=canonical_decimal(
                    _weight(
                        _ratio(Decimal(row.value_base), nav_base)
                        if nav_base > 0
                        else _ZERO_WEIGHT,
                        f"analytics.positions.{row.bucket_id}.{row.symbol}.weight",
                    ),
                    WEIGHT_SPEC,
                    f"analytics.positions.{row.bucket_id}.{row.symbol}.weight",
                ),
            )
            for row in sorted_rows
        ),
        provenance=_position_provenance(sorted_rows),
    )


def build_portfolio_analytics(
    request: PortfolioRequest,
    ledger: PortfolioLedger,
    prepared: PreparedPortfolioData,
    *,
    conversion_events: Sequence[FxConversionEvent] = (),
) -> PortfolioAnalytics:
    """Build exact analytics for one validated end ledger and its marks.

    The ledger bridge is recomputed here from the same prepared marks and
    direct FX pairs, so the published NAV can only equal the Decimal ledger
    arithmetic. Any missing mark/pair raises the existing declared request
    error; any internal identity mismatch raises an internal stage error and
    no partial analytics document is returned.
    """
    base_currency = request.base_currency
    book = FxRateBook.from_snapshots(request.fx_snapshots, at=request.valuation_at)
    marks = _marks_by_bucket(prepared)
    mark_values = {
        symbol: mark.price
        for bucket_marks in marks.values()
        for symbol, mark in bucket_marks.items()
    }
    ledger_bridge = value_ledger(
        ledger,
        mark_values,
        book,
        base_currency=base_currency,
    )
    bridge_by_id = {row.bucket_id: row for row in ledger_bridge.rows}
    nav_base = ledger_bridge.total.reported_base
    exact_nav_base = ledger_bridge.total.exact_base

    cash_rows: list[AnalyticsCashRow] = []
    position_builds: list[_PositionBuild] = []
    cash_exact_by_bucket: dict[str, Decimal] = {}
    for bucket in ledger.buckets:
        bridge_row = bridge_by_id.get(bucket.bucket_id)
        if bridge_row is None:
            _invariant(
                "valuation_bucket_mismatch",
                f"analytics.buckets.{bucket.bucket_id}",
            )
        fx_path = f"analytics.buckets.{bucket.bucket_id}.fx_rate_id"
        fx, rate = _fx_reference(
            bucket.currency,
            base_currency,
            book,
            request.valuation_at,
            path=fx_path,
        )
        cash_exact = _exact_product(bucket.cash, rate)
        cash_value = _money(cash_exact, f"analytics.cash.{bucket.bucket_id}.value_base")
        cash_exact_by_bucket[bucket.bucket_id] = cash_exact
        cash_rows.append(
            AnalyticsCashRow(
                bucket_id=bucket.bucket_id,
                market=bucket.market,
                currency=bucket.currency,
                valuation_date=request.trade_date,
                amount=canonical_decimal(
                    bucket.cash,
                    MONEY_SPEC,
                    f"analytics.cash.{bucket.bucket_id}.amount",
                ),
                fx=fx,
                value_base=canonical_decimal(
                    cash_value,
                    MONEY_SPEC,
                    f"analytics.cash.{bucket.bucket_id}.value_base",
                ),
                exact_value_base=_exact_text(
                    cash_exact,
                    f"analytics.cash.{bucket.bucket_id}.exact_value_base",
                ),
                rounding_residual=_exact_text(
                    cash_exact - cash_value,
                    f"analytics.cash.{bucket.bucket_id}.rounding_residual",
                ),
            )
        )

        bucket_marks = marks.get(bucket.bucket_id, {})
        for position in sorted(bucket.positions, key=lambda row: row.symbol):
            mark = bucket_marks.get(position.symbol)
            if mark is None:
                _reject(
                    "missing_valuation_mark",
                    f"analytics.marks.{bucket.bucket_id}.{position.symbol}",
                    bucket_id=bucket.bucket_id,
                    detail="every held instrument needs a declared valuation mark",
                )
            exact_local = _exact_product(Decimal(position.qty), mark.price)
            local_value = _money(
                exact_local,
                f"analytics.positions.{bucket.bucket_id}.{position.symbol}.local_value",
            )
            exact_base = _exact_product(exact_local, rate)
            value_base = _money(
                exact_base,
                f"analytics.positions.{bucket.bucket_id}.{position.symbol}.value_base",
            )
            weight = (
                _weight(
                    _ratio(value_base, nav_base),
                    f"analytics.positions.{bucket.bucket_id}.{position.symbol}.weight",
                )
                if nav_base > 0
                else _weight(_ZERO_WEIGHT, f"analytics.positions.{bucket.bucket_id}.{position.symbol}.weight")
            )
            position_builds.append(
                _PositionBuild(
                    row=AnalyticsPositionRow(
                        bucket_id=bucket.bucket_id,
                        market=bucket.market,
                        currency=bucket.currency,
                        symbol=position.symbol,
                        qty=position.qty,
                        price=_price_text(
                            mark.price,
                            f"analytics.positions.{bucket.bucket_id}.{position.symbol}.price",
                        ),
                        mark=AnalyticsMarkReference(
                            price_date=mark.price_date,
                            source=mark.source,
                            as_of=mark.as_of,
                        ),
                        local_value=canonical_decimal(
                            local_value,
                            MONEY_SPEC,
                            f"analytics.positions.{bucket.bucket_id}.{position.symbol}.local_value",
                        ),
                        fx=fx,
                        value_base=canonical_decimal(
                            value_base,
                            MONEY_SPEC,
                            f"analytics.positions.{bucket.bucket_id}.{position.symbol}.value_base",
                        ),
                        exact_value_base=_exact_text(
                            exact_base,
                            f"analytics.positions.{bucket.bucket_id}.{position.symbol}.exact_value_base",
                        ),
                        rounding_residual=_exact_text(
                            exact_base - value_base,
                            f"analytics.positions.{bucket.bucket_id}.{position.symbol}.rounding_residual",
                        ),
                        weight=canonical_decimal(
                            weight,
                            WEIGHT_SPEC,
                            f"analytics.positions.{bucket.bucket_id}.{position.symbol}.weight",
                        ),
                    ),
                    exact_base=exact_base,
                )
            )

    position_rows = tuple(build.row for build in position_builds)
    positions_by_bucket: dict[str, list[AnalyticsPositionRow]] = {}
    for row in position_rows:
        positions_by_bucket.setdefault(row.bucket_id, []).append(row)
    cash_by_bucket = {row.bucket_id: row for row in cash_rows}

    bucket_exposures: list[AnalyticsBucketExposure] = []
    for bucket in ledger.buckets:
        bridge_row = bridge_by_id[bucket.bucket_id]
        cash = cash_by_bucket[bucket.bucket_id]
        bucket_positions = positions_by_bucket.get(bucket.bucket_id, [])
        cash_base = Decimal(cash.value_base)
        position_value_base = _exact_sum(
            Decimal(row.value_base) for row in bucket_positions
        )
        reported = bridge_row.reported_base
        valuation_rounding = reported - cash_base - position_value_base
        if _money(valuation_rounding, "analytics.buckets.valuation_rounding") != (
            valuation_rounding
        ):
            _invariant(
                "bucket_exposure_rounding_mismatch",
                f"analytics.buckets.{bucket.bucket_id}.valuation_rounding",
            )
        bucket_exposures.append(
            AnalyticsBucketExposure(
                bucket_id=bucket.bucket_id,
                market=bucket.market,
                currency=bucket.currency,
                cash_base=canonical_decimal(
                    cash_base,
                    MONEY_SPEC,
                    f"analytics.buckets.{bucket.bucket_id}.cash_base",
                ),
                position_value_base=canonical_decimal(
                    position_value_base,
                    MONEY_SPEC,
                    f"analytics.buckets.{bucket.bucket_id}.position_value_base",
                ),
                valuation_rounding=canonical_decimal(
                    valuation_rounding,
                    MONEY_SPEC,
                    f"analytics.buckets.{bucket.bucket_id}.valuation_rounding",
                ),
                value_base=canonical_decimal(
                    reported,
                    MONEY_SPEC,
                    f"analytics.buckets.{bucket.bucket_id}.value_base",
                ),
                exact_value_base=_exact_text(
                    bridge_row.exact_base,
                    f"analytics.buckets.{bucket.bucket_id}.exact_value_base",
                ),
                rounding_residual=_exact_text(
                    bridge_row.residual,
                    f"analytics.buckets.{bucket.bucket_id}.rounding_residual",
                ),
                fx=cash.fx,
                provenance=_bucket_provenance(cash, bucket_positions),
            )
        )

    cash_base = _exact_sum(Decimal(row.value_base) for row in cash_rows)
    position_value_base = _exact_sum(
        Decimal(row.value_base) for row in position_rows
    )
    exact_cash_base = _exact_sum(
        Decimal(row.exact_value_base) for row in cash_rows
    )
    exact_position_base = _exact_sum(
        Decimal(build.exact_base) for build in position_builds
    )
    valuation_rounding = nav_base - cash_base - position_value_base
    if exact_cash_base + exact_position_base != exact_nav_base:
        _invariant(
            "analytics_exact_nav_mismatch",
            "analytics.exact_nav_base",
            "exact cash plus exact marked positions must equal the ledger exact NAV",
        )
    if cash_base + position_value_base + valuation_rounding != nav_base:
        _invariant("analytics_nav_bridge_mismatch", "analytics.nav_bridge")

    conversion_rows: list[AnalyticsConversionRow] = []
    conversion_rounding_base = Decimal(0)
    for index, event in enumerate(conversion_events):
        path = f"analytics.conversions[{index}]"
        expected_residual = event.exact_converted - event.converted_amount
        if expected_residual != event.residual:
            _invariant(
                "conversion_residual_mismatch",
                f"{path}.rounding_residual_local",
                "the conversion residual must tie exact amount to reported amount",
            )
        fx, rate = _fx_reference(
            event.to_currency,
            base_currency,
            book,
            request.valuation_at,
            path=f"{path}.fx_rate_id",
        )
        residual_base = _exact_product(event.residual, rate)
        conversion_rounding_base += residual_base
        conversion_rows.append(
            AnalyticsConversionRow(
                rate_id=event.rate_id,
                from_bucket_id=event.from_bucket_id,
                to_bucket_id=event.to_bucket_id,
                from_currency=event.from_currency,
                to_currency=event.to_currency,
                source_amount=canonical_decimal(
                    event.source_amount,
                    MONEY_SPEC,
                    f"{path}.source_amount",
                ),
                rate=_rate_text(event.rate, f"{path}.rate"),
                exact_converted=_exact_text(
                    event.exact_converted,
                    f"{path}.exact_converted",
                ),
                converted_amount=canonical_decimal(
                    event.converted_amount,
                    MONEY_SPEC,
                    f"{path}.converted_amount",
                ),
                rounding_residual_local=_exact_text(
                    event.residual,
                    f"{path}.rounding_residual_local",
                ),
                valuation_fx=fx,
                rounding_residual_base=_exact_text(
                    residual_base,
                    f"{path}.rounding_residual_base",
                ),
            )
        )

    currency_exposures = _currency_exposures(
        bucket_exposures,
        nav_base=nav_base,
    )
    market_exposures = _market_exposures(bucket_exposures, nav_base=nav_base)
    sector_exposures = _sector_exposures(
        request,
        ledger,
        position_rows,
        position_value_base=position_value_base,
    )
    concentration = _concentration(position_rows, nav_base=nav_base)

    if _exact_sum(Decimal(row.value_base) for row in currency_exposures) != nav_base:
        _invariant("analytics_currency_nav_mismatch", "analytics.currency_exposures")
    if _exact_sum(Decimal(row.value_base) for row in market_exposures) != nav_base:
        _invariant("analytics_market_nav_mismatch", "analytics.market_exposures")
    if _exact_sum(Decimal(row.value_base) for row in sector_exposures) != (
        position_value_base
    ):
        _invariant("analytics_sector_value_mismatch", "analytics.sector_exposures")

    warnings: tuple[str, ...] = ()
    if nav_base <= 0:
        warnings = (
            "portfolio NAV is not positive; position weights and concentration are reported as zero",
        )

    return PortfolioAnalytics(
        base_currency=base_currency,
        valuation_at=request.valuation_at,
        nav_base=canonical_decimal(nav_base, MONEY_SPEC, "analytics.nav_base"),
        cash_base=canonical_decimal(cash_base, MONEY_SPEC, "analytics.cash_base"),
        position_value_base=canonical_decimal(
            position_value_base,
            MONEY_SPEC,
            "analytics.position_value_base",
        ),
        valuation_rounding=canonical_decimal(
            valuation_rounding,
            MONEY_SPEC,
            "analytics.valuation_rounding",
        ),
        exact_nav_base=_exact_text(exact_nav_base, "analytics.exact_nav_base"),
        rounding_residual=_exact_text(
            exact_nav_base - nav_base,
            "analytics.rounding_residual",
        ),
        nav_bridge=AnalyticsNavBridge(
            cash_base=canonical_decimal(
                cash_base,
                MONEY_SPEC,
                "analytics.nav_bridge.cash_base",
            ),
            position_value_base=canonical_decimal(
                position_value_base,
                MONEY_SPEC,
                "analytics.nav_bridge.position_value_base",
            ),
            valuation_rounding=canonical_decimal(
                valuation_rounding,
                MONEY_SPEC,
                "analytics.nav_bridge.valuation_rounding",
            ),
            nav_base=canonical_decimal(
                nav_base,
                MONEY_SPEC,
                "analytics.nav_bridge.nav_base",
            ),
            exact_nav_base=_exact_text(
                exact_nav_base,
                "analytics.nav_bridge.exact_nav_base",
            ),
            rounding_residual=_exact_text(
                exact_nav_base - nav_base,
                "analytics.nav_bridge.rounding_residual",
            ),
            conversion_rounding_base=_exact_text(
                conversion_rounding_base,
                "analytics.nav_bridge.conversion_rounding_base",
            ),
        ),
        cash_rows=tuple(cash_rows),
        position_rows=position_rows,
        conversion_rows=tuple(conversion_rows),
        bucket_exposures=tuple(bucket_exposures),
        currency_exposures=currency_exposures,
        market_exposures=market_exposures,
        concentration=concentration,
        sector_exposures=sector_exposures,
        provenance=_provenance(
            (row.mark.price_date for row in position_rows),
            (
                reference
                for row in (*cash_rows, *position_rows)
                for reference in (row.fx,)
            ),
        ),
        warnings=warnings,
    )
