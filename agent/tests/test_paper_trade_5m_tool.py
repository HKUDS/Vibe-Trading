"""T6 gate — the public ``paper_trade_step`` surface for cn_a 5m.

The engine-only suites (T3/T4) prove matching against in-test frames.  This
suite drives the SAME public entry point the runner consumes, with the loader
injected: one ranged 5m fetch, the v1.2 document, the frozen v1.1 document
when no new field is used, the halted session, and the U6 rule that a provider
fault (anything that is not a ``ValueError`` input guard) is retryable
``PAPER_DATA_NOT_READY`` — never a transport crash and never a halt.

Every price is re-derived from the committed CSV fixtures by the test (see
``paper_trade_5m_fixtures.fixture_reference``), so a wrong reference inside
the engine cannot make an assertion agree with it.  Offline: no network, no
clock, no writes.
"""

from __future__ import annotations

import json
import re
from typing import Any, Iterable, Mapping, Sequence

import pandas as pd
import pytest

from src.config.paths import get_runtime_root
from src.tools.paper_trade import data_5m
from src.tools.paper_trade import data as data_module
from src.tools.paper_trade import tool as tool_module
from src.tools.paper_trade.schema import CANCELED_REASON_CODE
from src.tools.paper_trade.tool import PaperTradeDocument, run_paper_trade_step
from src.tools.paper_trade.wire import received_state_hash_from_payload
from tests.paper_trade_5m_fixtures import (
    FixtureCalendar,
    FixtureLoader,
    derive_daily,
    fixture_reference,
    load_5m,
    load_5m_all,
    session_values,
)

_DAY = "2026-10-20"
_HALTED = "2026-10-19"
_SYM = "600519.SH"
_WITNESS = "000001.SZ"
_THIRD = "600000.SH"
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_FEES = {
    "commission_rate": 0.00025,
    "commission_min": 5.0,
    "stamp_tax_sell": 0.0005,
    "transfer_fee": 0.00001,
}
#: The session bar the fixture actually encodes (T1 shape: 09:30 excluded).
_NORMAL_BAR = {"open": 1421.0, "high": 1422.0, "low": 1421.0, "close": 1422.0}


def _payload(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "account_id": "pa_5m_tool",
        "market": "cn_a",
        "account_state": {"cash": 1_000_000.0, "positions": []},
        "orders": [{"symbol": _SYM, "side": "buy", "qty": 100}],
        "from_date": _DAY,
        "to_date": _DAY,
        "fee_model": dict(_FEES),
        "interval": "5m",
    }
    base.update(overrides)
    return base


def _run(payload: dict[str, Any], *, loader: Any = None, calendar: Any = None):
    loader = FixtureLoader() if loader is None else loader
    calendar = FixtureCalendar((payload["to_date"],)) if calendar is None else calendar
    document = run_paper_trade_step(
        payload,
        loader=loader,
        ch_client=None,
        calendar_client=calendar,
        limits_client=None,
    )
    return json.loads(document), loader


def _strategy_payload(path: str, **overrides: Any) -> dict[str, Any]:
    payload = _payload(**overrides)
    payload.pop("orders")
    payload["strategy_path"] = path
    return payload


def _install_strategy(name: str, source: str) -> str:
    # The path policy only admits <runtime_root>/strategies; the conftest HOME
    # sandbox makes that a per-session temp dir.
    root = get_runtime_root() / "strategies"
    root.mkdir(parents=True, exist_ok=True)
    path = root / name
    path.write_text(source, encoding="utf-8")
    return str(path)


def _strategy_source(*universe: str) -> str:
    """A minimal SignalEngine selling each target symbol held at call start.

    With ``universe`` it declares UNIVERSE and orders exactly those symbols;
    without it, orders ``ctx.symbols`` (the served universe fallback).
    """
    declaration = f"UNIVERSE = {universe!r}\n\n" if universe else ""
    target = repr(universe) if universe else "ctx.symbols"
    return (
        declaration
        + "class SignalEngine:\n"
        + "\n"
        + "    def generate_signals(self, ctx, trade_date):\n"
        + "        held = {position.symbol: position.qty\n"
        + "                for position in ctx.account_state.positions}\n"
        + "        return [\n"
        + '            {"symbol": symbol, "side": "sell", "qty": held[symbol]}\n'
        + f"            for symbol in {target} if symbol in held\n"
        + "        ]\n"
    )


