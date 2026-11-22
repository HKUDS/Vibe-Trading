"""Pre-fill conversion replay from the published analytics rows."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from .models import PortfolioResult
from .reconcile_primitives import _ZERO, _exact, _issue, _money_even, _money_text, _text
from .reconcile_state import _state_maps


def _apply_conversions(
    issues: list[dict[str, Any]],
    document: PortfolioResult,
    buckets: dict[str, Any],
    cash: dict[str, Decimal],
    not_verified: list[str],
) -> tuple[bool, set[str]]:
    """Replay pre-fill conversions from the declared analytics rows.

    Returns whether the conversion arithmetic could be independently replayed
    and which buckets' cash stays unverified because their conversion could not
    be replayed. A conversion without a published rate or a conversion that
    fails its own replay leaves only its declared buckets unverified rather
    than silently assuming every converted bucket correct.
    """
    conversions = list(document.conversions)
    if not conversions:
        return True, set()
    conversion_buckets = {
        bucket_id
        for conversion in conversions
        for bucket_id in (conversion.from_bucket_id, conversion.to_bucket_id)
    }
    unverified_buckets: set[str] = set()
    analytics = document.analytics
    if analytics is None:
        not_verified.append(
            "fx conversion rates are absent without analytics; post-conversion "
            "cash and affected end-cash rows were not replayed."
        )
        return False, conversion_buckets
    rows = list(analytics.conversion_rows)
    if len(rows) != len(conversions):
        _issue(
            issues,
            "conversion_mismatch",
            "conversions",
            len(conversions),
            len(rows),
        )
    available = dict(cash)
    for index, conversion in enumerate(conversions):
        path = f"conversions[{index}]"
        if index >= len(rows):
            unverified_buckets.update(
                (conversion.from_bucket_id, conversion.to_bucket_id)
            )
            continue
        row = rows[index]
        if (
            conversion.rate_id != row.rate_id
            or conversion.from_bucket_id != row.from_bucket_id
            or conversion.to_bucket_id != row.to_bucket_id
            or Decimal(conversion.amount) != Decimal(row.source_amount)
        ):
            _issue(
                issues,
                "conversion_mismatch",
                path,
                {
                    "rate_id": conversion.rate_id,
                    "from_bucket_id": conversion.from_bucket_id,
                    "to_bucket_id": conversion.to_bucket_id,
                    "amount": conversion.amount,
                },
                {
                    "rate_id": row.rate_id,
                    "from_bucket_id": row.from_bucket_id,
                    "to_bucket_id": row.to_bucket_id,
                    "amount": row.source_amount,
                },
            )
        source_bucket = buckets.get(conversion.from_bucket_id)
        target_bucket = buckets.get(conversion.to_bucket_id)
        if source_bucket is None or target_bucket is None:
            _issue(
                issues,
                "conversion_bucket_mismatch",
                path,
                "declared buckets",
                {
                    "from": conversion.from_bucket_id,
                    "to": conversion.to_bucket_id,
                },
            )
            continue
        if (
            source_bucket.currency != row.from_currency
            or target_bucket.currency != row.to_currency
        ):
            _issue(
                issues,
                "conversion_currency_mismatch",
                path,
                {
                    "from": source_bucket.currency,
                    "to": target_bucket.currency,
                },
                {"from": row.from_currency, "to": row.to_currency},
            )
        source = Decimal(row.source_amount)
        rate = Decimal(row.rate)
        if rate <= 0:
            _issue(
                issues,
                "conversion_arithmetic_mismatch",
                f"{path}.rate",
                "> 0",
                row.rate,
            )
            continue
        exact = _exact(source, rate)
        expected_converted = _money_even(exact)
        expected_residual = exact - expected_converted
        declared_exact = Decimal(row.exact_converted)
        declared_converted = Decimal(row.converted_amount)
        declared_residual = Decimal(row.rounding_residual_local)
        if declared_exact != exact:
            _issue(
                issues,
                "conversion_arithmetic_mismatch",
                f"{path}.exact_converted",
                _text(exact),
                _text(declared_exact),
            )
        if declared_converted != expected_converted:
            _issue(
                issues,
                "conversion_arithmetic_mismatch",
                f"{path}.converted_amount",
                _money_text(expected_converted),
                _money_text(declared_converted),
            )
        if declared_residual != expected_residual:
            _issue(
                issues,
                "conversion_arithmetic_mismatch",
                f"{path}.rounding_residual_local",
                _text(expected_residual),
                _text(declared_residual),
            )
        expected_residual_base = _exact(
            expected_residual, Decimal(row.valuation_fx.rate)
        )
        if Decimal(row.rounding_residual_base) != expected_residual_base:
            _issue(
                issues,
                "conversion_arithmetic_mismatch",
                f"{path}.rounding_residual_base",
                _text(expected_residual_base),
                _text(Decimal(row.rounding_residual_base)),
            )
        if source <= 0:
            _issue(issues, "conversion_arithmetic_mismatch", f"{path}.amount", "> 0", conversion.amount)
            continue
        if available.get(conversion.from_bucket_id, _ZERO) < source:
            _issue(
                issues,
                "insufficient_conversion_cash",
                f"{path}.amount",
                _money_text(available.get(conversion.from_bucket_id, _ZERO)),
                _money_text(source),
            )
            continue
        available[conversion.from_bucket_id] -= source
        cash[conversion.from_bucket_id] -= source
        cash[conversion.to_bucket_id] += expected_converted
    return True, unverified_buckets


def _check_post_conversion(
    issues: list[dict[str, Any]],
    document: PortfolioResult,
    cash: dict[str, Decimal],
    positions: dict[tuple[str, str], dict[str, Any]],
    conversions_replayed: bool,
) -> None:
    post_cash, post_positions = _state_maps(document.post_conversion_portfolio)
    opening_buckets = {
        bucket.bucket_id: bucket for bucket in document.opening_portfolio.buckets
    }
    for bucket in document.post_conversion_portfolio.buckets:
        expected_bucket = opening_buckets.get(bucket.bucket_id)
        if expected_bucket is None:
            continue
        bucket_path = f"post_conversion_portfolio.buckets.{bucket.bucket_id}"
        if expected_bucket.market != bucket.market:
            _issue(
                issues,
                "conversion_bucket_mismatch",
                f"{bucket_path}.market",
                expected_bucket.market,
                bucket.market,
            )
        if expected_bucket.currency != bucket.currency:
            _issue(
                issues,
                "conversion_bucket_mismatch",
                f"{bucket_path}.currency",
                expected_bucket.currency,
                bucket.currency,
            )
    if not document.conversions or conversions_replayed:
        for bucket_id in sorted(set(cash) | set(post_cash)):
            path = f"post_conversion_portfolio.buckets.{bucket_id}.cash"
            if bucket_id not in post_cash:
                _issue(issues, "conversion_cash_mismatch", path, _money_text(cash[bucket_id]), None)
                continue
            if bucket_id not in cash:
                _issue(issues, "conversion_cash_mismatch", path, None, _money_text(post_cash[bucket_id]))
                continue
            if cash[bucket_id] != post_cash[bucket_id]:
                _issue(
                    issues,
                    "conversion_cash_mismatch",
                    path,
                    _money_text(cash[bucket_id]),
                    _money_text(post_cash[bucket_id]),
                )
        for key in sorted(set(positions) | set(post_positions)):
            bucket_id, symbol = key
            path = f"post_conversion_portfolio.buckets.{bucket_id}.positions[{symbol}]"
            if key not in positions:
                _issue(issues, "conversion_position_mismatch", path, None, post_positions[key]["qty"])
                continue
            if key not in post_positions:
                _issue(issues, "conversion_position_mismatch", path, positions[key]["qty"], None)
                continue
            if positions[key]["qty"] != post_positions[key]["qty"]:
                _issue(
                    issues,
                    "conversion_position_mismatch",
                    f"{path}.qty",
                    positions[key]["qty"],
                    post_positions[key]["qty"],
                )
            if positions[key]["currency"] != post_positions[key]["currency"]:
                _issue(
                    issues,
                    "conversion_position_mismatch",
                    f"{path}.currency",
                    positions[key]["currency"],
                    post_positions[key]["currency"],
                )
