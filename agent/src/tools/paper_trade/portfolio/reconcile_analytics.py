"""End-state, NAV bridge, exposure and concentration recomputation."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from .models import PortfolioResult
from .reconcile_attribution import _check_attribution
from .reconcile_primitives import (
    _ZERO,
    _exact,
    _issue,
    _money_even,
    _money_text,
    _ratio,
    _text,
    _weight,
)
from .reconcile_state import _state_maps


def _check_end_state(
    issues: list[dict[str, Any]],
    document: PortfolioResult,
    cash: dict[str, Decimal],
    positions: dict[tuple[str, str], dict[str, Any]],
    *,
    unverified_cash_buckets: set[str],
) -> None:
    end_cash, end_positions = _state_maps(document.end_portfolio)
    opening_buckets = {
        bucket.bucket_id: bucket for bucket in document.opening_portfolio.buckets
    }
    for bucket in document.end_portfolio.buckets:
        expected_bucket = opening_buckets.get(bucket.bucket_id)
        if expected_bucket is None:
            continue
        bucket_path = f"end_portfolio.buckets.{bucket.bucket_id}"
        if expected_bucket.market != bucket.market:
            _issue(
                issues,
                "end_bucket_mismatch",
                f"{bucket_path}.market",
                expected_bucket.market,
                bucket.market,
            )
        if expected_bucket.currency != bucket.currency:
            _issue(
                issues,
                "end_bucket_mismatch",
                f"{bucket_path}.currency",
                expected_bucket.currency,
                bucket.currency,
            )
    for bucket_id in sorted(set(cash) | set(end_cash)):
        if bucket_id in unverified_cash_buckets:
            continue
        path = f"end_portfolio.buckets.{bucket_id}.cash"
        if bucket_id not in end_cash:
            _issue(issues, "end_cash_mismatch", path, _money_text(cash[bucket_id]), None)
            continue
        if bucket_id not in cash:
            _issue(issues, "end_cash_mismatch", path, None, _money_text(end_cash[bucket_id]))
            continue
        if cash[bucket_id] != end_cash[bucket_id]:
            _issue(
                issues,
                "end_cash_mismatch",
                path,
                _money_text(cash[bucket_id]),
                _money_text(end_cash[bucket_id]),
            )
    for key in sorted(set(positions) | set(end_positions)):
        bucket_id, symbol = key
        path = f"end_portfolio.buckets.{bucket_id}.positions[{symbol}]"
        expected = positions.get(key)
        actual = end_positions.get(key)
        if actual is not None and actual["qty"] == 0:
            _issue(issues, "zero_end_position", f"{path}.qty", "nonzero or omitted", 0)
        if expected is None:
            if actual is not None and actual["qty"] != 0:
                _issue(
                    issues,
                    "unexpected_end_position",
                    path,
                    None,
                    actual["qty"],
                )
            continue
        if actual is None:
            _issue(issues, "missing_end_position", path, expected["qty"], None)
            continue
        if expected["qty"] != actual["qty"]:
            _issue(
                issues,
                "end_position_qty_mismatch",
                f"{path}.qty",
                expected["qty"],
                actual["qty"],
            )
        if expected["avg_cost"] != actual["avg_cost"]:
            _issue(
                issues,
                "end_position_avg_cost_mismatch",
                f"{path}.avg_cost",
                _money_text(expected["avg_cost"]),
                _money_text(actual["avg_cost"]),
            )
        if expected["currency"] != actual["currency"]:
            _issue(
                issues,
                "end_position_currency_mismatch",
                f"{path}.currency",
                expected["currency"],
                actual["currency"],
            )


def _analytics_checks(
    issues: list[dict[str, Any]],
    document: PortfolioResult,
    cash: dict[str, Decimal],
    positions: dict[tuple[str, str], dict[str, Any]],
    not_verified: list[str],
) -> None:
    analytics = document.analytics
    if analytics is None:
        not_verified.append(
            "analytics is absent; NAV, exposure and attribution arithmetic was not recomputed."
        )
        return

    nav_base = Decimal(analytics.nav_base)
    if analytics.base_currency != document.base_currency:
        _issue(
            issues,
            "analytics_nav_mismatch",
            "analytics.base_currency",
            document.base_currency,
            analytics.base_currency,
        )
    if analytics.valuation_at != document.valuation_at:
        _issue(
            issues,
            "analytics_nav_mismatch",
            "analytics.valuation_at",
            document.valuation_at.isoformat(),
            analytics.valuation_at.isoformat(),
        )
    cash_by_bucket: dict[str, Decimal] = {}
    cash_exact_by_bucket: dict[str, Decimal] = {}
    for index, row in enumerate(analytics.cash_rows):
        path = f"analytics.cash_rows[{index}]"
        bucket_cash = cash.get(row.bucket_id)
        if bucket_cash is None:
            _issue(issues, "analytics_cash_mismatch", f"{path}.bucket_id", "declared bucket", row.bucket_id)
            continue
        if Decimal(row.amount) != bucket_cash:
            _issue(
                issues,
                "analytics_cash_mismatch",
                f"{path}.amount",
                _money_text(bucket_cash),
                _money_text(Decimal(row.amount)),
            )
        rate = Decimal(row.fx.rate)
        exact = _exact(bucket_cash, rate)
        value = _money_even(exact)
        if Decimal(row.exact_value_base) != exact:
            _issue(
                issues,
                "analytics_rounding_mismatch",
                f"{path}.exact_value_base",
                _text(exact),
                _text(Decimal(row.exact_value_base)),
            )
        if Decimal(row.value_base) != value:
            _issue(
                issues,
                "analytics_rounding_mismatch",
                f"{path}.value_base",
                _money_text(value),
                _money_text(Decimal(row.value_base)),
            )
        if Decimal(row.rounding_residual) != exact - value:
            _issue(
                issues,
                "analytics_rounding_mismatch",
                f"{path}.rounding_residual",
                _text(exact - value),
                _text(Decimal(row.rounding_residual)),
            )
        cash_by_bucket[row.bucket_id] = value
        cash_exact_by_bucket[row.bucket_id] = exact

    position_value_by_bucket: dict[str, Decimal] = {}
    position_exact_by_bucket: dict[str, Decimal] = {}
    local_value_by_bucket: dict[str, Decimal] = {}
    position_rows: dict[tuple[str, str], Any] = {}
    for index, row in enumerate(analytics.position_rows):
        path = f"analytics.position_rows[{index}]"
        key = (row.bucket_id, row.symbol)
        if key in position_rows:
            _issue(
                issues,
                "analytics_position_mismatch",
                f"{path}.symbol",
                "one row per position",
                row.symbol,
            )
        position_rows[key] = row
        holding = positions.get(key)
        if holding is None:
            _issue(
                issues,
                "analytics_position_mismatch",
                path,
                "held position",
                {"bucket_id": row.bucket_id, "symbol": row.symbol},
            )
            continue
        if row.qty != holding["qty"]:
            _issue(
                issues,
                "analytics_position_mismatch",
                f"{path}.qty",
                holding["qty"],
                row.qty,
            )
        price = Decimal(row.price)
        if price <= 0:
            _issue(issues, "analytics_position_mismatch", f"{path}.price", "> 0", row.price)
            continue
        exact_local = _exact(Decimal(row.qty), price)
        local_value = _money_even(exact_local)
        rate = Decimal(row.fx.rate)
        exact_base = _exact(local_value, rate)
        value_base = _money_even(exact_base)
        if Decimal(row.local_value) != local_value:
            _issue(
                issues,
                "analytics_position_mismatch",
                f"{path}.local_value",
                _money_text(local_value),
                _money_text(Decimal(row.local_value)),
            )
        if Decimal(row.exact_value_base) != exact_base:
            _issue(
                issues,
                "analytics_rounding_mismatch",
                f"{path}.exact_value_base",
                _text(exact_base),
                _text(Decimal(row.exact_value_base)),
            )
        if Decimal(row.value_base) != value_base:
            _issue(
                issues,
                "analytics_position_mismatch",
                f"{path}.value_base",
                _money_text(value_base),
                _money_text(Decimal(row.value_base)),
            )
        if Decimal(row.rounding_residual) != exact_base - value_base:
            _issue(
                issues,
                "analytics_rounding_mismatch",
                f"{path}.rounding_residual",
                _text(exact_base - value_base),
                _text(Decimal(row.rounding_residual)),
            )
        expected_weight = _weight(_ratio(value_base, nav_base)) if nav_base > 0 else _ZERO
        if Decimal(row.weight) != expected_weight:
            _issue(
                issues,
                "analytics_exposure_mismatch",
                f"{path}.weight",
                format(expected_weight, ".12f"),
                row.weight,
            )
        position_value_by_bucket[row.bucket_id] = (
            position_value_by_bucket.get(row.bucket_id, _ZERO) + value_base
        )
        position_exact_by_bucket[row.bucket_id] = (
            position_exact_by_bucket.get(row.bucket_id, _ZERO) + exact_base
        )
        local_value_by_bucket[row.bucket_id] = (
            local_value_by_bucket.get(row.bucket_id, _ZERO) + local_value
        )

    expected_keys = {key for key, value in positions.items() if value["qty"] != 0}
    for key in sorted(expected_keys):
        if key not in position_rows:
            _issue(
                issues,
                "analytics_position_mismatch",
                f"analytics.position_rows[{key[0]}.{key[1]}]",
                "held position row",
                None,
            )

    bucket_exposures: dict[str, Any] = {}
    for index, row in enumerate(analytics.bucket_exposures):
        path = f"analytics.bucket_exposures[{index}]"
        bucket_exposures[row.bucket_id] = row
        cash_base = cash_by_bucket.get(row.bucket_id, _ZERO)
        cash_exact = cash_exact_by_bucket.get(row.bucket_id, _ZERO)
        position_value = position_value_by_bucket.get(row.bucket_id, _ZERO)
        position_exact = position_exact_by_bucket.get(row.bucket_id, _ZERO)
        if Decimal(row.cash_base) != cash_base:
            _issue(
                issues,
                "analytics_exposure_mismatch",
                f"{path}.cash_base",
                _money_text(cash_base),
                _money_text(Decimal(row.cash_base)),
            )
        if Decimal(row.position_value_base) != position_value:
            _issue(
                issues,
                "analytics_exposure_mismatch",
                f"{path}.position_value_base",
                _money_text(position_value),
                _money_text(Decimal(row.position_value_base)),
            )
        rounding = Decimal(row.valuation_rounding)
        value_base = cash_base + position_value + rounding
        if Decimal(row.value_base) != value_base:
            _issue(
                issues,
                "analytics_exposure_mismatch",
                f"{path}.value_base",
                _money_text(value_base),
                _money_text(Decimal(row.value_base)),
            )
        exact_value = cash_exact + position_exact
        if Decimal(row.exact_value_base) != exact_value:
            _issue(
                issues,
                "analytics_rounding_mismatch",
                f"{path}.exact_value_base",
                _text(exact_value),
                _text(Decimal(row.exact_value_base)),
            )
        if Decimal(row.rounding_residual) != exact_value - value_base:
            _issue(
                issues,
                "analytics_rounding_mismatch",
                f"{path}.rounding_residual",
                _text(exact_value - value_base),
                _text(Decimal(row.rounding_residual)),
            )

    for result_row in document.bucket_results:
        exposure = bucket_exposures.get(result_row.bucket_id)
        if exposure is None:
            _issue(
                issues,
                "bucket_nav_mismatch",
                f"bucket_results[{result_row.bucket_id}].nav_base",
                "analytics bucket exposure",
                None,
            )
            continue
        if Decimal(result_row.nav_base) != Decimal(exposure.value_base):
            _issue(
                issues,
                "bucket_nav_mismatch",
                f"bucket_results[{result_row.bucket_id}].nav_base",
                exposure.value_base,
                result_row.nav_base,
            )
        if (
            result_row.market != exposure.market
            or result_row.currency != exposure.currency
        ):
            _issue(
                issues,
                "bucket_row_mismatch",
                f"bucket_results[{result_row.bucket_id}]",
                {
                    "market": exposure.market,
                    "currency": exposure.currency,
                },
                {
                    "market": result_row.market,
                    "currency": result_row.currency,
                },
            )
        expected_rate_id = (
            None
            if result_row.currency == document.base_currency
            else exposure.fx.rate_id
        )
        if result_row.fx_rate_id != expected_rate_id:
            _issue(
                issues,
                "bucket_fx_mismatch",
                f"bucket_results[{result_row.bucket_id}].fx_rate_id",
                expected_rate_id,
                result_row.fx_rate_id,
            )
        if Decimal(result_row.position_value) != local_value_by_bucket.get(
            result_row.bucket_id, _ZERO
        ):
            _issue(
                issues,
                "bucket_position_value_mismatch",
                f"bucket_results[{result_row.bucket_id}].position_value",
                _money_text(local_value_by_bucket.get(result_row.bucket_id, _ZERO)),
                result_row.position_value,
            )

    cash_total = sum(cash_by_bucket.values(), _ZERO)
    position_total = sum(position_value_by_bucket.values(), _ZERO)
    exact_total = sum(cash_exact_by_bucket.values(), _ZERO) + sum(
        position_exact_by_bucket.values(), _ZERO
    )
    rounding_total = sum(
        (Decimal(row.valuation_rounding) for row in analytics.bucket_exposures), _ZERO
    )
    reported_total = cash_total + position_total + rounding_total
    conversion_rounding = sum(
        (Decimal(row.rounding_residual_base) for row in analytics.conversion_rows),
        _ZERO,
    )
    bridge = analytics.nav_bridge
    checks = (
        ("cash_base", Decimal(analytics.cash_base), cash_total),
        ("position_value_base", Decimal(analytics.position_value_base), position_total),
        ("valuation_rounding", Decimal(analytics.valuation_rounding), rounding_total),
        ("nav_base", nav_base, reported_total),
        ("exact_nav_base", Decimal(analytics.exact_nav_base), exact_total),
        ("rounding_residual", Decimal(analytics.rounding_residual), exact_total - reported_total),
    )
    for field_name, actual, expected in checks:
        if actual != expected:
            _issue(
                issues,
                "analytics_nav_mismatch",
                f"analytics.{field_name}",
                _text(expected),
                _text(actual),
            )
    bridge_checks = (
        ("cash_base", Decimal(bridge.cash_base), cash_total),
        ("position_value_base", Decimal(bridge.position_value_base), position_total),
        ("valuation_rounding", Decimal(bridge.valuation_rounding), rounding_total),
        ("nav_base", Decimal(bridge.nav_base), reported_total),
        ("exact_nav_base", Decimal(bridge.exact_nav_base), exact_total),
        ("rounding_residual", Decimal(bridge.rounding_residual), exact_total - reported_total),
        ("conversion_rounding_base", Decimal(bridge.conversion_rounding_base), conversion_rounding),
    )
    for field_name, actual, expected in bridge_checks:
        if actual != expected:
            _issue(
                issues,
                "analytics_nav_mismatch",
                f"analytics.nav_bridge.{field_name}",
                _text(expected),
                _text(actual),
            )
    if nav_base != Decimal(bridge.nav_base):
        _issue(
            issues,
            "analytics_nav_mismatch",
            "analytics.nav_base",
            bridge.nav_base,
            analytics.nav_base,
        )
    bucket_nav_total = sum(
        (Decimal(row.nav_base) for row in document.bucket_results), _ZERO
    )
    if bucket_nav_total != nav_base:
        _issue(
            issues,
            "analytics_nav_mismatch",
            "analytics.nav_base",
            _money_text(bucket_nav_total),
            analytics.nav_base,
        )

    _check_exposure_rollups(
        issues,
        analytics,
        bucket_exposures,
        cash_by_bucket,
        position_value_by_bucket,
        nav_base,
        "currency",
    )
    _check_exposure_rollups(
        issues,
        analytics,
        bucket_exposures,
        cash_by_bucket,
        position_value_by_bucket,
        nav_base,
        "market",
    )
    _check_sector_exposures(issues, analytics, position_rows)
    _check_concentration(issues, analytics, position_rows, nav_base)
    _check_attribution(
        issues,
        document,
        cash,
        positions,
        not_verified,
    )


def _check_exposure_rollups(
    issues: list[dict[str, Any]],
    analytics: Any,
    bucket_exposures: dict[str, Any],
    cash_by_bucket: dict[str, Decimal],
    position_value_by_bucket: dict[str, Decimal],
    nav_base: Decimal,
    kind: str,
) -> None:
    rows = (
        analytics.currency_exposures
        if kind == "currency"
        else analytics.market_exposures
    )
    grouped: dict[str, dict[str, Decimal | list[str]]] = {}
    for bucket_id, exposure in bucket_exposures.items():
        key = getattr(exposure, kind)
        entry = grouped.setdefault(
            key,
            {
                "cash": _ZERO,
                "position": _ZERO,
                "rounding": _ZERO,
                "value": _ZERO,
                "buckets": [],
            },
        )
        entry["cash"] += Decimal(exposure.cash_base)
        entry["position"] += Decimal(exposure.position_value_base)
        entry["rounding"] += Decimal(exposure.valuation_rounding)
        entry["value"] += Decimal(exposure.value_base)
        entry["buckets"].append(bucket_id)
    seen: set[str] = set()
    for index, row in enumerate(rows):
        path = f"analytics.{kind}_exposures[{index}]"
        key = getattr(row, kind)
        if key in seen:
            _issue(issues, "analytics_exposure_mismatch", path, "one row per group", key)
        seen.add(key)
        entry = grouped.get(key)
        if entry is None:
            _issue(issues, "analytics_exposure_mismatch", path, "declared group", key)
            continue
        expected = {
            "cash_base": entry["cash"],
            "position_value_base": entry["position"],
            "valuation_rounding": entry["rounding"],
            "value_base": entry["value"],
        }
        for field_name, value in expected.items():
            if Decimal(getattr(row, field_name)) != value:
                _issue(
                    issues,
                    "analytics_exposure_mismatch",
                    f"{path}.{field_name}",
                    _money_text(value),
                    getattr(row, field_name),
                )
        expected_weight = _weight(_ratio(entry["value"], nav_base)) if nav_base > 0 else _ZERO
        if Decimal(row.weight) != expected_weight:
            _issue(
                issues,
                "analytics_exposure_mismatch",
                f"{path}.weight",
                format(expected_weight, ".12f"),
                row.weight,
            )
        expected_buckets = tuple(sorted(entry["buckets"]))
        if row.bucket_ids != expected_buckets:
            _issue(
                issues,
                "analytics_exposure_mismatch",
                f"{path}.bucket_ids",
                list(expected_buckets),
                list(row.bucket_ids),
            )
    for key in sorted(set(grouped) - seen):
        _issue(
            issues,
            "analytics_exposure_mismatch",
            f"analytics.{kind}_exposures[{key}]",
            "published group",
            None,
        )


def _check_sector_exposures(
    issues: list[dict[str, Any]],
    analytics: Any,
    position_rows: dict[tuple[str, str], Any],
) -> None:
    assignment: dict[tuple[str, str], int] = {}
    position_value_base = Decimal(analytics.position_value_base)
    for index, row in enumerate(analytics.sector_exposures):
        path = f"analytics.sector_exposures[{index}]"
        values = _ZERO
        for bucket_id in row.bucket_ids:
            for symbol in row.symbols:
                key = (bucket_id, symbol)
                position = position_rows.get(key)
                if position is None:
                    continue
                if key in assignment:
                    _issue(
                        issues,
                        "analytics_exposure_mismatch",
                        f"{path}.symbols",
                        "one sector per position",
                        list(key),
                    )
                    continue
                assignment[key] = index
                values += Decimal(position.value_base)
        if Decimal(row.value_base) != values:
            _issue(
                issues,
                "analytics_exposure_mismatch",
                f"{path}.value_base",
                _money_text(values),
                row.value_base,
            )
        if position_value_base > 0:
            expected_weight = _weight(_ratio(values, position_value_base))
            if Decimal(row.weight_of_positions) != expected_weight:
                _issue(
                    issues,
                    "analytics_exposure_mismatch",
                    f"{path}.weight_of_positions",
                    format(expected_weight, ".12f"),
                    row.weight_of_positions,
                )
    for key in sorted(set(position_rows) - set(assignment)):
        _issue(
            issues,
            "analytics_exposure_mismatch",
            f"analytics.sector_exposures[{key[0]}.{key[1]}]",
            "one sector bucket",
            None,
        )


def _check_concentration(
    issues: list[dict[str, Any]],
    analytics: Any,
    position_rows: dict[tuple[str, str], Any],
    nav_base: Decimal,
) -> None:
    concentration = analytics.concentration
    path = "analytics.concentration"
    if concentration.position_count != len(position_rows):
        _issue(
            issues,
            "analytics_exposure_mismatch",
            f"{path}.position_count",
            len(position_rows),
            concentration.position_count,
        )
    weights: list[Decimal] = []
    published: dict[tuple[str, str], tuple[Decimal, Decimal]] = {}
    for key, row in position_rows.items():
        value = Decimal(row.value_base)
        exact_weight = _ratio(value, nav_base) if nav_base > 0 else _ZERO
        weights.append(exact_weight)
        published[key] = (value, _weight(exact_weight))
    for index, row in enumerate(concentration.position_weights):
        key = (row.bucket_id, row.symbol)
        item_path = f"{path}.position_weights[{index}]"
        expected = published.get(key)
        if expected is None:
            _issue(issues, "analytics_exposure_mismatch", item_path, "held position", list(key))
            continue
        if Decimal(row.value_base) != expected[0]:
            _issue(
                issues,
                "analytics_exposure_mismatch",
                f"{item_path}.value_base",
                _money_text(expected[0]),
                row.value_base,
            )
        if Decimal(row.weight) != expected[1]:
            _issue(
                issues,
                "analytics_exposure_mismatch",
                f"{item_path}.weight",
                format(expected[1], ".12f"),
                row.weight,
            )
    ordered = sorted(weights, reverse=True)
    expected_top1 = _weight(ordered[0]) if ordered else _ZERO
    expected_top5 = _weight(sum(ordered[:5], _ZERO))
    expected_hhi = _weight(sum((value * value for value in weights), _ZERO))
    if Decimal(concentration.top_1) != expected_top1:
        _issue(
            issues,
            "analytics_exposure_mismatch",
            f"{path}.top_1",
            format(expected_top1, ".12f"),
            concentration.top_1,
        )
    if Decimal(concentration.top_5) != expected_top5:
        _issue(
            issues,
            "analytics_exposure_mismatch",
            f"{path}.top_5",
            format(expected_top5, ".12f"),
            concentration.top_5,
        )
    if Decimal(concentration.hhi) != expected_hhi:
        _issue(
            issues,
            "analytics_exposure_mismatch",
            f"{path}.hhi",
            format(expected_hhi, ".12f"),
            concentration.hhi,
        )