def _outside_universe_source(declared: tuple[str, ...], target: str) -> str:
    """Declare one 5m UNIVERSE but order a held symbol, possibly outside it."""
    return (
        f"UNIVERSE = {declared!r}\n\n"
        "class SignalEngine:\n"
        "\n"
        "    def generate_signals(self, ctx, trade_date):\n"
        "        held = {position.symbol: position.qty\n"
        "                for position in ctx.account_state.positions}\n"
        f"        if {target!r} not in held:\n"
        "            return []\n"
        f"        return [{{'symbol': {target!r}, 'side': 'sell', 'qty': held[{target!r}]}}]\n"
    )


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


class _AuctionOnlyLoader(FixtureLoader):
    """Witness has a daily bar and, on the 5m leg, only the 09:30 print."""

    def fetch(
        self,
        codes: Iterable[str],
        start_date: str,
        end_date: str,
        *,
        interval: str = "1D",
        fields: Sequence[str] | None = None,
    ) -> Mapping[str, Any]:
        ordered = tuple(str(code) for code in codes)
        kind = str(interval)
        self.calls.append((ordered, start_date, end_date, kind))
        five_minute = kind.lower() in ("5m", "5min", "5")
        served: dict[str, Any] = {}
        for code in ordered:
            source = _SYM if code == _WITNESS else code
            if five_minute:
                frame = load_5m_all(source)
                frame = frame[frame.index.strftime("%H:%M") == "09:30"]
            else:
                frame = derive_daily(source)
            if not frame.empty:
                served[code] = frame.copy()
        return served


@pytest.mark.parametrize(
    ("path_model", "expected"),
    [("bar_median", 1421.50), ("bar_close", 1422.00)],
)
def test_normal_day_fills_exactly_at_the_recomputed_reference(
    path_model: str, expected: float
) -> None:
    document, _ = _run(_payload(path_model=path_model))

    assert document["schema_version"] == "pt-v1.2"
    assert _SHA_RE.match(document["engine_fingerprint"])
    assert [(fill["symbol"], fill["side"], fill["qty"], fill["price"]) for fill in document["fills"]] == [
        (_SYM, "buy", 100.0, expected)]
    assert document["fills"][0]["price"] == float(fixture_reference(_SYM, _DAY, path_model))
    assert document["canceled_orders"] == []
    assert document["events"] == []
    assert document["rejected_orders"] == []
    assert document["warnings"] == []
    assert document["data_provenance"]["source"] == "fixture"


def test_the_two_path_models_produce_different_prices_and_fingerprints() -> None:
    median, _ = _run(_payload(path_model="bar_median"))
    close, _ = _run(_payload(path_model="bar_close"))

    assert median["fills"][0]["price"] == 1421.50
    assert close["fills"][0]["price"] == 1422.00
    assert median["engine_fingerprint"] != close["engine_fingerprint"]


def test_non_marketable_limit_is_rejected_and_emergency_canceled() -> None:
    document, _ = _run(_payload(orders=[{"symbol": _SYM, "side": "buy", "qty": 100, "limit": 1.0}]))

    assert document["fills"] == []
    assert [(row["symbol"], row["reason_code"]) for row in document["rejected_orders"]] == [
        (_SYM, "limit_not_marketable")]
    assert document["rejected_orders"][0]["detail"] == "ref 1421.50 > limit 1.00"
    assert [(row["symbol"], row["reason_code"]) for row in document["canceled_orders"]] == [
        (_SYM, CANCELED_REASON_CODE)]
    assert document["events"] == []


def test_halted_session_fills_nothing_and_reports_only_halted() -> None:
    document, _ = _run(
        _payload(
            from_date=_HALTED,
            to_date=_HALTED,
            account_state={
                "cash": 1_000_000.0,
                "positions": [
                    {"symbol": _SYM, "qty": 100, "avg_cost": 1421.0},
                    {"symbol": _WITNESS, "qty": 1000, "avg_cost": 10.0},
                ],
            },
        )
    )

    assert document["fills"] == []
    assert [(row["symbol"], row["reason_code"]) for row in document["rejected_orders"]] == [
        (_SYM, "suspended")]
    assert [(row["symbol"], row["event_type"]) for row in document["events"]] == [
        (_SYM, "halted")]
    assert len(document["canceled_orders"]) == 1
    assert document["end_state"]["cash"] == 1_000_000.0
    assert {row["symbol"]: row["qty"] for row in document["end_state"]["positions"]} == {
        _SYM: 100.0,
        _WITNESS: 1000.0,
    }


