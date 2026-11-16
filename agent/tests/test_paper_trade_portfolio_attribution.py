"""One-day pt-v2.0 contribution, FX and weight-gap attribution.

The attribution document is a pure Decimal projection over the opening ledger,
the settled conversions, every execution fill, the ending ledger and the
planning/valuation marks. These tests freeze the exact NAV identity

    NAV_end_exact - NAV_start_exact
      = sum(position_contribution)
      + sum(cash_fx_effects)
      + conversion_effects
      + fee_effects
      + rounding_residual

and the weight tie-out between caller targets, the order plan and the realized
end ledger. Every mutation of a fill, conversion, mark, planned weight or
published realized weight must surface as a declared reconciliation issue; the
residual is never fitted to hide an error. No Brinson allocation/selection or
multi-day attribution is involved.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from jsonschema import Draft202012Validator, FormatChecker

from src.tools.paper_trade.portfolio import run_portfolio_step
from src.tools.paper_trade.portfolio.analytics import (
    build_portfolio_analytics,
    reconcile_attribution,
)
from src.tools.paper_trade.portfolio.data import TargetBarValuation
from src.tools.paper_trade.portfolio.hash import PortfolioDataHashes, document_hash
from src.tools.paper_trade.portfolio.models import AnalyticsAttribution, PortfolioResult
from src.tools.paper_trade.portfolio.schema import (
    PortfolioRequestError,
    parse_portfolio_request,
)
from src.tools.paper_trade.portfolio.wire import (
    PortfolioWireError,
    build_success_payload,
)

TRADE_DATE = date(2026, 11, 13)
PRIOR_DATE = date(2026, 11, 12)
DAY = TRADE_DATE.isoformat()
PRIOR = PRIOR_DATE.isoformat()
ZERO = Decimal(0)

_AGENT_ROOT = Path(__file__).resolve().parents[1]
_PACKAGED_SCHEMA = (
    _AGENT_ROOT / "src" / "tools" / "paper_trade" / "paper_trade_step-v2.0.json"
)
_MIRROR_SCHEMA = (
    _AGENT_ROOT.parent / "schema" / "tool_contracts" / "paper_trade_step-v2.0.json"
)
_LEGACY_EXPLICIT_GOLDEN = (
    _AGENT_ROOT
    / "tests"
    / "fixtures"
    / "paper_trade"
    / "golden"
    / "portfolio_explicit_cn_hk_us.json"
)
_TASK23_EXPLICIT_HASH = (
    "da38f7f6ea84cf7b9eeba0dfa4d3a4cf90f8f746422052eacfcfceb6fc996206"
)


class FakeLoader:
    """Offline loader double; attribution must never reach a provider."""

    def __init__(self, frames: dict[str, pd.DataFrame], name: str) -> None:
        self.name = name
        self.frames = frames

    def is_available(self) -> bool:
        return True

    def fetch(self, codes, start_date, end_date, *, interval="1D", fields=None):
        return {code: self.frames[code] for code in codes if code in self.frames}


class OpenCalendar:
    def get_trade_calendar(self, start_date: str, end_date: str) -> pd.DataFrame:
        rows = [
            {
                "exchange": "SSE",
                "cal_date": day.strftime("%Y-%m-%d"),
                "is_open": 1,
                "pretrade_date": "",
            }
            for day in pd.date_range(start_date, end_date)
        ]
        return pd.DataFrame(
            rows,
            columns=["exchange", "cal_date", "is_open", "pretrade_date"],
        )


def _frame(prior: float, target: float | None) -> pd.DataFrame:
    records = [
        {
            "trade_date": PRIOR,
            "open": prior,
            "high": prior,
            "low": prior,
            "close": prior,
            "volume": 1000.0,
        }
    ]
    if target is not None:
        records.append(
            {
                "trade_date": DAY,
                "open": target,
                "high": target,
                "low": target,
                "close": target,
                "volume": 1000.0,
            }
        )
    frame = pd.DataFrame(records)
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    return frame.set_index("trade_date")[["open", "high", "low", "close", "volume"]]


def _loaders() -> dict[str, FakeLoader]:
    return {
        "cn_a": FakeLoader({"600519.SH": _frame(1418.0, 1421.0)}, "cn-fixture"),
        "hk": FakeLoader({"00700.HK": _frame(410.0, 417.8)}, "hk-fixture"),
        "us": FakeLoader({"AAPL.US": _frame(340.0, 343.46)}, "us-fixture"),
    }


def _base_payload() -> dict[str, Any]:
    return {
        "tool": "paper_trade_step",
        "schema_version": "pt-v2.0",
        "mode": "portfolio",
        "account_id": "portfolio-attribution-01",
        "base_currency": "USD",
        "trade_date": DAY,
        "planning_at": "2026-11-13T12:00:00+00:00",
        "valuation_at": "2026-11-13T21:00:00+00:00",
        "interval": "1d",
        "fill_model": "all_or_none",
        "portfolio_state": {
            "buckets": [
                {
                    "bucket_id": "cn",
                    "market": "cn_a",
                    "currency": "CNY",
                    "cash": "100000.00",
                    "positions": [
                        {
                            "symbol": "600519.SH",
                            "qty": 100,
                            "avg_cost": "1400.00",
                            "currency": "CNY",
                        }
                    ],
                },
                {
                    "bucket_id": "hk",
                    "market": "hk",
                    "currency": "HKD",
                    "cash": "50000.00",
                    "positions": [
                        {
                            "symbol": "00700.HK",
                            "qty": 100,
                            "avg_cost": "300.00",
                            "currency": "HKD",
                        }
                    ],
                    "fee_model": {
                        "currency": "HKD",
                        "parameters": {"commission_rate": "0.0003"},
                    },
                },
                {
                    "bucket_id": "us",
                    "market": "us",
                    "currency": "USD",
                    "cash": "25000.00",
                    "positions": [],
                },
            ]
        },
        "sessions": [
            {
                "market": market,
                "status": "open",
                "source": "caller-calendar",
                "as_of": "2026-11-13T01:00:00+00:00",
            }
            for market in ("cn_a", "hk", "us")
        ],
        "fx_snapshots": [
            {
                "rate_id": "cny-usd-fix",
                "from": "CNY",
                "to": "USD",
                "rate": "0.14",
                "as_of": "2026-11-13T11:00:00+00:00",
                "source": "caller-fix",
            },
            {
                "rate_id": "hkd-usd-fix",
                "from": "HKD",
                "to": "USD",
                "rate": "0.128",
                "as_of": "2026-11-13T11:00:00+00:00",
                "source": "caller-fix",
            },
        ],
        "fx_conversions": [
            {
                "rate_id": "cny-usd-fix",
                "from_bucket_id": "cn",
                "to_bucket_id": "us",
                "amount": "1000.01",
            }
        ],
        "orders": [
            {
                "order_id": "cn-sell-1",
                "bucket_id": "cn",
                "symbol": "600519.SH",
                "currency": "CNY",
                "side": "sell",
                "qty": 100,
            },
            {
                "order_id": "us-buy-1",
                "bucket_id": "us",
                "symbol": "AAPL.US",
                "currency": "USD",
                "side": "buy",
                "qty": 10,
                "limit": "300.00",
            },
        ],
        "sectors": [
            {"bucket_id": "cn", "symbol": "600519.SH", "sector": "consumer"},
            {"bucket_id": "hk", "symbol": "00700.HK", "sector": "technology"},
            {"bucket_id": "us", "symbol": "AAPL.US", "sector": "technology"},
        ],
    }


def _target_payload() -> dict[str, Any]:
    payload = _base_payload()
    payload.pop("orders")
    payload["target_weights"] = [
        {
            "bucket_id": "cn",
            "symbol": "600519.SH",
            "currency": "CNY",
            "weight": "0.00",
        },
        {
            "bucket_id": "hk",
            "symbol": "00700.HK",
            "currency": "HKD",
            "weight": "0.16",
        },
        {
            "bucket_id": "us",
            "symbol": "AAPL.US",
            "currency": "USD",
            "weight": "0.20",
        },
    ]
    payload["rebalance_band"] = "0.01"
    return payload


def _noop_payload() -> dict[str, Any]:
    payload = _base_payload()
    payload["fx_conversions"] = []
    payload["orders"] = []
    payload["portfolio_state"]["buckets"][2]["positions"] = [
        {
            "symbol": "AAPL.US",
            "qty": 2,
            "avg_cost": "340.00",
            "currency": "USD",
        }
    ]
    return payload


def _rounding_payload() -> dict[str, Any]:
    return {
        "tool": "paper_trade_step",
        "schema_version": "pt-v2.0",
        "mode": "portfolio",
        "account_id": "portfolio-attribution-rounding-01",
        "base_currency": "USD",
        "trade_date": DAY,
        "planning_at": "2026-11-13T12:00:00+00:00",
        "valuation_at": "2026-11-13T21:00:00+00:00",
        "interval": "1d",
        "fill_model": "all_or_none",
        "portfolio_state": {
            "buckets": [
                {
                    "bucket_id": "us",
                    "market": "us",
                    "currency": "USD",
                    "cash": "1000.00",
                    "positions": [],
                }
            ]
        },
        "sessions": [
            {
                "market": "us",
                "status": "open",
                "source": "caller-calendar",
                "as_of": "2026-11-13T01:00:00+00:00",
            }
        ],
        "fx_snapshots": [],
        "fx_conversions": [],
        "orders": [
            {
                "order_id": "us-buy-rounding",
                "bucket_id": "us",
                "symbol": "AAPL.US",
                "currency": "USD",
                "side": "buy",
                "qty": 3,
            }
        ],
    }


def _rounding_loaders() -> dict[str, FakeLoader]:
    return {
        "us": FakeLoader({"AAPL.US": _frame(50.0, 50.005)}, "us-fixture"),
    }


def _run(
    payload: dict[str, Any] | None = None,
    *,
    loaders: dict[str, FakeLoader] | None = None,
):
    return run_portfolio_step(
        payload or _base_payload(),
        loaders=loaders or _loaders(),
        calendar_client=OpenCalendar(),
    )


def _decimal(value: str) -> Decimal:
    return Decimal(value)


def _sum(values) -> Decimal:
    return sum((_decimal(value) for value in values), ZERO)


def _attribution(step):
    attribution = step.document.analytics.attribution
    assert attribution is not None
    return attribution


def _rebuild(
    step,
    payload: dict[str, Any],
    *,
    fills=None,
    conversion_events=None,
    prepared=None,
    plan=None,
):
    request = parse_portfolio_request(payload)
    return build_portfolio_analytics(
        request,
        step.end_ledger,
        prepared or step.prepared_data,
        conversion_events=(
            step.conversion_replay.events
            if conversion_events is None
            else conversion_events
        ),
        opening_ledger=step.opening_ledger,
        post_conversion_ledger=step.post_conversion_ledger,
        fills=step.execution.fills if fills is None else fills,
        rejected_orders=step.execution.rejected_orders,
        canceled_orders=step.execution.canceled_orders,
        plan=step.order_plan if plan is None else plan,
    )


def _assert_attribution_identity(attribution) -> None:
    nav = attribution.nav
    total = (
        _decimal(attribution.position_contribution_base)
        + _decimal(attribution.cash_fx_effect_base)
        + _decimal(attribution.conversion_effect_base)
        + _decimal(attribution.fee_effect_base)
        + _decimal(attribution.rounding_residual)
    )
    assert total == _decimal(nav.nav_change_exact)
    assert _decimal(attribution.rounding_residual) == _decimal(
        attribution.expected_rounding_residual
    )
    assert _decimal(nav.nav_change_exact) == (
        _decimal(nav.end_exact_nav_base) - _decimal(nav.start_exact_nav_base)
    )
    assert _decimal(nav.start_exact_nav_base) == (
        _decimal(nav.start_nav_base) + _decimal(nav.start_rounding_residual)
    )
    assert _decimal(nav.end_exact_nav_base) == (
        _decimal(nav.end_nav_base) + _decimal(nav.end_rounding_residual)
    )


def _assert_weight_identity(attribution) -> None:
    weights = attribution.weights
    total = (
        _decimal(weights.lot_gap_total)
        + _decimal(weights.price_gap_total)
        + _decimal(weights.reject_gap_total)
        + _decimal(weights.cash_gap)
        + _decimal(weights.valuation_rounding_weight)
    )
    assert abs(total) <= _decimal(weights.weight_rounding_tolerance)
    assert abs(_decimal(weights.weight_rounding_residual)) == abs(total)
    assert weights.reconciled is True


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


def test_tampered_fill_produces_a_reconciliation_issue() -> None:
    # Given one valid step and a fill whose price is mutated after execution.
    step = _run()
    fills = step.execution.fills
    mutated = (
        replace(fills[0], price=fills[0].price + Decimal("1")),
        *fills[1:],
    )

    # When attribution is rebuilt from the tampered execution row.
    analytics = _rebuild(step, _base_payload(), fills=mutated)
    attribution = analytics.attribution
    assert attribution is not None

    # Then the mismatch is a declared issue; the residual is not fitted.
    assert attribution.reconciliation.reconciled is False
    assert attribution.reconciliation.issues
    assert any(
        issue.reason.startswith("attribution_fill")
        for issue in attribution.reconciliation.issues
    )
    assert _decimal(attribution.rounding_residual) != _decimal(
        attribution.expected_rounding_residual
    )


def test_tampered_conversion_produces_a_reconciliation_issue() -> None:
    # Given one valid conversion whose credited amount is mutated.
    step = _run()
    event = step.conversion_replay.events[0]
    mutated = (replace(event, converted_amount=event.converted_amount + Decimal("1")),)

    analytics = _rebuild(step, _base_payload(), conversion_events=mutated)
    attribution = analytics.attribution
    assert attribution is not None

    # Then conversion replay and the identity both reject the mutation.
    assert attribution.reconciliation.reconciled is False
    assert attribution.reconciliation.issues
    assert any(
        issue.reason.startswith("attribution_conversion")
        for issue in attribution.reconciliation.issues
    )
    assert _decimal(attribution.rounding_residual) != _decimal(
        attribution.expected_rounding_residual
    )


def test_tampered_mark_produces_a_reconciliation_issue() -> None:
    # Given a valuation mark that no longer agrees with the execution snapshot.
    step = _run()
    buckets = []
    for bucket in step.prepared_data.buckets:
        if bucket.bucket_id != "hk" or not isinstance(
            bucket.valuation, TargetBarValuation
        ):
            buckets.append(bucket)
            continue
        snapshot = bucket.valuation.snapshot
        bars = tuple(
            replace(bar, close=str(Decimal(bar.close) + Decimal("1")))
            if bar.symbol == "00700.HK"
            else bar
            for bar in snapshot.bars
        )
        buckets.append(
            replace(
                bucket,
                valuation=TargetBarValuation(snapshot=replace(snapshot, bars=bars)),
            )
        )
    prepared = replace(step.prepared_data, buckets=tuple(buckets))

    analytics = _rebuild(step, _base_payload(), prepared=prepared)
    attribution = analytics.attribution
    assert attribution is not None

    # Then the mark disagreement and resulting replay mismatch are explicit.
    assert attribution.reconciliation.reconciled is False
    assert attribution.reconciliation.issues
    assert any(
        issue.reason in {
            "attribution_valuation_execution_mark_mismatch",
            "attribution_fill_replay_mismatch",
        }
        for issue in attribution.reconciliation.issues
    )


def test_tampered_planned_weight_produces_a_reconciliation_issue() -> None:
    # Given a plan row whose planned weight no longer matches its quantity.
    step = _run()
    rows = list(step.order_plan.weights)
    index = next(
        index for index, row in enumerate(rows) if row.symbol == "00700.HK"
    )
    rows[index] = replace(
        rows[index],
        planned_weight=rows[index].planned_weight + Decimal("0.010000000000"),
    )
    plan = replace(step.order_plan, weights=tuple(rows))

    analytics = _rebuild(step, _base_payload(), plan=plan)
    attribution = analytics.attribution
    assert attribution is not None

    # Then the published weight view refuses to reconcile.
    assert attribution.reconciliation.reconciled is False
    assert any(
        issue.reason == "attribution_planned_weight_mismatch"
        for issue in attribution.reconciliation.issues
    )
    assert attribution.weights.reconciled is False


def test_mutated_realized_weight_has_a_reconciliation_issue() -> None:
    # Given a published attribution whose realized weight is changed in place.
    attribution = _attribution(_run())
    row = next(
        row for row in attribution.weights.rows if row.symbol == "00700.HK"
    )
    mutated_rows = tuple(
        item.model_copy(update={"realized_weight": "0.500000000000"})
        if item.symbol == row.symbol and item.bucket_id == row.bucket_id
        else item
        for item in attribution.weights.rows
    )
    mutated = attribution.model_copy(
        update={
            "weights": attribution.weights.model_copy(
                update={"rows": mutated_rows}
            )
        }
    )

    # Then the independent verifier reports the row, not a fitted residual.
    issues = reconcile_attribution(mutated)
    assert any(
        issue.reason == "attribution_realized_weight_mismatch"
        for issue in issues
    )


def test_tampered_realized_weight_is_rejected_by_the_public_wire() -> None:
    # Given a valid public document with one realized weight altered.
    public = build_success_payload(_run())
    rows = public["analytics"]["attribution"]["weights"]["rows"]
    row = next(row for row in rows if row["symbol"] == "00700.HK")
    row["realized_weight"] = "0.500000000000"

    # Then the public wire recomputes the weight and refuses the document.
    with pytest.raises(PortfolioWireError) as raised:
        build_success_payload(public)
    assert raised.value.reason.startswith("attribution_")
    assert "realized_weight" in raised.value.path or "weight" in raised.value.reason


def test_cross_bucket_conversion_identity_error_is_a_declared_issue() -> None:
    # Given a conversion redirected to a bucket with another currency.
    step = _run()
    event = step.conversion_replay.events[0]
    mutated = (
        replace(event, to_bucket_id="hk", to_currency="HKD"),
    )

    analytics = _rebuild(step, _base_payload(), conversion_events=mutated)
    attribution = analytics.attribution
    assert attribution is not None

    # Then the bucket/currency identity is rejected, never folded into NAV.
    assert attribution.reconciliation.reconciled is False
    assert any(
        issue.reason.startswith("attribution_conversion")
        for issue in attribution.reconciliation.issues
    )


def test_schema_mirrors_are_byte_identical_and_keep_attribution_optional() -> None:
    # Then the packaged contract and its public mirror stay one contract.
    assert _PACKAGED_SCHEMA.read_bytes() == _MIRROR_SCHEMA.read_bytes()
    document = json.loads(_PACKAGED_SCHEMA.read_text(encoding="utf-8"))
    analytics = document["schemas"]["result"]["$defs"]["analytics"]
    assert "attribution" in analytics["properties"]
    assert "attribution" not in analytics["required"]

    # And an old-shaped analytics object without attribution still validates.
    public = build_success_payload(_run(_noop_payload()))
    legacy = json.loads(json.dumps(public))
    legacy["analytics"].pop("attribution")
    schema = document["schemas"]["result"]
    assert list(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(legacy)
    ) == []
    assert PortfolioResult.model_validate(legacy).analytics.attribution is None


def test_task23_benchmark_document_without_attribution_keeps_its_hash() -> None:
    # Given a task-23-era document with a benchmark but no attribution key.
    payload = json.loads(_LEGACY_EXPLICIT_GOLDEN.read_text(encoding="utf-8"))
    payload["analytics"].pop("attribution")
    payload["hashes"]["document_hash"] = _TASK23_EXPLICIT_HASH
    layers = PortfolioDataHashes(
        plan_hash=payload["hashes"]["plan_hash"],
        planning_data_hash=payload["hashes"]["planning_data_hash"],
        execution_data_fingerprint=payload["hashes"]["execution_data_fingerprint"],
    )

    # When the archived document is validated and its hash recomputed...
    document = PortfolioResult.model_validate(payload)
    analytics = document.analytics
    assert analytics is not None

    # Then attribution is not resurrected as null and the archived hash holds.
    assert "attribution" not in analytics.model_fields_set
    assert document_hash(document, layers) == _TASK23_EXPLICIT_HASH
    public = build_success_payload(document)
    assert "attribution" not in public["analytics"]
    assert public["analytics"]["benchmark"] is not None


def test_new_attribution_document_keeps_attribution_and_explicit_benchmark() -> None:
    # Given a new document whose caller declared no benchmark.
    step = _run(_base_payload())
    document = step.document
    dumped = document.model_dump(mode="json", by_alias=True)
    layers = PortfolioDataHashes(
        plan_hash=dumped["hashes"]["plan_hash"],
        planning_data_hash=dumped["hashes"]["planning_data_hash"],
        execution_data_fingerprint=dumped["hashes"]["execution_data_fingerprint"],
    )

    # Then the real attribution is retained and the benchmark is explicit null.
    public = build_success_payload(document)
    assert public["analytics"]["attribution"]["scope"] == "one_day"
    assert "benchmark" in public["analytics"]
    assert public["analytics"]["benchmark"] is None

    # Then re-validating the full document neither drops nor invents attribution.
    reparsed = PortfolioResult.model_validate(dumped)
    redumped = reparsed.model_dump(mode="json", by_alias=True)
    assert redumped["analytics"]["attribution"] == dumped["analytics"]["attribution"]
    assert document_hash(reparsed, layers) == dumped["hashes"]["document_hash"]
