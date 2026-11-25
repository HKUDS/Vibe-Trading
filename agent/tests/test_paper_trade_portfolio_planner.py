"""Pure prior-mark target-weight planner tests for pt-v2.0."""

from __future__ import annotations

import ast
import inspect
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest

from src.tools.paper_trade.portfolio import planner
from src.tools.paper_trade.portfolio.ledger import (
    BucketLedger,
    LedgerPosition,
    PortfolioLedger,
)
from src.tools.paper_trade.portfolio.models import Currency, FxSnapshot, TargetWeight
from src.tools.paper_trade.portfolio.planner import PlanningMark, plan_target_weights
from src.tools.paper_trade.portfolio.schema import PortfolioRequestError

AS_OF = datetime(2026, 11, 13, 11, tzinfo=timezone.utc)
PLANNING_AT = datetime(2026, 11, 13, 12, tzinfo=timezone.utc)
TRADE_DATE = date(2026, 11, 13)
PRIOR_DATE = date(2026, 11, 12)


def _ledger(*, cash: dict[str, str] | None = None) -> PortfolioLedger:
    supplied = cash or {}
    return PortfolioLedger(
        buckets=(
            BucketLedger(
                bucket_id="cn",
                market="cn_a",
                currency="CNY",
                cash=Decimal(supplied.get("cn", "100000.00")),
                positions=(
                    LedgerPosition(
                        symbol="600519.SH",
                        qty=100,
                        avg_cost=Decimal("1400.00"),
                        market="cn_a",
                        currency="CNY",
                    ),
                ),
            ),
            BucketLedger(
                bucket_id="hk",
                market="hk",
                currency="HKD",
                cash=Decimal(supplied.get("hk", "50000.00")),
                positions=(
                    LedgerPosition(
                        symbol="00700.HK",
                        qty=100,
                        avg_cost=Decimal("300.00"),
                        market="hk",
                        currency="HKD",
                    ),
                ),
            ),
            BucketLedger(
                bucket_id="us",
                market="us",
                currency="USD",
                cash=Decimal(supplied.get("us", "25000.00")),
                positions=(
                    LedgerPosition(
                        symbol="AAPL.US",
                        qty=100,
                        avg_cost=Decimal("180.00"),
                        market="us",
                        currency="USD",
                    ),
                ),
            ),
        )
    )


def _mark(
    symbol: str,
    close: str,
    *,
    price_date: date = PRIOR_DATE,
    as_of: datetime = AS_OF,
) -> PlanningMark:
    return PlanningMark(
        symbol=symbol,
        price_date=price_date,
        close=Decimal(close),
        source="fixture.planning",
        as_of=as_of,
    )


def _marks() -> tuple[PlanningMark, ...]:
    return (
        _mark("600519.SH", "1450.00"),
        _mark("00700.HK", "320.00"),
        _mark("AAPL.US", "190.00"),
        _mark("MSFT.US", "410.00"),
    )


def _fx() -> tuple[FxSnapshot, ...]:
    return (
        FxSnapshot(
            rate_id="cny-usd-plan",
            from_currency="CNY",
            to_currency="USD",
            rate="0.14",
            as_of=AS_OF,
            source="fixture.fx",
        ),
        FxSnapshot(
            rate_id="hkd-usd-plan",
            from_currency="HKD",
            to_currency="USD",
            rate="0.128",
            as_of=AS_OF,
            source="fixture.fx",
        ),
    )


def _target(
    bucket_id: str,
    symbol: str,
    currency: Currency,
    weight: str,
) -> TargetWeight:
    return TargetWeight(
        bucket_id=bucket_id,
        symbol=symbol,
        currency=currency,
        weight=weight,
    )


def _targets() -> tuple[TargetWeight, ...]:
    return (
        _target("cn", "600519.SH", "CNY", "0.30"),
        _target("hk", "00700.HK", "HKD", "0.10"),
        _target("us", "AAPL.US", "USD", "0.20"),
        _target("us", "MSFT.US", "USD", "0.15"),
    )


def _targets_with(weights: dict[str, str]) -> tuple[TargetWeight, ...]:
    return tuple(
        _target(target.bucket_id, target.symbol, target.currency, weights.get(target.symbol, target.weight))
        for target in _targets()
    )


