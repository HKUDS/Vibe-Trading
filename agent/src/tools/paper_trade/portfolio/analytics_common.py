"""Shared constants, marks and exact-arithmetic helpers for portfolio analytics.

Every analytics cluster imports these helpers. The precision constant, the
rejection raiser and the exact product are re-exported from the canonical
``numeric`` module; the analytics-specific transforms stay here byte-identical
to the pre-split monolith.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal, localcontext
from typing import Final, NoReturn

from .data import PreparedPortfolioData
from .fx import FxRateBook
from .ledger import PortfolioLedger
from .models import (
    AnalyticsFxReference,
    AnalyticsMarkReference,
    AnalyticsPositionRow,
    Currency,
    PortfolioIssue,
)
from .numeric import (
    FX_RATE_SPEC,
    MONEY_SPEC,
    PRICE_SPEC,
    WEIGHT_SPEC,
    DecimalSpec,
    _EXACT_PRECISION,
    _exact_product as _exact_product,
    _reject as _reject,
    canonical_decimal,
    parse_price,
)
from .orchestrator import OrchestrationError


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


def _invariant(reason: str, path: str, detail: str = "") -> NoReturn:
    raise OrchestrationError(
        stage="valuate_reconcile",
        reason=reason,
        code="INTERNAL",
        path=path,
        detail=detail,
    )


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


def _attr_decimal(value: str) -> Decimal:
    return Decimal(value)
