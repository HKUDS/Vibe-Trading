"""T6 gate — the 5m input-scope gates of the public ``paper_trade_step``.

Everything here is refused (or resolved) BEFORE any provider work, so each
test asserts the in-band error shape and that the loader saw no call at all:
which cn_a symbols the 5m leg supports, one trading day per 5m step, the
measured ``stk_mins`` budget of one order symbol per step, the unmeasured BJ
leg, the 5m loader resolution (a daily-only chain cannot serve 5m), the
calendar snapshot, and a malformed provider payload.

Document shape, fills, halts and provider faults live in
``test_paper_trade_5m_tool``; UNIVERSE and order-scope gates live in
``test_paper_trade_5m_strategy``.  Seed constants and payload builders are
shared from ``paper_trade_5m_fixtures``.  Offline: no network, no clock, no
writes.
"""

from __future__ import annotations

import json
from typing import Any, Iterable, Mapping, Sequence

import pandas as pd
import pytest

from src.tools.paper_trade import data as data_module
from src.tools.paper_trade import data_5m
from src.tools.paper_trade import tool as tool_module
from src.tools.paper_trade.tool import run_paper_trade_step
from tests.paper_trade_5m_fixtures import (
    FixtureCalendar,
    FixtureLoader,
    _DAY,
    _HALTED,
    _SYM,
    _THIRD,
    _WITNESS,
    _install_strategy,
    _payload,
    _run,
    _strategy_payload,
    _strategy_source,
)


# ── F2/b: unsupported 5m instruments are refused before any fetch ──


@pytest.mark.parametrize("symbol", ["600519.SH", "000001.SZ", "300750.SZ", "688981.SH"])
def test_supported_five_minute_symbols(symbol: str) -> None:
    assert data_5m.is_supported_five_minute_symbol(symbol) is True


@pytest.mark.parametrize(
    "symbol", ["510300.SH", "159915.SZ", "000001.SH", "399001.SZ", "00700.HK", "830799.BJ"])
def test_unsupported_five_minute_symbols(symbol: str) -> None:
    assert data_5m.is_supported_five_minute_symbol(symbol) is False


@pytest.mark.parametrize(
    "symbol",
    ["510300.SH", "159915.SZ", "000001.SH", "399001.SZ", "00700.HK", "830799.BJ"])
def test_an_unsupported_5m_instrument_is_an_in_band_refusal_before_fetch(symbol: str) -> None:
    loader = FixtureLoader()
    document, _ = _run(
        _payload(orders=[{"symbol": symbol, "side": "buy", "qty": 100}]),
        loader=loader,
    )

    assert document["status"] == "error"
    assert document["code"] == "INVALID_REQUEST"
    assert symbol in document["message"]
    assert loader.calls == []


# ── F3: one trading day per 5m step ──


def test_5m_multi_day_is_an_in_band_refusal_before_fetch() -> None:
    loader = FixtureLoader()
    document, _ = _run(_payload(from_date=_HALTED, to_date=_DAY), loader=loader)

    assert document["status"] == "error"
    assert document["code"] == "INVALID_REQUEST"
    assert "interval 5m supports one trading day per step" in document["message"]
    assert loader.calls == []


def test_daily_multi_day_keeps_the_existing_orders_mode_gate() -> None:
    payload = _payload(from_date=_HALTED, to_date=_DAY)
    payload.pop("interval")

    document, _ = _run(payload)

    assert document["status"] == "error"
    assert document["code"] == "INVALID_REQUEST"
    assert "orders mode requires from_date == to_date" in document["message"]


# ── N2: the measured stk_mins budget caps one 5m step at one symbol ──


class _RateLimitedLoader(FixtureLoader):
    """The measured provider: a second 5m call in one step is refused."""

    def fetch(
        self,
        codes: Iterable[str],
        start_date: str,
        end_date: str,
        *,
        interval: str = "1D",
        fields: Sequence[str] | None = None,
    ) -> Mapping[str, Any]:
        if str(interval).lower() in ("5m", "5min", "5") and self.five_minute_calls():
            self.calls.append(
                (tuple(str(code) for code in codes), start_date, end_date, str(interval)))
            raise RuntimeError("stk_mins: 1 call/minute budget exhausted")
        return super().fetch(codes, start_date, end_date, interval=interval, fields=fields)


def test_three_5m_order_symbols_are_refused_before_any_fetch() -> None:
    loader = FixtureLoader()
    document, _ = _run(
        _payload(orders=[
            {"symbol": _SYM, "side": "buy", "qty": 100},
            {"symbol": _WITNESS, "side": "buy", "qty": 1000},
            {"symbol": _THIRD, "side": "buy", "qty": 100},
        ]),
        loader=loader,
    )

    assert document["status"] == "error"
    assert document["code"] == "INVALID_REQUEST"
    assert "at most 1 symbol per step" in document["message"]
    assert "received 3" in document["message"]
    for symbol in (_SYM, _WITNESS, _THIRD):
        assert symbol in document["message"]
    assert loader.calls == []


def test_two_5m_order_symbols_are_refused_before_any_fetch() -> None:
    loader = FixtureLoader()
    document, _ = _run(
        _payload(orders=[
            {"symbol": _SYM, "side": "buy", "qty": 100},
            {"symbol": _THIRD, "side": "buy", "qty": 100},
        ]),
        loader=loader,
    )

    assert document["status"] == "error"
    assert document["code"] == "INVALID_REQUEST"
    assert "at most 1 symbol per step" in document["message"]
    assert "1 call/minute, 1/hour, 2/day" in document["message"]
    assert "received 2" in document["message"]
    for symbol in (_SYM, _THIRD):
        assert symbol in document["message"]
    assert loader.calls == []