def _plan(
    *,
    ledger: PortfolioLedger | None = None,
    marks: tuple[PlanningMark, ...] | None = None,
    fx_snapshots: tuple[FxSnapshot, ...] | None = None,
    target_weights: tuple[TargetWeight, ...] | None = None,
    rebalance_band: str = "0",
) -> planner.TargetWeightAllocation:
    return plan_target_weights(
        _ledger() if ledger is None else ledger,
        trade_date=TRADE_DATE,
        planning_at=PLANNING_AT,
        base_currency="USD",
        marks=_marks() if marks is None else marks,
        fx_snapshots=_fx() if fx_snapshots is None else fx_snapshots,
        target_weights=_targets() if target_weights is None else target_weights,
        rebalance_band=rebalance_band,
    )


def _lines(plan: planner.TargetWeightAllocation) -> dict[str, planner.PlannerLine]:
    return {line.symbol: line for line in plan.lines}


def _assert_reason(exc: pytest.ExceptionInfo[PortfolioRequestError], reason: str) -> None:
    assert exc.value.code == "INVALID_REQUEST"
    assert exc.value.reason == reason


def test_three_currency_plan_has_stable_prior_mark_nav_and_values() -> None:
    # Given one post-conversion ledger spanning CNY, HKD and USD buckets.
    # When the pure planner values only strictly prior marks through direct FX pairs.
    plan = _plan()

    # Then planning NAV, per-bucket NAV and every line are deterministic.
    assert plan.nav.reported_nav == Decimal("88796.00")
    assert plan.nav.exact_nav == Decimal("88796.00")
    assert plan.nav.residual == Decimal("0.00")
    assert {row.bucket_id: row.nav_base for row in plan.buckets} == {
        "cn": Decimal("34300.00"),
        "hk": Decimal("10496.00"),
        "us": Decimal("44000.00"),
    }
    lines = _lines(plan)
    assert set(lines) == {"600519.SH", "00700.HK", "AAPL.US", "MSFT.US"}
    assert all(line.price_date < plan.trade_date for line in plan.lines)
    assert lines["600519.SH"] == planner.PlannerLine(
        bucket_id="cn",
        symbol="600519.SH",
        currency="CNY",
        price=Decimal("1450.000000"),
        price_date=PRIOR_DATE,
        mark_source="fixture.planning",
        mark_as_of=AS_OF,
        fx_rate_id="cny-usd-plan",
        fx_rate=Decimal("0.140000000000"),
        base_price=Decimal("203.000000"),
        current_qty=100,
        current_value_base=Decimal("20300.00"),
        current_weight=Decimal("0.228613901527"),
        target_weight=Decimal("0.300000000000"),
        target_value_base=Decimal("26638.80"),
        target_quantity=131,
        weight_gap=Decimal("0.071386098473"),
        within_band=False,
    )
    assert lines["00700.HK"].base_price == Decimal("40.96")
    assert lines["00700.HK"].current_value_base == Decimal("4096.00")
    assert lines["00700.HK"].current_weight == Decimal("0.046128203973")
    assert lines["00700.HK"].target_value_base == Decimal("8879.60")
    assert lines["00700.HK"].target_quantity == 216
    assert lines["AAPL.US"].base_price == Decimal("190.00")
    assert lines["AAPL.US"].current_weight == Decimal("0.213973602415")
    assert lines["AAPL.US"].target_value_base == Decimal("17759.20")
    assert lines["AAPL.US"].target_quantity == 93
    assert lines["AAPL.US"].weight_gap == Decimal("-0.013973602415")
    assert lines["MSFT.US"].current_qty == 0
    assert lines["MSFT.US"].current_value_base == Decimal("0.00")
    assert lines["MSFT.US"].target_value_base == Decimal("13319.40")
    assert lines["MSFT.US"].target_quantity == 32
    assert plan.target_weight_total == Decimal("0.75")
    assert plan.cash_weight == Decimal("0.25")
    for line in plan.lines:
        assert type(line.current_qty) is int
        assert type(line.target_quantity) is int
        assert isinstance(line.current_value_base, Decimal)
        assert isinstance(line.target_value_base, Decimal)


def test_default_zero_band_never_skips_a_line() -> None:
    # Given the default zero rebalance band.
    # When every target weight is planned.
    plan = _plan()

    # Then no weight is suppressed, including zero-gap lines.
    assert plan.rebalance_band == Decimal("0")
    assert all(line.within_band is False for line in plan.lines)


def test_nonzero_band_skips_only_weights_whose_absolute_gap_is_within_it() -> None:
    # Given a two-percent band and four gaps on both sides of it.
    # When the pure planner classifies each target weight.
    plan = _plan(rebalance_band="0.02")

    # Then only the AAPL gap is within the band and its target stays visible.
    assert {line.symbol: line.within_band for line in plan.lines} == {
        "600519.SH": False,
        "00700.HK": False,
        "AAPL.US": True,
        "MSFT.US": False,
    }
    assert _lines(plan)["AAPL.US"].target_quantity == 93


