"""Optional one-day benchmark projection for portfolio analytics.

Translates the caller's declared start/end observations through their own
direct FX pairs and compares the benchmark return with the portfolio's own
one-day return from strictly-prior planning marks.
"""

from __future__ import annotations

from datetime import timezone
from decimal import Decimal

from .analytics_common import (
    _BENCHMARK_MAX_AGE,
    _RETURN_SPEC,
    _exact_change,
    _exact_difference,
    _exact_product,
    _exact_text,
    _invariant,
    _money,
    _price_text,
    _rate_text,
    _reject,
    _return_value,
)
from .data import PreparedPortfolioData
from .fx import FxRateBook
from .ledger import PortfolioLedger, value_ledger
from .models import (
    AnalyticsBenchmark,
    AnalyticsBenchmarkObservation,
    AnalyticsFxReference,
    BenchmarkObservation,
    Currency,
    PortfolioRequest,
)
from .numeric import MONEY_SPEC, canonical_decimal, parse_price
from .schema import PortfolioRequestError


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