def test_a_v1_1_call_keeps_the_frozen_document() -> None:
    payload = _payload()
    for key in ("interval", "path_model", "fill_model", "session"):
        payload.pop(key, None)

    document, _ = _run(payload)

    assert document["schema_version"] == "pt-v1.1"
    assert "engine_fingerprint" not in document
    assert "canceled_orders" not in document
    assert "events" not in document
    assert document["fills"][0]["price"] == session_values(load_5m(_SYM, _DAY))["close"]


def test_fixture_loader_serves_both_legs_and_the_step_issues_one_5m_call() -> None:
    loader = FixtureLoader()
    document, same = _run(_payload(), loader=loader)

    assert document["fills"], document
    assert len(same.five_minute_calls()) == 1
    assert same.five_minute_calls()[0] == ((_SYM,), _DAY, "2026-10-21", "5m")
    assert [call for call in same.calls if call[3] == "1D"]

    raw = load_5m(_SYM, _DAY)
    assert len(raw) == 49
    daily = derive_daily(_SYM)
    assert list(daily["close"]) == [1420.0, 1422.0]
    assert _NORMAL_BAR == {key: session_values(raw)[key] for key in _NORMAL_BAR}


@pytest.mark.parametrize("fault", [RuntimeError("permission denied"), OSError("network down")])
def test_a_provider_fault_is_in_band_data_not_ready(fault: Exception, monkeypatch) -> None:
    def boom(*args: Any, **kwargs: Any) -> Any:
        raise fault

    monkeypatch.setattr(tool_module.data, "fetch_market_data", boom)

    document, _ = _run(_payload())

    assert document["status"] == "error"
    assert document["code"] == "PAPER_DATA_NOT_READY"
    assert type(fault).__name__ in document["message"]
    assert "halted" not in document["message"]


def test_a_value_error_stays_a_non_retryable_invalid_request(monkeypatch) -> None:
    def boom(*args: Any, **kwargs: Any) -> Any:
        raise ValueError("unknown market for paper data fetch: 'xx'")

    monkeypatch.setattr(tool_module.data, "fetch_market_data", boom)

    document, _ = _run(_payload())

    assert document["status"] == "error"
    assert document["code"] == "INVALID_REQUEST"
    assert "unknown market" in document["message"]


def test_the_document_is_a_str_that_carries_the_fetch_evidence() -> None:
    loader = FixtureLoader()
    raw = run_paper_trade_step(
        _payload(),
        loader=loader,
        ch_client=None,
        calendar_client=FixtureCalendar((_DAY,)),
        limits_client=None,
    )

    assert isinstance(raw, str)
    assert isinstance(raw, PaperTradeDocument)
    assert raw.market_data is not None
    assert raw.market_data.interval == "5m"
    assert raw.market_data.data[_SYM].session_bar is not None
    assert json.loads(raw)["schema_version"] == "pt-v1.2"
    assert str(raw) == raw


class _NoFiveMinuteLoader(FixtureLoader):
    """Daily leg works; the provider yields no 5m rows (quota/permission)."""

    def fetch(self, codes, start_date, end_date, *, interval="1D", fields=None):
        if str(interval).lower() in ("5m", "5min", "5"):
            self.calls.append((tuple(str(code) for code in codes), start_date, end_date, str(interval)))
            return {}
        return super().fetch(codes, start_date, end_date, interval=interval, fields=fields)


# ── F2/a: the 5m leg covers the ORDER symbols only ──


def test_positions_only_5m_step_issues_no_5m_fetch_and_advances_nav() -> None:
    loader = FixtureLoader()
    document, _ = _run(
        _payload(
            orders=[],
            account_state={
                "cash": 1_000_000.0,
                "positions": [{"symbol": _SYM, "qty": 100, "avg_cost": 1421.0}],
            },
        ),
        loader=loader,
    )

    assert document["schema_version"] == "pt-v1.2"
    assert document["fills"] == []
    assert document["events"] == []
    assert document["canceled_orders"] == []
    assert loader.five_minute_calls() == []
    assert document["nav_series"][-1]["nav"] == 1_142_200.0


def test_only_the_order_symbol_is_requested_from_the_5m_leg() -> None:
    loader = FixtureLoader()
    document, _ = _run(
        _payload(
            account_state={
                "cash": 1_000_000.0,
                "positions": [{"symbol": _WITNESS, "qty": 1000, "avg_cost": 10.0}],
            },
        ),
        loader=loader,
    )

    assert [fill["symbol"] for fill in document["fills"]] == [_SYM]
    assert len(loader.five_minute_calls()) == 1
    assert loader.five_minute_calls()[0][0] == (_SYM,)
    daily_codes = next(call[0] for call in loader.calls if call[3] == "1D")
    assert set(daily_codes) == {_SYM, _WITNESS}


