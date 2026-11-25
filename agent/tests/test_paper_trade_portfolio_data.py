"""Bucket-scoped raw market-data loading and all-bucket preflight tests."""

from __future__ import annotations

import math
from datetime import date, datetime, timezone

import pandas as pd
import pytest

from src.tools.paper_trade import engine
from src.tools.paper_trade.portfolio.data import preflight_portfolio_data
from src.tools.paper_trade.portfolio.models import Market, MarketSession
from src.tools.paper_trade.portfolio.sessions import (
    BucketSession,
    PortfolioSessionError,
    PortfolioSessions,
)

AS_OF = datetime(2026, 11, 13, 12, tzinfo=timezone.utc)
TRADE_DATE = date(2026, 11, 13)
PRIOR_DATE = date(2026, 11, 12)
DAY = TRADE_DATE.isoformat()
PRIOR = PRIOR_DATE.isoformat()


class SpyLoader:
    """Offline loader double that records every requested symbol batch."""

    def __init__(self, frames: dict[str, pd.DataFrame], name: str) -> None:
        self.name = name
        self.frames = frames
        self.calls: list[tuple[str, ...]] = []

    def is_available(self) -> bool:
        return True

    def fetch(self, codes, start_date, end_date, *, interval="1D", fields=None):
        self.calls.append(tuple(codes))
        return {code: self.frames[code] for code in codes if code in self.frames}


class SpyCalendar:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, str]] = []

    def get_trade_calendar(self, start_date: str, end_date: str) -> pd.DataFrame:
        self.calls.append((start_date, end_date))
        return pd.DataFrame(self.rows)


def _frame(rows: list[tuple[object, ...]], *, adjustment: str | None = None) -> pd.DataFrame:
    frame = pd.DataFrame(
        rows,
        columns=["trade_date", "open", "high", "low", "close", "volume"],
    )
    if adjustment is not None:
        frame.attrs["adjustment"] = adjustment
    return frame


def _steady(
    symbol_rows: tuple[str, float, float, float, float, float],
) -> pd.DataFrame:
    day, open_, high, low, close, volume = symbol_rows
    return _frame([(day, open_, high, low, close, volume)])


def _two_day(
    *,
    prior: float,
    target: float,
    prior_volume: float = 1000.0,
    target_volume: float = 1000.0,
    target_override: tuple[float, float, float, float] | None = None,
) -> pd.DataFrame:
    open_, high, low, close = target_override or (target, target, target, target)
    return _frame([
        (PRIOR, prior, prior, prior, prior, prior_volume),
        (DAY, open_, high, low, close, target_volume),
    ])


def _market_session(market: Market, status: str) -> MarketSession:
    return MarketSession(
        market=market,
        status=status,
        source="caller-calendar",
        as_of=AS_OF,
    )


def _bucket_session(
    bucket_id: str,
    market: Market,
    symbols: tuple[str, ...],
    *,
    status: str = "open",
    price_date: date = TRADE_DATE,
    required: bool = True,
) -> BucketSession:
    return BucketSession(
        bucket_id=bucket_id,
        market=market,
        price_date=price_date,
        required=required,
        position_symbols=symbols,
        session=_market_session(market, status),
    )


def _sessions(
    *buckets: BucketSession,
    trade_date: date = TRADE_DATE,
) -> PortfolioSessions:
    return PortfolioSessions(trade_date=trade_date, buckets=tuple(buckets))


def _loaders() -> dict[Market, SpyLoader]:
    return {
        "cn_a": SpyLoader({"600000.SS": _two_day(prior=9.5, target=10.2)}, "cn-fixture"),
        "hk": SpyLoader({"0700.HK": _two_day(prior=300.0, target=305.0)}, "hk-fixture"),
        "us": SpyLoader({"AAPL.US": _two_day(prior=190.0, target=195.0)}, "us-fixture"),
    }


def _open_calendar() -> SpyCalendar:
    return SpyCalendar([{"cal_date": DAY, "is_open": 1}])


def _preflight(
    sessions: PortfolioSessions,
    loaders: dict[Market, SpyLoader],
    *,
    calendar: SpyCalendar | None = None,
):
    return preflight_portfolio_data(
        sessions,
        loaders=loaders,
        ch_clients={"cn_a": None},
        calendar_client=calendar or _open_calendar(),
    )


def _three_open_sessions() -> PortfolioSessions:
    return _sessions(
        _bucket_session("cn", "cn_a", ("600000.SS",)),
        _bucket_session("hk", "hk", ("0700.HK",)),
        _bucket_session("us", "us", ("AAPL.US",)),
    )


