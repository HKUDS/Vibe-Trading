"""Direct-pair FX snapshots, conversion and NAV-bridge tests for pt-v2.0."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.tools.paper_trade.portfolio.fx import (FxConversionPlan, FxRate, FxRateBook, NavBridgeTotal,
    plan_conversions, total_nav_bridge, value_in_base_currency)
from src.tools.paper_trade.portfolio.models import (Currency, FxConversion, FxSnapshot, MarketSession,
    PortfolioBucket, PortfolioRequest, PortfolioState)
from src.tools.paper_trade.portfolio.schema import PortfolioRequestError

AS_OF = datetime(2026, 1, 5, 18, tzinfo=timezone.utc)
VALUATION = datetime(2026, 1, 5, 19, tzinfo=timezone.utc)
DAY = date(2026, 1, 5)
DEFAULT_CASH = {"cn": "100000.00", "hk": "20000.00", "us": "1000.00"}


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


def _bucket(bucket_id: str, market: str, currency: Currency, cash: str) -> PortfolioBucket:
    return PortfolioBucket(
        bucket_id=bucket_id, market=market, currency=currency, cash=cash, positions=()
    )


def _request(
    snapshots: tuple[FxSnapshot, ...],
    conversions: tuple[FxConversion, ...],
    *,
    cash: dict[str, str] | None = None,
) -> PortfolioRequest:
    balances = DEFAULT_CASH if cash is None else cash
    return PortfolioRequest(
        tool="paper_trade_step",
        schema_version="pt-v2.0",
        mode="portfolio",
        account_id="fx-fixture",
        base_currency="USD",
        trade_date=DAY,
        planning_at=AS_OF,
        valuation_at=VALUATION,
        portfolio_state=PortfolioState(
            buckets=(
                _bucket("cn", "cn_a", "CNY", balances["cn"]),
                _bucket("hk", "hk", "HKD", balances["hk"]),
                _bucket("us", "us", "USD", balances["us"]),
            )
        ),
        sessions=(
            MarketSession(market="cn_a", status="open", source="fixture", as_of=AS_OF),
            MarketSession(market="hk", status="open", source="fixture", as_of=AS_OF),
            MarketSession(market="us", status="open", source="fixture", as_of=AS_OF),
        ),
        fx_snapshots=snapshots,
        fx_conversions=conversions,
    )


def _conversion(rate_id: str, source: str, target: str, amount: str) -> FxConversion:
    return FxConversion(
        rate_id=rate_id, from_bucket_id=source, to_bucket_id=target, amount=amount
    )


def _reason(exc_info: pytest.ExceptionInfo[PortfolioRequestError]) -> str:
    return exc_info.value.reason


def test_snapshot_is_frozen_and_one_from_equals_rate_to() -> None:
    # Given a direct CNY/HKD snapshot carrying its own provenance.
    book = FxRateBook.from_snapshots((_snapshot("cny-hkd", "CNY", "HKD", "1.0835"),))

    # When the exact rate is looked up by its declared id.
    rate = book.by_id("cny-hkd")

    # Then the orientation and twelve-place rate are exactly as declared.
    assert isinstance(rate, FxRate)
    assert rate.from_currency == "CNY"
    assert rate.to_currency == "HKD"
    assert rate.rate == Decimal("1.083500000000")
    assert rate.source == "fixture.fx"
    assert Decimal("1") * rate.rate == Decimal("1.083500000000")
    with pytest.raises(FrozenInstanceError):
        rate.rate = Decimal("2")  # type: ignore[misc]


def test_three_currency_chain_converts_exactly_and_keeps_residual_visible() -> None:
    # Given direct CNY/HKD and HKD/USD pairs and two opening conversions.
    # The second conversion is funded by opening HKD, not by CNY proceeds.
    request = _request(
        (
            _snapshot("cny-hkd", "CNY", "HKD", "1.0835"),
            _snapshot("hkd-usd", "HKD", "USD", "0.128333"),
        ),
        (
            _conversion("cny-hkd", "cn", "hk", "30000.00"),
            _conversion("hkd-usd", "hk", "us", "12345.67"),
        ),
    )

    # When the conversions are planned against the opening cash.
    plan = plan_conversions(request)

    # Then each step uses only its direct pair, with exact Decimal arithmetic.
    assert isinstance(plan, FxConversionPlan)
    first, second = plan.events
    assert first.exact_converted == Decimal("32505.00000000")
    assert first.converted_amount == Decimal("32505.00")
    assert first.residual == Decimal("0")
    assert second.source_amount == Decimal("12345.67")
    assert second.exact_converted == Decimal("1584.35686811")
    assert second.converted_amount == Decimal("1584.36")
    assert second.residual == Decimal("-0.00313189")
    assert plan.cash_map() == {
        "cn": Decimal("70000.00"),
        "hk": Decimal("40159.33"),
        "us": Decimal("2584.36"),
    }


def test_conversion_rounds_half_even_and_reports_the_exact_residual() -> None:
    # Given an amount whose product sits exactly on a cent tie.
    request = _request(
        (_snapshot("hkd-usd", "HKD", "USD", "0.128333"),),
        (_conversion("hkd-usd", "hk", "us", "5000.00"),),
        cash={"cn": "0.00", "hk": "5000.00", "us": "0.00"},
    )

    # When the direct conversion is quantized to two target-currency places.
    event = plan_conversions(request).events[0]

    # Then ROUND_HALF_EVEN keeps the even cent and the residual is explicit.
    assert event.exact_converted == Decimal("641.66500000")
    assert event.converted_amount == Decimal("641.66")
    assert event.residual == Decimal("0.00500000")
    assert event.exact_converted == event.converted_amount + event.residual


def test_inverse_only_pair_is_rejected_for_conversion_and_valuation() -> None:
    # Given only an inverse USD/HKD snapshot.
    snapshots = (_snapshot("usd-hkd", "USD", "HKD", "7.8"),)
    book = FxRateBook.from_snapshots(snapshots)

    # Then a HKD/USD conversion naming that inverse id fails closed.
    with pytest.raises(PortfolioRequestError) as conversion_error:
        plan_conversions(
            _request(snapshots, (_conversion("usd-hkd", "hk", "us", "100.00"),))
        )
    assert _reason(conversion_error) == "inverse_fx_rate_only"

    # And base valuation never inverts the available pair either.
    with pytest.raises(PortfolioRequestError) as valuation_error:
        value_in_base_currency(
            "hk", "HKD", Decimal("100.00"), book, base_currency="USD"
        )
    assert _reason(valuation_error) == "inverse_fx_rate_only"


def test_triangulation_is_rejected_even_when_two_hops_exist() -> None:
    # Given CNY/HKD and HKD/USD pairs, but no direct CNY/USD pair.
    snapshots = (
        _snapshot("cny-hkd", "CNY", "HKD", "1.0835"),
        _snapshot("hkd-usd", "HKD", "USD", "0.128333"),
    )
    book = FxRateBook.from_snapshots(snapshots)

    # Then base valuation refuses to synthesize the missing direct pair.
    with pytest.raises(PortfolioRequestError) as valuation_error:
        value_in_base_currency(
            "cn", "CNY", Decimal("100.00"), book, base_currency="USD"
        )
    assert _reason(valuation_error) == "triangulation_not_supported"

    # And a conversion cannot borrow a rate id from another orientation.
    with pytest.raises(PortfolioRequestError) as conversion_error:
        plan_conversions(
            _request(
                snapshots,
                (_conversion("cny-hkd", "cn", "us", "100.00"),),
            )
        )
    assert _reason(conversion_error) == "fx_pair_mismatch"


def test_missing_direct_pair_and_unknown_rate_id_are_rejected() -> None:
    # Given a book with no pair at all.
    empty = FxRateBook.from_snapshots(())

    # Then base valuation names the missing direct pair.
    with pytest.raises(PortfolioRequestError) as valuation_error:
        value_in_base_currency(
            "cn", "CNY", Decimal("100.00"), empty, base_currency="USD"
        )
    assert _reason(valuation_error) == "missing_direct_fx_pair"

    # And a conversion naming an undeclared id cannot resolve a rate.
    with pytest.raises(PortfolioRequestError) as conversion_error:
        plan_conversions(
            _request((), (_conversion("ghost", "cn", "hk", "100.00"),))
        )
    assert _reason(conversion_error) == "unknown_fx_rate"


def test_stale_future_and_boundary_snapshots_are_checked_against_valuation_at() -> None:
    # Given a five-minute freshness budget anchored at the valuation instant.
    def book(as_of: datetime) -> FxRateBook:
        return FxRateBook.from_snapshots(
            (_snapshot("cny-hkd", "CNY", "HKD", "1.0835", as_of=as_of),),
            at=VALUATION,
            max_age=timedelta(minutes=5),
        )

    # Then an older snapshot is stale, a future one is rejected, and the
    # exact five-minute boundary is still fresh.
    with pytest.raises(PortfolioRequestError) as stale_error:
        book(VALUATION - timedelta(minutes=5, seconds=1)).require_direct("CNY", "HKD")
    assert _reason(stale_error) == "stale_fx_rate"

    with pytest.raises(PortfolioRequestError) as future_error:
        book(VALUATION + timedelta(seconds=1)).require_direct("CNY", "HKD")
    assert _reason(future_error) == "future_fx_rate"

    assert book(VALUATION - timedelta(minutes=5)).require_direct("CNY", "HKD").rate_id == "cny-hkd"


def test_conversion_rate_after_planning_at_is_future_even_before_valuation() -> None:
    # Given a rate stamped after planning_at but before valuation_at.
    request = _request(
        (
            _snapshot(
                "cny-hkd",
                "CNY",
                "HKD",
                "1.0835",
                as_of=AS_OF + timedelta(minutes=30),
            ),
        ),
        (_conversion("cny-hkd", "cn", "hk", "100.00"),),
    )

    # Then conversion freshness is anchored to planning_at.
    with pytest.raises(PortfolioRequestError) as exc_info:
        plan_conversions(request)
    assert _reason(exc_info) == "future_fx_rate"


def test_conversion_max_age_is_measured_from_planning_at() -> None:
    # Given rates four and six minutes before planning_at.
    def request(minutes_old: int) -> PortfolioRequest:
        return _request(
            (
                _snapshot(
                    "cny-hkd",
                    "CNY",
                    "HKD",
                    "1.0835",
                    as_of=AS_OF - timedelta(minutes=minutes_old),
                ),
            ),
            (_conversion("cny-hkd", "cn", "hk", "100.00"),),
        )

    # Then a five-minute budget accepts the newer rate and rejects the older.
    fresh = plan_conversions(request(4), max_age=timedelta(minutes=5))
    assert fresh.events[0].rate_id == "cny-hkd"
    with pytest.raises(PortfolioRequestError) as exc_info:
        plan_conversions(request(6), max_age=timedelta(minutes=5))
    assert _reason(exc_info) == "stale_fx_rate"


def test_invalid_degenerate_and_duplicate_rates_are_rejected() -> None:
    # Given rates outside the positive direct-pair domain.
    for raw in ("0", "-1.5"):
        with pytest.raises(PortfolioRequestError) as rate_error:
            FxRateBook.from_snapshots((_snapshot("bad", "CNY", "HKD", raw),))
        assert _reason(rate_error) == "decimal_out_of_range"

    # And an identity pair carries no conversion meaning.
    with pytest.raises(PortfolioRequestError) as degenerate_error:
        FxRateBook.from_snapshots((_snapshot("same", "CNY", "CNY", "1"),))
    assert _reason(degenerate_error) == "degenerate_fx_pair"

    # And two snapshots cannot share one rate id.
    with pytest.raises(PortfolioRequestError) as duplicate_error:
        FxRateBook.from_snapshots(
            (
                _snapshot("dup", "CNY", "HKD", "1.0835"),
                _snapshot("dup", "HKD", "USD", "0.128333"),
            )
        )
    assert _reason(duplicate_error) == "duplicate_fx_rate"


def test_ambiguous_direct_pairs_require_an_explicit_rate_id() -> None:
    # Given two direct CNY/USD snapshots with distinct provenance.
    book = FxRateBook.from_snapshots(
        (
            _snapshot("a", "CNY", "USD", "0.13857"),
            _snapshot("b", "CNY", "USD", "0.13858"),
        )
    )

    # Then base valuation refuses to guess which direct pair applies.
    with pytest.raises(PortfolioRequestError) as ambiguous_error:
        value_in_base_currency(
            "cn", "CNY", Decimal("100.00"), book, base_currency="USD"
        )
    assert _reason(ambiguous_error) == "ambiguous_direct_fx_pair"

    # And a conversion resolves the exact pair through its declared rate id.
    rate = book.require_direct("CNY", "USD", rate_id="b")
    assert rate.rate_id == "b"
    assert rate.rate == Decimal("0.138580000000")


def test_conversion_cannot_overspend_or_auto_fund_a_bucket() -> None:
    # Given a CNY bucket holding 100000.00.
    oversized = _request(
        (_snapshot("cny-hkd", "CNY", "HKD", "1.0835"),),
        (_conversion("cny-hkd", "cn", "hk", "200000.00"),),
    )

    # Then over-conversion is rejected instead of funded from elsewhere.
    with pytest.raises(PortfolioRequestError) as oversized_error:
        plan_conversions(oversized)
    assert _reason(oversized_error) == "insufficient_fx_cash"

    # And sequential conversions may not reuse cash already committed.
    overcommitted = _request(
        (_snapshot("cny-hkd", "CNY", "HKD", "1.0835"),),
        (
            _conversion("cny-hkd", "cn", "hk", "60000.00"),
            _conversion("cny-hkd", "cn", "hk", "60000.00"),
        ),
    )
    with pytest.raises(PortfolioRequestError) as second_error:
        plan_conversions(overcommitted)
    assert _reason(second_error) == "insufficient_fx_cash"


def test_converted_proceeds_cannot_fund_a_later_conversion() -> None:
    # Given the verifier repro: 100 CNY -> USD, then spend that USD on HKD.
    request = _request(
        (
            _snapshot("cny-usd", "CNY", "USD", "0.1386"),
            _snapshot("usd-hkd", "USD", "HKD", "7.8"),
        ),
        (
            _conversion("cny-usd", "cn", "us", "100.00"),
            _conversion("usd-hkd", "us", "hk", "13.86"),
        ),
        cash={"cn": "100.00", "hk": "0.00", "us": "0.00"},
    )

    # Then the second conversion cannot spend the first conversion's USD.
    with pytest.raises(PortfolioRequestError) as exc_info:
        plan_conversions(request)
    assert _reason(exc_info) == "insufficient_fx_cash"
    assert exc_info.value.path == "fx_conversions[1].amount"
    assert exc_info.value.bucket_id == "us"


def test_same_source_conversions_are_limited_by_remaining_opening_cash() -> None:
    # Given 100.00 CNY of opening cash split into two same-source conversions.
    snapshots = (_snapshot("cny-hkd", "CNY", "HKD", "1.0835"),)
    exact = _request(
        snapshots,
        (
            _conversion("cny-hkd", "cn", "hk", "60.00"),
            _conversion("cny-hkd", "cn", "hk", "40.00"),
        ),
        cash={"cn": "100.00", "hk": "0.00", "us": "0.00"},
    )

    # Then the pair may consume exactly the opening source cash.
    plan = plan_conversions(exact)
    assert [event.source_amount for event in plan.events] == [
        Decimal("60.00"),
        Decimal("40.00"),
    ]
    assert plan.cash_map() == {
        "cn": Decimal("0.00"),
        "hk": Decimal("108.35"),
        "us": Decimal("0.00"),
    }

    # And one cent beyond the remaining opening cash is rejected.
    over = _request(
        snapshots,
        (
            _conversion("cny-hkd", "cn", "hk", "60.00"),
            _conversion("cny-hkd", "cn", "hk", "40.01"),
        ),
        cash={"cn": "100.00", "hk": "0.00", "us": "0.00"},
    )
    with pytest.raises(PortfolioRequestError) as exc_info:
        plan_conversions(over)
    assert _reason(exc_info) == "insufficient_fx_cash"
    assert exc_info.value.bucket_id == "cn"


def test_non_positive_conversion_amount_and_self_conversion_are_rejected() -> None:
    # Given conversions whose amount is zero or whose endpoints coincide.
    for amount, reason in (("0.00", "invalid_fx_amount"), ("-1.00", "invalid_fx_amount")):
        request = _request(
            (_snapshot("cny-hkd", "CNY", "HKD", "1.0835"),),
            (_conversion("cny-hkd", "cn", "hk", amount),),
        )
        with pytest.raises(PortfolioRequestError) as amount_error:
            plan_conversions(request)
        assert _reason(amount_error) == reason

    identity = _request(
        (),
        (_conversion("same", "cn", "cn", "100.00"),),
    )
    with pytest.raises(PortfolioRequestError) as identity_error:
        plan_conversions(identity)
    assert _reason(identity_error) == "identity_fx_conversion"


def test_post_fill_conversion_stage_is_rejected() -> None:
    # Given a conversion planned for the pre-fill opening stage only.
    request = _request(
        (_snapshot("cny-hkd", "CNY", "HKD", "1.0835"),),
        (_conversion("cny-hkd", "cn", "hk", "100.00"),),
    )

    # Then a post-fill attempt cannot settle through this module.
    with pytest.raises(PortfolioRequestError) as exc_info:
        plan_conversions(request, stage="post_fill")
    assert _reason(exc_info) == "post_fill_fx_conversion"


def test_nav_bridge_reports_base_values_residuals_and_exact_balance() -> None:
    # Given direct CNY/USD and HKD/USD pairs for every non-USD bucket.
    book = FxRateBook.from_snapshots(
        (
            _snapshot("cny-usd", "CNY", "USD", "0.13857"),
            _snapshot("hkd-usd", "HKD", "USD", "0.128333"),
        )
    )
    events = (
        value_in_base_currency("cn", "CNY", Decimal("70000.00"), book, base_currency="USD"),
        value_in_base_currency("hk", "HKD", Decimal("40159.33"), book, base_currency="USD"),
        value_in_base_currency("us", "USD", Decimal("2584.36"), book, base_currency="USD"),
    )

    # When the bridge rows are totalled.
    total = total_nav_bridge(events)

    # Then every residual is explicit and reported plus residual equals exact.
    assert [event.rate for event in events] == [
        Decimal("0.138570000000"),
        Decimal("0.128333000000"),
        Decimal("1"),
    ]
    assert events[2].rate_id is None
    assert events[0].reported_base == Decimal("9699.90")
    assert events[1].reported_base == Decimal("5153.77")
    assert events[1].residual == Decimal("-0.00270311")
    assert isinstance(total, NavBridgeTotal)
    assert total.reported_base == Decimal("17438.03")
    assert total.exact_base == Decimal("17438.02729689")
    assert total.residual == Decimal("-0.00270311")
    assert total.exact_base == total.reported_base + total.residual
    assert total.balanced is True
