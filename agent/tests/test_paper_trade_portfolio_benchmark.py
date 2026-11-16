"""Explicit caller-supplied pt-v2.0 benchmark observations and deviation.

The benchmark is a pure projection over two caller-declared observations and
the declared direct FX pairs. These tests freeze the exact one-day benchmark
return, the portfolio's own one-day NAV return and their deviation, prove the
absent case is an explicit ``benchmark: null``, and require deterministic
failures for malformed, stale or currency-mismatched observations. No default
benchmark is inferred and no live data is fetched.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal, localcontext
from typing import Any

import pandas as pd
import pytest

from src.tools.paper_trade.portfolio import run_portfolio_step
from src.tools.paper_trade.portfolio.fx import FxRateBook
from src.tools.paper_trade.portfolio.hash import PortfolioDataHashes, document_hash
from src.tools.paper_trade.portfolio.ledger import value_ledger
from src.tools.paper_trade.portfolio.models import PortfolioResult
from src.tools.paper_trade.portfolio.schema import (
    PortfolioRequestError,
    load_portfolio_contract_schema,
    parse_portfolio_request,
)
from src.tools.paper_trade.portfolio.wire import (
    PortfolioWireError,
    build_success_payload,
    serialize_success,
)

TRADE_DATE = date(2026, 11, 13)
PRIOR_DATE = date(2026, 11, 12)
DAY = TRADE_DATE.isoformat()
PRIOR = PRIOR_DATE.isoformat()


class FakeLoader:
    """Offline loader double; benchmark analytics must never reach a provider."""

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


def _three_market_payload(*, benchmark: dict[str, Any] | None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "tool": "paper_trade_step",
        "schema_version": "pt-v2.0",
        "mode": "portfolio",
        "account_id": "portfolio-benchmark-01",
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
    if benchmark is not None:
        payload["benchmark"] = benchmark
    return payload


def _usd_benchmark() -> dict[str, Any]:
    return {
        "benchmark_id": "caller-usd-benchmark",
        "start": {
            "observed_at": "2026-11-12T21:00:00+00:00",
            "value": "100.00",
            "currency": "USD",
        },
        "end": {
            "observed_at": "2026-11-13T21:00:00+00:00",
            "value": "101.00",
            "currency": "USD",
        },
    }


def _usd_only_payload() -> dict[str, Any]:
    return {
        "tool": "paper_trade_step",
        "schema_version": "pt-v2.0",
        "mode": "portfolio",
        "account_id": "portfolio-benchmark-fx-01",
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
                    "positions": [
                        {
                            "symbol": "AAPL.US",
                            "qty": 10,
                            "avg_cost": "48.00",
                            "currency": "USD",
                        }
                    ],
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
        "fx_snapshots": [
            {
                "rate_id": "cny-usd-start",
                "from": "CNY",
                "to": "USD",
                "rate": "0.14",
                "as_of": "2026-11-12T12:00:00+00:00",
                "source": "caller-start-fix",
            },
            {
                "rate_id": "cny-usd-end",
                "from": "CNY",
                "to": "USD",
                "rate": "0.15",
                "as_of": "2026-11-13T12:00:00+00:00",
                "source": "caller-end-fix",
            },
        ],
        "fx_conversions": [],
        "orders": [],
        "benchmark": {
            "benchmark_id": "caller-cny-benchmark",
            "start": {
                "observed_at": "2026-11-12T21:00:00+00:00",
                "value": "700.00",
                "currency": "CNY",
                "rate_id": "cny-usd-start",
            },
            "end": {
                "observed_at": "2026-11-13T21:00:00+00:00",
                "value": "721.00",
                "currency": "CNY",
                "rate_id": "cny-usd-end",
            },
        },
    }


def _three_market_loaders() -> dict[str, FakeLoader]:
    return {
        "cn_a": FakeLoader({"600519.SH": _frame(95.0, 100.0)}, "cn-fixture"),
        "hk": FakeLoader({"00700.HK": _frame(38.0, 40.0)}, "hk-fixture"),
        "us": FakeLoader({"AAPL.US": _frame(48.0, 50.0)}, "us-fixture"),
    }


def _usd_loaders() -> dict[str, FakeLoader]:
    return {"us": FakeLoader({"AAPL.US": _frame(48.0, 50.0)}, "us-fixture")}


def _run(payload: dict[str, Any], *, usd_only: bool = False):
    return run_portfolio_step(
        payload,
        loaders=_usd_loaders() if usd_only else _three_market_loaders(),
        calendar_client=OpenCalendar(),
    )


def _assert_no_floats(value: Any) -> None:
    if isinstance(value, float):
        raise AssertionError(f"float leaked into benchmark analytics: {value!r}")
    if isinstance(value, dict):
        for item in value.values():
            _assert_no_floats(item)
    elif isinstance(value, list):
        for item in value:
            _assert_no_floats(item)


def test_explicit_observations_publish_exact_return_and_deviation() -> None:
    # Given two caller-declared USD benchmark levels of 100 -> 101.
    step = _run(_three_market_payload(benchmark=_usd_benchmark()))

    # Then the benchmark is present with both observations and their provenance.
    analytics = step.document.analytics
    assert analytics is not None
    benchmark = analytics.benchmark
    assert benchmark is not None
    assert benchmark.benchmark_id == "caller-usd-benchmark"
    assert benchmark.start.observed_at == datetime(2026, 11, 12, 21, tzinfo=UTC)
    assert benchmark.end.observed_at == datetime(2026, 11, 13, 21, tzinfo=UTC)
    assert (benchmark.start.value, benchmark.start.value_base) == ("100.000000", "100.00")
    assert (benchmark.end.value, benchmark.end.value_base) == ("101.000000", "101.00")
    assert benchmark.start.fx.rate_id == "identity:USD"
    assert benchmark.end.fx.rate_id == "identity:USD"
    assert benchmark.start.fx.source == "base_currency_identity"

    # Then the one-day benchmark return is exact and carries no float.
    assert benchmark.benchmark_return == "0.010000000000"
    assert Decimal(benchmark.exact_benchmark_return) == Decimal("0.01")

    # Then the portfolio return is the exact reported NAV change from prior marks.
    assert benchmark.portfolio_start_nav_base == "557.32"
    assert benchmark.portfolio_start_exact_nav_base == "557.32"
    assert benchmark.portfolio_end_nav_base == "569.60"
    assert benchmark.portfolio_end_exact_nav_base == "569.6"
    assert benchmark.portfolio_return == "0.022034019953"
    with localcontext() as context:
        context.prec = 60
        expected_portfolio_return = Decimal("569.60") / Decimal("557.32") - Decimal(1)
    assert Decimal(benchmark.exact_portfolio_return) == expected_portfolio_return

    # Then deviation is exactly portfolio return minus benchmark return.
    assert benchmark.deviation == "0.012034019953"
    with localcontext() as context:
        context.prec = 60
        expected_deviation = (
            Decimal(benchmark.exact_portfolio_return)
            - Decimal(benchmark.exact_benchmark_return)
        )
    assert Decimal(benchmark.exact_deviation) == expected_deviation
    _assert_no_floats(step.document.model_dump(mode="json", by_alias=True))

    # Then the public wire and packaged result schema accept the document.
    public = build_success_payload(step)
    assert public["analytics"]["benchmark"]["deviation"] == "0.012034019953"
    assert public["analytics"]["benchmark"]["start"]["fx"]["rate_id"] == "identity:USD"


def _subcent_step(cn_cash: str, hk_cash: str):
    payload = _three_market_payload(benchmark=_usd_benchmark())
    payload["portfolio_state"]["buckets"][0]["cash"] = cn_cash
    payload["portfolio_state"]["buckets"][1]["cash"] = hk_cash
    return payload, _run(payload)


@pytest.mark.parametrize(
    ("cn_cash", "hk_cash", "reported", "exact"),
    [
        pytest.param("1000.03", "500.03", "557.32", "557.32804", id="sub-cent-small"),
        pytest.param(
            "100000.03", "50000.03", "20753.32", "20753.32804", id="sub-cent-realistic"
        ),
    ],
)
def test_subcent_opening_cash_publishes_the_start_nav_residual(
    cn_cash: str,
    hk_cash: str,
    reported: str,
    exact: str,
) -> None:
    # Given sub-cent opening cash in two currencies and a declared benchmark.
    payload, step = _subcent_step(cn_cash, hk_cash)
    analytics = step.document.analytics
    assert analytics is not None
    benchmark = analytics.benchmark
    assert benchmark is not None

    # Then the reported start NAV is the ledger's bucket-reported sum, not a
    # fresh rounding of the exact total (which would round up one cent).
    request = parse_portfolio_request(payload)
    planning_book = FxRateBook.from_snapshots(
        request.fx_snapshots,
        at=request.planning_at,
    )
    start_bridge = value_ledger(
        step.opening_ledger,
        {"600519.SH": Decimal("95"), "00700.HK": Decimal("38"), "AAPL.US": Decimal("48")},
        planning_book,
        base_currency=request.base_currency,
        path="test.benchmark_start_marks",
    )
    assert benchmark.portfolio_start_nav_base == reported
    assert start_bridge.total.reported_base == Decimal(reported)
    assert Decimal(exact).quantize(Decimal("0.01")) != Decimal(reported)

    # Then the explicit residual ties that reported NAV to the exact bridge.
    assert benchmark.portfolio_start_exact_nav_base == exact
    assert benchmark.portfolio_start_rounding_residual == "0.00804"
    assert Decimal(reported) + Decimal(benchmark.portfolio_start_rounding_residual) == (
        Decimal(exact)
    )

    # Then the public wire publishes the same evidence and accepts it.
    public = build_success_payload(step)
    published = public["analytics"]["benchmark"]
    assert published["portfolio_start_nav_base"] == reported
    assert published["portfolio_start_exact_nav_base"] == exact
    assert published["portfolio_start_rounding_residual"] == "0.00804"
    PortfolioResult.model_validate(public)


def test_wire_rejects_a_tampered_start_nav_residual() -> None:
    # Given a valid sub-cent starter with a real benchmark document.
    payload = build_success_payload(_subcent_step("1000.03", "500.03")[1])

    # When the residual is changed without changing the reported or exact NAV.
    tampered = json.loads(json.dumps(payload))
    tampered["analytics"]["benchmark"]["portfolio_start_rounding_residual"] = "0.00805"

    # Then the public boundary refuses the inconsistent start-NAV bridge.
    with pytest.raises(PortfolioWireError) as caught:
        build_success_payload(tampered)
    assert caught.value.reason == "benchmark_nav_mismatch"
    assert caught.value.path == (
        "analytics.benchmark.portfolio_start_rounding_residual"
    )


def test_absent_benchmark_serializes_an_explicit_null() -> None:
    # Given a step with no caller benchmark.
    step = _run(_three_market_payload(benchmark=None))
    analytics = step.document.analytics
    assert analytics is not None
    assert analytics.benchmark is None

    # Then the builder explicitly set the field, even when its value is None.
    assert "benchmark" in analytics.model_fields_set

    # Then the new document carries the key explicitly as null, not omitted.
    dumped = step.document.model_dump(mode="json", by_alias=True, exclude_none=True)
    assert "benchmark" in dumped["analytics"]
    assert dumped["analytics"]["benchmark"] is None
    public = json.loads(serialize_success(step))
    assert "benchmark" in public["analytics"]
    assert public["analytics"]["benchmark"] is None

    # Then no default benchmark name, return or deviation is fabricated.
    assert public["analytics"].get("benchmark_id") is None


def test_legacy_analytics_without_benchmark_keeps_its_document_hash() -> None:
    # Given a task-22-era document whose analytics never carried a benchmark key.
    step = _run(_three_market_payload(benchmark=_usd_benchmark()))
    payload = step.document.model_dump(mode="json", by_alias=True, exclude_none=True)
    payload["analytics"].pop("benchmark")
    layers = PortfolioDataHashes(
        plan_hash=payload["hashes"]["plan_hash"],
        planning_data_hash=payload["hashes"]["planning_data_hash"],
        execution_data_fingerprint=payload["hashes"]["execution_data_fingerprint"],
    )
    archived = PortfolioResult.model_validate(payload)
    legacy_hash = document_hash(archived, layers)
    assert legacy_hash != payload["hashes"]["document_hash"]
    payload["hashes"]["document_hash"] = legacy_hash

    # When the archived document is reparsed and its hash recomputed...
    document = PortfolioResult.model_validate(payload)

    # Then the serialized shape and the whole document hash are unchanged: the
    # absent benchmark key is not resurrected as an explicit null.
    assert "benchmark" not in document.analytics.model_fields_set
    redumped = document.model_dump(mode="json", by_alias=True, exclude_none=True)
    assert "benchmark" not in redumped["analytics"]
    assert document_hash(document, layers) == legacy_hash
    assert "benchmark" not in build_success_payload(document)["analytics"]


def test_old_analytics_document_without_benchmark_key_remains_valid() -> None:
    # Given a task-22-style analytics document that predates the benchmark key.
    step = _run(_three_market_payload(benchmark=None))
    payload = step.document.model_dump(mode="json", by_alias=True, exclude_none=True)
    payload["analytics"].pop("benchmark")
    document = PortfolioResult.model_validate(payload)
    layers = PortfolioDataHashes(
        plan_hash=payload["hashes"]["plan_hash"],
        planning_data_hash=payload["hashes"]["planning_data_hash"],
        execution_data_fingerprint=payload["hashes"]["execution_data_fingerprint"],
    )
    payload["hashes"]["document_hash"] = document_hash(document, layers)

    # Then the legacy shape still validates and serializes without inventing one.
    public = build_success_payload(payload)
    assert "benchmark" not in public["analytics"]


def test_cross_currency_benchmark_uses_each_declared_direct_rate() -> None:
    # Given a CNY benchmark converted through separate start and end direct pairs.
    step = _run(_usd_only_payload(), usd_only=True)
    analytics = step.document.analytics
    assert analytics is not None
    benchmark = analytics.benchmark
    assert benchmark is not None

    # Then each observation resolves its own declared pair, never an inversion.
    assert benchmark.start.fx.rate_id == "cny-usd-start"
    assert benchmark.start.fx.rate == "0.140000000000"
    assert benchmark.end.fx.rate_id == "cny-usd-end"
    assert benchmark.end.fx.rate == "0.150000000000"
    assert (benchmark.start.value_base, benchmark.end.value_base) == ("98.00", "108.15")
    assert Decimal(benchmark.start.exact_value_base) == Decimal("98.00")
    assert Decimal(benchmark.end.exact_value_base) == Decimal("108.15")

    # Then the benchmark return uses those converted levels, not local levels.
    assert benchmark.benchmark_return == "0.103571428571"
    assert benchmark.portfolio_return == "0.013513513514"
    assert benchmark.deviation == "-0.090057915058"

    # Then both direct pairs appear in the document provenance.
    rate_ids = {row.rate_id for row in analytics.provenance.fx}
    assert {"cny-usd-start", "cny-usd-end"} <= rate_ids


def _parsed_error(payload: dict[str, Any]) -> PortfolioRequestError:
    with pytest.raises(PortfolioRequestError) as caught:
        parse_portfolio_request(payload)
    return caught.value


def test_missing_end_observation_is_a_declared_error() -> None:
    payload = _three_market_payload(benchmark=_usd_benchmark())
    payload["benchmark"].pop("end")

    error = _parsed_error(payload)

    assert (error.reason, error.path) == ("invalid_field", "benchmark.end")


def test_timezone_naive_observation_is_a_declared_error() -> None:
    benchmark = _usd_benchmark()
    benchmark["start"]["observed_at"] = "2026-11-12T21:00:00"
    payload = _three_market_payload(benchmark=benchmark)

    error = _parsed_error(payload)

    assert (error.reason, error.path) == (
        "invalid_timestamp",
        "benchmark.start.observed_at",
    )


@pytest.mark.parametrize(
    ("mutate", "reason", "path"),
    [
        (
            lambda benchmark: benchmark["start"].update(currency="CNY"),
            "missing_benchmark_fx_rate",
            "benchmark.start.rate_id",
        ),
        (
            lambda benchmark: benchmark["start"].update(rate_id="cny-usd"),
            "unexpected_benchmark_fx_rate",
            "benchmark.start.rate_id",
        ),
        (
            lambda benchmark: (
                benchmark["start"].update(currency="CNY", rate_id="hkd-usd"),
                benchmark["end"].update(currency="CNY", rate_id="hkd-usd"),
            ),
            "fx_pair_mismatch",
            "benchmark.start.rate_id",
        ),
        (
            lambda benchmark: (
                benchmark["start"].update(currency="CNY", rate_id="usd-cny"),
                benchmark["end"].update(currency="CNY", rate_id="usd-cny"),
            ),
            "inverse_fx_rate_only",
            "benchmark.start.rate_id",
        ),
        (
            lambda benchmark: benchmark.update(
                start={
                    "observed_at": "2026-11-10T21:00:00+00:00",
                    "value": "100.00",
                    "currency": "USD",
                },
                end={
                    "observed_at": "2026-11-11T21:00:00+00:00",
                    "value": "101.00",
                    "currency": "USD",
                },
            ),
            "stale_benchmark_observation",
            "benchmark.end.observed_at",
        ),
        (
            lambda benchmark: benchmark.update(
                start={
                    "observed_at": "2026-11-11T21:00:00+00:00",
                    "value": "100.00",
                    "currency": "USD",
                },
                end={
                    "observed_at": "2026-11-12T21:00:00+00:00",
                    "value": "101.00",
                    "currency": "USD",
                },
            ),
            "stale_benchmark_observation",
            "benchmark.end.observed_at",
        ),
        (
            lambda benchmark: benchmark["end"].update(
                currency="CNY",
                rate_id="cny-usd",
            ),
            "benchmark_currency_mismatch",
            "benchmark.end.currency",
        ),
        (
            lambda benchmark: benchmark["end"].update(
                observed_at="2026-11-13T22:00:00+00:00"
            ),
            "future_benchmark_observation",
            "benchmark.end.observed_at",
        ),
        (
            lambda benchmark: benchmark.update(
                start={
                    "observed_at": "2026-11-13T21:00:00+00:00",
                    "value": "100.00",
                    "currency": "USD",
                },
                end={
                    "observed_at": "2026-11-12T21:00:00+00:00",
                    "value": "101.00",
                    "currency": "USD",
                },
            ),
            "invalid_benchmark_observation_order",
            "benchmark.end.observed_at",
        ),
        (
            lambda benchmark: benchmark["start"].update(value="0"),
            "invalid_benchmark_value",
            "benchmark.start.value",
        ),
    ],
)
def test_malformed_benchmark_is_a_deterministic_error(
    mutate,
    reason: str,
    path: str,
) -> None:
    payload = _three_market_payload(benchmark=_usd_benchmark())
    payload["fx_snapshots"].append(
        {
            "rate_id": "usd-cny",
            "from": "USD",
            "to": "CNY",
            "rate": "7.14",
            "as_of": "2026-11-13T11:00:00+00:00",
            "source": "caller-inverse",
        }
    )
    mutate(payload["benchmark"])

    error = _parsed_error(payload)

    assert (error.reason, error.path) == (reason, path)


def test_benchmark_rate_later_than_its_observation_is_rejected() -> None:
    payload = _usd_only_payload()
    payload["benchmark"]["start"].update(
        observed_at="2026-11-12T11:00:00+00:00",
        rate_id="cny-usd-start",
    )

    error = _parsed_error(payload)

    assert (error.reason, error.path) == ("future_fx_rate", "benchmark.start.rate_id")


def test_non_positive_benchmark_value_is_rejected_before_analytics() -> None:
    payload = _three_market_payload(benchmark=_usd_benchmark())
    payload["benchmark"]["start"]["value"] = "-1.00"

    error = _parsed_error(payload)

    assert (error.reason, error.path) == (
        "invalid_benchmark_value",
        "benchmark.start.value",
    )


def test_wire_rejects_tampered_benchmark_arithmetic() -> None:
    # Given a valid public document with a real benchmark.
    step = _run(_three_market_payload(benchmark=_usd_benchmark()))
    payload = build_success_payload(step)

    # When a deviation is changed without changing the observations or NAVs.
    tampered = json.loads(json.dumps(payload))
    tampered["analytics"]["benchmark"]["deviation"] = "0.500000000000"

    # Then the public boundary refuses the misleading success document.
    with pytest.raises(PortfolioWireError) as caught:
        build_success_payload(tampered)
    assert caught.value.reason == "benchmark_deviation_mismatch"
    assert caught.value.path == "analytics.benchmark.deviation"


def test_benchmark_result_fields_match_the_packaged_contract() -> None:
    step = _run(_three_market_payload(benchmark=_usd_benchmark()))
    payload = build_success_payload(step)
    schema = load_portfolio_contract_schema("result")

    from jsonschema import Draft202012Validator, FormatChecker

    errors = list(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(payload)
    )
    assert errors == []
