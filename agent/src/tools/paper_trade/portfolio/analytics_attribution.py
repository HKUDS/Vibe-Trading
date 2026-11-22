"""Coordinator and final assembly of the one-day attribution document.

``_attribution`` keeps its historic signature and delegates to the bridge,
replay, roll-up and weight clusters in their original computation order; the
assembly publishes the provisional document, runs the independent verifier and
merges its issues without ever fitting the residual.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from .analytics_attribution_bridge import (
    _AttributionState,
    _BridgeResult,
    _attribution_bridge,
)
from .analytics_attribution_replay import _ReplayResult, _attribution_replay
from .analytics_attribution_rollups import _RollupResult, _attribution_rollups
from .analytics_attribution_weights import _attribution_weights
from .analytics_common import (
    _ATTRIBUTION_NOT_VERIFIED,
    _Mark,
    _exact_difference,
    _exact_text,
    _merge_issues,
)
from .analytics_exposure import _provenance
from .analytics_verify import reconcile_attribution
from .data import PreparedPortfolioData
from .fx import FxConversionEvent, FxRateBook
from .ledger import PortfolioLedger
from .models import (
    AnalyticsAttribution,
    AnalyticsAttributionNav,
    AnalyticsAttributionReconciliation,
    AnalyticsCashRow,
    AnalyticsWeightReconciliation,
    AnalyticsPositionRow,
    AnalyticsReconciliationCheck,
    PortfolioRequest,
)
from .numeric import MONEY_SPEC, canonical_decimal
from .orchestrator import ExecutionCancellation, ExecutionFill, ExecutionRejection
from .order_plan import OrderPlan


def _attribution_document(
    state: _AttributionState,
    bridge: _BridgeResult,
    replay: _ReplayResult,
    rollups: _RollupResult,
    weights: AnalyticsWeightReconciliation,
) -> AnalyticsAttribution:
    """Assemble, independently verify and publish the attribution document."""
    request = state.request
    fills = state.fills
    nav_base = state.nav_base
    exact_nav_base = state.exact_nav_base
    issues = state.issues
    checks = state.checks
    base_currency = request.base_currency
    start_nav = bridge.start_nav
    start_exact = bridge.start_exact
    planning_marks = bridge.planning_marks
    planning_rates = bridge.planning_rates
    valuation_rates = bridge.valuation_rates
    cash_fx_rows = bridge.cash_fx_rows
    cash_fx_total = bridge.cash_fx_total
    conversion_effects = bridge.conversion_effects
    conversion_total = bridge.conversion_total
    fee_effects = bridge.fee_effects
    fee_total = bridge.fee_total
    rounding_rows = bridge.rounding_rows
    expected_rounding = bridge.expected_rounding
    symbol_rows = replay.symbol_rows
    position_total = replay.position_total
    market_rows = rollups.market_rows
    currency_rows = rollups.currency_rows
    nav_change_exact = rollups.nav_change_exact
    nav_change_reported = rollups.nav_change_reported
    rounding_residual = rollups.rounding_residual
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
    state = _AttributionState(
        request=request,
        prepared=prepared,
        opening_ledger=opening_ledger,
        post_conversion_ledger=post_conversion_ledger,
        end_ledger=end_ledger,
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
    bridge = _attribution_bridge(state)
    replay = _attribution_replay(state, bridge)
    rollups = _attribution_rollups(state, bridge, replay)
    weights = _attribution_weights(state, bridge, replay)
    return _attribution_document(state, bridge, replay, rollups, weights)
