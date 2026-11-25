"""Exact analytics recomputation for the public pt-v2.0 wire.

The optional ``analytics`` object is checked against the public ledger by
``wire_success._assert_analytics``; this module owns the exact-arithmetic
helpers and the per-section validators (benchmark observations, one-day
attribution) that recompute every published ratio and reconciliation before
the document can be published. Each refusal raises
:class:`~.wire_errors.PortfolioWireError` (INTERNAL transport), never an
in-band error envelope.
"""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal, localcontext

from pydantic import ValidationError

from .analytics import reconcile_attribution
from .models import AnalyticsAttribution, JsonObject, JsonValue
from .wire_contract import _DECIMAL_PATTERN
from .wire_errors import _reject
from .wire_normalize import _location_path, _pydantic_reason


def _decimal_value(value: JsonValue, path: str) -> Decimal:
    """Read a canonical public decimal after the shape/decimal checks."""
    if not isinstance(value, str) or _DECIMAL_PATTERN.fullmatch(value) is None:
        _reject("invalid_decimal", path, detail="expected a canonical fixed-point string")
    return Decimal(value)


def _analytics_sum(rows: list[JsonValue], path: str) -> Decimal:
    total = Decimal(0)
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            _reject("invalid_analytics", f"{path}[{index}]")
        total += _decimal_value(row.get("value_base"), f"{path}[{index}].value_base")
    return total


def _exact_change(numerator: Decimal, denominator: Decimal) -> Decimal:
    """Recompute the published 60-digit one-day ratio exactly, never at 28 digits."""
    with localcontext() as context:
        context.prec = 60
        return numerator / denominator - 1


