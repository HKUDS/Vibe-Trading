"""Decimal reconstruct-and-check execution adapter tests for pt-v2.0.

The adapter must treat the legacy daily engine only as an ordered
fill/reject/cancel producer. Every quantity, execution price and fee is
reconstructed from the source integer order, the target-day close snapshot and
the same ``MarketRules``; the legacy float ``Fill`` is a consistency guard, and
legacy ``end_state``/``NavPoint`` never enter portfolio accounting.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

import pandas as pd
import pytest

from src.tools.paper_trade import engine
from src.tools.paper_trade.portfolio import execution
from src.tools.paper_trade.portfolio.data import preflight_portfolio_data
from src.tools.paper_trade.portfolio.execution import (
    DecimalExecutionAdapter,
    ExecutionAdapterError,
)
from src.tools.paper_trade.portfolio.ledger import (
    BucketLedger,
    CashMovement,
    PortfolioLedger,
    PositionMovement,
)
from src.tools.paper_trade.portfolio.numeric import parse_effective_fee_model
from src.tools.paper_trade.portfolio.order_plan import build_explicit_order_plan
from src.tools.paper_trade.portfolio.planner import PlanningMark
from src.tools.paper_trade.portfolio.schema import parse_portfolio_request
from src.tools.paper_trade.portfolio.sessions import resolve_portfolio_sessions
from src.tools.paper_trade.rules import MarketRules
from src.tools.paper_trade.schema import AccountState, NavPoint
from tests.paper_trade_portfolio_fixture import valid_portfolio_payload

AS_OF = datetime(2026, 11, 13, 12, tzinfo=timezone.utc)
TRADE_DATE = date(2026, 11, 13)
PRIOR_DATE = date(2026, 11, 12)
DAY = TRADE_DATE.isoformat()
PRIOR = PRIOR_DATE.isoformat()

CN_CLOSE = Decimal("1421.00")
HK_CLOSE = Decimal("417.80")
US_CLOSE = Decimal("343.46")

BUY_ORDERS = [
    {
        "order_id": "cn-buy-1",
        "bucket_id": "cn",
        "symbol": "600519.SH",
        "currency": "CNY",
        "side": "buy",
        "qty": 100,
    },
    {
        "order_id": "hk-buy-1",
        "bucket_id": "hk",
        "symbol": "00700.HK",
        "currency": "HKD",
        "side": "buy",
        "qty": 100,
    },
    {
        "order_id": "us-buy-1",
        "bucket_id": "us",
        "symbol": "AAPL.US",
        "currency": "USD",
        "side": "buy",
        "qty": 10,
    },
]

SELL_ORDERS = [
    {
        "order_id": "cn-sell-1",
        "bucket_id": "cn",
        "symbol": "600519.SH",
        "currency": "CNY",
        "side": "sell",
        "qty": 100,
    },
    {
        "order_id": "hk-sell-1",
        "bucket_id": "hk",
        "symbol": "00700.HK",
        "currency": "HKD",
        "side": "sell",
        "qty": 100,
    },
    {
        "order_id": "us-sell-1",
        "bucket_id": "us",
        "symbol": "AAPL.US",
        "currency": "USD",
        "side": "sell",
        "qty": 10,
    },
]

MARKS = (
    PlanningMark(
        symbol="600519.SH",
        price_date=PRIOR_DATE,
        close=Decimal("1418.00"),
        source="fixture.prior",
        as_of=AS_OF,
    ),
    PlanningMark(
        symbol="00700.HK",
        price_date=PRIOR_DATE,
        close=Decimal("410.00"),
        source="fixture.prior",
        as_of=AS_OF,
    ),
    PlanningMark(
        symbol="AAPL.US",
        price_date=PRIOR_DATE,
        close=Decimal("340.00"),
        source="fixture.prior",
        as_of=AS_OF,
    ),
)


class FakeLoader:
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
            {"exchange": "SSE", "cal_date": day.strftime("%Y-%m-%d"), "is_open": 1,
             "pretrade_date": ""}
            for day in pd.date_range(start_date, end_date)
        ]
        return pd.DataFrame(rows, columns=["exchange", "cal_date", "is_open", "pretrade_date"])


def _frame(prior: float, target: float) -> pd.DataFrame:
    records = [
        {"trade_date": PRIOR, "open": prior, "high": prior, "low": prior,
         "close": prior, "volume": 1000.0},
        {"trade_date": DAY, "open": target, "high": target, "low": target,
         "close": target, "volume": 1000.0},
    ]
    frame = pd.DataFrame(records)
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    return frame.set_index("trade_date")[["open", "high", "low", "close", "volume"]]


def _payload(
    orders: list[dict[str, Any]],
    *,
    cn_cash: str = "100000.00",
    us_positions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    payload = valid_portfolio_payload()
    payload["fx_conversions"] = []
    payload["portfolio_state"]["buckets"][0]["cash"] = cn_cash
    if us_positions is not None:
        payload["portfolio_state"]["buckets"][2]["positions"] = us_positions
    payload["orders"] = orders
    return payload


def _request(payload: dict[str, Any]):
    return parse_portfolio_request(payload)


def _ledger(request) -> PortfolioLedger:
    return PortfolioLedger.from_request(request)


def _prepared(request):
    loaders = {
        "cn_a": FakeLoader({"600519.SH": _frame(1418.0, 1421.0)}, "cn-fixture"),
        "hk": FakeLoader({"00700.HK": _frame(410.0, 417.8)}, "hk-fixture"),
        "us": FakeLoader({"AAPL.US": _frame(340.0, 343.46)}, "us-fixture"),
    }
    sessions = resolve_portfolio_sessions(
        request,
        price_dates={session.market: request.trade_date for session in request.sessions},
    )
    symbols_by_bucket: dict[str, set[str]] = {}
    for order in request.orders or ():
        symbols_by_bucket.setdefault(order.bucket_id, set()).add(order.symbol)
    return preflight_portfolio_data(
        sessions,
        symbols_by_bucket=symbols_by_bucket,
        loaders=loaders,
        ch_clients={"cn_a": None},
        calendar_client=OpenCalendar(),
    )


def _plan(request, ledger: PortfolioLedger):
    models = tuple(
        parse_effective_fee_model(bucket)
        for bucket in request.portfolio_state.buckets
    )
    return build_explicit_order_plan(
        request.orders or (),
        ledger=ledger,
        trade_date=request.trade_date,
        planning_at=request.planning_at,
        base_currency=request.base_currency,
        marks=MARKS,
        fx_snapshots=request.fx_snapshots,
        fee_models=models,
    )


def _scenario(
    orders: list[dict[str, Any]],
    *,
    cn_cash: str = "100000.00",
    us_positions: list[dict[str, Any]] | None = None,
):
    request = _request(_payload(orders, cn_cash=cn_cash, us_positions=us_positions))
    ledger = _ledger(request)
    plan = _plan(request, ledger)
    prepared = _prepared(request)
    return request, ledger, plan, prepared


def _by_bucket(ledger: PortfolioLedger) -> dict[str, BucketLedger]:
    return {bucket.bucket_id: bucket for bucket in ledger.buckets}


def _by_symbol(ledger: PortfolioLedger) -> dict[str, Any]:
    return {position.symbol: position for position in ledger.positions()}


def test_buy_fills_match_independent_fee_goldens_and_replay_exact_cash() -> None:
    # Given three canonical buys whose fees are hand-computed to the cent.
    request, ledger, plan, prepared = _scenario(BUY_ORDERS, cn_cash="200000.00")

    # When the Decimal adapter reconstructs every fill and ledger event.
    outcome = DecimalExecutionAdapter().match(request, ledger, plan, prepared)
    end = ledger.apply(outcome.ledger_events)

    # Then reconstructed fees equal the independent goldens at Decimal precision.
    # cn: max(142100*0.00025, 5) + 142100*0.00001 = 35.525 + 1.421 -> 36.95
    # hk: 12.534 + whole-HKD stamp 42 + levy 1.2534 -> 55.79
    # us: max(10*0.0049, 0.99) + 0 -> 0.99
    assert outcome.complete is True
    assert outcome.rejected_orders == ()
    assert outcome.canceled_orders == ()
    assert [(fill.plan_order_id, fill.price, fill.fee) for fill in outcome.fills] == [
        ("cn-buy-1", CN_CLOSE, Decimal("36.95")),
        ("hk-buy-1", HK_CLOSE, Decimal("55.79")),
        ("us-buy-1", US_CLOSE, Decimal("0.99")),
    ]

    # Then the event stream is exactly cash-positive/negative plus position moves.
    assert outcome.ledger_events == (
        CashMovement(bucket_id="cn", amount=Decimal("-142136.95")),
        PositionMovement(
            bucket_id="cn", symbol="600519.SH", qty_delta=100,
            avg_cost=Decimal("1410.50"),
        ),
        CashMovement(bucket_id="hk", amount=Decimal("-41835.79")),
        PositionMovement(
            bucket_id="hk", symbol="00700.HK", qty_delta=100,
            avg_cost=Decimal("358.90"),
        ),
        CashMovement(bucket_id="us", amount=Decimal("-3435.59")),
        PositionMovement(
            bucket_id="us", symbol="AAPL.US", qty_delta=10,
            avg_cost=Decimal("343.46"),
        ),
    )

    # Then the Decimal portfolio ended at independently computed cash/positions.
    buckets = _by_bucket(end)
    assert buckets["cn"].cash == Decimal("57863.05")
    assert buckets["hk"].cash == Decimal("8164.21")
    assert buckets["us"].cash == Decimal("21564.41")
    positions = _by_symbol(end)
    assert (positions["600519.SH"].qty, positions["600519.SH"].avg_cost) == (
        200, Decimal("1410.50"))
    assert (positions["00700.HK"].qty, positions["00700.HK"].avg_cost) == (
        200, Decimal("358.90"))
    assert (positions["AAPL.US"].qty, positions["AAPL.US"].avg_cost) == (
        10, Decimal("343.46"))


def test_sell_fills_require_positive_proceeds_and_replay_exact_cash() -> None:
    # Given three canonical sells against held positions.
    request, ledger, plan, prepared = _scenario(
        SELL_ORDERS,
        us_positions=[
            {"symbol": "AAPL.US", "qty": 10, "avg_cost": "300.00", "currency": "USD"}
        ],
    )

    # When the adapter reconstructs the sale proceeds and fees.
    outcome = DecimalExecutionAdapter().match(request, ledger, plan, prepared)
    end = ledger.apply(outcome.ledger_events)

    # Then sell fees match goldens: cn stamp makes 107.996 -> 108.00.
    assert outcome.complete is True
    assert [(fill.plan_order_id, fill.fee) for fill in outcome.fills] == [
        ("cn-sell-1", Decimal("108.00")),
        ("hk-sell-1", Decimal("55.79")),
        ("us-sell-1", Decimal("0.99")),
    ]
    assert outcome.ledger_events == (
        CashMovement(bucket_id="cn", amount=Decimal("141992.00")),
        PositionMovement(bucket_id="cn", symbol="600519.SH", qty_delta=-100),
        CashMovement(bucket_id="hk", amount=Decimal("41724.21")),
        PositionMovement(bucket_id="hk", symbol="00700.HK", qty_delta=-100),
        CashMovement(bucket_id="us", amount=Decimal("3433.61")),
        PositionMovement(bucket_id="us", symbol="AAPL.US", qty_delta=-10),
    )

    # Then sold positions vanish and cash equals opening plus exact proceeds.
    buckets = _by_bucket(end)
    assert buckets["cn"].cash == Decimal("241992.00")
    assert buckets["hk"].cash == Decimal("91724.21")
    assert buckets["us"].cash == Decimal("28433.61")
    assert _by_symbol(end) == {}


def test_legacy_end_state_and_nav_points_are_ignored(monkeypatch) -> None:
    # Given a real engine outcome whose float end_state/NAV rows are poisoned.
    real_run = engine.run_day_loop

    def poisoned(*args, **kwargs):
        outcome = real_run(*args, **kwargs)
        return replace(
            outcome,
            end_state=AccountState(cash=-123.45, positions=()),
            nav_series=(
                NavPoint(date=DAY, nav=float("nan"), cash=-123.45, position_value=float("inf")),
            ),
        )

    monkeypatch.setattr(engine, "run_day_loop", poisoned)
    request, ledger, plan, prepared = _scenario(BUY_ORDERS, cn_cash="200000.00")

    # When the adapter replays only fills into the Decimal ledger.
    outcome = DecimalExecutionAdapter().match(request, ledger, plan, prepared)
    end = ledger.apply(outcome.ledger_events)

    # Then the poisoned legacy values never reach the portfolio end state.
    assert len(outcome.fills) == 3
    assert _by_bucket(end)["cn"].cash == Decimal("57863.05")
    assert _by_bucket(end)["us"].cash == Decimal("21564.41")


def test_mismatched_legacy_fill_aborts_before_any_end_ledger(monkeypatch) -> None:
    # Given a legacy Fill whose float fee no longer matches reconstruction.
    real_run = engine.run_day_loop

    def mismatched(*args, **kwargs):
        outcome = real_run(*args, **kwargs)
        fills = list(outcome.fills)
        fills[0] = replace(fills[0], fee=fills[0].fee + 1.0)
        return replace(outcome, fills=tuple(fills))

    monkeypatch.setattr(engine, "run_day_loop", mismatched)
    request, ledger, plan, prepared = _scenario(BUY_ORDERS, cn_cash="200000.00")

    # When / Then the adapter raises and returns no fills or end ledger.
    with pytest.raises(ExecutionAdapterError) as caught:
        DecimalExecutionAdapter().match(request, ledger, plan, prepared)
    assert caught.value.reason == "legacy_execution_mismatch"
    assert caught.value.bucket_id == "cn"


def test_nonpositive_sale_proceeds_abort() -> None:
    # Given a sale whose reconstructed fee exceeds its whole notional.
    request, ledger, plan, prepared = _scenario(
        SELL_ORDERS,
        us_positions=[
            {"symbol": "AAPL.US", "qty": 10, "avg_cost": "300.00", "currency": "USD"}
        ],
    )
    original = execution._fee_for
    execution._fee_for = lambda rules, side, qty, price: (  # type: ignore[assignment]
        Decimal("999999.00") if side == "sell" else original(rules, side, qty, price)
    )
    try:
        with pytest.raises(ExecutionAdapterError) as caught:
            DecimalExecutionAdapter().match(request, ledger, plan, prepared)
    finally:
        execution._fee_for = original  # type: ignore[assignment]
    assert caught.value.reason == "nonpositive_sale_proceeds"
    assert caught.value.bucket_id == "cn"


def test_negative_reconstructed_fee_aborts(monkeypatch) -> None:
    # Given a reconstruction that would book a negative fee.
    request, ledger, plan, prepared = _scenario(BUY_ORDERS, cn_cash="200000.00")
    monkeypatch.setattr(
        execution, "_fee_for", lambda rules, side, qty, price: Decimal("-0.01"))
    with pytest.raises(ExecutionAdapterError) as caught:
        DecimalExecutionAdapter().match(request, ledger, plan, prepared)
    assert caught.value.reason == "negative_execution_fee"


def test_negative_cash_after_fill_aborts(monkeypatch) -> None:
    # Given an engine gate that accepts a buy whose booked fee exceeds cash.
    request, ledger, plan, prepared = _scenario(
        [
            {
                "order_id": "us-buy-1",
                "bucket_id": "us",
                "symbol": "AAPL.US",
                "currency": "USD",
                "side": "buy",
                "qty": 10,
            }
        ],
    )
    monkeypatch.setattr(
        MarketRules,
        "cash_rejection",
        lambda self, side, qty, price, cash, *, volume_share=False: None,
    )
    monkeypatch.setattr(
        MarketRules, "fee", lambda self, side, qty, price: Decimal("999999.00"))
    with pytest.raises(ExecutionAdapterError) as caught:
        DecimalExecutionAdapter().match(request, ledger, plan, prepared)
    assert caught.value.reason == "negative_execution_cash"
    assert caught.value.bucket_id == "us"


def test_duplicate_terminal_outcome_aborts(monkeypatch) -> None:
    # Given the legacy matcher reports the same planned order twice.
    real_run = engine.run_day_loop

    def duplicate(*args, **kwargs):
        outcome = real_run(*args, **kwargs)
        if not outcome.fills:
            return outcome
        return replace(outcome, fills=(outcome.fills[0], outcome.fills[0]))

    monkeypatch.setattr(engine, "run_day_loop", duplicate)
    request, ledger, plan, prepared = _scenario(BUY_ORDERS, cn_cash="200000.00")
    with pytest.raises(ExecutionAdapterError) as caught:
        DecimalExecutionAdapter().match(request, ledger, plan, prepared)
    assert caught.value.reason == "duplicate_order_outcome"


def test_missing_terminal_outcome_aborts(monkeypatch) -> None:
    # Given the legacy matcher omits every terminal row for a planned order.
    real_run = engine.run_day_loop

    def missing(*args, **kwargs):
        outcome = real_run(*args, **kwargs)
        return replace(outcome, fills=(), rejected_orders=(), canceled_orders=())

    monkeypatch.setattr(engine, "run_day_loop", missing)
    request, ledger, plan, prepared = _scenario(BUY_ORDERS, cn_cash="200000.00")
    with pytest.raises(ExecutionAdapterError) as caught:
        DecimalExecutionAdapter().match(request, ledger, plan, prepared)
    assert caught.value.reason == "missing_order_outcome"


def test_nonfinite_legacy_fill_value_aborts(monkeypatch) -> None:
    # Given a legacy Fill carrying an infinite price.
    real_run = engine.run_day_loop

    def nonfinite(*args, **kwargs):
        outcome = real_run(*args, **kwargs)
        fills = list(outcome.fills)
        fills[0] = replace(fills[0], price=float("inf"))
        return replace(outcome, fills=tuple(fills))

    monkeypatch.setattr(engine, "run_day_loop", nonfinite)
    request, ledger, plan, prepared = _scenario(BUY_ORDERS, cn_cash="200000.00")
    with pytest.raises(ExecutionAdapterError) as caught:
        DecimalExecutionAdapter().match(request, ledger, plan, prepared)
    assert caught.value.reason == "nonfinite_legacy_value"


def test_malformed_request_aborts() -> None:
    # Given a non-request object at the adapter boundary.
    request, ledger, plan, prepared = _scenario(BUY_ORDERS, cn_cash="200000.00")
    with pytest.raises(ExecutionAdapterError) as caught:
        DecimalExecutionAdapter().match(object(), ledger, plan, prepared)  # type: ignore[arg-type]
    assert caught.value.reason == "invalid_request"


def test_stale_or_mismatched_ledger_aborts() -> None:
    # Given a ledger whose cash disagrees with the plan's post-conversion cash.
    request, ledger, plan, prepared = _scenario(BUY_ORDERS, cn_cash="200000.00")
    stale = PortfolioLedger(
        buckets=tuple(
            replace(bucket, cash=Decimal("1.00"))
            if bucket.bucket_id == "cn"
            else bucket
            for bucket in ledger.buckets
        )
    )
    with pytest.raises(ExecutionAdapterError) as caught:
        DecimalExecutionAdapter().match(request, stale, plan, prepared)
    assert caught.value.reason == "plan_ledger_cash_mismatch"
    assert caught.value.bucket_id == "cn"


def test_rejected_order_is_one_terminal_outcome_without_ledger_events() -> None:
    # Given a buy limit below the target close: the legacy matcher rejects it.
    request, ledger, plan, prepared = _scenario(
        [
            {
                "order_id": "us-buy-1",
                "bucket_id": "us",
                "symbol": "AAPL.US",
                "currency": "USD",
                "side": "buy",
                "qty": 10,
                "limit": "300.00",
            }
        ],
    )

    # When the adapter maps the ordered reject row.
    outcome = DecimalExecutionAdapter().match(request, ledger, plan, prepared)

    # Then exactly one terminal outcome exists and no cash/position moves.
    assert outcome.complete is False
    assert outcome.fills == ()
    assert outcome.canceled_orders == ()
    assert len(outcome.rejected_orders) == 1
    rejection = outcome.rejected_orders[0]
    assert (rejection.plan_order_id, rejection.qty, rejection.trade_date) == (
        "us-buy-1", 10, TRADE_DATE)
    assert rejection.reason_code == "limit_not_marketable"
    assert outcome.ledger_events == ()
    assert ledger.apply(outcome.ledger_events) == ledger
