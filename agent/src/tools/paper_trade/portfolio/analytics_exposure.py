"""Valuation marks, provenance and exposure roll-ups for portfolio analytics.

Indexes exactly the prepared marks, applies caller sectors verbatim with an
explicit ``unclassified`` bucket, and derives currency/market/sector exposure
and concentration from the published position rows.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date
from decimal import Decimal

from .analytics_common import (
    _UNCLASSIFIED,
    _ZERO_WEIGHT,
    _Mark,
    _exact_sum,
    _invariant,
    _ratio,
    _reject,
    _weight,
)
from .data import PreparedPortfolioData, PriorMarkValuation, TargetBarValuation
from .ledger import PortfolioLedger
from .models import (
    AnalyticsBucketExposure,
    AnalyticsCashRow,
    AnalyticsConcentration,
    AnalyticsCurrencyExposure,
    AnalyticsFxReference,
    AnalyticsMarketExposure,
    AnalyticsPositionRow,
    AnalyticsPositionWeight,
    AnalyticsProvenance,
    AnalyticsSectorExposure,
    Currency,
    Market,
    PortfolioRequest,
)
from .numeric import MONEY_SPEC, WEIGHT_SPEC, canonical_decimal, parse_price


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