def test_unmentioned_holding_targets_zero_and_capital_remains_cash() -> None:
    # Given target weights that omit an existing AAPL holding.
    # When the planner builds the full union of held and targeted instruments.
    targets = tuple(target for target in _targets() if target.symbol != "AAPL.US")
    plan = _plan(target_weights=targets)

    # Then the omitted holding is targeted to zero and the rest is cash.
    apple = _lines(plan)["AAPL.US"]
    assert apple.target_weight == Decimal("0")
    assert apple.target_value_base == Decimal("0.00")
    assert apple.target_quantity == 0
    assert apple.current_weight == Decimal("0.213973602415")
    assert plan.target_weight_total == Decimal("0.55")
    assert plan.cash_weight == Decimal("0.45")


def test_plan_is_order_independent_and_has_no_float_arithmetic() -> None:
    # Given the same marks and targets supplied in reverse order.
    # When both plans are built.
    forward = _plan()
    reversed_inputs = _plan(
        marks=tuple(reversed(_marks())),
        target_weights=tuple(reversed(_targets())),
    )

    # Then the immutable result is identical and no line value is a float.
    assert reversed_inputs == forward
    numeric_values: list[Any] = [
        forward.nav.reported_nav,
        forward.nav.exact_nav,
        forward.nav.residual,
        forward.target_weight_total,
        forward.cash_weight,
    ]
    for line in forward.lines:
        numeric_values.extend(
            (
                line.price,
                line.fx_rate,
                line.base_price,
                line.current_value_base,
                line.current_weight,
                line.target_weight,
                line.target_value_base,
                line.weight_gap,
            )
        )
    assert all(isinstance(value, Decimal) for value in numeric_values)


def test_planner_does_not_import_execution_or_matcher_modules() -> None:
    # Given the planner module source.
    # When its imports are inspected as an architecture boundary.
    tree = ast.parse(inspect.getsource(planner))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    # Then no execution-data or matching module can leak into planning.
    assert not any("engine" in name for name in imported)
    assert not any(name.endswith("data") for name in imported)


def test_weight_sum_above_one_fails_before_planning() -> None:
    # Given four individually valid weights whose exact sum is 1.10.
    # When / Then the planner rejects the portfolio target.
    with pytest.raises(PortfolioRequestError) as caught:
        _plan(
            target_weights=_targets_with(
                {
                    "600519.SH": "0.40",
                    "00700.HK": "0.30",
                    "AAPL.US": "0.20",
                    "MSFT.US": "0.20",
                }
            )
        )

    _assert_reason(caught, "target_weights_exceed_one")


def test_negative_target_weight_is_rejected() -> None:
    # Given a negative long-only weight.
    # When / Then it cannot reach mark valuation or matching.
    with pytest.raises(PortfolioRequestError) as caught:
        _plan(target_weights=_targets_with({"MSFT.US": "-0.01"}))

    _assert_reason(caught, "invalid_target_weight")


def test_missing_planning_mark_for_a_held_instrument_is_rejected() -> None:
    # Given an AAPL holding with no planning mark even though it has no target.
    # When / Then the planner fails closed instead of inventing a price.
    marks = tuple(mark for mark in _marks() if mark.symbol != "AAPL.US")
    targets = tuple(target for target in _targets() if target.symbol != "AAPL.US")
    with pytest.raises(PortfolioRequestError) as caught:
        _plan(marks=marks, target_weights=targets)

    _assert_reason(caught, "missing_planning_mark")
    assert caught.value.path == "planning_marks.AAPL.US"


def test_same_day_mark_is_stale_and_rejected() -> None:
    # Given a mark dated on trade_date instead of strictly before it.
    # When / Then the planner rejects the non-prior mark.
    marks = tuple(
        replace(mark, price_date=TRADE_DATE) if mark.symbol == "AAPL.US" else mark
        for mark in _marks()
    )
    with pytest.raises(PortfolioRequestError) as caught:
        _plan(marks=marks)

    _assert_reason(caught, "stale_planning_mark")


def test_future_dated_mark_is_rejected() -> None:
    # Given a mark dated after trade_date.
    # When / Then the planner rejects the lookahead bar.
    marks = tuple(
        replace(mark, price_date=date(2026, 11, 16)) if mark.symbol == "AAPL.US" else mark
        for mark in _marks()
    )
    with pytest.raises(PortfolioRequestError) as caught:
        _plan(marks=marks)

    _assert_reason(caught, "future_planning_mark")