def _assert_error(
    caught: pytest.ExceptionInfo[PortfolioSessionError],
    *,
    code: str,
    reason: str,
    bucket: str,
) -> None:
    assert caught.value.code == code
    assert caught.value.reason == reason
    assert caught.value.bucket_id == bucket
    assert str(caught.value).startswith(f"{code}:{reason}:")


def test_three_market_preflight_reports_independent_ready_buckets(monkeypatch) -> None:
    # Given cn_a/hk/us raw loader fixtures with a complete calendar and no orders.
    match_calls: list[tuple[object, object]] = []
    monkeypatch.setattr(
        engine,
        "match_orders",
        lambda *args, **kwargs: match_calls.append((args, kwargs)),
    )
    loaders = _loaders()

    # When every bucket is preflighted in declared order.
    prepared = _preflight(_three_open_sessions(), loaders)

    # Then each bucket carries its own target-day and lookback provenance.
    assert [bucket.bucket_id for bucket in prepared.buckets] == ["cn", "hk", "us"]
    assert [entry.bucket_id for entry in prepared.preflight] == ["cn", "hk", "us"]
    assert [entry.market_data.market for entry in prepared.preflight] == ["cn_a", "hk", "us"]
    assert [entry.market_data.symbols for entry in prepared.preflight] == [
        ("600000.SS",),
        ("0700.HK",),
        ("AAPL.US",),
    ]
    assert [entry.provenance.source for entry in prepared.preflight] == [
        "cn-fixture",
        "hk-fixture",
        "us-fixture",
    ]
    for entry in prepared.preflight:
        assert entry.readiness.ready is True
        assert entry.day_plan[-1].date == DAY
        assert entry.day_plan[-1].skip_reason is None
        assert entry.prepared.planning.price_date == PRIOR_DATE
        assert entry.prepared.planning.source.endswith(":planning")
        assert entry.prepared.execution is not None
        assert entry.prepared.execution.price_date == TRADE_DATE
        assert entry.prepared.execution.source.endswith(":execution")
        assert entry.prepared.valuation.kind == "target_bars"

    cn, hk, us = prepared.preflight
    assert {bar.symbol: bar.close for bar in cn.prepared.execution.bars} == {"600000.SS": "10.2"}
    assert {bar.symbol: bar.close for bar in hk.prepared.execution.bars} == {"0700.HK": "305"}
    assert {bar.symbol: bar.close for bar in us.prepared.execution.bars} == {"AAPL.US": "195"}
    assert [call for call in loaders["cn_a"].calls] == [("600000.SS",)]
    assert [call for call in loaders["hk"].calls] == [("0700.HK",)]
    assert [call for call in loaders["us"].calls] == [("AAPL.US",)]
    assert match_calls == []


def test_closed_bucket_uses_prior_mark_semantics_without_target_bars() -> None:
    # Given a closed HK bucket whose loader serves lookback but no target bar.
    hk = SpyLoader({"0700.HK": _steady((PRIOR, 300.0, 300.0, 300.0, 300.0, 1000.0))}, "hk-fixture")
    prepared = _preflight(
        _sessions(
            _bucket_session("cn", "cn_a", ("600000.SS",)),
            _bucket_session("hk", "hk", ("0700.HK",), status="closed"),
            _bucket_session("us", "us", ("AAPL.US",)),
        ),
        {**_loaders(), "hk": hk},
    )

    # Then HK is valued from its dated prior close and never exposed as matchable.
    closed = prepared.closed
    assert [bucket.bucket_id for bucket in closed] == ["hk"]
    assert closed[0].execution is None
    assert closed[0].valuation.kind == "prior_marks"
    mark = closed[0].valuation.marks[0]
    assert (mark.symbol, mark.price_date, mark.close) == ("0700.HK", PRIOR_DATE, "300")
    assert closed[0].planning.price_date == PRIOR_DATE
    assert [bucket.bucket_id for bucket in prepared.matchable] == ["cn", "us"]


def test_cn_a_calendar_gap_stops_before_any_fetch_or_match(monkeypatch) -> None:
    # Given a cn_a calendar response missing the target date.
    match_calls: list[object] = []
    monkeypatch.setattr(engine, "match_orders", lambda *a, **k: match_calls.append(a))
    loaders = _loaders()
    calendar = SpyCalendar([{"cal_date": PRIOR, "is_open": 1}])

    # When preflight starts with the cn_a bucket.
    with pytest.raises(PortfolioSessionError) as caught:
        _preflight(_three_open_sessions(), loaders, calendar=calendar)

    # Then the incomplete calendar fails closed before any provider call.
    _assert_error(caught, code="PAPER_DATA_NOT_READY", reason="calendar_unavailable", bucket="cn")
    assert loaders["cn_a"].calls == []
    assert loaders["hk"].calls == []
    assert loaders["us"].calls == []
    assert match_calls == []


