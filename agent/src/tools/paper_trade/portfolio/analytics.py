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

The optional attribution document is the same one-day ledger replay expressed
as symbol, market and currency contributions, explicit conversion and fee
effects, and a separately computed two-decimal execution-notional rounding
residual. It is not Brinson allocation/selection/interaction, not sector
attribution and not multi-day period attribution; caller targets are published
only as declared target weights, never as promised executions.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal, localcontext
from typing import Final, NoReturn

from .data import (
    PreparedPortfolioData,
    PriorMarkValuation,
    TargetBarValuation,
)
from .fx import FxConversionEvent, FxRateBook
from .ledger import PortfolioLedger, value_ledger
from .models import (
    AnalyticsAttribution,
    AnalyticsAttributionNav,
    AnalyticsAttributionReconciliation,
    AnalyticsBenchmark,
    AnalyticsBenchmarkObservation,
    AnalyticsBucketExposure,
    AnalyticsCashFxEffect,
    AnalyticsCashRow,
    AnalyticsConcentration,
    AnalyticsConversionEffect,
    AnalyticsConversionRow,
    AnalyticsCurrencyContribution,
    AnalyticsCurrencyExposure,
    AnalyticsExecutionRounding,
    AnalyticsFeeEffect,
    AnalyticsFxReference,
    AnalyticsMarketContribution,
    AnalyticsMarketExposure,
    AnalyticsMarkReference,
    AnalyticsNavBridge,
    AnalyticsPositionRow,
    AnalyticsPositionWeight,
    AnalyticsProvenance,
    AnalyticsReconciliationCheck,
    AnalyticsSectorExposure,
    AnalyticsSymbolContribution,
    AnalyticsWeightReconciliation,
    AnalyticsWeightRow,
    BenchmarkObservation,
    Currency,
    Market,
    PortfolioAnalytics,
    PortfolioIssue,
    PortfolioRequest,
)
from .numeric import (
    FX_RATE_SPEC,
    MONEY_SPEC,
    PRICE_SPEC,
    WEIGHT_SPEC,
    DecimalSpec,
    canonical_decimal,
    parse_price,
)
from .orchestrator import (
    ExecutionCancellation,
    ExecutionFill,
    ExecutionRejection,
    OrchestrationError,
)
from .order_plan import OrderPlan
from .schema import PortfolioRequestError

__all__ = ["build_portfolio_analytics", "reconcile_attribution"]

_EXACT_PRECISION: Final = 60
_UNCLASSIFIED: Final = "unclassified"
_ZERO_WEIGHT: Final = Decimal(0)
_RETURN_SPEC: Final = DecimalSpec(scale=12)
_SIGNED_WEIGHT_SPEC: Final = DecimalSpec(
    scale=12,
    minimum=Decimal(-1),
    maximum=Decimal(1),
)
_WEIGHT_SUM_SPEC: Final = DecimalSpec(
    scale=12,
    minimum=Decimal(-10),
    maximum=Decimal(10),
)
_WEIGHT_QUANTUM: Final = Decimal("0.000000000001")
_WEIGHT_HALF_QUANTUM: Final = _WEIGHT_QUANTUM / 2
_ATTRIBUTION_NOT_VERIFIED: Final = (
    "caller-supplied planning and valuation marks are not re-fetched or compared "
    "with an independent market source",
    "execution prices are checked against the prepared target-day snapshot, not a "
    "broker or venue feed",
    "caller targets are declarations; realized weights are end-ledger valuations and "
    "are not promised target executions",
    "sector allocation/selection, Brinson attribution and multi-day period "
    "attribution are out of scope",
)
_BENCHMARK_MAX_AGE: Final = timedelta(days=1)


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


def _return_value(value: Decimal, path: str) -> Decimal:
    """Render a signed one-day return/deviation at the weight scale."""
    with localcontext() as context:
        context.prec = _EXACT_PRECISION
        quantized = value.quantize(Decimal(1).scaleb(-12), rounding=ROUND_HALF_EVEN)
    if quantized.is_zero():
        quantized = Decimal(0)
    return Decimal(canonical_decimal(quantized, _RETURN_SPEC, path))


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


def _exact_change(numerator: Decimal, denominator: Decimal) -> Decimal:
    """Return ``numerator / denominator - 1`` at the module's exact precision."""
    with localcontext() as context:
        context.prec = _EXACT_PRECISION
        return numerator / denominator - 1