def test_a_provider_omitted_5m_leg_names_the_symbol_and_stays_retryable() -> None:
    loader = _NoFiveMinuteLoader()
    document, _ = _run(_payload(), loader=loader)

    assert document["status"] == "error"
    assert document["code"] == "PAPER_DATA_NOT_READY"
    assert _SYM in document["message"]
    assert "provider omitted the 5m leg" in document["message"]
    assert "retry after the quota window" in document["message"]
    assert "halted" not in document["message"]
    assert "inconsistent" not in document["message"]
    assert len(loader.five_minute_calls()) == 1


def test_an_order_symbol_with_no_bar_at_all_is_halted_not_data_not_ready() -> None:
    document, _ = _run(
        _payload(
            orders=[{"symbol": _WITNESS, "side": "buy", "qty": 1000}],
            account_state={
                "cash": 1_000_000.0,
                "positions": [{"symbol": _SYM, "qty": 100, "avg_cost": 1421.0}],
            },
        )
    )

    assert "status" not in document
    assert [(row["symbol"], row["event_type"]) for row in document["events"]] == [
        (_WITNESS, "halted")]
    assert [(row["symbol"], row["reason_code"]) for row in document["rejected_orders"]] == [
        (_WITNESS, "suspended")]
    assert document["fills"] == []


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


# ── N1: 5m strategy mode requires an explicit UNIVERSE ──


def test_a_5m_strategy_without_a_universe_is_refused_before_any_fetch() -> None:
    path = _install_strategy("no_universe_5m.py", _strategy_source())
    loader = FixtureLoader()
    document, _ = _run(
        _strategy_payload(
            path,
            account_state={
                "cash": 1_000_000.0,
                "positions": [{"symbol": _SYM, "qty": 100, "avg_cost": 1421.0}],
            },
        ),
        loader=loader,
    )

    assert document["status"] == "error"
    assert document["code"] == "INVALID_REQUEST"
    assert "explicit non-empty UNIVERSE" in document["message"]
    assert "rejected_orders" not in document
    assert "suspended" not in json.dumps(document)
    assert loader.calls == []


def test_a_5m_strategy_with_a_universe_fills_and_leaves_an_outside_position_alone() -> None:
    path = _install_strategy("universe_5m.py", _strategy_source(_SYM))
    loader = FixtureLoader()
    document, _ = _run(
        _strategy_payload(
            path,
            account_state={
                "cash": 1_000_000.0,
                "positions": [
                    {"symbol": _SYM, "qty": 100, "avg_cost": 1421.0},
                    {"symbol": _WITNESS, "qty": 1000, "avg_cost": 10.0},
                ],
            },
        ),
        loader=loader,
    )

    assert "status" not in document
    assert [(fill["symbol"], fill["side"], fill["qty"], fill["price"])
            for fill in document["fills"]] == [(_SYM, "sell", 100.0, 1421.50)]
    assert document["events"] == []
    assert document["rejected_orders"] == []
    assert loader.five_minute_calls()[0][0] == (_SYM,)
    witness = next(
        position for position in document["end_state"]["positions"]
        if position["symbol"] == _WITNESS)
    assert (witness["qty"], witness["avg_cost"]) == (1000.0, 10.0)


def test_a_1d_strategy_without_a_universe_keeps_running() -> None:
    path = _install_strategy("no_universe_1d.py", _strategy_source())
    payload = _strategy_payload(
        path,
        account_state={
            "cash": 1_000_000.0,
            "positions": [{"symbol": _SYM, "qty": 100, "avg_cost": 1421.0}],
        },
    )
    payload.pop("interval")

    document, _ = _run(payload)

    assert document["schema_version"] == "pt-v1.1"
    assert [(fill["symbol"], fill["side"], fill["qty"], fill["price"])
            for fill in document["fills"]] == [(_SYM, "sell", 100.0, 1422.0)]


# ── N1-B: a 5m strategy may not order outside its declared UNIVERSE ──


def test_a_5m_strategy_order_outside_its_universe_is_refused_not_suspended() -> None:
    path = _install_strategy(
        "outside_order_5m.py", _outside_universe_source((_SYM,), _WITNESS))
    payload = _strategy_payload(
        path,
        account_state={
            "cash": 1_000_000.0,
            "positions": [
                {"symbol": _SYM, "qty": 100, "avg_cost": 1421.0},
                {"symbol": _WITNESS, "qty": 1000, "avg_cost": 10.0},
            ],
        },
    )
    loader = FixtureLoader()
    document, _ = _run(payload, loader=loader)

    assert document["status"] == "error"
    assert document["code"] == "INVALID_REQUEST"
    assert _WITNESS in document["message"]
    assert "outside the 5m UNIVERSE" in document["message"]
    assert _SYM in document["message"]
    assert document.get("fills", []) == []
    assert document.get("rejected_orders", []) == []
    assert "suspended" not in json.dumps(document)
    assert "end_state" not in document
    assert document["received_state_hash"] == received_state_hash_from_payload(payload)
    assert loader.five_minute_calls()[0][0] == (_SYM,)