def test_mark_observed_after_the_planning_instant_is_rejected() -> None:
    # Given a prior-dated close whose provenance timestamp is after planning_at.
    # When / Then the planner rejects the future observation.
    marks = tuple(
        replace(mark, as_of=PLANNING_AT + timedelta(hours=1)) if mark.symbol == "AAPL.US" else mark
        for mark in _marks()
    )
    with pytest.raises(PortfolioRequestError) as caught:
        _plan(marks=marks)

    _assert_reason(caught, "future_planning_mark")


def test_negative_rebalance_band_is_rejected() -> None:
    # Given a negative band.
    # When / Then the planner rejects the malformed rebalance tolerance.
    with pytest.raises(PortfolioRequestError) as caught:
        _plan(rebalance_band="-0.01")

    _assert_reason(caught, "invalid_rebalance_band")


def test_negative_post_conversion_cash_is_infeasible() -> None:
    # Given a post-conversion bucket whose cash is below zero.
    # When / Then no plan can be produced from that ledger.
    with pytest.raises(PortfolioRequestError) as caught:
        _plan(ledger=_ledger(cash={"cn": "-1.00"}))

    _assert_reason(caught, "infeasible_post_conversion_cash")
    assert caught.value.bucket_id == "cn"


def test_duplicate_target_instrument_is_rejected() -> None:
    # Given the same instrument twice in one target list.
    # When / Then uniqueness fails before any quantity is computed.
    targets = _targets() + (_target("us", "MSFT.US", "USD", "0"),)
    with pytest.raises(PortfolioRequestError) as caught:
        _plan(target_weights=targets)

    _assert_reason(caught, "duplicate_target_instrument")


def test_target_instrument_owned_by_another_bucket_is_rejected() -> None:
    # Given AAPL, owned by the US bucket, targeted through the HK bucket.
    # When / Then the planner refuses the cross-bucket instrument.
    targets = (
        _target("cn", "600519.SH", "CNY", "0.30"),
        _target("hk", "00700.HK", "HKD", "0.10"),
        _target("hk", "AAPL.US", "HKD", "0.20"),
        _target("us", "MSFT.US", "USD", "0.15"),
    )
    with pytest.raises(PortfolioRequestError) as caught:
        _plan(target_weights=targets)

    _assert_reason(caught, "instrument_bucket_mismatch")


def test_target_currency_must_match_its_bucket() -> None:
    # Given a USD bucket target declared in CNY.
    # When / Then the canonical bucket currency is enforced.
    targets = (
        _target("cn", "600519.SH", "CNY", "0.30"),
        _target("hk", "00700.HK", "HKD", "0.10"),
        _target("us", "AAPL.US", "USD", "0.20"),
        _target("us", "MSFT.US", "CNY", "0.15"),
    )
    with pytest.raises(PortfolioRequestError) as caught:
        _plan(target_weights=targets)

    _assert_reason(caught, "instrument_currency_mismatch")


def test_unknown_target_bucket_is_rejected() -> None:
    # Given a target naming a bucket absent from the post-conversion ledger.
    # When / Then the planner does not invent an account.
    targets = (
        _target("cn", "600519.SH", "CNY", "0.30"),
        _target("jp", "7203.JP", "USD", "0.10"),
    )
    with pytest.raises(PortfolioRequestError) as caught:
        _plan(target_weights=targets)

    _assert_reason(caught, "unknown_bucket")


def test_missing_direct_planning_fx_pair_is_rejected() -> None:
    # Given no CNY-to-USD planning pair for a CNY bucket.
    # When / Then the planner does not invert or triangulate a rate.
    with pytest.raises(PortfolioRequestError) as caught:
        _plan(fx_snapshots=())

    _assert_reason(caught, "missing_direct_fx_pair")


def test_nonpositive_planning_nav_is_rejected() -> None:
    # Given a zero-cash, zero-position ledger.
    # When / Then target weights cannot be scaled against a nonpositive NAV.
    ledger = PortfolioLedger(
        buckets=(BucketLedger(bucket_id="us", market="us", currency="USD", cash=Decimal("0.00")),)
    )
    with pytest.raises(PortfolioRequestError) as caught:
        _plan(ledger=ledger, marks=(), fx_snapshots=(), target_weights=())

    _assert_reason(caught, "nonpositive_planning_nav")