@pytest.mark.parametrize("failing_market", ["hk", "us"])
def test_later_bucket_zero_target_bars_stops_fetch_and_never_matches(
    monkeypatch,
    failing_market: Market,
) -> None:
    # Given a valid cn_a bucket followed by a later bucket with zero target bars.
    match_calls: list[object] = []
    monkeypatch.setattr(engine, "match_orders", lambda *a, **k: match_calls.append(a))
    loaders = _loaders()
    symbol = "0700.HK" if failing_market == "hk" else "AAPL.US"
    loaders[failing_market] = SpyLoader(
        {symbol: _steady((PRIOR, 300.0, 300.0, 300.0, 300.0, 1000.0))},
        f"{failing_market}-fixture",
    )

    # When the later bucket is preflighted.
    with pytest.raises(PortfolioSessionError) as caught:
        _preflight(_three_open_sessions(), loaders)

    # Then that bucket fails closed, no later bucket is fetched, and no match runs.
    _assert_error(
        caught,
        code="PAPER_DATA_NOT_READY",
        reason="open_bucket_zero_target_bars",
        bucket=failing_market,
    )
    assert loaders["cn_a"].calls == [("600000.SS",)]
    assert loaders[failing_market].calls == [(symbol,)]
    if failing_market == "hk":
        assert loaders["us"].calls == []
    assert match_calls == []


def test_unresolved_split_rejects_the_bucket_before_matching(monkeypatch) -> None:
    # Given a >2/3 price drop with no volume confirmation on the US target day.
    match_calls: list[object] = []
    monkeypatch.setattr(engine, "match_orders", lambda *a, **k: match_calls.append(a))
    loaders = _loaders()
    loaders["us"] = SpyLoader(
        {"AAPL.US": _two_day(prior=100.0, target=63.0)},
        "us-fixture",
    )

    # When the split candidate reaches preflight.
    with pytest.raises(PortfolioSessionError) as caught:
        _preflight(_three_open_sessions(), loaders)

    # Then the bucket is rejected fail-closed before any fill.
    _assert_error(
        caught,
        code="PAPER_DATA_NOT_READY",
        reason="corporate_action_unresolved",
        bucket="us",
    )
    assert match_calls == []


def test_nonfinite_target_ohlc_is_rejected(monkeypatch) -> None:
    # Given a target bar whose open is not finite.
    monkeypatch.setattr(engine, "match_orders", lambda *a, **k: pytest.fail("matcher called"))
    loaders = _loaders()
    loaders["us"] = SpyLoader(
        {"AAPL.US": _two_day(
            prior=190.0,
            target=195.0,
            target_override=(math.nan, 195.0, 195.0, 195.0),
        )},
        "us-fixture",
    )

    # When preflight reads the target OHLC.
    with pytest.raises(PortfolioSessionError) as caught:
        _preflight(_three_open_sessions(), loaders)

    # Then the bad bar fails closed with the bucket identity.
    _assert_error(caught, code="PAPER_DATA_NOT_READY", reason="nonfinite_price_bar", bucket="us")


def test_adjusted_injected_frame_is_rejected_as_non_raw() -> None:
    # Given an injected frame that declares a forward-adjusted caliber.
    loaders = _loaders()
    loaders["cn_a"] = SpyLoader(
        {"600000.SS": _two_day(prior=9.5, target=10.2)},
        "cn-fixture",
    )
    loaders["cn_a"].frames["600000.SS"].attrs["adjustment"] = "qfq"

    # When preflight checks the served frame caliber.
    with pytest.raises(PortfolioSessionError) as caught:
        _preflight(_three_open_sessions(), loaders)

    # Then adjusted prices never become an execution input.
    _assert_error(caught, code="PAPER_DATA_NOT_READY", reason="adjusted_prices_rejected", bucket="cn")


def test_stale_session_price_date_is_rejected_before_any_fetch() -> None:
    # Given a bucket still stamped with the prior session date.
    loaders = _loaders()
    sessions = _sessions(
        _bucket_session("cn", "cn_a", ("600000.SS",), price_date=PRIOR_DATE),
        _bucket_session("hk", "hk", ("0700.HK",)),
        _bucket_session("us", "us", ("AAPL.US",)),
    )

    # When preflight is asked to use the stale bucket.
    with pytest.raises(PortfolioSessionError) as caught:
        _preflight(sessions, loaders)

    # Then it fails before loading any market data.
    _assert_error(caught, code="PAPER_DATA_NOT_READY", reason="session_data_disagreement", bucket="cn")
    assert loaders["cn_a"].calls == []
    assert loaders["hk"].calls == []
    assert loaders["us"].calls == []