def _exact_difference(left: Decimal, right: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = _EXACT_PRECISION
        return left - right


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


def _planning_mark_values(prepared: PreparedPortfolioData) -> dict[str, Decimal]:
    """Read the same strictly-prior planning marks the planner already used."""
    values: dict[str, Decimal] = {}
    for bucket in prepared.buckets:
        for bar in bucket.planning.bars:
            path = f"benchmark.portfolio_start_marks.{bucket.bucket_id}.{bar.symbol}"
            if bar.symbol in values:
                _invariant("duplicate_planning_mark", path)
            values[bar.symbol] = parse_price(bar.close, path)
    return values


def _benchmark_observation(
    observation: BenchmarkObservation,
    base_currency: Currency,
    book: FxRateBook,
    *,
    path: str,
) -> tuple[AnalyticsBenchmarkObservation, Decimal]:
    """Translate one declared level through its own direct pair, never an inverse."""
    observed_at = observation.observed_at
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        _reject(
            "invalid_benchmark_timestamp",
            f"{path}.observed_at",
            detail="benchmark timestamps need an explicit UTC offset",
        )
    try:
        value = parse_price(observation.value, f"{path}.value")
    except PortfolioRequestError as exc:
        _reject(
            "invalid_benchmark_value",
            f"{path}.value",
            detail=f"benchmark levels must be positive prices ({exc.reason})",
        )
    if observation.currency == base_currency:
        if observation.rate_id is not None:
            _reject(
                "unexpected_benchmark_fx_rate",
                f"{path}.rate_id",
                detail="a base-currency observation needs no translation pair",
            )
        rate = Decimal(1)
        fx = AnalyticsFxReference(
            rate_id=f"identity:{base_currency}",
            from_currency=observation.currency,
            to_currency=base_currency,
            rate=_rate_text(rate, f"{path}.rate"),
            as_of=observed_at,
            source="base_currency_identity",
        )
    else:
        if observation.rate_id is None:
            _reject(
                "missing_benchmark_fx_rate",
                f"{path}.rate_id",
                detail="a non-base benchmark level must name its direct pair",
            )
        rate_row = book.require_direct(
            observation.currency,
            base_currency,
            path=f"{path}.rate_id",
            rate_id=observation.rate_id,
        )
        if rate_row.as_of > observed_at:
            _reject(
                "future_fx_rate",
                f"{path}.rate_id",
                detail="the benchmark rate is later than its observation",
            )
        rate = rate_row.rate
        fx = AnalyticsFxReference(
            rate_id=rate_row.rate_id,
            from_currency=rate_row.from_currency,
            to_currency=rate_row.to_currency,
            rate=_rate_text(rate, f"{path}.rate"),
            as_of=rate_row.as_of,
            source=rate_row.source,
        )
    exact_value_base = _exact_product(value, rate)
    value_base = _money(exact_value_base, f"{path}.value_base")
    row = AnalyticsBenchmarkObservation(
        observed_at=observed_at,
        value=_price_text(value, f"{path}.value"),
        currency=observation.currency,
        value_base=canonical_decimal(value_base, MONEY_SPEC, f"{path}.value_base"),
        exact_value_base=_exact_text(exact_value_base, f"{path}.exact_value_base"),
        rounding_residual=_exact_text(
            _exact_difference(exact_value_base, value_base),
            f"{path}.rounding_residual",
        ),
        fx=fx,
    )
    return row, exact_value_base


def _benchmark(
    request: PortfolioRequest,
    *,
    opening_ledger: PortfolioLedger | None,
    prepared: PreparedPortfolioData,
    base_currency: Currency,
    book: FxRateBook,
    nav_base: Decimal,
    exact_nav_base: Decimal,
) -> AnalyticsBenchmark | None:
    """Build the optional one-day benchmark projection or return ``None``."""
    declared = request.benchmark
    if declared is None:
        return None
    start, start_value_base = _benchmark_observation(
        declared.start,
        base_currency,
        book,
        path="benchmark.start",
    )
    end, end_value_base = _benchmark_observation(
        declared.end,
        base_currency,
        book,
        path="benchmark.end",
    )
    if declared.start.currency != declared.end.currency:
        _reject(
            "benchmark_currency_mismatch",
            "benchmark.end.currency",
            detail="one benchmark declares one currency across both observations",
        )
    if declared.start.observed_at >= declared.end.observed_at:
        _reject(
            "invalid_benchmark_observation_order",
            "benchmark.end.observed_at",
            detail="the end observation must follow the start observation",
        )
    if declared.end.observed_at > request.valuation_at:
        _reject(
            "future_benchmark_observation",
            "benchmark.end.observed_at",
            detail="the benchmark end observation is later than valuation_at",
        )
    if declared.end.observed_at.astimezone(timezone.utc).date() != request.trade_date:
        _reject(
            "stale_benchmark_observation",
            "benchmark.end.observed_at",
            detail="the benchmark end observation is not dated the trade date",
        )
    if request.valuation_at - declared.end.observed_at > _BENCHMARK_MAX_AGE:
        _reject(
            "stale_benchmark_observation",
            "benchmark.end.observed_at",
            detail="the benchmark end observation is older than one day",
        )
    if opening_ledger is None:
        _invariant(
            "missing_benchmark_opening_ledger",
            "benchmark.portfolio_start_nav_base",
        )
    planning_book = FxRateBook.from_snapshots(
        request.fx_snapshots,
        at=request.planning_at,
    )
    start_bridge = value_ledger(
        opening_ledger,
        _planning_mark_values(prepared),
        planning_book,
        base_currency=base_currency,
        path="benchmark.portfolio_start_marks",
    )
    start_nav_base = start_bridge.total.reported_base
    start_exact_nav_base = start_bridge.total.exact_base
    start_residual = _exact_difference(start_exact_nav_base, start_nav_base)
    if start_nav_base + start_residual != start_exact_nav_base:
        _invariant(
            "benchmark_start_nav_mismatch",
            "benchmark.portfolio_start_rounding_residual",
        )
    if start_nav_base <= 0 or start_exact_nav_base <= 0:
        _reject(
            "nonpositive_benchmark_start_nav",
            "benchmark.portfolio_start_nav_base",
            detail="a one-day portfolio return needs a positive prior NAV",
        )
    exact_benchmark_return = _exact_change(end_value_base, start_value_base)
    exact_portfolio_return = _exact_change(exact_nav_base, start_exact_nav_base)
    exact_deviation = _exact_difference(exact_portfolio_return, exact_benchmark_return)
    return AnalyticsBenchmark(
        benchmark_id=declared.benchmark_id,
        start=start,
        end=end,
        benchmark_return=canonical_decimal(
            _return_value(exact_benchmark_return, "benchmark.benchmark_return"),
            _RETURN_SPEC,
            "benchmark.benchmark_return",
        ),
        exact_benchmark_return=_exact_text(
            exact_benchmark_return,
            "benchmark.exact_benchmark_return",
        ),
        portfolio_start_nav_base=canonical_decimal(
            start_nav_base,
            MONEY_SPEC,
            "benchmark.portfolio_start_nav_base",
        ),
        portfolio_start_exact_nav_base=_exact_text(
            start_exact_nav_base,
            "benchmark.portfolio_start_exact_nav_base",
        ),
        portfolio_start_rounding_residual=_exact_text(
            start_residual,
            "benchmark.portfolio_start_rounding_residual",
        ),
        portfolio_end_nav_base=canonical_decimal(
            nav_base,
            MONEY_SPEC,
            "benchmark.portfolio_end_nav_base",
        ),
        portfolio_end_exact_nav_base=_exact_text(
            exact_nav_base,
            "benchmark.portfolio_end_exact_nav_base",
        ),
        portfolio_return=canonical_decimal(
            _return_value(exact_portfolio_return, "benchmark.portfolio_return"),
            _RETURN_SPEC,
            "benchmark.portfolio_return",
        ),
        exact_portfolio_return=_exact_text(
            exact_portfolio_return,
            "benchmark.exact_portfolio_return",
        ),
        deviation=canonical_decimal(
            _return_value(exact_deviation, "benchmark.deviation"),
            _RETURN_SPEC,
            "benchmark.deviation",
        ),
        exact_deviation=_exact_text(exact_deviation, "benchmark.exact_deviation"),
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


def _signed_weight_value(value: Decimal, path: str) -> Decimal:
    return Decimal(_signed_weight(value, path))


def _signed_weight(value: Decimal, path: str) -> str:
    if value.is_zero():
        value = Decimal(0)
    return canonical_decimal(value, _SIGNED_WEIGHT_SPEC, path)


def _weight_sum(value: Decimal, path: str) -> str:
    if value.is_zero():
        value = Decimal(0)
    return canonical_decimal(value, _WEIGHT_SUM_SPEC, path)


def _weight_rounding_tolerance(row_count: int) -> Decimal:
    return _WEIGHT_HALF_QUANTUM * Decimal(row_count + 2) + _WEIGHT_QUANTUM


def _execution_notional(value: Decimal) -> Decimal:
    """Reproduce the execution adapter's 2dp ROUND_HALF_UP cash notional."""
    with localcontext() as context:
        context.prec = _EXACT_PRECISION
        return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _mark_reference(mark: _Mark) -> AnalyticsMarkReference:
    return AnalyticsMarkReference(
        price_date=mark.price_date,
        source=mark.source,
        as_of=mark.as_of,
    )


def _planning_mark_meta(prepared: PreparedPortfolioData) -> dict[str, _Mark]:
    marks: dict[str, _Mark] = {}
    for bucket in prepared.buckets:
        for bar in bucket.planning.bars:
            path = f"attribution.planning_marks.{bucket.bucket_id}.{bar.symbol}"
            if bar.symbol in marks:
                _invariant("duplicate_planning_mark", path)
            marks[bar.symbol] = _Mark(
                price=parse_price(bar.close, path),
                price_date=bucket.planning.price_date,
                source=bucket.planning.source,
                as_of=bucket.planning.as_of,
            )
    return marks


def _position_quantities(ledger: PortfolioLedger) -> dict[tuple[str, str], int]:
    return {
        (bucket.bucket_id, position.symbol): position.qty
        for bucket in ledger.buckets
        for position in bucket.positions
    }


def _attribution_issue(
    reason: str,
    path: str,
    detail: str,
    *,
    bucket_id: str | None = None,
) -> PortfolioIssue:
    return PortfolioIssue(
        reason=reason,
        path=path,
        detail=detail,
        bucket_id=bucket_id,
    )


def _merge_issues(rows: Iterable[PortfolioIssue]) -> tuple[PortfolioIssue, ...]:
    unique: dict[tuple[str, str, str, str | None], PortfolioIssue] = {}
    for row in rows:
        key = (row.reason, row.path, row.detail, row.bucket_id)
        unique.setdefault(key, row)
    return tuple(unique.values())


def _attribution(
    request: PortfolioRequest,
    *,
    prepared: PreparedPortfolioData,
    opening_ledger: PortfolioLedger,
    post_conversion_ledger: PortfolioLedger,
    end_ledger: PortfolioLedger,
    conversion_events: Sequence[FxConversionEvent],
    fills: Sequence[ExecutionFill],
    rejected_orders: Sequence[ExecutionRejection],
    canceled_orders: Sequence[ExecutionCancellation],
    plan: OrderPlan,
    cash_rows: Sequence[AnalyticsCashRow],
    position_rows: Sequence[AnalyticsPositionRow],
    valuation_rounding: Decimal,
    nav_base: Decimal,
    exact_nav_base: Decimal,
    book: FxRateBook,
    marks: dict[str, dict[str, _Mark]],
) -> AnalyticsAttribution:
    """Build the exact one-day NAV bridge and weight tie-out.

    The bridge uses only declared ledger events: opening cash and positions at
    strictly-prior planning marks and planning FX, settled conversions, the
    execution adapter's fills, the ending ledger at valuation marks and FX, and
    a separately computed two-decimal execution-notional rounding residual.
    Attribution-specific disagreements are published as issues; they are never
    absorbed into the residual.
    """
    base_currency = request.base_currency
    issues: list[PortfolioIssue] = []
    checks: list[AnalyticsReconciliationCheck] = []
    planning_marks = _planning_mark_meta(prepared)
    planning_prices = {symbol: mark.price for symbol, mark in planning_marks.items()}
    planning_book = FxRateBook.from_snapshots(
        request.fx_snapshots,
        at=request.planning_at,
    )
    start_bridge = value_ledger(
        opening_ledger,
        planning_prices,
        planning_book,
        base_currency=base_currency,
        path="attribution.planning_marks",
    )
    planning_bridge = value_ledger(
        post_conversion_ledger,
        planning_prices,
        planning_book,
        base_currency=base_currency,
        path="attribution.planning_marks",
    )
    start_nav = start_bridge.total.reported_base
    start_exact = start_bridge.total.exact_base
    planning_nav = planning_bridge.total.reported_base
    planning_exact = planning_bridge.total.exact_base

    end_buckets = {bucket.bucket_id: bucket for bucket in end_ledger.buckets}
    opening_buckets = {bucket.bucket_id: bucket for bucket in opening_ledger.buckets}
    post_buckets = {
        bucket.bucket_id: bucket for bucket in post_conversion_ledger.buckets
    }
    if set(opening_buckets) != set(end_buckets) or set(post_buckets) != set(end_buckets):
        issues.append(
            _attribution_issue(
                "attribution_bucket_set_mismatch",
                "attribution.buckets",
                "opening, post-conversion and ending ledgers must name the same buckets",
            )
        )

    planning_rates: dict[str, tuple[AnalyticsFxReference, Decimal]] = {}
    valuation_rates: dict[str, tuple[AnalyticsFxReference, Decimal]] = {}
    for bucket_id, bucket in end_buckets.items():
        planning_rates[bucket_id] = _fx_reference(
            bucket.currency,
            base_currency,
            planning_book,
            request.planning_at,
            path=f"attribution.cash_fx.{bucket_id}.opening_rate",
        )
        valuation_rates[bucket_id] = _fx_reference(
            bucket.currency,
            base_currency,
            book,
            request.valuation_at,
            path=f"attribution.cash_fx.{bucket_id}.ending_rate",
        )
    for bucket_id, bucket in opening_buckets.items():
        end_bucket = end_buckets.get(bucket_id)
        if end_bucket is not None and (
            end_bucket.currency != bucket.currency
            or end_bucket.market != bucket.market
        ):
            issues.append(
                _attribution_issue(
                    "attribution_bucket_identity_mismatch",
                    f"attribution.buckets.{bucket_id}",
                    "a bucket's market and currency must be stable across the day",
                    bucket_id=bucket_id,
                )
            )

    # Cash FX is valued on opening cash only; conversion and fill cash already
    # exist at the valuation instant and are valued there exactly once.
    cash_fx_rows: list[AnalyticsCashFxEffect] = []
    cash_fx_total = Decimal(0)
    for bucket_id in sorted(end_buckets):
        bucket = end_buckets[bucket_id]
        opening = opening_buckets.get(bucket_id)
        opening_cash = opening.cash if opening is not None else Decimal(0)
        opening_ref, opening_rate = planning_rates[bucket_id]
        ending_ref, ending_rate = valuation_rates[bucket_id]
        effect = _exact_product(
            opening_cash,
            _exact_difference(ending_rate, opening_rate),
        )
        cash_fx_total = _exact_sum((cash_fx_total, effect))
        cash_fx_rows.append(
            AnalyticsCashFxEffect(
                bucket_id=bucket_id,
                market=bucket.market,
                currency=bucket.currency,
                opening_cash=canonical_decimal(
                    opening_cash,
                    MONEY_SPEC,
                    f"attribution.cash_fx.{bucket_id}.opening_cash",
                ),
                ending_cash=canonical_decimal(
                    bucket.cash,
                    MONEY_SPEC,
                    f"attribution.cash_fx.{bucket_id}.ending_cash",
                ),
                opening_fx=opening_ref,
                ending_fx=ending_ref,
                cash_fx_effect_base=_exact_text(
                    effect,
                    f"attribution.cash_fx.{bucket_id}.effect",
                ),
            )
        )

    conversion_effects: list[AnalyticsConversionEffect] = []
    conversion_total = Decimal(0)
    for index, event in enumerate(conversion_events):
        path = f"attribution.conversions[{index}]"
        source_bucket = end_buckets.get(event.from_bucket_id)
        target_bucket = end_buckets.get(event.to_bucket_id)
        if source_bucket is None or target_bucket is None:
            issues.append(
                _attribution_issue(
                    "attribution_conversion_bucket_mismatch",
                    path,
                    "a conversion must name two declared buckets",
                )
            )
        else:
            if (
                source_bucket.currency != event.from_currency
                or target_bucket.currency != event.to_currency
            ):
                issues.append(
                    _attribution_issue(
                        "attribution_conversion_bucket_mismatch",
                        path,
                        "the event currency disagrees with its bucket currency",
                    )
                )
        source_ref, source_rate = _fx_reference(
            event.from_currency,
            base_currency,
            book,
            request.valuation_at,
            path=f"{path}.source_rate",
        )
        target_ref, target_rate = _fx_reference(
            event.to_currency,
            base_currency,
            book,
            request.valuation_at,
            path=f"{path}.target_rate",
        )
        expected_exact = _exact_product(event.source_amount, event.rate)
        expected_residual = _exact_difference(
            event.exact_converted,
            event.converted_amount,
        )
        if event.exact_converted != expected_exact:
            issues.append(
                _attribution_issue(
                    "attribution_conversion_math_mismatch",
                    f"{path}.exact_converted",
                    "exact_converted must equal source_amount * rate",
                )
            )
        if event.residual != expected_residual:
            issues.append(
                _attribution_issue(
                    "attribution_conversion_math_mismatch",
                    f"{path}.rounding_residual_local",
                    "the conversion residual must tie exact to converted",
                )
            )
        source_effect = _exact_product(
            -event.source_amount,
            source_rate,
        )
        target_effect = _exact_product(event.converted_amount, target_rate)
        effect = _exact_sum((source_effect, target_effect))
        conversion_total = _exact_sum((conversion_total, effect))
        conversion_effects.append(
            AnalyticsConversionEffect(
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
                source_fx=source_ref,
                target_fx=target_ref,
                source_effect_base=_exact_text(
                    source_effect,
                    f"{path}.source_effect_base",
                ),
                target_effect_base=_exact_text(
                    target_effect,
                    f"{path}.target_effect_base",
                ),
                conversion_effect_base=_exact_text(
                    effect,
                    f"{path}.conversion_effect_base",
                ),
                rounding_loss_base=_exact_text(
                    -_exact_product(expected_residual, target_rate),
                    f"{path}.rounding_loss_base",
                ),
            )
        )

    fee_effects: list[AnalyticsFeeEffect] = []
    rounding_rows: list[AnalyticsExecutionRounding] = []
    fee_total = Decimal(0)
    expected_rounding = Decimal(0)
    trade_cash: dict[tuple[str, str], Decimal] = {}
    fills_by_key: dict[tuple[str, str], list[ExecutionFill]] = {}
    for fill in fills:
        fills_by_key.setdefault((fill.bucket_id, fill.symbol), []).append(fill)

    for index, fill in enumerate(fills):
        path = f"attribution.fills[{index}]"
        rate_pair = valuation_rates.get(fill.bucket_id)
        bucket = end_buckets.get(fill.bucket_id)
        if rate_pair is None or bucket is None:
            issues.append(
                _attribution_issue(
                    "attribution_fill_bucket_mismatch",
                    path,
                    "a fill must name a declared ending bucket",
                    bucket_id=fill.bucket_id,
                )
            )
            ref, rate = _fx_reference(
                fill.currency,
                base_currency,
                book,
                request.valuation_at,
                path=f"{path}.fx",
            )
        else:
            ref, rate = rate_pair
            if bucket.currency != fill.currency:
                issues.append(
                    _attribution_issue(
                        "attribution_fill_currency_mismatch",
                        path,
                        "a fill's currency must equal its bucket currency",
                        bucket_id=fill.bucket_id,
                    )
                )
        exact_notional = _exact_product(Decimal(fill.qty), fill.price)
        notional = _execution_notional(exact_notional)
        rounding = _exact_difference(exact_notional, notional)
        signed_rounding = rounding if fill.side == "buy" else -rounding
        rounding_base = _exact_product(signed_rounding, rate)
        expected_rounding = _exact_sum((expected_rounding, rounding_base))
        fee_effect = _exact_product(-fill.fee, rate)
        fee_total = _exact_sum((fee_total, fee_effect))
        fee_effects.append(
            AnalyticsFeeEffect(
                plan_order_id=fill.plan_order_id,
                bucket_id=fill.bucket_id,
                symbol=fill.symbol,
                side=fill.side,
                qty=fill.qty,
                execution_price=_price_text(fill.price, f"{path}.price"),
                fee_local=canonical_decimal(
                    fill.fee,
                    MONEY_SPEC,
                    f"{path}.fee_local",
                ),
                fx=ref,
                fee_effect_base=_exact_text(fee_effect, f"{path}.fee_effect_base"),
            )
        )
        rounding_rows.append(
            AnalyticsExecutionRounding(
                plan_order_id=fill.plan_order_id,
                bucket_id=fill.bucket_id,
                symbol=fill.symbol,
                side=fill.side,
                qty=fill.qty,
                execution_price=_price_text(fill.price, f"{path}.price"),
                exact_notional_local=_exact_text(
                    exact_notional,
                    f"{path}.exact_notional",
                ),
                notional_local=canonical_decimal(
                    notional,
                    MONEY_SPEC,
                    f"{path}.notional_local",
                ),
                rounding_local=_exact_text(rounding, f"{path}.rounding_local"),
                fx=ref,
                rounding_effect_base=_exact_text(
                    rounding_base,
                    f"{path}.rounding_effect_base",
                ),
            )
        )
        key = (fill.bucket_id, fill.symbol)
        signed_notional = (
            -exact_notional if fill.side == "buy" else exact_notional
        )
        trade_cash[key] = _exact_sum(
            (trade_cash.get(key, Decimal(0)), _exact_product(signed_notional, rate))
        )

    # Execution prices and valuation marks must agree with the prepared
    # target-day snapshot. A changed mark or fill cannot pass unnoticed.
    execution_closes: dict[str, dict[str, Decimal]] = {}
    for bucket in prepared.buckets:
        if bucket.execution is None:
            continue
        execution_closes[bucket.bucket_id] = {
            bar.symbol: parse_price(
                bar.close,
                f"attribution.execution_marks.{bucket.bucket_id}.{bar.symbol}",
            )
            for bar in bucket.execution.bars
        }
        if isinstance(bucket.valuation, TargetBarValuation):
            execution_map = execution_closes[bucket.bucket_id]
            for bar in bucket.valuation.snapshot.bars:
                close = execution_map.get(bar.symbol)
                if close is None:
                    continue
                valuation_close = parse_price(
                    bar.close,
                    f"attribution.valuation_marks.{bucket.bucket_id}.{bar.symbol}",
                )
                if close != valuation_close:
                    issues.append(
                        _attribution_issue(
                            "attribution_valuation_execution_mark_mismatch",
                            f"attribution.valuation_marks.{bucket.bucket_id}.{bar.symbol}",
                            "the valuation close disagrees with the execution snapshot",
                            bucket_id=bucket.bucket_id,
                        )
                    )
    for index, fill in enumerate(fills):
        closes = execution_closes.get(fill.bucket_id)
        if closes is None:
            continue
        close = closes.get(fill.symbol)
        if close is None or close != fill.price:
            issues.append(
                _attribution_issue(
                    "attribution_fill_price_mark_mismatch",
                    f"attribution.fills[{index}].price",
                    "the fill price disagrees with the prepared execution close",
                    bucket_id=fill.bucket_id,
                )
            )

    # Replay conversions and fills against the actual ledgers without ever
    # adjusting the ending state to make the bridge balance.
    conversion_cash = {
        bucket_id: bucket.cash for bucket_id, bucket in opening_buckets.items()
    }
    conversion_ok = True
    for event in conversion_events:
        if (
            event.from_bucket_id not in conversion_cash
            or event.to_bucket_id not in conversion_cash
        ):
            conversion_ok = False
            continue
        conversion_cash[event.from_bucket_id] = _exact_sum(
            (
                conversion_cash[event.from_bucket_id],
                -event.source_amount,
            )
        )
        conversion_cash[event.to_bucket_id] = _exact_sum(
            (
                conversion_cash[event.to_bucket_id],
                event.converted_amount,
            )
        )
    for bucket_id, bucket in post_buckets.items():
        if conversion_cash.get(bucket_id) != bucket.cash:
            conversion_ok = False
            issues.append(
                _attribution_issue(
                    "attribution_conversion_replay_mismatch",
                    f"attribution.conversions.{bucket_id}",
                    "opening cash plus conversions does not equal post-conversion cash",
                    bucket_id=bucket_id,
                )
            )
    checks.append(
        AnalyticsReconciliationCheck(
            name="conversion_replay",
            passed=conversion_ok,
            detail="opening cash plus settled conversions equals the post-conversion ledger",
        )
    )

    fill_cash = {
        bucket_id: bucket.cash for bucket_id, bucket in post_buckets.items()
    }
    fill_qty = _position_quantities(post_conversion_ledger)
    fill_replay_ok = True
    for fill in fills:
        if fill.bucket_id not in fill_cash:
            fill_replay_ok = False
            continue
        exact_notional = _exact_product(Decimal(fill.qty), fill.price)
        notional = _execution_notional(exact_notional)
        delta = (
            _exact_difference(notional, fill.fee)
            if fill.side == "sell"
            else _exact_sum((notional, fill.fee))
        )
        if fill.side == "buy":
            delta = -delta
        fill_cash[fill.bucket_id] = _exact_sum((fill_cash[fill.bucket_id], delta))
        key = (fill.bucket_id, fill.symbol)
        qty_delta = fill.qty if fill.side == "buy" else -fill.qty
        fill_qty[key] = fill_qty.get(key, 0) + qty_delta
    for bucket_id, bucket in end_buckets.items():
        if fill_cash.get(bucket_id) != bucket.cash:
            fill_replay_ok = False
            issues.append(
                _attribution_issue(
                    "attribution_fill_replay_mismatch",
                    f"attribution.fills.{bucket_id}.cash",
                    "post-conversion cash plus fills does not equal ending cash",
                    bucket_id=bucket_id,
                )
            )
    end_qty = _position_quantities(end_ledger)
    for key in sorted(set(fill_qty) | set(end_qty)):
        if fill_qty.get(key, 0) != end_qty.get(key, 0):
            fill_replay_ok = False
            issues.append(
                _attribution_issue(
                    "attribution_fill_replay_mismatch",
                    f"attribution.fills.{key[0]}.{key[1]}.qty",
                    "post-conversion quantities plus fills do not equal ending quantities",
                    bucket_id=key[0],
                )
            )
    checks.append(
        AnalyticsReconciliationCheck(
            name="fill_replay",
            passed=fill_replay_ok,
            detail="post-conversion cash and quantities plus fills equal the ending ledger",
        )
    )

    opening_qty = _position_quantities(opening_ledger)
    bucket_rank = {
        bucket_id: index for index, bucket_id in enumerate(end_buckets)
    }
    keys = sorted(
        set(opening_qty)
        | set(end_qty)
        | {(row.bucket_id, row.symbol) for row in plan.weights},
        key=lambda key: (bucket_rank.get(key[0], len(bucket_rank)), key[0], key[1]),
    )
    symbol_rows: list[AnalyticsSymbolContribution] = []
    symbol_by_key: dict[tuple[str, str], AnalyticsSymbolContribution] = {}
    for bucket_id, symbol in keys:
        bucket = end_buckets.get(bucket_id) or opening_buckets.get(bucket_id)
        if bucket is None:
            issues.append(
                _attribution_issue(
                    "attribution_position_bucket_mismatch",
                    f"attribution.positions.{bucket_id}.{symbol}",
                    "a position bucket is absent from the ending ledger",
                    bucket_id=bucket_id,
                )
            )
            continue
        opening_mark = planning_marks.get(symbol)
        if opening_mark is None:
            _reject(
                "missing_planning_mark",
                f"attribution.planning_marks.{symbol}",
                bucket_id=bucket_id,
                detail="every attributed instrument needs a strict prior planning mark",
            )
        end_mark = marks.get(bucket_id, {}).get(symbol)
        key_fills = fills_by_key.get((bucket_id, symbol), [])
        if end_mark is None:
            if key_fills:
                last_fill = key_fills[-1]
                end_mark = _Mark(
                    price=last_fill.price,
                    price_date=last_fill.trade_date,
                    source="execution_fill",
                    as_of=request.valuation_at,
                )
            else:
                end_mark = opening_mark
        if end_qty.get((bucket_id, symbol), 0) > 0 and end_mark is None:
            _reject(
                "missing_valuation_mark",
                f"attribution.valuation_marks.{bucket_id}.{symbol}",
                bucket_id=bucket_id,
            )
        opening_ref, opening_rate = planning_rates[bucket_id]
        ending_ref, ending_rate = valuation_rates[bucket_id]
        opening_units = opening_qty.get((bucket_id, symbol), 0)
        ending_units = end_qty.get((bucket_id, symbol), 0)
        traded = sum(
            fill.qty if fill.side == "buy" else -fill.qty for fill in key_fills
        )
        opening_local = _exact_product(Decimal(opening_units), opening_mark.price)
        ending_local = _exact_product(Decimal(ending_units), end_mark.price)
        opening_value = _exact_product(opening_local, opening_rate)
        ending_value = _exact_product(ending_local, ending_rate)
        currency_effect = _exact_product(
            opening_local,
            _exact_difference(ending_rate, opening_rate),
        )
        trade_base = trade_cash.get((bucket_id, symbol), Decimal(0))
        market_effect = _exact_sum(
            (
                _exact_difference(ending_value, opening_value),
                -currency_effect,
                trade_base,
            )
        )
        total_effect = _exact_sum((market_effect, currency_effect))
        if ending_units == 0 and opening_units > 0:
            outcome = "closed"
        elif opening_units == 0 and ending_units > 0:
            outcome = "opened"
        elif ending_units > opening_units:
            outcome = "increased"
        elif ending_units < opening_units:
            outcome = "reduced"
        else:
            outcome = "unchanged"
        row = AnalyticsSymbolContribution(
            bucket_id=bucket_id,
            market=bucket.market,
            currency=bucket.currency,
            symbol=symbol,
            opening_qty=opening_units,
            ending_qty=ending_units,
            traded_qty=traded,
            opening_price=_price_text(
                opening_mark.price,
                f"attribution.positions.{bucket_id}.{symbol}.opening_price",
            ),
            ending_price=_price_text(
                end_mark.price,
                f"attribution.positions.{bucket_id}.{symbol}.ending_price",
            ),
            opening_mark=_mark_reference(opening_mark),
            ending_mark=_mark_reference(end_mark),
            opening_fx=opening_ref,
            ending_fx=ending_ref,
            opening_local_value=_exact_text(
                opening_local,
                f"attribution.positions.{bucket_id}.{symbol}.opening_local",
            ),
            ending_local_value=_exact_text(
                ending_local,
                f"attribution.positions.{bucket_id}.{symbol}.ending_local",
            ),
            opening_value_base=_exact_text(
                opening_value,
                f"attribution.positions.{bucket_id}.{symbol}.opening_value",
            ),
            ending_value_base=_exact_text(
                ending_value,
                f"attribution.positions.{bucket_id}.{symbol}.ending_value",
            ),
            trade_cash_base=_exact_text(
                trade_base,
                f"attribution.positions.{bucket_id}.{symbol}.trade_cash",
            ),
            market_contribution_base=_exact_text(
                market_effect,
                f"attribution.positions.{bucket_id}.{symbol}.market_contribution",
            ),
            currency_contribution_base=_exact_text(
                currency_effect,
                f"attribution.positions.{bucket_id}.{symbol}.currency_contribution",
            ),
            total_contribution_base=_exact_text(
                total_effect,
                f"attribution.positions.{bucket_id}.{symbol}.total_contribution",
            ),
            outcome=outcome,
        )
        symbol_rows.append(row)
        symbol_by_key[(bucket_id, symbol)] = row

    position_total = _exact_sum(
        Decimal(row.total_contribution_base) for row in symbol_rows
    )

    # Market and currency views are complete roll-ups of the symbol, cash FX,
    # conversion and fee rows; they tie to the NAV change plus the same residual.
    market_roll: dict[str, dict[str, Decimal]] = {}
    currency_roll: dict[str, dict[str, Decimal]] = {}

    def _roll(
        target: dict[str, dict[str, Decimal]],
        key: str,
        field: str,
        value: Decimal,
        bucket_id: str,
    ) -> None:
        row = target.setdefault(
            key,
            {
                "position": Decimal(0),
                "cash": Decimal(0),
                "conversion": Decimal(0),
                "fee": Decimal(0),
                "buckets": set(),
            },
        )
        row[field] = _exact_sum((row[field], value))
        row["buckets"].add(bucket_id)

    for row in symbol_rows:
        _roll(
            market_roll,
            row.market,
            "position",
            Decimal(row.total_contribution_base),
            row.bucket_id,
        )
        _roll(
            currency_roll,
            row.currency,
            "position",
            Decimal(row.total_contribution_base),
            row.bucket_id,
        )
    for row in cash_fx_rows:
        _roll(
            market_roll,
            row.market,
            "cash",
            Decimal(row.cash_fx_effect_base),
            row.bucket_id,
        )
        _roll(
            currency_roll,
            row.currency,
            "cash",
            Decimal(row.cash_fx_effect_base),
            row.bucket_id,
        )
    for row in conversion_effects:
        source_bucket = end_buckets.get(row.from_bucket_id)
        target_bucket = end_buckets.get(row.to_bucket_id)
        if source_bucket is not None:
            _roll(
                market_roll,
                source_bucket.market,
                "conversion",
                Decimal(row.source_effect_base),
                row.from_bucket_id,
            )
            _roll(
                currency_roll,
                row.from_currency,
                "conversion",
                Decimal(row.source_effect_base),
                row.from_bucket_id,
            )
        if target_bucket is not None:
            _roll(
                market_roll,
                target_bucket.market,
                "conversion",
                Decimal(row.target_effect_base),
                row.to_bucket_id,
            )
            _roll(
                currency_roll,
                row.to_currency,
                "conversion",
                Decimal(row.target_effect_base),
                row.to_bucket_id,
            )
    for row in fee_effects:
        bucket = end_buckets.get(row.bucket_id)
        if bucket is None:
            continue
        _roll(
            market_roll,
            bucket.market,
            "fee",
            Decimal(row.fee_effect_base),
            row.bucket_id,
        )
        _roll(
            currency_roll,
            bucket.currency,
            "fee",
            Decimal(row.fee_effect_base),
            row.bucket_id,
        )

    def _roll_rows(
        values: dict[str, dict[str, Decimal]],
        factory,
    ):
        rows = []
        for key in sorted(values):
            value = values[key]
            total = _exact_sum(
                (value["position"], value["cash"], value["conversion"], value["fee"])
            )
            rows.append(
                factory(
                    key=key,
                    position=value["position"],
                    cash=value["cash"],
                    conversion=value["conversion"],
                    fee=value["fee"],
                    total=total,
                    bucket_ids=tuple(sorted(value["buckets"])),
                )
            )
        return tuple(rows)

    market_rows = _roll_rows(
        market_roll,
        lambda **value: AnalyticsMarketContribution(
            market=value["key"],
            position_contribution_base=_exact_text(
                value["position"],
                "attribution.market_contributions.position",
            ),
            cash_fx_effect_base=_exact_text(
                value["cash"],
                "attribution.market_contributions.cash",
            ),
            conversion_effect_base=_exact_text(
                value["conversion"],
                "attribution.market_contributions.conversion",
            ),
            fee_effect_base=_exact_text(
                value["fee"],
                "attribution.market_contributions.fee",
            ),
            total_contribution_base=_exact_text(
                value["total"],
                "attribution.market_contributions.total",
            ),
            bucket_ids=value["bucket_ids"],
        ),
    )
    currency_rows = _roll_rows(
        currency_roll,
        lambda **value: AnalyticsCurrencyContribution(
            currency=value["key"],
            position_contribution_base=_exact_text(
                value["position"],
                "attribution.currency_contributions.position",
            ),
            cash_fx_effect_base=_exact_text(
                value["cash"],
                "attribution.currency_contributions.cash",
            ),
            conversion_effect_base=_exact_text(
                value["conversion"],
                "attribution.currency_contributions.conversion",
            ),
            fee_effect_base=_exact_text(
                value["fee"],
                "attribution.currency_contributions.fee",
            ),
            total_contribution_base=_exact_text(
                value["total"],
                "attribution.currency_contributions.total",
            ),
            bucket_ids=value["bucket_ids"],
        ),
    )

    nav_change_exact = _exact_difference(exact_nav_base, start_exact)
    nav_change_reported = _exact_difference(nav_base, start_nav)
    rounding_residual = _exact_difference(
        nav_change_exact,
        _exact_sum(
            (
                position_total,
                cash_fx_total,
                conversion_total,
                fee_total,
            )
        ),
    )
    rounding_ok = rounding_residual == expected_rounding
    checks.append(
        AnalyticsReconciliationCheck(
            name="nav_contribution_identity",
            passed=rounding_ok,
            detail=(
                "position + cash FX + conversion + fee + execution rounding "
                "equals the exact NAV change"
            ),
        )
    )
    if not rounding_ok:
        issues.append(
            _attribution_issue(
                "attribution_rounding_residual_mismatch",
                "attribution.rounding_residual",
                "the identity residual differs from the independently computed "
                "execution-notional rounding",
            )
        )

    position_values = {
        (row.bucket_id, row.symbol): Decimal(row.value_base) for row in position_rows
    }
    end_qty = _position_quantities(end_ledger)
    fill_by_key = {
        (fill.bucket_id, fill.symbol): fill for fill in fills
    }
    rejected_by_key = {
        (row.bucket_id, row.symbol): row for row in rejected_orders
    }
    canceled_by_key = {
        (row.bucket_id, row.symbol): row for row in canceled_orders
    }
    weight_rows: list[AnalyticsWeightRow] = []
    weight_issues: list[PortfolioIssue] = []
    plan_keys: set[tuple[str, str]] = set()
    for index, row in enumerate(plan.weights):
        bucket_id = row.bucket_id
        symbol = row.symbol
        key = (bucket_id, symbol)
        plan_keys.add(key)
        path = f"attribution.weights.rows[{index}]"
        bucket = end_buckets.get(bucket_id)
        if bucket is None:
            weight_issues.append(
                _attribution_issue(
                    "attribution_plan_bucket_mismatch",
                    path,
                    "a plan weight names an undeclared ending bucket",
                    bucket_id=bucket_id,
                )
            )
            continue
        mark = planning_marks.get(symbol)
        rate_pair = planning_rates.get(bucket_id)
        if mark is None or rate_pair is None:
            weight_issues.append(
                _attribution_issue(
                    "attribution_planned_weight_mismatch",
                    f"{path}.planned_weight",
                    "the plan weight has no planning mark/rate to audit",
                    bucket_id=bucket_id,
                )
            )
            planned_value = Decimal(0)
        else:
            planned_value = _money(
                _exact_product(
                    Decimal(row.planned_qty),
                    _exact_product(mark.price, rate_pair[1]),
                ),
                f"{path}.planned_value",
            )
            expected = (
                _weight(_ratio(planned_value, planning_nav), f"{path}.planned_weight")
                if planning_nav > 0
                else Decimal(0)
            )
            if expected != row.planned_weight:
                weight_issues.append(
                    _attribution_issue(
                        "attribution_planned_weight_mismatch",
                        f"{path}.planned_weight",
                        "the plan weight does not equal planned quantity times the "
                        "planning mark and direct-pair FX",
                        bucket_id=bucket_id,
                    )
                )
        symbol_row = symbol_by_key.get(key)
        realized_value = position_values.get(key, Decimal(0))
        realized_units = end_qty.get(key, 0)
        if symbol_row is None:
            planned_at_end_value = Decimal(0)
            if row.planned_qty:
                weight_issues.append(
                    _attribution_issue(
                        "attribution_missing_end_mark",
                        f"{path}.planned_at_end_weight",
                        "a nonzero planned quantity has no ending mark",
                        bucket_id=bucket_id,
                    )
                )
        else:
            planned_at_end_value = _money(
                _exact_product(
                    Decimal(row.planned_qty),
                    _exact_product(
                        Decimal(symbol_row.ending_price),
                        Decimal(symbol_row.ending_fx.rate),
                    ),
                ),
                f"{path}.planned_at_end_value",
            )
        planned_at_end_weight = (
            _weight(_ratio(planned_at_end_value, nav_base), f"{path}.planned_at_end_weight")
            if nav_base > 0
            else Decimal(0)
        )
        realized_weight = (
            _weight(_ratio(realized_value, nav_base), f"{path}.realized_weight") if nav_base > 0 else Decimal(0)
        )
        planned_weight = row.planned_weight
        target = row.target_weight
        target_gap = (
            _signed_weight(realized_weight - target, f"{path}.target_gap")
            if target is not None
            else None
        )
        lot_gap = (
            _signed_weight(planned_weight - target, f"{path}.lot_gap")
            if target is not None
            else "0"
        )
        price_gap = _signed_weight(
            planned_at_end_weight - planned_weight,
            f"{path}.price_gap",
        )
        reject_gap = _signed_weight(
            realized_weight - planned_at_end_weight,
            f"{path}.reject_gap",
        )
        if key in fill_by_key:
            outcome = "filled"
        elif key in rejected_by_key:
            outcome = "rejected"
        elif key in canceled_by_key:
            outcome = "canceled"
        else:
            outcome = "not_ordered"
        weight_rows.append(
            AnalyticsWeightRow(
                bucket_id=bucket_id,
                market=bucket.market,
                currency=bucket.currency,
                symbol=symbol,
                target_weight=(
                    _signed_weight(target, f"{path}.target")
                    if target is not None
                    else None
                ),
                planned_weight=_weight_sum(
                    planned_weight,
                    f"{path}.planned_weight",
                ),
                planned_at_end_weight=_weight_sum(
                    planned_at_end_weight,
                    f"{path}.planned_at_end_weight",
                ),
                realized_weight=_weight_sum(
                    realized_weight,
                    f"{path}.realized_weight",
                ),
                target_gap=target_gap,
                lot_gap=lot_gap,
                price_gap=price_gap,
                reject_gap=reject_gap,
                planned_value_base=_exact_text(
                    planned_value,
                    f"{path}.planned_value",
                ),
                planned_at_end_value_base=_exact_text(
                    planned_at_end_value,
                    f"{path}.planned_at_end_value",
                ),
                realized_value_base=canonical_decimal(
                    realized_value,
                    MONEY_SPEC,
                    f"{path}.realized_value",
                ),
                planned_qty=row.planned_qty,
                realized_qty=realized_units,
                qty_gap=realized_units - row.planned_qty,
                outcome=outcome,
            )
        )
    for key in sorted(set(end_qty) - plan_keys):
        weight_issues.append(
            _attribution_issue(
                "attribution_missing_plan_weight",
                f"attribution.weights.{key[0]}.{key[1]}",
                "an ending position has no plan weight row",
                bucket_id=key[0],
            )
        )

    target_mode = plan.mode == "target_weights"
    target_total = (
        _weight_sum(
            _exact_sum(
                (
                    Decimal(row.target_weight)
                    for row in weight_rows
                    if row.target_weight is not None
                )
            ),
            "attribution.weights.target_total",
        )
        if target_mode
        else None
    )
    planned_total_value = _exact_sum(
        Decimal(row.planned_weight) for row in weight_rows
    )
    realized_total_value = _exact_sum(
        Decimal(row.realized_weight) for row in weight_rows
    )
    lot_total_value = _exact_sum(Decimal(row.lot_gap) for row in weight_rows)
    price_total_value = _exact_sum(Decimal(row.price_gap) for row in weight_rows)
    reject_total_value = _exact_sum(Decimal(row.reject_gap) for row in weight_rows)
    planned_cash = _exact_difference(Decimal(1), planned_total_value)
    target_cash = (
        _exact_difference(Decimal(1), Decimal(target_total))
        if target_total is not None
        else None
    )
    realized_cash = (
        _weight(
            _ratio(_exact_sum(Decimal(row.value_base) for row in cash_rows), nav_base),
            "attribution.weights.realized_cash",
        )
        if nav_base > 0
        else Decimal(0)
    )
    valuation_weight = (
        _signed_weight_value(
            _ratio(valuation_rounding, nav_base),
            "attribution.weights.valuation_rounding",
        )
        if nav_base > 0
        else Decimal(0)
    )
    cash_basis = target_cash if target_cash is not None else planned_cash
    cash_gap = _exact_difference(realized_cash, cash_basis)
    weight_rounding = _exact_sum(
        (
            lot_total_value,
            price_total_value,
            reject_total_value,
            cash_gap,
            valuation_weight,
        )
    )
    tolerance = _weight_rounding_tolerance(len(weight_rows))
    weight_identity_ok = abs(weight_rounding) <= tolerance
    weights_reconciled = weight_identity_ok and not weight_issues
    issues.extend(weight_issues)
    if not weight_identity_ok:
        issues.append(
            _attribution_issue(
                "attribution_weight_identity_mismatch",
                "attribution.weights",
                "target/planned/realized weight gaps exceed the declared rounding "
                "tolerance",
            )
        )
    checks.append(
        AnalyticsReconciliationCheck(
            name="weight_gap_identity",
            passed=weight_identity_ok,
            detail=(
                "lot + price + reject + cash gap + valuation rounding equals the "
                "declared weight rounding residual"
            ),
        )
    )

    weights = AnalyticsWeightReconciliation(
        planning_nav_base=canonical_decimal(
            planning_nav,
            MONEY_SPEC,
            "attribution.weights.planning_nav_base",
        ),
        planning_exact_nav_base=_exact_text(
            planning_exact,
            "attribution.weights.planning_exact_nav_base",
        ),
        planning_rounding_residual=_exact_text(
            _exact_difference(planning_exact, planning_nav),
            "attribution.weights.planning_rounding_residual",
        ),
        target_weight_total=target_total,
        target_cash_weight=(
            _weight_sum(target_cash, "attribution.weights.target_cash_weight")
            if target_cash is not None
            else None
        ),
        planned_weight_total=_weight_sum(
            planned_total_value,
            "attribution.weights.planned_total",
        ),
        planned_cash_weight=_weight_sum(
            planned_cash,
            "attribution.weights.planned_cash",
        ),
        realized_weight_total=_weight_sum(
            realized_total_value,
            "attribution.weights.realized_total",
        ),
        realized_cash_weight=_weight_sum(
            realized_cash,
            "attribution.weights.realized_cash",
        ),
        valuation_rounding_weight=_weight_sum(
            valuation_weight,
            "attribution.weights.valuation_rounding",
        ),
        lot_gap_total=_weight_sum(
            lot_total_value,
            "attribution.weights.lot_total",
        ),
        price_gap_total=_weight_sum(
            price_total_value,
            "attribution.weights.price_total",
        ),
        reject_gap_total=_weight_sum(
            reject_total_value,
            "attribution.weights.reject_total",
        ),
        cash_gap=_weight_sum(cash_gap, "attribution.weights.cash_gap"),
        weight_rounding_residual=_weight_sum(
            weight_rounding,
            "attribution.weights.residual",
        ),
        weight_rounding_tolerance=_weight_sum(
            tolerance,
            "attribution.weights.tolerance",
        ),
        reconciled=weights_reconciled,
        rows=tuple(weight_rows),
    )

    nav_row = AnalyticsAttributionNav(
        start_at=request.planning_at,
        end_at=request.valuation_at,
        start_nav_base=canonical_decimal(
            start_nav,
            MONEY_SPEC,
            "attribution.nav.start_nav_base",
        ),
        start_exact_nav_base=_exact_text(
            start_exact,
            "attribution.nav.start_exact_nav_base",
        ),
        start_rounding_residual=_exact_text(
            _exact_difference(start_exact, start_nav),
            "attribution.nav.start_rounding_residual",
        ),
        end_nav_base=canonical_decimal(
            nav_base,
            MONEY_SPEC,
            "attribution.nav.end_nav_base",
        ),
        end_exact_nav_base=_exact_text(
            exact_nav_base,
            "attribution.nav.end_exact_nav_base",
        ),
        end_rounding_residual=_exact_text(
            _exact_difference(exact_nav_base, nav_base),
            "attribution.nav.end_rounding_residual",
        ),
        nav_change_reported=canonical_decimal(
            nav_change_reported,
            MONEY_SPEC,
            "attribution.nav.nav_change_reported",
        ),
        nav_change_exact=_exact_text(
            nav_change_exact,
            "attribution.nav.nav_change_exact",
        ),
    )

    provenance = _provenance(
        (
            *(mark.price_date for mark in planning_marks.values()),
            *(row.ending_mark.price_date for row in symbol_rows),
            *(fill.trade_date for fill in fills),
        ),
        (
            *(ref for ref, _ in planning_rates.values()),
            *(ref for ref, _ in valuation_rates.values()),
            *(row.source_fx for row in conversion_effects),
            *(row.target_fx for row in conversion_effects),
            *(row.fx for row in fee_effects),
            *(row.fx for row in rounding_rows),
        ),
    )
    provisional = AnalyticsAttribution(
        base_currency=base_currency,
        nav=nav_row,
        symbol_contributions=tuple(
            sorted(
                symbol_rows,
                key=lambda row: (row.bucket_id, row.symbol),
            )
        ),
        cash_fx_effects=tuple(cash_fx_rows),
        conversion_effects=tuple(conversion_effects),
        fee_effects=tuple(fee_effects),
        execution_rounding=tuple(rounding_rows),
        market_contributions=market_rows,
        currency_contributions=currency_rows,
        position_contribution_base=_exact_text(
            position_total,
            "attribution.position_contribution_base",
        ),
        cash_fx_effect_base=_exact_text(
            cash_fx_total,
            "attribution.cash_fx_effect_base",
        ),
        conversion_effect_base=_exact_text(
            conversion_total,
            "attribution.conversion_effect_base",
        ),
        fee_effect_base=_exact_text(
            fee_total,
            "attribution.fee_effect_base",
        ),
        rounding_residual=_exact_text(
            rounding_residual,
            "attribution.rounding_residual",
        ),
        expected_rounding_residual=_exact_text(
            expected_rounding,
            "attribution.expected_rounding_residual",
        ),
        weights=weights,
        reconciliation=AnalyticsAttributionReconciliation(
            reconciled=False,
            checks=tuple(checks),
            issues=tuple(issues),
            not_verified=_ATTRIBUTION_NOT_VERIFIED,
        ),
        provenance=provenance,
    )
    verifier_issues = reconcile_attribution(provisional)
    merged = _merge_issues((*issues, *verifier_issues))
    checks.append(
        AnalyticsReconciliationCheck(
            name="published_arithmetic",
            passed=not verifier_issues,
            detail="every published contribution, FX, fee and weight row recomputes",
        )
    )
    reconciled = all(check.passed for check in checks) and not merged
    return provisional.model_copy(
        update={
            "reconciliation": AnalyticsAttributionReconciliation(
                reconciled=reconciled,
                checks=tuple(checks),
                issues=merged,
                not_verified=_ATTRIBUTION_NOT_VERIFIED,
            )
        }
    )


def _attr_decimal(value: str) -> Decimal:
    return Decimal(value)


def reconcile_attribution(
    attribution: AnalyticsAttribution,
) -> tuple[PortfolioIssue, ...]:
    """Independently recompute a published attribution document.

    Every total is rebuilt from the published raw rows. The function never
    adjusts a component to force the identity; a mismatch becomes an issue.
    """
    issues: list[PortfolioIssue] = []

    def fail(
        reason: str,
        path: str,
        detail: str,
        bucket_id: str | None = None,
    ) -> None:
        issues.append(
            _attribution_issue(
                reason,
                path,
                detail,
                bucket_id=bucket_id,
            )
        )

    def equal(
        actual: Decimal,
        expected: Decimal,
        reason: str,
        path: str,
        detail: str,
        bucket_id: str | None = None,
    ) -> None:
        if actual != expected:
            fail(reason, path, detail, bucket_id)

    nav = attribution.nav
    start_reported = _attr_decimal(nav.start_nav_base)
    start_exact = _attr_decimal(nav.start_exact_nav_base)
    end_reported = _attr_decimal(nav.end_nav_base)
    end_exact = _attr_decimal(nav.end_exact_nav_base)
    equal(
        _attr_decimal(nav.start_rounding_residual),
        _exact_difference(start_exact, start_reported),
        "attribution_nav_mismatch",
        "attribution.nav.start_rounding_residual",
        "start exact NAV must equal reported NAV plus its residual",
    )
    equal(
        _attr_decimal(nav.end_rounding_residual),
        _exact_difference(end_exact, end_reported),
        "attribution_nav_mismatch",
        "attribution.nav.end_rounding_residual",
        "end exact NAV must equal reported NAV plus its residual",
    )
    equal(
        _attr_decimal(nav.nav_change_exact),
        _exact_difference(end_exact, start_exact),
        "attribution_nav_mismatch",
        "attribution.nav.nav_change_exact",
        "the exact NAV change must be end minus start",
    )
    equal(
        _attr_decimal(nav.nav_change_reported),
        _exact_difference(end_reported, start_reported),
        "attribution_nav_mismatch",
        "attribution.nav.nav_change_reported",
        "the reported NAV change must be end minus start",
    )

    cash_by_bucket = {row.bucket_id: row for row in attribution.cash_fx_effects}
    if len(cash_by_bucket) != len(attribution.cash_fx_effects):
        fail(
            "attribution_duplicate_bucket",
            "attribution.cash_fx_effects",
            "a bucket may publish exactly one cash FX row",
        )
    opening_by_bucket: dict[str, Decimal] = {}
    ending_by_bucket: dict[str, Decimal] = {}
    opening_cash_units: dict[str, Decimal] = {}
    ending_cash_units: dict[str, Decimal] = {}
    opening_position_local: dict[str, Decimal] = {}
    ending_position_local: dict[str, Decimal] = {}
    opening_position_money: dict[str, Decimal] = {}
    ending_position_money: dict[str, Decimal] = {}
    symbol_by_key: dict[tuple[str, str], AnalyticsSymbolContribution] = {}
    for index, row in enumerate(attribution.symbol_contributions):
        key = (row.bucket_id, row.symbol)
        if key in symbol_by_key:
            fail(
                "attribution_duplicate_position",
                f"attribution.symbol_contributions[{index}]",
                "a bucket/instrument pair may publish exactly one contribution",
                row.bucket_id,
            )
        symbol_by_key[key] = row
        opening_local = _attr_decimal(row.opening_local_value)
        ending_local = _attr_decimal(row.ending_local_value)
        opening_rate = _attr_decimal(row.opening_fx.rate)
        ending_rate = _attr_decimal(row.ending_fx.rate)
        if (
            row.opening_fx.from_currency != row.currency
            or row.ending_fx.from_currency != row.currency
        ):
            fail(
                "attribution_fx_reference_mismatch",
                f"attribution.symbol_contributions[{index}].opening_fx",
                "position FX references must name the position currency",
                row.bucket_id,
            )
        equal(
            opening_local,
            _exact_product(Decimal(row.opening_qty), _attr_decimal(row.opening_price)),
            "attribution_position_math_mismatch",
            f"attribution.symbol_contributions[{index}].opening_local_value",
            "opening local value must equal quantity times price",
            row.bucket_id,
        )
        equal(
            ending_local,
            _exact_product(Decimal(row.ending_qty), _attr_decimal(row.ending_price)),
            "attribution_position_math_mismatch",
            f"attribution.symbol_contributions[{index}].ending_local_value",
            "ending local value must equal quantity times price",
            row.bucket_id,
        )
        equal(
            _attr_decimal(row.opening_value_base),
            _exact_product(opening_local, opening_rate),
            "attribution_position_math_mismatch",
            f"attribution.symbol_contributions[{index}].opening_value_base",
            "opening base value must equal local value times opening FX",
            row.bucket_id,
        )
        equal(
            _attr_decimal(row.ending_value_base),
            _exact_product(ending_local, ending_rate),
            "attribution_position_math_mismatch",
            f"attribution.symbol_contributions[{index}].ending_value_base",
            "ending base value must equal local value times ending FX",
            row.bucket_id,
        )
        currency_expected = _exact_product(
            opening_local,
            _exact_difference(ending_rate, opening_rate),
        )
        equal(
            _attr_decimal(row.currency_contribution_base),
            currency_expected,
            "attribution_position_math_mismatch",
            f"attribution.symbol_contributions[{index}].currency_contribution_base",
            "currency contribution must revalue opening local value",
            row.bucket_id,
        )
        trade_expected = Decimal(0)
        for fill in attribution.execution_rounding:
            if fill.bucket_id != row.bucket_id or fill.symbol != row.symbol:
                continue
            sign = Decimal(1) if fill.side == "sell" else Decimal(-1)
            trade_expected = _exact_sum(
                (
                    trade_expected,
                    _exact_product(
                        sign * _attr_decimal(fill.exact_notional_local),
                        _attr_decimal(fill.fx.rate),
                    ),
                )
            )
        equal(
            _attr_decimal(row.trade_cash_base),
            trade_expected,
            "attribution_position_math_mismatch",
            f"attribution.symbol_contributions[{index}].trade_cash_base",
            "trade cash must equal signed exact fill notionals at ending FX",
            row.bucket_id,
        )
        equal(
            _attr_decimal(row.market_contribution_base),
            _exact_sum(
                (
                    _exact_difference(
                        _attr_decimal(row.ending_value_base),
                        _attr_decimal(row.opening_value_base),
                    ),
                    -currency_expected,
                    trade_expected,
                )
            ),
            "attribution_position_math_mismatch",
            f"attribution.symbol_contributions[{index}].market_contribution_base",
            "market contribution must equal ending minus opening minus FX plus trade cash",
            row.bucket_id,
        )
        equal(
            _attr_decimal(row.total_contribution_base),
            _exact_sum(
                (
                    _attr_decimal(row.market_contribution_base),
                    _attr_decimal(row.currency_contribution_base),
                )
            ),
            "attribution_position_math_mismatch",
            f"attribution.symbol_contributions[{index}].total_contribution_base",
            "total contribution must equal market plus currency",
            row.bucket_id,
        )
        if row.traded_qty != row.ending_qty - row.opening_qty:
            fail(
                "attribution_position_math_mismatch",
                f"attribution.symbol_contributions[{index}].traded_qty",
                "traded quantity must equal ending quantity minus opening quantity",
                row.bucket_id,
            )
        opening_position_local[row.bucket_id] = _exact_sum(
            (opening_position_local.get(row.bucket_id, Decimal(0)), opening_local)
        )
        ending_position_local[row.bucket_id] = _exact_sum(
            (ending_position_local.get(row.bucket_id, Decimal(0)), ending_local)
        )
        opening_position_money[row.bucket_id] = _exact_sum(
            (
                opening_position_money.get(row.bucket_id, Decimal(0)),
                _money(opening_local, "attribution.reconcile.opening_local"),
            )
        )
        ending_position_money[row.bucket_id] = _exact_sum(
            (
                ending_position_money.get(row.bucket_id, Decimal(0)),
                _money(ending_local, "attribution.reconcile.ending_local"),
            )
        )

    for index, row in enumerate(attribution.cash_fx_effects):
        opening_rate = _attr_decimal(row.opening_fx.rate)
        ending_rate = _attr_decimal(row.ending_fx.rate)
        opening_cash = _attr_decimal(row.opening_cash)
        equal(
            _attr_decimal(row.cash_fx_effect_base),
            _exact_product(
                opening_cash,
                _exact_difference(ending_rate, opening_rate),
            ),
            "attribution_cash_fx_mismatch",
            f"attribution.cash_fx_effects[{index}].cash_fx_effect_base",
            "cash FX must revalue opening cash between the declared direct pairs",
            row.bucket_id,
        )
        opening_cash_units[row.bucket_id] = opening_cash
        ending_cash_units[row.bucket_id] = _attr_decimal(row.ending_cash)
        opening_by_bucket[row.bucket_id] = _exact_sum(
            (
                _attr_decimal(row.opening_cash),
                opening_position_local.get(row.bucket_id, Decimal(0)),
            )
        )
        ending_by_bucket[row.bucket_id] = _exact_sum(
            (
                _attr_decimal(row.ending_cash),
                ending_position_local.get(row.bucket_id, Decimal(0)),
            )
        )

    start_expected = Decimal(0)
    end_expected = Decimal(0)
    start_reported_expected = Decimal(0)
    end_reported_expected = Decimal(0)
    for bucket_id, row in cash_by_bucket.items():
        start_exact_bucket = _exact_product(
            opening_by_bucket.get(bucket_id, Decimal(0)),
            _attr_decimal(row.opening_fx.rate),
        )
        end_exact_bucket = _exact_product(
            ending_by_bucket.get(bucket_id, Decimal(0)),
            _attr_decimal(row.ending_fx.rate),
        )
        start_expected = _exact_sum((start_expected, start_exact_bucket))
        end_expected = _exact_sum((end_expected, end_exact_bucket))
        start_reported_expected = _exact_sum(
            (
                start_reported_expected,
                _money(
                    _exact_product(
                        _exact_sum(
                            (
                                opening_cash_units.get(bucket_id, Decimal(0)),
                                opening_position_money.get(bucket_id, Decimal(0)),
                            )
                        ),
                        _attr_decimal(row.opening_fx.rate),
                    ),
                    "attribution.reconcile.start_reported",
                ),
            )
        )
        end_reported_expected = _exact_sum(
            (
                end_reported_expected,
                _money(
                    _exact_product(
                        _exact_sum(
                            (
                                ending_cash_units.get(bucket_id, Decimal(0)),
                                ending_position_money.get(bucket_id, Decimal(0)),
                            )
                        ),
                        _attr_decimal(row.ending_fx.rate),
                    ),
                    "attribution.reconcile.end_reported",
                ),
            )
        )
    equal(
        start_reported_expected,
        start_reported,
        "attribution_nav_mismatch",
        "attribution.nav.start_nav_base",
        "per-bucket reported opening NAV must sum to start NAV",
    )
    equal(
        end_reported_expected,
        end_reported,
        "attribution_nav_mismatch",
        "attribution.nav.end_nav_base",
        "per-bucket reported ending NAV must sum to end NAV",
    )
    equal(
        start_expected,
        start_exact,
        "attribution_nav_mismatch",
        "attribution.nav.start_exact_nav_base",
        "opening cash and positions at planning marks/FX must equal start NAV",
    )
    equal(
        end_expected,
        end_exact,
        "attribution_nav_mismatch",
        "attribution.nav.end_exact_nav_base",
        "ending cash and positions at valuation marks/FX must equal end NAV",
    )

    conversion_total = Decimal(0)
    conversion_cash: dict[str, Decimal] = {
        bucket_id: opening_cash_units.get(bucket_id, Decimal(0))
        for bucket_id in cash_by_bucket
    }
    for index, row in enumerate(attribution.conversion_effects):
        source_rate = _attr_decimal(row.source_fx.rate)
        target_rate = _attr_decimal(row.target_fx.rate)
        if (
            row.source_fx.from_currency != row.from_currency
            or row.target_fx.from_currency != row.to_currency
        ):
            fail(
                "attribution_fx_reference_mismatch",
                f"attribution.conversion_effects[{index}].source_fx",
                "conversion FX references must name the event currencies",
            )
        exact = _exact_product(_attr_decimal(row.source_amount), _attr_decimal(row.rate))
        equal(
            _attr_decimal(row.exact_converted),
            exact,
            "attribution_conversion_math_mismatch",
            f"attribution.conversion_effects[{index}].exact_converted",
            "exact converted amount must equal source amount times rate",
        )
        equal(
            _attr_decimal(row.rounding_residual_local),
            _exact_difference(exact, _attr_decimal(row.converted_amount)),
            "attribution_conversion_math_mismatch",
            f"attribution.conversion_effects[{index}].rounding_residual_local",
            "conversion rounding must tie exact to credited amount",
        )
        source_effect = _exact_product(-_attr_decimal(row.source_amount), source_rate)
        target_effect = _exact_product(_attr_decimal(row.converted_amount), target_rate)
        equal(
            _attr_decimal(row.source_effect_base),
            source_effect,
            "attribution_conversion_math_mismatch",
            f"attribution.conversion_effects[{index}].source_effect_base",
            "source effect must debit source amount at its ending FX",
        )
        equal(
            _attr_decimal(row.target_effect_base),
            target_effect,
            "attribution_conversion_math_mismatch",
            f"attribution.conversion_effects[{index}].target_effect_base",
            "target effect must credit converted amount at its ending FX",
        )
        equal(
            _attr_decimal(row.conversion_effect_base),
            _exact_sum((source_effect, target_effect)),
            "attribution_conversion_math_mismatch",
            f"attribution.conversion_effects[{index}].conversion_effect_base",
            "conversion effect must be source plus target",
        )
        equal(
            _attr_decimal(row.rounding_loss_base),
            -_exact_product(
                _exact_difference(exact, _attr_decimal(row.converted_amount)),
                target_rate,
            ),
            "attribution_conversion_math_mismatch",
            f"attribution.conversion_effects[{index}].rounding_loss_base",
            "conversion rounding loss must be the unconverted remainder",
        )
        conversion_total = _exact_sum(
            (conversion_total, _attr_decimal(row.conversion_effect_base))
        )
        if row.from_bucket_id in conversion_cash:
            conversion_cash[row.from_bucket_id] = _exact_sum(
                (
                    conversion_cash[row.from_bucket_id],
                    -_attr_decimal(row.source_amount),
                )
            )
        else:
            fail(
                "attribution_conversion_bucket_mismatch",
                f"attribution.conversion_effects[{index}].from_bucket_id",
                "the source bucket has no cash row",
                row.from_bucket_id,
            )
        if row.to_bucket_id in conversion_cash:
            conversion_cash[row.to_bucket_id] = _exact_sum(
                (
                    conversion_cash[row.to_bucket_id],
                    _attr_decimal(row.converted_amount),
                )
            )
        else:
            fail(
                "attribution_conversion_bucket_mismatch",
                f"attribution.conversion_effects[{index}].to_bucket_id",
                "the target bucket has no cash row",
                row.to_bucket_id,
            )

    fee_total = Decimal(0)
    fee_by_order = {}
    for index, row in enumerate(attribution.fee_effects):
        if row.plan_order_id in fee_by_order:
            fail(
                "attribution_duplicate_fill",
                f"attribution.fee_effects[{index}].plan_order_id",
                "one plan order may publish one fee row",
                row.bucket_id,
            )
        fee_by_order[row.plan_order_id] = row
        bucket = cash_by_bucket.get(row.bucket_id)
        if bucket is not None and row.fx.from_currency != bucket.currency:
            fail(
                "attribution_fx_reference_mismatch",
                f"attribution.fee_effects[{index}].fx",
                "fee FX references must name the bucket currency",
                row.bucket_id,
            )
        equal(
            _attr_decimal(row.fee_effect_base),
            _exact_product(-_attr_decimal(row.fee_local), _attr_decimal(row.fx.rate)),
            "attribution_fee_mismatch",
            f"attribution.fee_effects[{index}].fee_effect_base",
            "fee effect must be the negative local fee at ending FX",
            row.bucket_id,
        )
        fee_total = _exact_sum((fee_total, _attr_decimal(row.fee_effect_base)))

    rounding_by_order = {}
    expected_rounding = Decimal(0)
    for index, row in enumerate(attribution.execution_rounding):
        if row.plan_order_id in rounding_by_order:
            fail(
                "attribution_duplicate_fill",
                f"attribution.execution_rounding[{index}].plan_order_id",
                "one plan order may publish one rounding row",
                row.bucket_id,
            )
        rounding_by_order[row.plan_order_id] = row
        bucket = cash_by_bucket.get(row.bucket_id)
        if bucket is not None and row.fx.from_currency != bucket.currency:
            fail(
                "attribution_fx_reference_mismatch",
                f"attribution.execution_rounding[{index}].fx",
                "execution rounding FX references must name the bucket currency",
                row.bucket_id,
            )
        exact = _exact_product(Decimal(row.qty), _attr_decimal(row.execution_price))
        notional = _execution_notional(exact)
        rounding = _exact_difference(exact, notional)
        equal(
            _attr_decimal(row.exact_notional_local),
            exact,
            "attribution_execution_rounding_mismatch",
            f"attribution.execution_rounding[{index}].exact_notional_local",
            "exact notional must equal quantity times execution price",
            row.bucket_id,
        )
        equal(
            _attr_decimal(row.notional_local),
            notional,
            "attribution_execution_rounding_mismatch",
            f"attribution.execution_rounding[{index}].notional_local",
            "execution notional must be the two-decimal ROUND_HALF_UP cash amount",
            row.bucket_id,
        )
        equal(
            _attr_decimal(row.rounding_local),
            rounding,
            "attribution_execution_rounding_mismatch",
            f"attribution.execution_rounding[{index}].rounding_local",
            "rounding must equal exact minus execution notional",
            row.bucket_id,
        )
        signed = rounding if row.side == "buy" else -rounding
        effect = _exact_product(signed, _attr_decimal(row.fx.rate))
        equal(
            _attr_decimal(row.rounding_effect_base),
            effect,
            "attribution_execution_rounding_mismatch",
            f"attribution.execution_rounding[{index}].rounding_effect_base",
            "rounding effect must carry the fill side into base currency",
            row.bucket_id,
        )
        expected_rounding = _exact_sum((expected_rounding, effect))

    for index, row in enumerate(attribution.fee_effects):
        rounding = rounding_by_order.get(row.plan_order_id)
        if rounding is None:
            fail(
                "attribution_missing_fill_row",
                f"attribution.fee_effects[{index}].plan_order_id",
                "every fee row needs its execution rounding row",
                row.bucket_id,
            )
            continue
        if row.bucket_id not in conversion_cash:
            continue
        notional = _attr_decimal(rounding.notional_local)
        fee = _attr_decimal(row.fee_local)
        delta = _exact_difference(notional, fee) if row.side == "sell" else -_exact_sum((notional, fee))
        conversion_cash[row.bucket_id] = _exact_sum((conversion_cash[row.bucket_id], delta))
    for bucket_id, row in cash_by_bucket.items():
        equal(
            conversion_cash.get(bucket_id, Decimal(0)),
            _attr_decimal(row.ending_cash),
            "attribution_cash_replay_mismatch",
            f"attribution.cash_fx_effects.{bucket_id}.ending_cash",
            "opening cash plus conversions and fills must equal ending cash",
            bucket_id,
        )

    position_total = _exact_sum(
        _attr_decimal(row.total_contribution_base)
        for row in attribution.symbol_contributions
    )
    cash_fx_total = _exact_sum(
        _attr_decimal(row.cash_fx_effect_base) for row in attribution.cash_fx_effects
    )
    equal(
        _attr_decimal(attribution.position_contribution_base),
        position_total,
        "attribution_total_mismatch",
        "attribution.position_contribution_base",
        "position total must equal the symbol contribution sum",
    )
    equal(
        _attr_decimal(attribution.cash_fx_effect_base),
        cash_fx_total,
        "attribution_total_mismatch",
        "attribution.cash_fx_effect_base",
        "cash FX total must equal the bucket FX row sum",
    )
    equal(
        _attr_decimal(attribution.conversion_effect_base),
        conversion_total,
        "attribution_total_mismatch",
        "attribution.conversion_effect_base",
        "conversion total must equal the conversion row sum",
    )
    equal(
        _attr_decimal(attribution.fee_effect_base),
        fee_total,
        "attribution_total_mismatch",
        "attribution.fee_effect_base",
        "fee total must equal the fee row sum",
    )
    equal(
        _attr_decimal(attribution.expected_rounding_residual),
        expected_rounding,
        "attribution_execution_rounding_mismatch",
        "attribution.expected_rounding_residual",
        "expected rounding must equal the execution rounding row sum",
    )
    identity_residual = _exact_difference(
        _attr_decimal(nav.nav_change_exact),
        _exact_sum(
            (
                position_total,
                cash_fx_total,
                conversion_total,
                fee_total,
            )
        ),
    )
    equal(
        _attr_decimal(attribution.rounding_residual),
        identity_residual,
        "attribution_identity_mismatch",
        "attribution.rounding_residual",
        "rounding residual must equal the unfitted NAV identity difference",
    )
    equal(
        identity_residual,
        expected_rounding,
        "attribution_rounding_residual_mismatch",
        "attribution.rounding_residual",
        "the identity residual must equal the execution rounding rows",
    )

    def _expected_rolls(rows):
        rolls: dict[str, dict[str, Decimal | set[str]]] = {}
        for row in rows:
            key = row[0]
            values = rolls.setdefault(
                key,
                {
                    "position": Decimal(0),
                    "cash": Decimal(0),
                    "conversion": Decimal(0),
                    "fee": Decimal(0),
                    "buckets": set(),
                },
            )
            values[row[1]] = _exact_sum(
                (values[row[1]], _attr_decimal(row[2]))
            )
            values["buckets"].add(row[3])
        return rolls

    market_inputs: list[tuple[str, str, str, str]] = []
    currency_inputs: list[tuple[str, str, str, str]] = []
    for row in attribution.symbol_contributions:
        market_inputs.append(
            (row.market, "position", row.total_contribution_base, row.bucket_id)
        )
        currency_inputs.append(
            (row.currency, "position", row.total_contribution_base, row.bucket_id)
        )
    for row in attribution.cash_fx_effects:
        market_inputs.append(
            (row.market, "cash", row.cash_fx_effect_base, row.bucket_id)
        )
        currency_inputs.append(
            (row.currency, "cash", row.cash_fx_effect_base, row.bucket_id)
        )
    for row in attribution.conversion_effects:
        source_bucket = cash_by_bucket.get(row.from_bucket_id)
        target_bucket = cash_by_bucket.get(row.to_bucket_id)
        if source_bucket is not None:
            market_inputs.append(
                (source_bucket.market, "conversion", row.source_effect_base, row.from_bucket_id)
            )
            currency_inputs.append(
                (row.from_currency, "conversion", row.source_effect_base, row.from_bucket_id)
            )
        if target_bucket is not None:
            market_inputs.append(
                (target_bucket.market, "conversion", row.target_effect_base, row.to_bucket_id)
            )
            currency_inputs.append(
                (row.to_currency, "conversion", row.target_effect_base, row.to_bucket_id)
            )
    for row in attribution.fee_effects:
        bucket = cash_by_bucket.get(row.bucket_id)
        if bucket is not None:
            market_inputs.append((bucket.market, "fee", row.fee_effect_base, row.bucket_id))
            currency_inputs.append((bucket.currency, "fee", row.fee_effect_base, row.bucket_id))

    for label, published_rows, inputs in (
        ("market", attribution.market_contributions, market_inputs),
        ("currency", attribution.currency_contributions, currency_inputs),
    ):
        expected_rolls = _expected_rolls(inputs)
        published = {row.market if label == "market" else row.currency: row for row in published_rows}
        for key in sorted(set(published) | set(expected_rolls)):
            row = published.get(key)
            expected = expected_rolls.get(key)
            if row is None or expected is None:
                fail(
                    f"attribution_{label}_rollup_mismatch",
                    f"attribution.{label}_contributions.{key}",
                    f"the {label} roll-up row set differs from the raw rows",
                )
                continue
            field_names = {
                "position": "position_contribution_base",
                "cash": "cash_fx_effect_base",
                "conversion": "conversion_effect_base",
                "fee": "fee_effect_base",
            }
            for field, attribute in field_names.items():
                equal(
                    _attr_decimal(getattr(row, attribute)),
                    expected[field],
                    f"attribution_{label}_rollup_mismatch",
                    f"attribution.{label}_contributions.{key}.{field}",
                    f"the {label} {field} roll-up must equal its raw rows",
                )
            equal(
                _attr_decimal(row.total_contribution_base),
                _exact_sum(
                    (
                        expected["position"],
                        expected["cash"],
                        expected["conversion"],
                        expected["fee"],
                    )
                ),
                f"attribution_{label}_rollup_mismatch",
                f"attribution.{label}_contributions.{key}.total",
                f"the {label} total must equal all four effects",
            )
            if tuple(row.bucket_ids) != tuple(sorted(expected["buckets"])):
                fail(
                    f"attribution_{label}_rollup_mismatch",
                    f"attribution.{label}_contributions.{key}.bucket_ids",
                    f"the {label} bucket ids must match the contributing rows",
                )
        equal(
            _exact_sum(
                _attr_decimal(row.total_contribution_base) for row in published_rows
            ) + identity_residual,
            _attr_decimal(nav.nav_change_exact),
            f"attribution_{label}_rollup_mismatch",
            f"attribution.{label}_contributions",
            f"all {label} totals plus the residual must equal the NAV change",
        )

    _reconcile_weights(attribution, cash_by_bucket, symbol_by_key, issues)
    return tuple(issues)


def _reconcile_weights(
    attribution: AnalyticsAttribution,
    cash_rows: dict[str, AnalyticsCashFxEffect],
    symbol_by_key: dict[tuple[str, str], AnalyticsSymbolContribution],
    issues: list[PortfolioIssue],
) -> None:
    weights = attribution.weights
    nav = _attr_decimal(attribution.nav.end_nav_base)
    planning_nav = _attr_decimal(weights.planning_nav_base)
    position_values = _exact_sum(
        (
            _money(
                _attr_decimal(symbol.ending_value_base),
                "attribution.weights.position_value",
            )
            for symbol in symbol_by_key.values()
        )
    )
    for row in weights.rows:
        key = (row.bucket_id, row.symbol)
        symbol = symbol_by_key.get(key)
        realized_value = (
            _money(
                _attr_decimal(symbol.ending_value_base),
                f"attribution.weights.{row.bucket_id}.{row.symbol}.realized_value",
            )
            if symbol is not None
            else Decimal(0)
        )
        if _attr_decimal(row.realized_value_base) != realized_value:
            issues.append(
                _attribution_issue(
                    "attribution_realized_value_mismatch",
                    f"attribution.weights.{row.bucket_id}.{row.symbol}.realized_value_base",
                    "realized value must equal the published ending position money value",
                    bucket_id=row.bucket_id,
                )
            )
        realized_weight = (
            _weight(_ratio(realized_value, nav), "attribution.weights.realized_weight") if nav > 0 else Decimal(0)
        )
        if row.realized_weight != _weight_sum(
            realized_weight,
            "attribution.weights.realized_weight",
        ):
            issues.append(
                _attribution_issue(
                    "attribution_realized_weight_mismatch",
                    f"attribution.weights.{row.bucket_id}.{row.symbol}.realized_weight",
                    "realized weight must equal realized value over end NAV",
                    bucket_id=row.bucket_id,
                )
            )
        planned_at_end_value = (
            _money(
                _exact_product(
                    Decimal(row.planned_qty),
                    _exact_product(
                        _attr_decimal(symbol.ending_price),
                        _attr_decimal(symbol.ending_fx.rate),
                    ),
                ),
                f"attribution.weights.{row.bucket_id}.{row.symbol}.planned_at_end",
            )
            if symbol is not None
            else Decimal(0)
        )
        if _attr_decimal(row.planned_at_end_value_base) != planned_at_end_value:
            issues.append(
                _attribution_issue(
                    "attribution_weight_math_mismatch",
                    f"attribution.weights.{row.bucket_id}.{row.symbol}.planned_at_end_value_base",
                    "planned-at-end value must equal planned quantity at the ending mark",
                    bucket_id=row.bucket_id,
                )
            )
        planned_at_end_weight = (
            _weight(_ratio(planned_at_end_value, nav), "attribution.weights.planned_at_end_weight") if nav > 0 else Decimal(0)
        )
        if row.planned_at_end_weight != _weight_sum(
            planned_at_end_weight,
            "attribution.weights.planned_at_end_weight",
        ):
            issues.append(
                _attribution_issue(
                    "attribution_weight_math_mismatch",
                    f"attribution.weights.{row.bucket_id}.{row.symbol}.planned_at_end_weight",
                    "planned-at-end weight must equal planned-at-end value over end NAV",
                    bucket_id=row.bucket_id,
                )
            )
        expected_planned_weight = (
            _weight(
                _ratio(_attr_decimal(row.planned_value_base), planning_nav),
                "attribution.weights.planned_weight",
            )
            if planning_nav > 0
            else Decimal(0)
        )
        if row.planned_weight != _weight_sum(
            expected_planned_weight,
            "attribution.weights.planned_weight",
        ):
            issues.append(
                _attribution_issue(
                    "attribution_planned_weight_mismatch",
                    f"attribution.weights.{row.bucket_id}.{row.symbol}.planned_weight",
                    "planned weight must equal planned value over planning NAV",
                    bucket_id=row.bucket_id,
                )
            )
        target = (
            _attr_decimal(row.target_weight)
            if row.target_weight is not None
            else None
        )
        expected_target_gap = (
            _signed_weight(
                _attr_decimal(row.realized_weight) - target,
                "attribution.weights.target_gap",
            )
            if target is not None
            else None
        )
        if row.target_gap != expected_target_gap:
            issues.append(
                _attribution_issue(
                    "attribution_weight_math_mismatch",
                    f"attribution.weights.{row.bucket_id}.{row.symbol}.target_gap",
                    "target gap must be realized minus target weight",
                    bucket_id=row.bucket_id,
                )
            )
        expected_lot_gap = (
            _signed_weight(
                _attr_decimal(row.planned_weight) - target,
                "attribution.weights.lot_gap",
            )
            if target is not None
            else "0"
        )
        if row.lot_gap != expected_lot_gap:
            issues.append(
                _attribution_issue(
                    "attribution_weight_math_mismatch",
                    f"attribution.weights.{row.bucket_id}.{row.symbol}.lot_gap",
                    "lot gap must be planned minus target weight",
                    bucket_id=row.bucket_id,
                )
            )
        expected_price_gap = _signed_weight(
            _attr_decimal(row.planned_at_end_weight)
            - _attr_decimal(row.planned_weight),
            "attribution.weights.price_gap",
        )
        if row.price_gap != expected_price_gap:
            issues.append(
                _attribution_issue(
                    "attribution_weight_math_mismatch",
                    f"attribution.weights.{row.bucket_id}.{row.symbol}.price_gap",
                    "price gap must be planned-at-end minus planned weight",
                    bucket_id=row.bucket_id,
                )
            )
        expected_reject_gap = _signed_weight(
            _attr_decimal(row.realized_weight)
            - _attr_decimal(row.planned_at_end_weight),
            "attribution.weights.reject_gap",
        )
        if row.reject_gap != expected_reject_gap:
            issues.append(
                _attribution_issue(
                    "attribution_weight_math_mismatch",
                    f"attribution.weights.{row.bucket_id}.{row.symbol}.reject_gap",
                    "reject gap must be realized minus planned-at-end weight",
                    bucket_id=row.bucket_id,
                )
            )
        if row.qty_gap != row.realized_qty - row.planned_qty:
            issues.append(
                _attribution_issue(
                    "attribution_weight_math_mismatch",
                    f"attribution.weights.{row.bucket_id}.{row.symbol}.qty_gap",
                    "quantity gap must be realized minus planned quantity",
                    bucket_id=row.bucket_id,
                )
            )

    cash_total = Decimal(0)
    for row in cash_rows.values():
        cash_total = _exact_sum(
            (
                cash_total,
                _money(
                    _exact_product(
                        _attr_decimal(row.ending_cash),
                        _attr_decimal(row.ending_fx.rate),
                    ),
                    "attribution.weights.cash",
                ),
            )
        )
    bucket_reported = Decimal(0)
    for bucket_id, row in cash_rows.items():
        ending_cash = _attr_decimal(row.ending_cash)
        ending_local_money = Decimal(0)
        for symbol in symbol_by_key.values():
            if symbol.bucket_id == bucket_id:
                ending_local_money = _exact_sum(
                    (
                        ending_local_money,
                        _money(
                            _attr_decimal(symbol.ending_local_value),
                            "attribution.weights.ending_local",
                        ),
                    )
                )
        bucket_reported = _exact_sum(
            (
                bucket_reported,
                _money(
                    _exact_product(
                        _exact_sum((ending_cash, ending_local_money)),
                        _attr_decimal(row.ending_fx.rate),
                    ),
                    "attribution.weights.bucket_reported",
                ),
            )
        )
    if _attr_decimal(attribution.nav.end_nav_base) != bucket_reported:
        issues.append(
            _attribution_issue(
                "attribution_nav_mismatch",
                "attribution.nav.end_nav_base",
                "the reported end NAV must equal the per-bucket reported NAV sum",
            )
        )
    valuation_rounding = _exact_difference(
        _attr_decimal(attribution.nav.end_nav_base),
        _exact_sum((cash_total, position_values)),
    )
    realized_cash = _weight(_ratio(cash_total, nav), "attribution.weights.realized_cash") if nav > 0 else Decimal(0)
    valuation_weight = (
        _signed_weight_value(
            _ratio(valuation_rounding, nav),
            "attribution.weights.valuation_rounding",
        )
        if nav > 0
        else Decimal(0)
    )
    if weights.realized_cash_weight != _weight_sum(
        realized_cash,
        "attribution.weights.realized_cash",
    ):
        issues.append(
            _attribution_issue(
                "attribution_weight_math_mismatch",
                "attribution.weights.realized_cash_weight",
                "realized cash weight must equal ending cash over end NAV",
            )
        )
    if weights.valuation_rounding_weight != _weight_sum(
        valuation_weight,
        "attribution.weights.valuation_rounding",
    ):
        issues.append(
            _attribution_issue(
                "attribution_weight_math_mismatch",
                "attribution.weights.valuation_rounding_weight",
                "valuation rounding weight must equal NAV rounding over end NAV",
            )
        )
    target_total = _exact_sum(
        (
            _attr_decimal(row.target_weight)
            for row in weights.rows
            if row.target_weight is not None
        )
    )
    has_targets = any(row.target_weight is not None for row in weights.rows)
    if has_targets:
        if weights.target_weight_total != _weight_sum(
            target_total,
            "attribution.weights.target_total",
        ):
            issues.append(
                _attribution_issue(
                    "attribution_weight_math_mismatch",
                    "attribution.weights.target_weight_total",
                    "target total must equal the published target weights",
                )
            )
        target_cash = _exact_difference(Decimal(1), target_total)
        if weights.target_cash_weight != _weight_sum(
            target_cash,
            "attribution.weights.target_cash",
        ):
            issues.append(
                _attribution_issue(
                    "attribution_weight_math_mismatch",
                    "attribution.weights.target_cash_weight",
                    "target cash weight must be one minus target total",
                )
            )
    else:
        if weights.target_weight_total is not None or weights.target_cash_weight is not None:
            issues.append(
                _attribution_issue(
                    "attribution_weight_math_mismatch",
                    "attribution.weights.target_weight_total",
                    "explicit-order documents must not publish target weights",
                )
            )
        target_cash = None
    planned_total = _exact_sum(
        _attr_decimal(row.planned_weight) for row in weights.rows
    )
    realized_total = _exact_sum(
        _attr_decimal(row.realized_weight) for row in weights.rows
    )
    if weights.planned_weight_total != _weight_sum(
        planned_total,
        "attribution.weights.planned_total",
    ):
        issues.append(
            _attribution_issue(
                "attribution_weight_math_mismatch",
                "attribution.weights.planned_weight_total",
                "planned total must equal the published planned weights",
            )
        )
    if weights.planned_cash_weight != _weight_sum(
        _exact_difference(Decimal(1), planned_total),
        "attribution.weights.planned_cash",
    ):
        issues.append(
            _attribution_issue(
                "attribution_weight_math_mismatch",
                "attribution.weights.planned_cash_weight",
                "planned cash weight must be one minus planned total",
            )
        )
    if weights.realized_weight_total != _weight_sum(
        realized_total,
        "attribution.weights.realized_total",
    ):
        issues.append(
            _attribution_issue(
                "attribution_weight_math_mismatch",
                "attribution.weights.realized_weight_total",
                "realized total must equal the published realized weights",
            )
        )
    cash_basis = target_cash if target_cash is not None else _exact_difference(
        Decimal(1), planned_total
    )
    cash_gap = _exact_difference(realized_cash, cash_basis)
    if weights.cash_gap != _weight_sum(
        cash_gap,
        "attribution.weights.cash_gap",
    ):
        issues.append(
            _attribution_issue(
                "attribution_weight_math_mismatch",
                "attribution.weights.cash_gap",
                "cash gap must be realized cash minus the target or planned cash basis",
            )
        )
    lot_total = _exact_sum(
        _attr_decimal(row.lot_gap) for row in weights.rows
    )
    price_total = _exact_sum(
        _attr_decimal(row.price_gap) for row in weights.rows
    )
    reject_total = _exact_sum(
        _attr_decimal(row.reject_gap) for row in weights.rows
    )
    for name, expected in (
        ("lot_gap_total", lot_total),
        ("price_gap_total", price_total),
        ("reject_gap_total", reject_total),
    ):
        if getattr(weights, name) != _weight_sum(
            expected,
            f"attribution.weights.{name}",
        ):
            issues.append(
                _attribution_issue(
                    "attribution_weight_math_mismatch",
                    f"attribution.weights.{name}",
                    f"{name} must equal the published row sum",
                )
            )
    residual = _exact_sum(
        (
            lot_total,
            price_total,
            reject_total,
            cash_gap,
            valuation_weight,
        )
    )
    if weights.weight_rounding_residual != _weight_sum(
        residual,
        "attribution.weights.residual",
    ):
        issues.append(
            _attribution_issue(
                "attribution_weight_rounding_mismatch",
                "attribution.weights.weight_rounding_residual",
                "the weight residual must be the unfitted gap sum",
            )
        )
    tolerance = _weight_rounding_tolerance(len(weights.rows))
    if weights.weight_rounding_tolerance != _weight_sum(
        tolerance,
        "attribution.weights.tolerance",
    ):
        issues.append(
            _attribution_issue(
                "attribution_weight_rounding_mismatch",
                "attribution.weights.weight_rounding_tolerance",
                "the declared tolerance must be the row-count rounding bound",
            )
        )
    if abs(residual) > tolerance:
        issues.append(
            _attribution_issue(
                "attribution_weight_identity_mismatch",
                "attribution.weights",
                "weight gaps exceed the declared rounding tolerance",
            )
        )
    if weights.reconciled and abs(residual) > tolerance:
        issues.append(
            _attribution_issue(
                "attribution_weight_rounding_mismatch",
                "attribution.weights.reconciled",
                "a reconciled verdict cannot carry an out-of-bound residual",
            )
        )


def build_portfolio_analytics(
    request: PortfolioRequest,
    ledger: PortfolioLedger,
    prepared: PreparedPortfolioData,
    *,
    conversion_events: Sequence[FxConversionEvent] = (),
    opening_ledger: PortfolioLedger | None = None,
    post_conversion_ledger: PortfolioLedger | None = None,
    fills: Sequence[ExecutionFill] = (),
    rejected_orders: Sequence[ExecutionRejection] = (),
    canceled_orders: Sequence[ExecutionCancellation] = (),
    plan: OrderPlan | None = None,
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

    benchmark = _benchmark(
        request,
        opening_ledger=opening_ledger,
        prepared=prepared,
        base_currency=base_currency,
        book=book,
        nav_base=nav_base,
        exact_nav_base=exact_nav_base,
    )
    if opening_ledger is None:
        _reject(
            "missing_attribution_input",
            "attribution.opening_ledger",
            detail="attribution needs the actual opening ledger",
        )
    if post_conversion_ledger is None:
        _reject(
            "missing_attribution_input",
            "attribution.post_conversion_ledger",
            detail="attribution needs the actual post-conversion ledger",
        )
    if plan is None:
        _reject(
            "missing_attribution_input",
            "attribution.plan",
            detail="attribution needs the executed order plan",
        )
    attribution = _attribution(
        request,
        prepared=prepared,
        opening_ledger=opening_ledger,
        post_conversion_ledger=post_conversion_ledger,
        end_ledger=ledger,
        conversion_events=conversion_events,
        fills=fills,
        rejected_orders=rejected_orders,
        canceled_orders=canceled_orders,
        plan=plan,
        cash_rows=cash_rows,
        position_rows=position_rows,
        valuation_rounding=valuation_rounding,
        nav_base=nav_base,
        exact_nav_base=exact_nav_base,
        book=book,
        marks=marks,
    )
    benchmark_fx = () if benchmark is None else (benchmark.start.fx, benchmark.end.fx)
    fx_references = tuple(
        reference
        for row in (*cash_rows, *position_rows)
        for reference in (row.fx,)
    ) + benchmark_fx + attribution.provenance.fx

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
            fx_references,
        ),
        benchmark=benchmark,
        attribution=attribution,
        warnings=warnings,
    )
