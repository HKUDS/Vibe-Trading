"""Exact Decimal pt-v2.0 portfolio valuation, exposure and concentration.

The analytics layer is a pure post-valuation projection over the same ledger,
valuation marks and direct FX pairs the step already used. These tests freeze
the complete three-currency arithmetic, prove every exposure ties back to the
Decimal ledger, and require explicit provenance or a declared failure instead
of inferred currencies or sectors.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal
from typing import Any

import pandas as pd
import pytest
from jsonschema import Draft202012Validator, FormatChecker

from src.tools.paper_trade.portfolio import run_portfolio_step
from src.tools.paper_trade.portfolio.analytics import build_portfolio_analytics
from src.tools.paper_trade.portfolio.data import (
    PriorMarkValuation,
    TargetBarValuation,
)
from src.tools.paper_trade.portfolio.hash import PortfolioDataHashes, document_hash
from src.tools.paper_trade.portfolio.models import PortfolioResult
from src.tools.paper_trade.portfolio.orchestrator import OrchestrationError
from src.tools.paper_trade.portfolio.schema import (
    PortfolioRequestError,
    load_portfolio_contract_schema,
    parse_portfolio_request,
)
from src.tools.paper_trade.portfolio.wire import (
    PortfolioWireError,
    build_error_from_exception,
    build_success_payload,
)

TRADE_DATE = date(2026, 11, 13)
PRIOR_DATE = date(2026, 11, 12)
DAY = TRADE_DATE.isoformat()
PRIOR = PRIOR_DATE.isoformat()
ZERO_WEIGHT = "0.000000000000"


class FakeLoader:
    """Offline loader double; analytics must never reach a provider."""

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
        "cn_a": FakeLoader({"600519.SH": _frame(95.0, 100.0)}, "cn-fixture"),
        "hk": FakeLoader({"00700.HK": _frame(38.0, 40.0)}, "hk-fixture"),
        "us": FakeLoader({"AAPL.US": _frame(48.0, 50.0)}, "us-fixture"),
    }


def _payload() -> dict[str, Any]:
    return {
        "tool": "paper_trade_step",
        "schema_version": "pt-v2.0",
        "mode": "portfolio",
        "account_id": "portfolio-analytics-01",
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
                    "cash": "1000.00",
                    "positions": [
                        {
                            "symbol": "600519.SH",
                            "qty": 10,
                            "avg_cost": "100.00",
                            "currency": "CNY",
                        }
                    ],
                },
                {
                    "bucket_id": "hk",
                    "market": "hk",
                    "currency": "HKD",
                    "cash": "500.00",
                    "positions": [
                        {
                            "symbol": "00700.HK",
                            "qty": 5,
                            "avg_cost": "40.00",
                            "currency": "HKD",
                        }
                    ],
                },
                {
                    "bucket_id": "us",
                    "market": "us",
                    "currency": "USD",
                    "cash": "100.00",
                    "positions": [
                        {
                            "symbol": "AAPL.US",
                            "qty": 2,
                            "avg_cost": "50.00",
                            "currency": "USD",
                        }
                    ],
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
                "rate_id": "cny-usd",
                "from": "CNY",
                "to": "USD",
                "rate": "0.14",
                "as_of": "2026-11-13T11:00:00+00:00",
                "source": "caller-cny",
            },
            {
                "rate_id": "hkd-usd",
                "from": "HKD",
                "to": "USD",
                "rate": "0.128",
                "as_of": "2026-11-13T11:00:00+00:00",
                "source": "caller-hkd",
            },
        ],
        "fx_conversions": [],
        "orders": [],
        "sectors": [
            {"bucket_id": "cn", "symbol": "600519.SH", "sector": "consumer"},
            {"bucket_id": "hk", "symbol": "00700.HK", "sector": "technology"},
        ],
    }


def _run(payload: dict[str, Any] | None = None):
    return run_portfolio_step(
        payload or _payload(),
        loaders=_loaders(),
        calendar_client=OpenCalendar(),
    )


def _money(value: str) -> Decimal:
    return Decimal(value)


def _dump(step) -> dict[str, Any]:
    return step.document.model_dump(mode="json", by_alias=True, exclude_none=True)


def _assert_no_floats(value: Any) -> None:
    if isinstance(value, float):
        raise AssertionError(f"float leaked into analytics: {value!r}")
    if isinstance(value, dict):
        for item in value.values():
            _assert_no_floats(item)
    elif isinstance(value, list):
        for item in value:
            _assert_no_floats(item)


def test_three_currency_nav_exposures_concentration_and_sectors_are_exact() -> None:
    # Given one CN, one HK and one US bucket with no orders.
    step = _run()
    document = step.document
    analytics = document.analytics

    # Then the new three-market step always publishes analytics.
    assert analytics is not None
    assert analytics.base_currency == "USD"
    assert analytics.nav_base == "569.60"
    assert analytics.cash_base == "304.00"
    assert analytics.position_value_base == "265.60"
    assert analytics.valuation_rounding == "0.00"
    assert analytics.nav_bridge.nav_base == "569.60"
    assert analytics.nav_bridge.cash_base == "304.00"
    assert analytics.nav_bridge.position_value_base == "265.60"

    # Then the rounded bridge is exactly the Decimal ledger NAV.
    bucket_nav = sum(
        (_money(row.nav_base) for row in document.bucket_results), Decimal(0)
    )
    assert bucket_nav == _money(analytics.nav_base)
    assert _money(analytics.nav_base) == (
        _money(analytics.cash_base)
        + _money(analytics.position_value_base)
        + _money(analytics.valuation_rounding)
    )

    # Then the exact identity is cash plus marked quantity value, both in FX.
    exact_cash = sum(
        (_money(row.exact_value_base) for row in analytics.cash_rows), Decimal(0)
    )
    exact_positions = sum(
        (_money(row.exact_value_base) for row in analytics.position_rows), Decimal(0)
    )
    assert exact_cash == Decimal("304.00")
    assert exact_positions == Decimal("265.60")
    assert exact_cash + exact_positions == _money(analytics.exact_nav_base)
    assert _money(analytics.nav_base) + _money(analytics.rounding_residual) == (
        _money(analytics.exact_nav_base)
    )

    # Then per-currency exposure sums to NAV exactly.
    assert [row.currency for row in analytics.currency_exposures] == [
        "CNY",
        "HKD",
        "USD",
    ]
    assert [row.value_base for row in analytics.currency_exposures] == [
        "280.00",
        "89.60",
        "200.00",
    ]
    assert sum(
        (_money(row.value_base) for row in analytics.currency_exposures), Decimal(0)
    ) == _money(analytics.nav_base)

    # Then per-market exposure sums to NAV exactly.
    assert [row.market for row in analytics.market_exposures] == ["cn_a", "hk", "us"]
    assert [row.value_base for row in analytics.market_exposures] == [
        "280.00",
        "89.60",
        "200.00",
    ]
    assert sum(
        (_money(row.value_base) for row in analytics.market_exposures), Decimal(0)
    ) == _money(analytics.nav_base)

    # Then concentration is measured on position value over NAV.
    concentration = analytics.concentration
    assert concentration.position_count == 3
    assert concentration.top_1 == "0.245786516854"
    assert concentration.top_5 == "0.466292134831"
    assert concentration.hhi == "0.093252903674"
    assert [(row.symbol, row.value_base) for row in concentration.position_weights] == [
        ("600519.SH", "140.00"),
        ("AAPL.US", "100.00"),
        ("00700.HK", "25.60"),
    ]

    # Then sectors include an explicit unclassified bucket for AAPL.US.
    assert [(row.sector, row.value_base) for row in analytics.sector_exposures] == [
        ("consumer", "140.00"),
        ("unclassified", "100.00"),
        ("technology", "25.60"),
    ]
    assert sum(
        (_money(row.value_base) for row in analytics.sector_exposures), Decimal(0)
    ) == _money(analytics.position_value_base)
    assert analytics.unclassified_sector == "unclassified"

    # Then every row carries dated mark/valuation and direct FX provenance.
    assert [
        (row.currency, row.amount, row.value_base) for row in analytics.cash_rows
    ] == [("CNY", "1000.00", "140.00"), ("HKD", "500.00", "64.00"), ("USD", "100.00", "100.00")]
    for row in analytics.cash_rows:
        assert row.valuation_date == TRADE_DATE
        assert row.fx.from_currency == row.currency
        assert row.fx.to_currency == "USD"
        assert row.fx.rate_id
        assert row.fx.as_of.tzinfo is not None
        assert row.fx.source
    assert [(row.symbol, row.mark.price_date) for row in analytics.position_rows] == [
        ("600519.SH", TRADE_DATE),
        ("00700.HK", TRADE_DATE),
        ("AAPL.US", TRADE_DATE),
    ]
    by_symbol = {row.symbol: row for row in analytics.position_rows}
    assert by_symbol["600519.SH"].fx.rate_id == "cny-usd"
    assert by_symbol["600519.SH"].fx.rate == "0.140000000000"
    assert by_symbol["600519.SH"].fx.source == "caller-cny"
    assert by_symbol["00700.HK"].fx.rate_id == "hkd-usd"
    assert by_symbol["00700.HK"].fx.rate == "0.128000000000"
    assert by_symbol["AAPL.US"].fx.rate_id == "identity:USD"
    assert by_symbol["AAPL.US"].fx.source == "base_currency_identity"
    for row in analytics.position_rows:
        assert row.mark.source.endswith(":valuation")
        assert row.mark.as_of.tzinfo is not None

    # Then every published analytics value is JSON-native (no floats/Decimals).
    dumped = analytics.model_dump(mode="json", by_alias=True, exclude_none=True)
    _assert_no_floats(dumped)
    assert not isinstance(dumped["nav_base"], Decimal)

    # Then the document hash covers analytics deterministically.
    layers = PortfolioDataHashes(
        plan_hash=document.hashes.plan_hash,
        planning_data_hash=document.hashes.planning_data_hash,
        execution_data_fingerprint=document.hashes.execution_data_fingerprint,
    )
    assert document.hashes.document_hash == document_hash(document, layers)
    assert _dump(_run()) == _dump(step)

    # Then the public wire document validates and retains the analytics.
    public = build_success_payload(step)
    schema = load_portfolio_contract_schema("result")
    assert list(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(public)
    ) == []
    assert public["analytics"]["nav_base"] == "569.60"


def test_closed_market_prior_mark_and_conversion_rounding_are_explicit() -> None:
    # Given an HK bucket that is closed and a CN bucket buying on the target day.
    payload = _payload()
    payload["portfolio_state"]["buckets"][0]["cash"] = "20000.00"
    payload["fx_conversions"] = [
        {
            "rate_id": "cny-usd",
            "from_bucket_id": "cn",
            "to_bucket_id": "us",
            "amount": "100.01",
        }
    ]
    payload["orders"] = [
        {
            "order_id": "cn-buy-1",
            "bucket_id": "cn",
            "symbol": "600519.SH",
            "currency": "CNY",
            "side": "buy",
            "qty": 100,
        }
    ]
    for session in payload["sessions"]:
        if session["market"] == "hk":
            session["status"] = "closed"

    # When the step values the closed HK position at its prior mark.
    step = _run(payload)
    analytics = step.document.analytics
    assert analytics is not None

    # Then the held HK position carries a prior-date mark, not the target date.
    hk = next(row for row in analytics.position_rows if row.symbol == "00700.HK")
    assert hk.price == "38.000000"
    assert hk.mark.price_date == PRIOR_DATE
    assert hk.mark.source == "hk-fixture:prior_mark"

    # Then the conversion rounding is declared in local and base currency.
    assert len(analytics.conversion_rows) == 1
    conversion = analytics.conversion_rows[0]
    assert conversion.rate_id == "cny-usd"
    assert conversion.source_amount == "100.01"
    assert conversion.rate == "0.140000000000"
    assert conversion.exact_converted == "14.0014"
    assert conversion.converted_amount == "14.00"
    assert conversion.rounding_residual_local == "0.0014"
    assert conversion.valuation_fx.from_currency == "USD"
    assert conversion.valuation_fx.rate_id == "identity:USD"
    assert conversion.rounding_residual_base == "0.0014"
    assert analytics.nav_bridge.conversion_rounding_base == "0.0014"


def test_missing_direct_fx_pair_fails_closed_before_analytics() -> None:
    # Given a held CNY position and no CNY->USD snapshot.
    payload = _payload()
    payload["fx_snapshots"] = [
        row for row in payload["fx_snapshots"] if row["rate_id"] != "cny-usd"
    ]

    # When the step values the ledger.
    with pytest.raises(OrchestrationError) as raised:
        _run(payload)

    # Then the missing direct pair is a declared request error, never a guess.
    assert raised.value.code == "INVALID_REQUEST"
    assert raised.value.reason == "missing_direct_fx_pair"
    assert raised.value.path == "planning_marks.cn.fx_rate_id"


def test_missing_valuation_mark_fails_closed_without_guessing_a_price() -> None:
    # Given a successful step and its prepared valuation snapshots.
    step = _run()
    request = parse_portfolio_request(_payload())

    # When every target mark is removed from the prepared bundle.
    buckets = tuple(
        replace(
            bucket,
            valuation=TargetBarValuation(
                snapshot=replace(bucket.valuation.snapshot, bars=())
            ),
        )
        if isinstance(bucket.valuation, TargetBarValuation)
        else replace(
            bucket,
            valuation=PriorMarkValuation(marks=()),
        )
        for bucket in step.prepared_data.buckets
    )
    prepared = replace(step.prepared_data, buckets=buckets)

    # Then analytics raises a declared missing-mark error, never a fallback.
    with pytest.raises(PortfolioRequestError) as raised:
        build_portfolio_analytics(request, step.end_ledger, prepared)

    assert raised.value.reason == "missing_valuation_mark"


def test_non_hkd_hk_counter_and_fee_metadata_fail_closed() -> None:
    # Given an HK bucket whose cash is HKD but whose fee model is USD.
    payload = _payload()
    payload["portfolio_state"]["buckets"][1]["fee_model"] = {
        "currency": "USD",
        "parameters": {"commission_rate": "0.0003"},
    }

    # Then the request parser refuses the non-HKD HK counter.
    with pytest.raises(PortfolioRequestError) as raised:
        parse_portfolio_request(payload)
    assert raised.value.reason == "non_hkd_hk_counter"

    # And changing the bucket/position currency cannot smuggle HKD by market.
    payload = _payload()
    payload["portfolio_state"]["buckets"][1]["currency"] = "USD"
    payload["portfolio_state"]["buckets"][1]["positions"][0]["currency"] = "USD"
    with pytest.raises(PortfolioRequestError) as raised:
        parse_portfolio_request(payload)
    assert raised.value.reason == "invalid_bucket_currency"


def test_absent_sector_mapping_is_explicitly_unclassified_not_inferred() -> None:
    # Given the three-currency fixture with no caller sectors at all.
    payload = _payload()
    payload["sectors"] = []

    # When analytics groups position value by caller sector.
    analytics = _run(payload).document.analytics
    assert analytics is not None

    # Then every position lands in the explicit unclassified bucket.
    assert [row.sector for row in analytics.sector_exposures] == ["unclassified"]
    assert analytics.sector_exposures[0].value_base == "265.60"
    assert analytics.sector_exposures[0].symbols == (
        "00700.HK",
        "600519.SH",
        "AAPL.US",
    )


def test_duplicate_or_unknown_sector_metadata_fails_closed() -> None:
    # Given two conflicting sectors for one held position.
    payload = _payload()
    payload["sectors"].append(
        {"bucket_id": "cn", "symbol": "600519.SH", "sector": "industrials"}
    )

    with pytest.raises(PortfolioRequestError) as raised:
        _run(payload)
    assert raised.value.reason == "duplicate_sector"

    # Given a sector naming an undeclared instrument.
    payload = _payload()
    payload["sectors"].append(
        {"bucket_id": "us", "symbol": "MSFT.US", "sector": "technology"}
    )
    with pytest.raises(PortfolioRequestError) as raised:
        _run(payload)
    assert raised.value.reason == "unknown_sector_symbol"


def test_old_documents_without_analytics_still_validate_and_serialize() -> None:
    # Given a new document dump with its optional analytics member removed.
    step = _run()
    document = _dump(step)
    legacy = {key: value for key, value in document.items() if key != "analytics"}

    # Then the existing model and public wire accept the old shape unchanged.
    parsed = PortfolioResult.model_validate(legacy)
    assert parsed.analytics is None
    public = build_success_payload(legacy)
    assert "analytics" not in public
    schema = load_portfolio_contract_schema("result")
    assert list(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(public)
    ) == []


def test_tampered_analytics_nav_is_rejected_by_the_public_wire() -> None:
    # Given a document whose analytics claims a different NAV than the ledger.
    step = _run()
    document = _dump(step)
    document["analytics"]["nav_base"] = "999999.99"

    # Then the public wire refuses to publish a misleading success document.
    with pytest.raises(PortfolioWireError) as raised:
        build_success_payload(document)
    assert raised.value.reason == "analytics_nav_mismatch"


def test_analytics_errors_never_serialize_as_success_documents() -> None:
    # Given a malformed request that has no analytics.
    raw = {"tool": "paper_trade_step", "mode": "portfolio", "schema_version": "pt-v2.0"}
    with pytest.raises(PortfolioRequestError) as raised:
        parse_portfolio_request(raw)
    error = build_error_from_exception(raw, raised.value)

    # Then the public error envelope is stable and carries no ledger/analytics.
    assert error["status"] == "error"
    assert error["code"] == "INVALID_REQUEST"
    assert "analytics" not in error
    assert "end_portfolio" not in error
    assert "fills" not in error
    schema = load_portfolio_contract_schema("error_envelope")
    assert list(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(error)
    ) == []
