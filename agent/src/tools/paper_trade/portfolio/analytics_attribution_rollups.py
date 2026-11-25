"""Market/currency roll-up and NAV-identity cluster of the one-day attribution.

Rolls the symbol, cash FX, conversion and fee rows into complete market and
currency views and checks the unfitted NAV contribution identity. The
computation body is byte-identical to the pre-split ``_attribution`` roll-up
section.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .analytics_attribution_bridge import _AttributionState, _BridgeResult
from .analytics_attribution_replay import _ReplayResult
from .analytics_common import (
    _attribution_issue,
    _exact_difference,
    _exact_sum,
    _exact_text,
)
from .models import (
    AnalyticsCurrencyContribution,
    AnalyticsMarketContribution,
    AnalyticsReconciliationCheck,
)


@dataclass(frozen=True, slots=True)
class _RollupResult:
    """Market/currency contribution rows and the NAV change terms."""

    market_rows: tuple[AnalyticsMarketContribution, ...]
    currency_rows: tuple[AnalyticsCurrencyContribution, ...]
    nav_change_exact: Decimal
    nav_change_reported: Decimal
    rounding_residual: Decimal


def _attribution_rollups(
    state: _AttributionState, bridge: _BridgeResult, replay: _ReplayResult
) -> _RollupResult:
    """Roll contributions into market/currency views and check the identity."""
    nav_base = state.nav_base
    exact_nav_base = state.exact_nav_base
    issues = state.issues
    checks = state.checks
    end_buckets = bridge.end_buckets
    start_nav = bridge.start_nav
    start_exact = bridge.start_exact
    cash_fx_rows = bridge.cash_fx_rows
    cash_fx_total = bridge.cash_fx_total
    conversion_effects = bridge.conversion_effects
    conversion_total = bridge.conversion_total
    fee_effects = bridge.fee_effects
    fee_total = bridge.fee_total
    expected_rounding = bridge.expected_rounding
    symbol_rows = replay.symbol_rows
    position_total = replay.position_total
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
    return _RollupResult(
        market_rows=market_rows,
        currency_rows=currency_rows,
        nav_change_exact=nav_change_exact,
        nav_change_reported=nav_change_reported,
        rounding_residual=rounding_residual,
    )
