"""Explicit market-session routing and closed-market valuation inputs."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime, timezone

import pytest

from src.tools.paper_trade.portfolio.data import (
    BucketMarketData,
    CalendarCoverage,
    DataSnapshot,
    PriceBar,
    PriorMark,
    prepare_portfolio_data,
)
from src.tools.paper_trade.portfolio.models import (
    Market,
    MarketSession,
    PortfolioBucket,
    PortfolioOrder,
    PortfolioPosition,
    PortfolioRequest,
    PortfolioState,
    TargetWeight,
)
from src.tools.paper_trade.portfolio.sessions import resolve_portfolio_sessions

AS_OF = datetime(2026, 1, 5, 18, tzinfo=timezone.utc)
TRADE_DATE = date(2026, 1, 5)
PRIOR_DATE = date(2026, 1, 2)


def _session(market: Market, status: str) -> MarketSession:
    return MarketSession(market=market, status=status, source="caller-calendar", as_of=AS_OF)


def _request(sessions: tuple[MarketSession, ...]) -> PortfolioRequest:
    return PortfolioRequest(
        tool="paper_trade_step",
        schema_version="pt-v2.0",
        mode="portfolio",
        account_id="three-market",
        base_currency="USD",
        trade_date=TRADE_DATE,
        planning_at=AS_OF,
        valuation_at=datetime(2026, 1, 5, 19, tzinfo=timezone.utc),
        portfolio_state=PortfolioState(
            buckets=(
                PortfolioBucket(
                    bucket_id="cn",
                    market="cn_a",
                    currency="CNY",
                    cash="1000.00",
                    positions=(PortfolioPosition(symbol="600000.SS", qty=10, avg_cost="9.00", currency="CNY"),),
                ),
                PortfolioBucket(
                    bucket_id="hk",
                    market="hk",
                    currency="HKD",
                    cash="2000.00",
                    positions=(PortfolioPosition(symbol="0700.HK", qty=7, avg_cost="300.00", currency="HKD"),),
                ),
                PortfolioBucket(
                    bucket_id="us",
                    market="us",
                    currency="USD",
                    cash="3000.00",
                    positions=(),
                ),
            )
        ),
        sessions=sessions,
        orders=(
            PortfolioOrder(order_id="cn-1", bucket_id="cn", symbol="600000.SS", currency="CNY", side="buy", qty=10),
            PortfolioOrder(order_id="us-1", bucket_id="us", symbol="AAPL.US", currency="USD", side="buy", qty=2),
        ),
    )


def _snapshot(day: date, symbols: tuple[str, ...]) -> DataSnapshot:
    return DataSnapshot(
        price_date=day,
        source="fixture-bars",
        as_of=AS_OF,
        bars=tuple(PriceBar(symbol=symbol, close="10.00") for symbol in symbols),
    )


def _market_data(bucket_id: str, market: Market, symbols: tuple[str, ...]) -> BucketMarketData:
    return BucketMarketData(
        bucket_id=bucket_id,
        market=market,
        price_date=TRADE_DATE,
        planning=_snapshot(PRIOR_DATE, symbols),
        execution=_snapshot(TRADE_DATE, symbols),
        valuation=_snapshot(TRADE_DATE, symbols),
        prior_marks=(
            PriorMark(symbol="0700.HK", price_date=PRIOR_DATE, close="301.00", source="prior-close", as_of=AS_OF),
        ) if market == "hk" else (),
        calendar=CalendarCoverage(price_date=TRADE_DATE, is_open=True, source="snapshot-calendar", as_of=AS_OF)
        if market == "cn_a" else None,
    )


def test_open_buckets_match_and_closed_holdings_use_prior_marks() -> None:
    # Given caller-declared CN-open/HK-closed/US-open sessions and explicit data.
    request = _request((_session("cn_a", "open"), _session("hk", "closed"), _session("us", "open")))
    sessions = resolve_portfolio_sessions(
        request,
        price_dates={"cn_a": TRADE_DATE, "hk": TRADE_DATE, "us": TRADE_DATE},
    )

    # When the descriptors are prepared and the caller routes only matchable buckets.
    prepared = prepare_portfolio_data(
        sessions,
        (
            _market_data("cn", "cn_a", ("600000.SS",)),
            _market_data("hk", "hk", ()),
            _market_data("us", "us", ("AAPL.US",)),
        ),
    )
    matched: list[str] = []
    for bucket in prepared.buckets:
        if bucket.session.matchable:
            matched.append(bucket.bucket_id)

    # Then HK is valued from its dated prior mark without entering matching.
    assert matched == ["cn", "us"]
    assert [bucket.bucket_id for bucket in prepared.matchable] == ["cn", "us"]
    assert [bucket.bucket_id for bucket in prepared.closed] == ["hk"]
    hk = prepared.closed[0]
    assert hk.valuation.kind == "prior_marks"
    assert hk.valuation.marks[0].price_date == PRIOR_DATE
    assert hk.valuation.marks[0].symbol == "0700.HK"
    assert hk.execution is None
    assert prepared.matchable[0].planning.price_date == PRIOR_DATE


def _three_market_sessions() -> tuple[MarketSession, ...]:
    return (_session("cn_a", "open"), _session("hk", "closed"), _session("us", "open"))


def _three_market_data() -> tuple[BucketMarketData, ...]:
    return (
        _market_data("cn", "cn_a", ("600000.SS",)),
        _market_data("hk", "hk", ()),
        _market_data("us", "us", ("AAPL.US",)),
    )


def _resolved(request: PortfolioRequest | None = None):
    return resolve_portfolio_sessions(
        request or _request(_three_market_sessions()),
        price_dates={"cn_a": TRADE_DATE, "hk": TRADE_DATE, "us": TRADE_DATE},
    )


def _assert_error(
    caught: pytest.ExceptionInfo[ValueError], expected: tuple[str, str, str]
) -> None:
    code, reason, bucket = expected
    assert caught.value.code == code
    assert caught.value.reason == reason
    assert caught.value.bucket_id == bucket
    assert str(caught.value) == f"{code}:{reason}:{caught.value.path}:{bucket}"


def test_session_price_date_must_equal_the_request_trade_date() -> None:
    # Given a session descriptor whose target date disagrees with the request.
    request = _request(_three_market_sessions())

    # When / Then no older execution date can be substituted for the requested day.
    with pytest.raises(ValueError) as caught:
        resolve_portfolio_sessions(
            request,
            price_dates={"cn_a": TRADE_DATE, "hk": PRIOR_DATE, "us": TRADE_DATE},
        )

    _assert_error(caught, ("PAPER_DATA_NOT_READY", "session_data_disagreement", "hk"))


def test_required_closed_bucket_aborts_before_data_or_matching() -> None:
    # Given an order targeting a caller-declared closed HK bucket.
    request = _request(_three_market_sessions()).model_copy(
        update={
            "orders": (
                PortfolioOrder(
                    order_id="hk-1", bucket_id="hk", symbol="0700.HK",
                    currency="HKD", side="buy", qty=100,
                ),
            )
        }
    )

    # When / Then session resolution fails before any data preparation or fill.
    with pytest.raises(ValueError) as caught:
        _resolved(request)

    _assert_error(caught, ("INVALID_REQUEST", "required_bucket_closed", "hk"))


def test_nonzero_targets_are_required_but_zero_targets_may_be_closed() -> None:
    # Given target weights with only CN nonzero and HK explicitly zero.
    request = _request(_three_market_sessions()).model_copy(
        update={
            "orders": None,
            "target_weights": (
                TargetWeight(bucket_id="cn", symbol="600000.SS", currency="CNY", weight="0.5"),
                TargetWeight(bucket_id="hk", symbol="0700.HK", currency="HKD", weight="0.0"),
                TargetWeight(bucket_id="us", symbol="AAPL.US", currency="USD", weight="0"),
            ),
        }
    )

    # When / Then only the nonzero target makes its bucket required.
    resolved = _resolved(request)

    assert {bucket.bucket_id for bucket in resolved.buckets if bucket.required} == {"cn"}


@pytest.mark.parametrize(
    ("bucket_index", "change", "expected"),
    [
        (2, {"execution": DataSnapshot(price_date=TRADE_DATE, source="empty", as_of=AS_OF)},
         ("PAPER_DATA_NOT_READY", "open_bucket_zero_target_bars", "us")),
        (0, {"calendar": None},
         ("PAPER_DATA_NOT_READY", "missing_calendar_coverage", "cn")),
        (1, {"prior_marks": ()},
         ("PAPER_DATA_NOT_READY", "missing_prior_mark", "hk")),
        (0, {"price_date": PRIOR_DATE},
         ("PAPER_DATA_NOT_READY", "session_data_disagreement", "cn")),
    ],
)
def test_invalid_data_returns_stable_bucket_scoped_errors(
    bucket_index: int,
    change: dict[str, DataSnapshot | date | tuple[PriorMark, ...] | None],
    expected: tuple[str, str, str],
) -> None:
    # Given one malformed readiness descriptor in an otherwise valid fixture.
    rows = list(_three_market_data())
    rows[bucket_index] = replace(rows[bucket_index], **change)

    # When / Then preparation returns the stable reason and bucket identity.
    with pytest.raises(ValueError) as caught:
        prepare_portfolio_data(_resolved(), tuple(rows))

    _assert_error(caught, expected)


def test_stale_prior_mark_is_not_accepted_as_closed_valuation() -> None:
    # Given a same-day mark masquerading as a prior close for closed HK.
    rows = list(_three_market_data())
    rows[1] = replace(
        rows[1],
        prior_marks=(replace(rows[1].prior_marks[0], price_date=TRADE_DATE),),
    )

    # When / Then the stale valuation input fails closed.
    with pytest.raises(ValueError) as caught:
        prepare_portfolio_data(_resolved(), tuple(rows))

    _assert_error(caught, ("PAPER_DATA_NOT_READY", "stale_prior_mark", "hk"))


def test_duplicate_bucket_data_is_rejected_as_malformed_input() -> None:
    # Given duplicate descriptors for one bucket.
    rows = _three_market_data()

    # When / Then no ambiguous descriptor can be selected silently.
    with pytest.raises(ValueError) as caught:
        prepare_portfolio_data(_resolved(), rows + rows[:1])

    _assert_error(caught, ("INVALID_REQUEST", "duplicate_bucket_data", "cn"))


def test_calendar_and_session_disagreement_is_explicit() -> None:
    # Given cn_a declared open while its snapshot calendar says closed.
    rows = list(_three_market_data())
    rows[0] = replace(rows[0], calendar=replace(rows[0].calendar, is_open=False))

    # When / Then the disagreement is not resolved by guessing from bars.
    with pytest.raises(ValueError) as caught:
        prepare_portfolio_data(_resolved(), tuple(rows))

    _assert_error(caught, ("PAPER_DATA_NOT_READY", "session_data_disagreement", "cn"))


def test_session_and_data_values_are_immutable() -> None:
    # Given resolved session and prepared data values.
    resolved = _resolved()
    prepared = prepare_portfolio_data(resolved, _three_market_data())

    # When / Then mutation is rejected by the frozen value objects.
    with pytest.raises(FrozenInstanceError):
        setattr(resolved.buckets[0], "price_date", PRIOR_DATE)
    with pytest.raises(FrozenInstanceError):
        setattr(prepared.buckets[0], "execution", None)
