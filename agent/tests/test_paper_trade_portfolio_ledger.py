"""Immutable bucket-ledger, conversion replay and NAV-bridge tests for pt-v2.0."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.tools.paper_trade.portfolio.fx import (
    FxConversionEvent,
    FxConversionPlan,
    FxRateBook,
    plan_conversions,
)
from src.tools.paper_trade.portfolio.ledger import (
    BucketLedger,
    CashMovement,
    ConversionReplay,
    LedgerNavBridge,
    PortfolioLedger,
    PositionMovement,
    apply_conversions,
    value_ledger,
)
from src.tools.paper_trade.portfolio.models import (
    Currency,
    FxConversion,
    FxSnapshot,
    MarketSession,
    PortfolioBucket,
    PortfolioPosition,
    PortfolioRequest,
    PortfolioState,
)
from src.tools.paper_trade.portfolio.schema import PortfolioRequestError

AS_OF = datetime(2026, 1, 5, 18, tzinfo=timezone.utc)
VALUATION = datetime(2026, 1, 5, 19, tzinfo=timezone.utc)
DAY = date(2026, 1, 5)


def _snapshot(
    rate_id: str,
    from_currency: Currency,
    to_currency: Currency,
    rate: str,
    *,
    as_of: datetime = AS_OF,
) -> FxSnapshot:
    return FxSnapshot(
        rate_id=rate_id,
        from_currency=from_currency,
        to_currency=to_currency,
        rate=rate,
        as_of=as_of,
        source="fixture.fx",
    )


def _position(symbol: str, qty: int, avg_cost: str, currency: Currency) -> PortfolioPosition:
    return PortfolioPosition(symbol=symbol, qty=qty, avg_cost=avg_cost, currency=currency)


def _bucket(
    bucket_id: str,
    market: str,
    currency: Currency,
    cash: str,
    positions: tuple[PortfolioPosition, ...] = (),
) -> PortfolioBucket:
    return PortfolioBucket(
        bucket_id=bucket_id,
        market=market,
        currency=currency,
        cash=cash,
        positions=positions,
    )


def _opening_buckets() -> tuple[PortfolioBucket, ...]:
    return (
        _bucket(
            "cn",
            "cn_a",
            "CNY",
            "100000.00",
            (_position("600519.SH", 10, "1500.00", "CNY"),),
        ),
        _bucket(
            "hk",
            "hk",
            "HKD",
            "20000.00",
            (_position("0700.HK", 100, "400.00", "HKD"),),
        ),
        _bucket(
            "us",
            "us",
            "USD",
            "1000.00",
            (_position("AAPL.US", 5, "200.00", "USD"),),
        ),
    )


def _request(
    snapshots: tuple[FxSnapshot, ...],
    conversions: tuple[FxConversion, ...],
    *,
    buckets: tuple[PortfolioBucket, ...] | None = None,
) -> PortfolioRequest:
    return PortfolioRequest(
        tool="paper_trade_step",
        schema_version="pt-v2.0",
        mode="portfolio",
        account_id="ledger-fixture",
        base_currency="USD",
        trade_date=DAY,
        planning_at=AS_OF,
        valuation_at=VALUATION,
        portfolio_state=PortfolioState(buckets=_opening_buckets() if buckets is None else buckets),
        sessions=(
            MarketSession(market="cn_a", status="open", source="fixture", as_of=AS_OF),
            MarketSession(market="hk", status="open", source="fixture", as_of=AS_OF),
            MarketSession(market="us", status="open", source="fixture", as_of=AS_OF),
        ),
        fx_snapshots=snapshots,
        fx_conversions=conversions,
    )


def _conversion(rate_id: str, source: str, target: str, amount: str) -> FxConversion:
    return FxConversion(rate_id=rate_id, from_bucket_id=source, to_bucket_id=target, amount=amount)


def _conversion_request() -> PortfolioRequest:
    return _request(
        (
            _snapshot("cny-hkd", "CNY", "HKD", "1.0835"),
            _snapshot("hkd-usd", "HKD", "USD", "0.128333"),
        ),
        (
            _conversion("cny-hkd", "cn", "hk", "30000.00"),
            _conversion("hkd-usd", "hk", "us", "12345.67"),
        ),
    )


def _direct_usd_book(
    *,
    at: datetime | None = None,
    max_age: timedelta | None = None,
) -> FxRateBook:
    return FxRateBook.from_snapshots(
        (
            _snapshot("cny-usd", "CNY", "USD", "0.13857"),
            _snapshot("hkd-usd", "HKD", "USD", "0.128333"),
        ),
        at=at,
        max_age=max_age,
    )


def _reason(exc_info: pytest.ExceptionInfo[PortfolioRequestError]) -> str:
    return exc_info.value.reason


def _post_conversion_ledger() -> PortfolioLedger:
    request = _conversion_request()
    return apply_conversions(PortfolioLedger.from_state(request.portfolio_state), plan_conversions(request)).post_conversion


def test_opening_ledger_parses_exact_cash_and_positions_and_is_immutable() -> None:
    # Given one model portfolio with isolated CNY, HKD and USD buckets.
    ledger = PortfolioLedger.from_state(PortfolioState(buckets=_opening_buckets()))

    # Then every account keeps its own canonical cash and parent market/currency.
    assert isinstance(ledger, PortfolioLedger)
    assert ledger.cash_map() == {
        "cn": Decimal("100000.00"),
        "hk": Decimal("20000.00"),
        "us": Decimal("1000.00"),
    }
    cn = ledger.bucket("cn")
    assert isinstance(cn, BucketLedger)
    assert (cn.market, cn.currency) == ("cn_a", "CNY")
    position = cn.positions[0]
    assert (position.symbol, position.qty, position.avg_cost) == (
        "600519.SH",
        10,
        Decimal("1500.00"),
    )
    assert (position.market, position.currency) == ("cn_a", "CNY")

    # And neither the ledger, its buckets nor the cash view can be mutated.
    with pytest.raises(FrozenInstanceError):
        ledger.buckets[0].cash = Decimal("0.00")  # type: ignore[misc]
    with pytest.raises(TypeError):
        ledger.cash_map()["cn"] = Decimal("0.00")  # type: ignore[index]


def test_replay_applies_caller_conversions_with_exact_cash_conservation() -> None:
    # Given the verified two-step plan over opening CNY and HKD cash.
    request = _conversion_request()
    ledger = PortfolioLedger.from_state(request.portfolio_state)
    plan = plan_conversions(request)

    # When the caller's plan is replayed into the typed ledger.
    replay = apply_conversions(ledger, plan)

    # Then the post-conversion cash is exactly the plan's final cash.
    assert isinstance(replay, ConversionReplay)
    assert replay.opening_cash == (
        ("cn", Decimal("100000.00")),
        ("hk", Decimal("20000.00")),
        ("us", Decimal("1000.00")),
    )
    assert replay.post_conversion_cash == (
        ("cn", Decimal("70000.00")),
        ("hk", Decimal("40159.33")),
        ("us", Decimal("2584.36")),
    )
    assert replay.post_conversion.cash_map() == plan.cash_map()
    assert replay.post_conversion.bucket("cn").cash == Decimal("70000.00")
    assert replay.post_conversion.bucket("hk").cash == Decimal("40159.33")
    assert replay.post_conversion.bucket("us").cash == Decimal("2584.36")

    # And the event residual is the exact difference between exact and credited.
    assert replay.events[1].exact_converted == Decimal("1584.35686811")
    assert replay.events[1].converted_amount == Decimal("1584.36")
    assert replay.events[1].residual == Decimal("-0.00313189")
    assert replay.total_residual == Decimal("-0.00313189")
    assert all(
        event.exact_converted == event.converted_amount + event.residual
        for event in replay.events
    )

    # And positions never move during a pre-fill conversion, nor does the source ledger.
    assert replay.post_conversion.bucket("cn").positions == ledger.bucket("cn").positions
    assert replay.post_conversion.bucket("hk").positions == ledger.bucket("hk").positions
    assert replay.post_conversion.bucket("us").positions == ledger.bucket("us").positions
    assert ledger.cash_map()["cn"] == Decimal("100000.00")


def test_conversion_events_cannot_be_funded_by_earlier_proceeds() -> None:
    # Given a forged plan that spends the USD credited by its own first event.
    ledger = PortfolioLedger.from_state(
        PortfolioState(
            buckets=(
                _bucket("cn", "cn_a", "CNY", "100.00"),
                _bucket("hk", "hk", "HKD", "0.00"),
                _bucket("us", "us", "USD", "0.00"),
            )
        )
    )
    plan = FxConversionPlan(
        events=(
            FxConversionEvent(
                rate_id="cny-usd",
                from_bucket_id="cn",
                to_bucket_id="us",
                from_currency="CNY",
                to_currency="USD",
                source_amount=Decimal("100.00"),
                rate=Decimal("0.138600000000"),
                exact_converted=Decimal("13.8600000000"),
                converted_amount=Decimal("13.86"),
                residual=Decimal("0.0000000000"),
            ),
            FxConversionEvent(
                rate_id="usd-hkd",
                from_bucket_id="us",
                to_bucket_id="hk",
                from_currency="USD",
                to_currency="HKD",
                source_amount=Decimal("13.86"),
                rate=Decimal("7.800000000000"),
                exact_converted=Decimal("108.1080000000"),
                converted_amount=Decimal("108.11"),
                residual=Decimal("-0.0020000000"),
            ),
        ),
        cash=(
            ("cn", Decimal("0.00")),
            ("hk", Decimal("108.11")),
            ("us", Decimal("0.00")),
        ),
    )

    # Then opening USD stays unavailable to the second conversion.
    with pytest.raises(PortfolioRequestError) as exc_info:
        apply_conversions(ledger, plan)
    assert _reason(exc_info) == "insufficient_fx_cash"
    assert exc_info.value.bucket_id == "us"
    assert exc_info.value.path == "fx_conversions[1].source_amount"


def test_stale_plan_and_foreign_plan_cash_are_rejected_without_an_end_ledger() -> None:
    # Given a plan built from 100000.00 CNY but a ledger that now holds 100.00.
    request = _conversion_request()
    plan = plan_conversions(request)
    stale_ledger = PortfolioLedger.from_state(
        PortfolioState(
            buckets=(
                _bucket("cn", "cn_a", "CNY", "100.00"),
                _bucket("hk", "hk", "HKD", "20000.00"),
                _bucket("us", "us", "USD", "1000.00"),
            )
        )
    )
    with pytest.raises(PortfolioRequestError) as stale_error:
        apply_conversions(stale_ledger, plan)
    assert _reason(stale_error) == "insufficient_fx_cash"
    assert stale_error.value.bucket_id == "cn"

    # And a plan that does not cover every ledger account cannot silently drop one.
    foreign_plan = plan_conversions(
        _request(
            (_snapshot("cny-hkd", "CNY", "HKD", "1.0835"),),
            (_conversion("cny-hkd", "cn", "hk", "100.00"),),
            buckets=(
                _bucket("cn", "cn_a", "CNY", "100000.00"),
                _bucket("hk", "hk", "HKD", "20000.00"),
            ),
        )
    )
    with pytest.raises(PortfolioRequestError) as cash_error:
        apply_conversions(PortfolioLedger.from_state(request.portfolio_state), foreign_plan)
    assert _reason(cash_error) == "fx_plan_cash_mismatch"


def test_duplicate_bucket_ids_are_rejected_before_fx_dicts_can_coalesce() -> None:
    # Given two accounts claiming the same bucket id under different markets.
    duplicate = (
        _bucket("cn", "cn_a", "CNY", "100.00"),
        _bucket("cn", "us", "USD", "100.00"),
    )

    # Then typed construction refuses the duplicate id.
    with pytest.raises(PortfolioRequestError) as state_error:
        PortfolioLedger.from_state(PortfolioState(buckets=duplicate))
    assert _reason(state_error) == "duplicate_bucket"
    assert state_error.value.bucket_id == "cn"

    # And direct dataclass construction enforces the same invariant.
    with pytest.raises(PortfolioRequestError) as direct_error:
        PortfolioLedger(
            buckets=(
                BucketLedger("cn", "cn_a", "CNY", Decimal("100.00")),
                BucketLedger("cn", "us", "USD", Decimal("100.00")),
            )
        )
    assert _reason(direct_error) == "duplicate_bucket"


def test_duplicate_instruments_are_rejected_within_and_across_buckets() -> None:
    # Given one symbol repeated inside a bucket.
    in_bucket = (
        _bucket(
            "us",
            "us",
            "USD",
            "1000.00",
            (
                _position("AAPL.US", 1, "200.00", "USD"),
                _position("AAPL.US", 1, "200.00", "USD"),
            ),
        ),
    )
    with pytest.raises(PortfolioRequestError) as local_error:
        PortfolioLedger.from_state(PortfolioState(buckets=in_bucket))
    assert _reason(local_error) == "duplicate_instrument"
    assert local_error.value.bucket_id == "us"

    # And the same symbol repeated across separate buckets is also refuted.
    across_buckets = (
        _bucket("us-a", "us", "USD", "1000.00", (_position("AAPL.US", 1, "200.00", "USD"),)),
        _bucket("us-b", "us", "USD", "1000.00", (_position("AAPL.US", 1, "200.00", "USD"),)),
    )
    with pytest.raises(PortfolioRequestError) as global_error:
        PortfolioLedger.from_state(PortfolioState(buckets=across_buckets))
    assert _reason(global_error) == "duplicate_instrument"
    assert global_error.value.bucket_id == "us-b"


def test_non_hkd_hk_and_mismatched_counters_are_rejected() -> None:
    # Given an HK bucket that does not settle in HKD.
    with pytest.raises(PortfolioRequestError) as bucket_error:
        PortfolioLedger.from_state(
            PortfolioState(buckets=(_bucket("hk", "hk", "USD", "100.00"),))
        )
    assert _reason(bucket_error) == "non_hkd_hk_counter"
    assert bucket_error.value.bucket_id == "hk"

    # And an HK position quoted in another currency.
    with pytest.raises(PortfolioRequestError) as counter_error:
        PortfolioLedger.from_state(
            PortfolioState(
                buckets=(
                    _bucket(
                        "hk",
                        "hk",
                        "HKD",
                        "100.00",
                        (_position("0700.HK", 1, "400.00", "CNY"),),
                    ),
                )
            )
        )
    assert _reason(counter_error) == "non_hkd_hk_counter"
    assert counter_error.value.bucket_id == "hk"

    # And a non-HK instrument cannot borrow a different settlement currency.
    with pytest.raises(PortfolioRequestError) as mismatch_error:
        PortfolioLedger.from_state(
            PortfolioState(
                buckets=(
                    _bucket(
                        "cn",
                        "cn_a",
                        "CNY",
                        "100.00",
                        (_position("600519.SH", 1, "1500.00", "USD"),),
                    ),
                )
            )
        )
    assert _reason(mismatch_error) == "instrument_currency_mismatch"


def test_post_fill_conversion_attempt_returns_no_replay_or_end_ledger() -> None:
    # Given a valid pre-fill plan.
    request = _conversion_request()
    ledger = PortfolioLedger.from_state(request.portfolio_state)
    plan = plan_conversions(request)

    # Then asking the ledger to settle it after fills is refused outright.
    with pytest.raises(PortfolioRequestError) as exc_info:
        apply_conversions(ledger, plan, stage="post_fill")
    assert _reason(exc_info) == "post_fill_fx_conversion"
    assert ledger.cash_map()["cn"] == Decimal("100000.00")


def test_missing_inverse_triangulated_and_stale_valuation_pairs_are_rejected() -> None:
    # Given a converted ledger holding CNY, HKD and USD accounts.
    ledger = _post_conversion_ledger()
    marks = {"600519.SH": "1501.23", "0700.HK": "405.55", "AAPL.US": "333.333333"}

    # Then an inverse-only pair cannot value CNY.
    inverse = FxRateBook.from_snapshots((_snapshot("usd-cny", "USD", "CNY", "7.2166"),))
    with pytest.raises(PortfolioRequestError) as inverse_error:
        value_ledger(ledger, marks, inverse, base_currency="USD")
    assert _reason(inverse_error) == "inverse_fx_rate_only"

    # And two hops never synthesize the missing direct pair.
    two_hop = FxRateBook.from_snapshots(
        (
            _snapshot("cny-hkd", "CNY", "HKD", "1.0835"),
            _snapshot("hkd-usd", "HKD", "USD", "0.128333"),
        )
    )
    with pytest.raises(PortfolioRequestError) as hop_error:
        value_ledger(ledger, marks, two_hop, base_currency="USD")
    assert _reason(hop_error) == "triangulation_not_supported"

    # And absent direct pairs are named, never guessed.
    empty = FxRateBook.from_snapshots(())
    with pytest.raises(PortfolioRequestError) as missing_error:
        value_ledger(ledger, marks, empty, base_currency="USD")
    assert _reason(missing_error) == "missing_direct_fx_pair"

    # And the same direct pair is checked against the valuation instant.
    late = FxRateBook.from_snapshots(
        (_snapshot("cny-usd", "CNY", "USD", "0.13857", as_of=VALUATION + timedelta(seconds=1)),),
        at=VALUATION,
    )
    with pytest.raises(PortfolioRequestError) as future_error:
        value_ledger(ledger, marks, late, base_currency="USD")
    assert _reason(future_error) == "future_fx_rate"
    stale = FxRateBook.from_snapshots(
        (_snapshot("cny-usd", "CNY", "USD", "0.13857", as_of=VALUATION - timedelta(minutes=6)),),
        at=VALUATION,
        max_age=timedelta(minutes=5),
    )
    with pytest.raises(PortfolioRequestError) as stale_error:
        value_ledger(ledger, marks, stale, base_currency="USD")
    assert _reason(stale_error) == "stale_fx_rate"


def test_nav_bridge_reports_exact_local_position_residuals_and_base_total() -> None:
    # Given the post-conversion ledger and direct CNY/USD and HKD/USD pairs.
    ledger = _post_conversion_ledger()
    marks = {"600519.SH": "1501.23", "0700.HK": "405.55", "AAPL.US": "333.333333"}

    # When every bucket is valued in the base currency.
    bridge = value_ledger(ledger, marks, _direct_usd_book(at=VALUATION), base_currency="USD")

    # Then each bucket carries reported and exact local NAV plus any local residual.
    assert isinstance(bridge, LedgerNavBridge)
    rows = {row.bucket_id: row for row in bridge.rows}
    us = rows["us"]
    assert us.position_value == Decimal("1666.67")
    assert us.exact_position_value == Decimal("1666.666665")
    assert us.local_nav == Decimal("4251.03")
    assert us.exact_local_nav == Decimal("4251.026665")
    assert us.local_residual == Decimal("-0.003335")
    assert us.reported_base == Decimal("4251.03")
    assert us.exact_base == Decimal("4251.026665")
    assert us.residual == Decimal("-0.003335")
    assert us.rate_id is None
    assert us.rate == Decimal("1")

    cn = rows["cn"]
    assert cn.local_nav == Decimal("85012.30")
    assert cn.reported_base == Decimal("11780.15")
    assert cn.exact_base == Decimal("11780.1544110")
    assert cn.residual == Decimal("0.0044110")
    assert cn.rate_id == "cny-usd"

    hk = rows["hk"]
    assert hk.local_nav == Decimal("80714.33")
    assert hk.reported_base == Decimal("10358.31")
    assert hk.exact_base == Decimal("10358.31211189")
    assert hk.residual == Decimal("0.00211189")
    assert hk.rate_id == "hkd-usd"

    # And the exact total is reported plus residual, with the identity balanced.
    assert bridge.total.reported_base == Decimal("26389.49")
    assert bridge.total.exact_base == Decimal("26389.49318789")
    assert bridge.total.residual == Decimal("0.00318789")
    assert bridge.total.exact_base == bridge.total.reported_base + bridge.total.residual
    assert bridge.total.balanced is True
    assert bridge.balanced is True
    assert len(bridge.bridge_events) == 3


def test_missing_marks_invalid_base_and_float_cash_fail_closed() -> None:
    # Given a converted ledger and only two of its three position marks.
    ledger = _post_conversion_ledger()
    with pytest.raises(PortfolioRequestError) as mark_error:
        value_ledger(
            ledger,
            {"600519.SH": "1501.23", "0700.HK": "405.55"},
            _direct_usd_book(),
            base_currency="USD",
        )
    assert _reason(mark_error) == "missing_valuation_mark"
    assert mark_error.value.bucket_id == "us"

    # And the base currency must be one of the canonical settlement currencies.
    with pytest.raises(PortfolioRequestError) as base_error:
        value_ledger(
            ledger,
            {"600519.SH": "1501.23", "0700.HK": "405.55", "AAPL.US": "333.333333"},
            _direct_usd_book(),
            base_currency="EUR",  # type: ignore[arg-type]
        )
    assert _reason(base_error) == "invalid_base_currency"

    # And no float can enter a typed ledger.
    with pytest.raises(PortfolioRequestError) as float_error:
        BucketLedger("us", "us", "USD", 100.0)  # type: ignore[arg-type]
    assert _reason(float_error) == "invalid_decimal"


def test_event_based_updates_stay_inside_one_bucket() -> None:
    # Given three empty buckets.
    ledger = PortfolioLedger.from_state(
        PortfolioState(
            buckets=(
                _bucket("cn", "cn_a", "CNY", "100.00"),
                _bucket("hk", "hk", "HKD", "200.00"),
                _bucket("us", "us", "USD", "300.00"),
            )
        )
    )

    # When one cash movement and one position movement touch only the US bucket.
    updated = ledger.apply(
        (
            CashMovement("us", Decimal("25.50")),
            PositionMovement("us", "MSFT.US", 2, Decimal("410.25")),
        )
    )

    # Then the US cash and position change exactly, with no cross-bucket funding.
    assert updated.cash_map() == {
        "cn": Decimal("100.00"),
        "hk": Decimal("200.00"),
        "us": Decimal("325.50"),
    }
    position = updated.bucket("us").positions[0]
    assert (position.symbol, position.qty, position.avg_cost) == (
        "MSFT.US",
        2,
        Decimal("410.25"),
    )
    assert updated.bucket("cn").positions == ()
    assert updated.bucket("hk").positions == ()
    assert ledger.cash_map()["us"] == Decimal("300.00")

    # And a full sell removes the instrument without changing cash.
    closed = updated.apply((PositionMovement("us", "MSFT.US", -2),))
    assert closed.bucket("us").positions == ()
    assert closed.cash_map()["us"] == Decimal("325.50")

    # And an instrument owned by another bucket cannot be re-homed silently.
    with pytest.raises(PortfolioRequestError) as collision_error:
        updated.apply(
            (
                PositionMovement("cn", "MSFT.US", 1, Decimal("410.25")),
            )
        )
    assert _reason(collision_error) == "instrument_bucket_mismatch"


@pytest.mark.parametrize(
    ("converted", "residual", "us_cash"),
    (
        ("999999.99", "-998415.63313189", "1000999.99"),
        ("-100.00", "1684.35686811", "900.00"),
    ),
)
def test_forged_converted_amount_and_plugged_residual_are_rejected_without_a_replay(
    converted: str, residual: str, us_cash: str
) -> None:
    # Given the valid plan whose second event is rewritten to mint target cash.
    request = _conversion_request()
    ledger = PortfolioLedger.from_state(request.portfolio_state)
    plan = plan_conversions(request)
    forged = FxConversionPlan(
        events=(
            plan.events[0],
            replace(
                plan.events[1],
                converted_amount=Decimal(converted),
                residual=Decimal(residual),
            ),
        ),
        cash=(
            ("cn", Decimal("70000.00")),
            ("hk", Decimal("40159.33")),
            ("us", Decimal(us_cash)),
        ),
    )

    # Then the fabricated credit is rejected and no end ledger is returned.
    result = None
    with pytest.raises(PortfolioRequestError) as exc_info:
        result = apply_conversions(ledger, forged)
    assert result is None
    assert _reason(exc_info) == "fx_event_mismatch"
    assert exc_info.value.path == "fx_conversions[1].converted_amount"
    assert exc_info.value.bucket_id == "hk"

    # And the source ledger still holds its exact opening cash.
    assert ledger.cash_map()["us"] == Decimal("1000.00")


def test_same_currency_conversion_between_two_usd_buckets_is_rejected() -> None:
    # Given two USD-settled accounts and a USD->USD event between them.
    ledger = PortfolioLedger.from_state(
        PortfolioState(
            buckets=(
                _bucket("us-a", "us", "USD", "1000.00"),
                _bucket("us-b", "us", "USD", "1000.00"),
            )
        )
    )
    plan = FxConversionPlan(
        events=(
            FxConversionEvent(
                rate_id="usd-usd",
                from_bucket_id="us-a",
                to_bucket_id="us-b",
                from_currency="USD",
                to_currency="USD",
                source_amount=Decimal("100.00"),
                rate=Decimal("2.000000000000"),
                exact_converted=Decimal("200.00000000000000"),
                converted_amount=Decimal("200.00"),
                residual=Decimal("0"),
            ),
        ),
        cash=(("us-a", Decimal("900.00")), ("us-b", Decimal("1200.00"))),
    )

    # Then the identity currency pair cannot manufacture USD at rate 2.0.
    result = None
    with pytest.raises(PortfolioRequestError) as exc_info:
        result = apply_conversions(ledger, plan)
    assert result is None
    assert _reason(exc_info) == "identity_fx_conversion"
    assert exc_info.value.bucket_id == "us-a"
    assert exc_info.value.path == "fx_conversions[0].to_currency"


def test_duplicate_plan_cash_keys_are_rejected_instead_of_last_wins_coalescing() -> None:
    # Given a valid plan whose cash tuple names the USD bucket twice.
    request = _conversion_request()
    ledger = PortfolioLedger.from_state(request.portfolio_state)
    plan = plan_conversions(request)
    duplicate = FxConversionPlan(
        events=plan.events,
        cash=plan.cash + (("us", plan.cash_map()["us"]),),
    )

    # Then the duplicated key is a malformed plan, not a silently coalesced map.
    result = None
    with pytest.raises(PortfolioRequestError) as exc_info:
        result = apply_conversions(ledger, duplicate)
    assert result is None
    assert _reason(exc_info) == "duplicate_plan_cash"
    assert exc_info.value.path == "fx_conversions.cash"


def test_valid_three_currency_replay_and_nav_totals_remain_exact() -> None:
    # Given the unchanged valid two-step plan.
    request = _conversion_request()
    replay = apply_conversions(
        PortfolioLedger.from_state(request.portfolio_state),
        plan_conversions(request),
    )

    # Then the valid replay and its base-currency totals stay exact.
    assert replay.post_conversion_cash_map() == {
        "cn": Decimal("70000.00"),
        "hk": Decimal("40159.33"),
        "us": Decimal("2584.36"),
    }
    bridge = value_ledger(
        replay.post_conversion,
        {"600519.SH": "1501.23", "0700.HK": "405.55", "AAPL.US": "333.333333"},
        _direct_usd_book(at=VALUATION),
        base_currency="USD",
    )
    assert bridge.total.reported_base == Decimal("26389.49")
    assert bridge.total.exact_base == Decimal("26389.49318789")
    assert bridge.total.residual == Decimal("0.00318789")


def test_conversion_event_currency_mismatch_and_bad_residual_are_rejected() -> None:
    # Given a valid plan whose event is re-labelled with the wrong source currency.
    request = _conversion_request()
    ledger = PortfolioLedger.from_state(request.portfolio_state)
    plan = plan_conversions(request)
    first = plan.events[0]
    mismatched = FxConversionPlan(
        events=(
            FxConversionEvent(
                rate_id=first.rate_id,
                from_bucket_id=first.from_bucket_id,
                to_bucket_id=first.to_bucket_id,
                from_currency="USD",
                to_currency=first.to_currency,
                source_amount=first.source_amount,
                rate=first.rate,
                exact_converted=first.exact_converted,
                converted_amount=first.converted_amount,
                residual=first.residual,
            ),
        ),
        cash=plan.cash,
    )
    with pytest.raises(PortfolioRequestError) as pair_error:
        apply_conversions(ledger, mismatched)
    assert _reason(pair_error) == "fx_pair_mismatch"

    # And an event whose residual does not tie out is refused.
    broken = FxConversionPlan(
        events=(
            FxConversionEvent(
                rate_id=first.rate_id,
                from_bucket_id=first.from_bucket_id,
                to_bucket_id=first.to_bucket_id,
                from_currency=first.from_currency,
                to_currency=first.to_currency,
                source_amount=first.source_amount,
                rate=first.rate,
                exact_converted=first.exact_converted,
                converted_amount=first.converted_amount,
                residual=Decimal("0.01000000"),
            ),
        ),
        cash=plan.cash,
    )
    with pytest.raises(PortfolioRequestError) as residual_error:
        apply_conversions(ledger, broken)
    assert _reason(residual_error) == "fx_event_mismatch"
