"""One-day attribution bridge, weight views and execution-rounding tests.

Freeze the exact NAV contribution identity, the target/planned/realized weight
tie-out, the explicit zero decomposition for absent trades and the computed
two-decimal execution rounding; missing attribution inputs stay declared
errors. Shared fixtures live in ``paper_trade_portfolio_attribution_helpers``.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from src.tools.paper_trade.portfolio.analytics import (
    build_portfolio_analytics,
    reconcile_attribution,
)
from src.tools.paper_trade.portfolio.models import AnalyticsAttribution
from src.tools.paper_trade.portfolio.schema import (
    PortfolioRequestError,
    parse_portfolio_request,
)
from src.tools.paper_trade.portfolio.wire import build_success_payload
from tests.paper_trade_portfolio_attribution_helpers import (
    PRIOR_DATE,
    TRADE_DATE,
    ZERO,
    FakeLoader,
    _PACKAGED_SCHEMA,
    _assert_attribution_identity,
    _assert_weight_identity,
    _attribution,
    _base_payload,
    _decimal,
    _frame,
    _noop_payload,
    _rounding_loaders,
    _rounding_payload,
    _run,
    _sum,
    _target_payload,
)


def test_three_currency_contribution_fx_fee_and_reject_reconcile_exactly() -> None:
    # Given a CN sell, a rejected US buy, one conversion and three currencies.
    step = _run()
    attribution = _attribution(step)

    # Then the document is explicitly one-day attribution, not Brinson/multi-day.
    assert attribution.scope == "one_day"
    assert attribution.formula_version == "pt-attribution-v1"
    assert attribution.reconciliation.reconciled is True
    assert attribution.reconciliation.issues == ()
    assert any(
        "Brinson" in note for note in attribution.reconciliation.not_verified
    )
    assert PRIOR_DATE in attribution.provenance.price_dates
    assert TRADE_DATE in attribution.provenance.price_dates
    assert attribution.provenance.fx

    # Then the NAV identity holds term by term.
    _assert_attribution_identity(attribution)
    nav = attribution.nav
    assert _decimal(nav.end_exact_nav_base) == _decimal(
        step.document.analytics.exact_nav_base
    )
    assert _decimal(nav.end_nav_base) == _decimal(step.document.analytics.nav_base)

    # Then the CN sell's market move is its prior-to-execution gain.
    cn = next(
        row
        for row in attribution.symbol_contributions
        if row.symbol == "600519.SH"
    )
    assert cn.opening_qty == 100
    assert cn.ending_qty == 0
    assert cn.traded_qty == -100
    assert cn.currency_contribution_base == "0"
    assert _decimal(cn.market_contribution_base) == Decimal("42")
    assert _decimal(cn.total_contribution_base) == Decimal("42")

    # Then the held HK position separates market and currency (both nonnegative).
    hk = next(
        row
        for row in attribution.symbol_contributions
        if row.symbol == "00700.HK"
    )
    assert hk.opening_qty == 100
    assert hk.ending_qty == 100
    assert hk.traded_qty == 0
    assert _decimal(hk.market_contribution_base) > 0
    assert hk.currency_contribution_base == "0"

    # Then conversion rounding is a real loss, not a fabricated gain.
    assert len(attribution.conversion_effects) == 1
    conversion = attribution.conversion_effects[0]
    assert conversion.converted_amount == "140.00"
    assert conversion.rounding_residual_local == "0.0014"
    assert _decimal(conversion.conversion_effect_base) == Decimal("-0.0014")
    assert _decimal(conversion.rounding_loss_base) == Decimal("-0.0014")

    # Then the CN sell paid a positive fee whose base effect is negative.
    assert len(attribution.fee_effects) == 1
    fee = attribution.fee_effects[0]
    assert fee.plan_order_id == "cn-sell-1"
    assert _decimal(fee.fee_local) > 0
    assert _decimal(fee.fee_effect_base) < 0
    assert _decimal(attribution.fee_effect_base) == _decimal(fee.fee_effect_base)

    # Then cash FX is explicit (zero here because both legs use one direct pair).
    assert len(attribution.cash_fx_effects) == 3
    assert _sum(row.cash_fx_effect_base for row in attribution.cash_fx_effects) == ZERO

    # Then market and currency views both tie to the NAV change minus residual.
    assert _sum(
        row.total_contribution_base for row in attribution.market_contributions
    ) + _decimal(attribution.rounding_residual) == _decimal(
        nav.nav_change_exact
    )
    assert _sum(
        row.total_contribution_base for row in attribution.currency_contributions
    ) + _decimal(attribution.rounding_residual) == _decimal(
        nav.nav_change_exact
    )

    # Then weights publish target/planned/realized views and a reject gap.
    weights = attribution.weights
    _assert_weight_identity(attribution)
    assert weights.target_weight_total is None
    assert weights.target_cash_weight is None
    us = next(row for row in weights.rows if row.symbol == "AAPL.US")
    assert us.target_weight is None
    assert us.outcome == "rejected"
    assert us.realized_qty == 0
    assert us.planned_qty == 10
    assert _decimal(us.reject_gap) < 0
    assert _decimal(us.realized_weight) == ZERO
    assert _decimal(us.reject_gap) == -_decimal(us.planned_at_end_weight)

    # Then the public wire document keeps every attribution field and validates.
    public = build_success_payload(step)
    assert public["analytics"]["attribution"]["scope"] == "one_day"
    schema = json.loads(_PACKAGED_SCHEMA.read_text(encoding="utf-8"))["schemas"][
        "result"
    ]
    assert list(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(public)
    ) == []
    assert reconcile_attribution(AnalyticsAttribution.model_validate(
        public["analytics"]["attribution"]
    )) == ()


def test_target_weight_views_reconcile_to_declared_rounding_residual() -> None:
    # Given caller targets, a band, conversions and both fillable/rejected lines.
    step = _run(_target_payload())
    attribution = _attribution(step)
    weights = attribution.weights

    # Then target weights and their cash complement are explicit.
    assert weights.target_weight_total is not None
    assert weights.target_cash_weight is not None
    assert _decimal(weights.target_weight_total) + _decimal(
        weights.target_cash_weight
    ) == Decimal(1)
    assert _decimal(weights.planned_weight_total) + _decimal(
        weights.planned_cash_weight
    ) == Decimal(1)

    # Then every published row ties target -> planned -> realized.
    for row in weights.rows:
        assert row.target_weight is not None
        expected_target_gap = _decimal(row.realized_weight) - _decimal(
            row.target_weight
        )
        assert _decimal(row.target_gap) == expected_target_gap
        assert _decimal(row.lot_gap) == (
            _decimal(row.planned_weight) - _decimal(row.target_weight)
        )
        assert _decimal(row.price_gap) == (
            _decimal(row.planned_at_end_weight) - _decimal(row.planned_weight)
        )
        assert _decimal(row.reject_gap) == (
            _decimal(row.realized_weight) - _decimal(row.planned_at_end_weight)
        )

    # Then the weight tie-out includes the declared rounding residual.
    _assert_weight_identity(attribution)
    assert _decimal(weights.weight_rounding_tolerance) > ZERO
    _assert_attribution_identity(attribution)
    assert attribution.reconciliation.reconciled is True


def test_absent_trades_publish_an_explicit_zero_decomposition() -> None:
    # Given no orders, no conversions and no price or FX movement.
    payload = _noop_payload()
    loaders = {
        "cn_a": FakeLoader({"600519.SH": _frame(1418.0, 1418.0)}, "cn-fixture"),
        "hk": FakeLoader({"00700.HK": _frame(410.0, 410.0)}, "hk-fixture"),
        "us": FakeLoader({"AAPL.US": _frame(340.0, 340.0)}, "us-fixture"),
    }

    # When the step values the unchanged ledger.
    attribution = _attribution(_run(payload, loaders=loaders))

    # Then every contribution bucket is explicitly zero, not absent.
    assert attribution.nav.nav_change_exact == "0"
    assert attribution.position_contribution_base == "0"
    assert attribution.cash_fx_effect_base == "0"
    assert attribution.conversion_effect_base == "0"
    assert attribution.fee_effect_base == "0"
    assert attribution.rounding_residual == "0"
    assert attribution.expected_rounding_residual == "0"
    assert attribution.conversion_effects == ()
    assert attribution.fee_effects == ()
    assert attribution.execution_rounding == ()
    assert all(row.total_contribution_base == "0" for row in attribution.symbol_contributions)
    assert attribution.reconciliation.reconciled is True
    _assert_weight_identity(attribution)


def test_nonzero_execution_rounding_is_computed_and_tied_not_hidden() -> None:
    # Given a 50.005 close and three shares, whose 150.015 cash notional rounds.
    step = _run(_rounding_payload(), loaders=_rounding_loaders())
    attribution = _attribution(step)

    # Then the fill's two-decimal cash rounding is nonzero and explicit.
    assert len(attribution.execution_rounding) == 1
    row = attribution.execution_rounding[0]
    assert row.exact_notional_local == "150.015"
    assert row.notional_local == "150.02"
    assert row.rounding_local == "-0.005"
    assert _decimal(attribution.rounding_residual) == Decimal("-0.005")
    assert _decimal(attribution.expected_rounding_residual) == Decimal("-0.005")
    _assert_attribution_identity(attribution)
    assert attribution.reconciliation.reconciled is True


def test_missing_attribution_inputs_are_declared_and_never_fabricated() -> None:
    # Given one valid step whose plan is withheld from a direct build.
    step = _run()
    request = parse_portfolio_request(_base_payload())

    # Then the attribution inputs are required, not silently defaulted.
    with pytest.raises(PortfolioRequestError) as raised:
        build_portfolio_analytics(
            request,
            step.end_ledger,
            step.prepared_data,
            opening_ledger=step.opening_ledger,
            post_conversion_ledger=step.post_conversion_ledger,
            fills=step.execution.fills,
        )
    assert raised.value.reason == "missing_attribution_input"
    assert raised.value.path == "attribution.plan"