def _exact_difference(left: Decimal, right: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = 60
        return left - right


def _canonical_ratio(value: Decimal, path: str) -> str:
    """Render one signed ratio at the published twelve-decimal scale."""
    if not value.is_finite():
        _reject("invalid_benchmark", path, detail="ratios must be finite")
    quantized = value.quantize(Decimal(1).scaleb(-12), rounding=ROUND_HALF_EVEN)
    if quantized.is_zero():
        quantized = Decimal(0)
    return format(quantized, ".12f")


def _canonical_money(value: Decimal, path: str) -> str:
    """Render one money value at the published two-decimal scale."""
    if not value.is_finite():
        _reject("invalid_benchmark", path, detail="money must be finite")
    quantized = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
    if quantized.is_zero():
        quantized = Decimal(0)
    return format(quantized, ".2f")


def _assert_benchmark(payload: JsonObject, *, nav: Decimal, exact_nav: Decimal) -> None:
    """Recompute every benchmark ratio from its exact observations."""
    required = (
        "benchmark_id",
        "start",
        "end",
        "benchmark_return",
        "exact_benchmark_return",
        "portfolio_start_nav_base",
        "portfolio_start_exact_nav_base",
        "portfolio_start_rounding_residual",
        "portfolio_end_nav_base",
        "portfolio_end_exact_nav_base",
        "portfolio_return",
        "exact_portfolio_return",
        "deviation",
        "exact_deviation",
    )
    for key in required:
        if key not in payload:
            _reject("missing_field", f"analytics.benchmark.{key}")
    if not isinstance(payload.get("benchmark_id"), str) or not payload["benchmark_id"]:
        _reject("invalid_benchmark", "analytics.benchmark.benchmark_id")
    observations: list[Decimal] = []
    for leg in ("start", "end"):
        raw = payload.get(leg)
        if not isinstance(raw, dict):
            _reject("invalid_benchmark", f"analytics.benchmark.{leg}")
        exact = _decimal_value(
            raw.get("exact_value_base"),
            f"analytics.benchmark.{leg}.exact_value_base",
        )
        level = _decimal_value(
            raw.get("value"),
            f"analytics.benchmark.{leg}.value",
        )
        if exact <= 0 or level <= 0:
            _reject(
                "invalid_benchmark",
                f"analytics.benchmark.{leg}.exact_value_base",
                detail="benchmark levels must be positive",
            )
        reported = _decimal_value(
            raw.get("value_base"),
            f"analytics.benchmark.{leg}.value_base",
        )
        if _canonical_money(exact, f"analytics.benchmark.{leg}") != raw.get("value_base"):
            _reject(
                "benchmark_observation_mismatch",
                f"analytics.benchmark.{leg}.value_base",
            )
        residual = _decimal_value(
            raw.get("rounding_residual"),
            f"analytics.benchmark.{leg}.rounding_residual",
        )
        if residual != _exact_difference(exact, reported):
            _reject(
                "benchmark_observation_mismatch",
                f"analytics.benchmark.{leg}.rounding_residual",
            )
        observations.append(exact)

    start_nav = _decimal_value(
        payload.get("portfolio_start_exact_nav_base"),
        "analytics.benchmark.portfolio_start_exact_nav_base",
    )
    end_nav = _decimal_value(
        payload.get("portfolio_end_exact_nav_base"),
        "analytics.benchmark.portfolio_end_exact_nav_base",
    )
    if start_nav <= 0 or end_nav <= 0:
        _reject(
            "invalid_benchmark",
            "analytics.benchmark.portfolio_start_exact_nav_base",
            detail="portfolio NAVs must be positive",
        )
    reported_start = _decimal_value(
        payload.get("portfolio_start_nav_base"),
        "analytics.benchmark.portfolio_start_nav_base",
    )
    if reported_start != Decimal(
        _canonical_money(
            reported_start,
            "analytics.benchmark.portfolio_start_nav_base",
        )
    ):
        _reject(
            "benchmark_nav_mismatch",
            "analytics.benchmark.portfolio_start_nav_base",
            detail="the reported start NAV must represent whole cents",
        )
    start_residual = _decimal_value(
        payload.get("portfolio_start_rounding_residual"),
        "analytics.benchmark.portfolio_start_rounding_residual",
    )
    if reported_start + start_residual != start_nav:
        _reject(
            "benchmark_nav_mismatch",
            "analytics.benchmark.portfolio_start_rounding_residual",
            detail="the reported start NAV plus its residual must equal the exact start NAV",
        )
    if _decimal_value(
        payload.get("portfolio_end_nav_base"),
        "analytics.benchmark.portfolio_end_nav_base",
    ) != nav:
        _reject(
            "benchmark_nav_mismatch",
            "analytics.benchmark.portfolio_end_nav_base",
            detail="the benchmark end NAV must equal analytics NAV",
        )
    if end_nav != exact_nav:
        _reject(
            "benchmark_nav_mismatch",
            "analytics.benchmark.portfolio_end_exact_nav_base",
            detail="the benchmark exact end NAV must equal analytics exact NAV",
        )
    exact_benchmark_return = _exact_change(observations[1], observations[0])
    exact_portfolio_return = _exact_change(end_nav, start_nav)
    exact_deviation = _exact_difference(exact_portfolio_return, exact_benchmark_return)
    expected = (
        (
            "exact_benchmark_return",
            exact_benchmark_return,
            "benchmark_return_mismatch",
        ),
        (
            "exact_portfolio_return",
            exact_portfolio_return,
            "benchmark_portfolio_return_mismatch",
        ),
        ("exact_deviation", exact_deviation, "benchmark_deviation_mismatch"),
    )
    for key, value, reason in expected:
        if _decimal_value(
            payload.get(key),
            f"analytics.benchmark.{key}",
        ) != value:
            _reject(
                reason,
                f"analytics.benchmark.{key}",
            )
    for key, value in (
        ("benchmark_return", exact_benchmark_return),
        ("portfolio_return", exact_portfolio_return),
        ("deviation", exact_deviation),
    ):
        if payload.get(key) != _canonical_ratio(
            value,
            f"analytics.benchmark.{key}",
        ):
            _reject(
                "benchmark_return_mismatch"
                if key == "benchmark_return"
                else f"benchmark_{key}_mismatch",
                f"analytics.benchmark.{key}",
            )

def _assert_attribution(
    raw: JsonObject,
    *,
    nav: Decimal,
    exact_nav: Decimal,
    base_currency: str,
) -> None:
    """Recompute the optional one-day attribution before publishing it."""
    try:
        attribution = AnalyticsAttribution.model_validate(raw)
    except ValidationError as exc:
        first = exc.errors()[0]
        path = _location_path(tuple(first.get("loc", ())))
        _reject(
            _pydantic_reason(str(first.get("type", "")), path),
            f"analytics.attribution.{path}",
            detail=str(first.get("msg", "invalid attribution value")),
        )
    if attribution.base_currency != base_currency:
        _reject(
            "attribution_base_currency_mismatch",
            "analytics.attribution.base_currency",
            detail="attribution must use the document base currency",
        )
    if _decimal_value(
        attribution.nav.end_nav_base,
        "analytics.attribution.nav.end_nav_base",
    ) != nav:
        _reject(
            "attribution_nav_mismatch",
            "analytics.attribution.nav.end_nav_base",
            detail="attribution end NAV must equal analytics NAV",
        )
    if _decimal_value(
        attribution.nav.end_exact_nav_base,
        "analytics.attribution.nav.end_exact_nav_base",
    ) != exact_nav:
        _reject(
            "attribution_nav_mismatch",
            "analytics.attribution.nav.end_exact_nav_base",
            detail="attribution exact end NAV must equal analytics exact NAV",
        )
    try:
        issues = reconcile_attribution(attribution)
    except (ArithmeticError, ValueError) as exc:
        _reject(
            "invalid_attribution",
            "analytics.attribution",
            detail=f"{type(exc).__name__}: {exc}"[:200],
        )
    if issues:
        first = issues[0]
        path = (
            first.path
            if first.path.startswith("attribution.")
            else f"analytics.attribution.{first.path}"
        )
        _reject(
            first.reason,
            f"analytics.{path}",
            bucket_id=first.bucket_id,
            detail=first.detail,
        )
    if not attribution.reconciliation.reconciled:
        _reject(
            "attribution_not_reconciled",
            "analytics.attribution.reconciliation",
            detail="the attribution document declares a failed reconciliation",
        )
    if attribution.reconciliation.issues or not all(
        check.passed for check in attribution.reconciliation.checks
    ):
        _reject(
            "attribution_reconciliation_mismatch",
            "analytics.attribution.reconciliation",
            detail="a reconciled verdict cannot carry issues or failed checks",
        )