def test_a_5m_strategy_order_inside_its_universe_still_fills() -> None:
    path = _install_strategy(
        "inside_order_5m.py", _outside_universe_source((_SYM,), _SYM))
    document, _ = _run(
        _strategy_payload(
            path,
            account_state={
                "cash": 1_000_000.0,
                "positions": [{"symbol": _SYM, "qty": 100, "avg_cost": 1421.0}],
            },
        )
    )

    assert "status" not in document
    assert [(fill["symbol"], fill["side"], fill["qty"], fill["price"])
            for fill in document["fills"]] == [(_SYM, "sell", 100.0, 1421.50)]
    assert document["rejected_orders"] == []
    assert document["events"] == []


def test_a_1d_strategy_order_outside_its_universe_is_not_gated() -> None:
    path = _install_strategy(
        "outside_order_1d.py", _outside_universe_source((_SYM,), _WITNESS))
    payload = _strategy_payload(
        path,
        account_state={
            "cash": 1_000_000.0,
            "positions": [{"symbol": _WITNESS, "qty": 1000, "avg_cost": 10.0}],
        },
    )
    payload.pop("interval")
    loader = FixtureLoader()
    document, _ = _run(payload, loader=loader)

    assert document["schema_version"] == "pt-v1.1"
    assert "status" not in document
    assert document["fills"] == []
    assert [(row["symbol"], row["reason_code"]) for row in document["rejected_orders"]] == [
        (_WITNESS, "suspended")]
    assert loader.five_minute_calls() == []


# ── N2: the measured stk_mins budget caps one 5m step at one symbol ──


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


# ── D3: a pure-valuation 5m step hashes the daily bars that produced it ──


def test_a_5m_valuation_step_without_orders_hashes_the_daily_bars() -> None:
    def valuation(day: str) -> dict[str, Any]:
        document, _ = _run(_payload(
            orders=[],
            from_date=day,
            to_date=day,
            account_state={
                "cash": 1_000_000.0,
                "positions": [{"symbol": _SYM, "qty": 100, "avg_cost": 1421.0}],
            },
        ))
        return document

    earlier = valuation("2026-10-16")
    later = valuation(_DAY)
    repeated = valuation(_DAY)

    assert _SHA_RE.match(earlier["engine_fingerprint"])
    assert _SHA_RE.match(later["engine_fingerprint"])
    assert earlier["engine_fingerprint"] != later["engine_fingerprint"]
    assert repeated["engine_fingerprint"] == later["engine_fingerprint"]


# ── N3: an auction-only day is a halt, not a provider omission ──


def test_an_auction_only_symbol_with_a_daily_bar_is_halted_not_data_not_ready() -> None:
    loader = _AuctionOnlyLoader()
    document, _ = _run(
        _payload(orders=[{"symbol": _WITNESS, "side": "buy", "qty": 100}]),
        loader=loader,
    )

    assert "status" not in document, document
    assert [(row["symbol"], row["event_type"]) for row in document["events"]] == [
        (_WITNESS, "halted")]
    assert [(row["symbol"], row["reason_code"]) for row in document["rejected_orders"]] == [
        (_WITNESS, "suspended")]
    assert document["fills"] == []
    assert not any("provider omitted" in warning for warning in document["warnings"])


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


# ── The strategy path honours the declared reference-price model ──


def test_a_5m_strategy_honours_the_declared_path_model() -> None:
    path = _install_strategy("path_model_5m.py", _strategy_source(_SYM))
    account_state = {
        "cash": 1_000_000.0,
        "positions": [{"symbol": _SYM, "qty": 100, "avg_cost": 1421.0}],
    }

    median_document, _ = _run(_strategy_payload(
        path, account_state=account_state, path_model="bar_median"))
    close_document, _ = _run(_strategy_payload(
        path, account_state=account_state, path_model="bar_close"))

    assert median_document["fills"][0]["price"] == 1421.50
    assert close_document["fills"][0]["price"] == 1422.00
    assert median_document["engine_fingerprint"] != close_document["engine_fingerprint"]