def test_one_5m_order_symbol_issues_exactly_one_provider_call() -> None:
    loader = _RateLimitedLoader()
    document, _ = _run(_payload(), loader=loader)

    assert [(fill["symbol"], fill["price"]) for fill in document["fills"]] == [
        (_SYM, 1421.50)]
    assert len(loader.five_minute_calls()) == 1
    assert loader.five_minute_calls()[0][0] == (_SYM,)


def test_a_5m_strategy_universe_over_the_budget_is_refused_before_any_fetch() -> None:
    path = _install_strategy(
        "wide_universe_5m.py", _strategy_source(_SYM, _WITNESS, _THIRD))
    loader = FixtureLoader()
    document, _ = _run(_strategy_payload(path), loader=loader)

    assert document["status"] == "error"
    assert document["code"] == "INVALID_REQUEST"
    assert "at most 1 symbol per step" in document["message"]
    assert "received 3" in document["message"]
    assert loader.calls == []


# ── N7: BJ 5m is unmeasured and refused for P0 ──


def test_bj_5m_is_refused_until_the_leg_is_measured() -> None:
    loader = FixtureLoader()
    document, _ = _run(
        _payload(orders=[{"symbol": "830799.BJ", "side": "buy", "qty": 100}]),
        loader=loader,
    )

    assert document["status"] == "error"
    assert document["code"] == "INVALID_REQUEST"
    assert "830799.BJ" in document["message"]
    assert "BJ 4xx" not in document["message"]
    assert loader.calls == []


# ── The 5m leg resolves its own loader; the daily chain cannot serve it ──


class _DailyOnlyLoader:
    """The shape of the a_share daily chain head (``TencentRawLoader``)."""

    name = "tencent_raw"

    def is_available(self) -> bool:
        return True

    def fetch(self, codes, start_date, end_date, *, interval="1D", fields=None):
        if interval != "1D":
            raise ValueError("Paper execution requires daily bars")
        return {}


def test_a_daily_only_loader_is_reported_as_a_5m_fetch_failure() -> None:
    document, _ = _run(_payload(), loader=_DailyOnlyLoader())

    assert document["status"] == "error"
    assert document["code"] == "PAPER_DATA_NOT_READY"
    assert "5m fetch" in document["message"]
    assert "tencent_raw" in document["message"]
    assert "provider omitted" not in document["message"]


def test_a_missing_5m_loader_names_the_loader_not_the_provider(monkeypatch) -> None:
    monkeypatch.setattr(data_module, "_resolve_five_minute_loader", lambda loader: None)

    result = data_module.fetch_market_data(
        "cn_a", (_SYM,), _DAY, _DAY,
        loader=FixtureLoader(), ch_client=None, interval="5m",
        five_minute_symbols=(_SYM,),
    )
    verdict = data_module.assess_readiness(result, _DAY)

    assert verdict.ready is False
    assert verdict.code == "PAPER_DATA_NOT_READY"
    assert "no available 5m loader" in (verdict.message or "")
    assert "provider omitted" not in (verdict.message or "")


def test_auto_resolution_uses_the_stk_mins_loader_not_the_daily_chain(monkeypatch) -> None:
    import backtest.loaders.tushare as tushare_loader

    class _FakeTushare:
        name = "tushare"

        def is_available(self) -> bool:
            return True

    monkeypatch.setattr(tushare_loader, "DataLoader", _FakeTushare)

    assert isinstance(data_module._resolve_five_minute_loader(data_module._AUTO), _FakeTushare)


def test_auto_resolution_refuses_when_no_5m_loader_is_configured(monkeypatch) -> None:
    import backtest.loaders.tushare as tushare_loader

    def _unavailable():
        raise RuntimeError("TUSHARE_TOKEN is not configured")

    monkeypatch.setattr(tushare_loader, "DataLoader", _unavailable)

    assert data_module._resolve_five_minute_loader(data_module._AUTO) is None


# ── The calendar is snapshotted once and that snapshot reaches the engine ──


def test_the_calendar_is_snapshotted_once_and_passed_to_the_engine(monkeypatch) -> None:
    class _CountingConnector:
        def __init__(self) -> None:
            self.calendar_reads = 0

        def query(self, sql, *args, **kwargs):
            return pd.DataFrame()

        def get_trade_calendar(self, start_date, end_date):
            self.calendar_reads += 1
            return FixtureCalendar((end_date,)).get_trade_calendar(start_date, end_date)

    connector = _CountingConnector()
    builds: list[int] = []

    def _build():
        builds.append(1)
        return connector

    monkeypatch.setattr(tool_module, "_default_cn_a_connector", _build)

    document = json.loads(
        run_paper_trade_step(
            _payload(),
            loader=FixtureLoader(),
            ch_client=None,
            calendar_client=tool_module._AUTO,
            limits_client=None,
        )
    )

    assert "status" not in document, document
    assert len(builds) == 1
    assert connector.calendar_reads == 1


# ── A malformed provider payload is data-not-ready, not a caller error ──


class _MalformedPayloadLoader(FixtureLoader):
    def fetch(self, codes, start_date, end_date, *, interval="1D", fields=None):
        if interval == "5m":
            return {
                codes[0]: pd.DataFrame({
                    "trade_time": ["not-a-timestamp"],
                    "open": [1.0], "high": [1.0], "low": [1.0],
                    "close": [1.0], "vol": [1.0],
                })
            }
        return super().fetch(codes, start_date, end_date, interval=interval, fields=fields)


def test_a_malformed_5m_payload_is_data_not_ready_not_invalid_request() -> None:
    document, _ = _run(_payload(), loader=_MalformedPayloadLoader())

    assert document["status"] == "error"
    assert document["code"] == "PAPER_DATA_NOT_READY", document
    assert "could not be parsed" in document["message"]
