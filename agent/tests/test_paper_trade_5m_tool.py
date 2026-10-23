"""T6 gate — the public ``paper_trade_step`` surface for cn_a 5m (document leg).

The engine-only suites (T3/T4) prove matching against in-test frames.  This
suite drives the SAME public entry point the runner consumes, with the loader
injected: the document shape, the normal fill and its path-model reference,
the halted session, the frozen v1.1 document when no new field is used, the
fetch evidence carried by the returned string, the order-symbol-only 5m leg,
a provider omission, and the U6 rule that a provider fault (anything that is
not a ``ValueError`` input guard) is retryable ``PAPER_DATA_NOT_READY`` —
never a transport crash and never a halt.

The input-scope gates (symbol support, multi-day, symbol budget, BJ, loader
resolution) live in ``test_paper_trade_5m_scope``; the strategy-mode gates
(UNIVERSE declaration, order scope, 1d non-gating, path model) live in
``test_paper_trade_5m_strategy``.  The seed constants and payload builders are
shared from ``paper_trade_5m_fixtures``.

Every price is re-derived from the committed CSV fixtures by the test (see
``paper_trade_5m_fixtures.fixture_reference``), so a wrong reference inside
the engine cannot make an assertion agree with it.  Offline: no network, no
clock, no writes.
"""

from __future__ import annotations

import json
from typing import Any, Iterable, Mapping, Sequence

import pytest

from src.tools.paper_trade import tool as tool_module
from src.tools.paper_trade.schema import CANCELED_REASON_CODE
from src.tools.paper_trade.tool import PaperTradeDocument, run_paper_trade_step
from tests.paper_trade_5m_fixtures import (
    FixtureCalendar,
    FixtureLoader,
    _DAY,
    _HALTED,
    _SHA_RE,
    _SYM,
    _WITNESS,
    _payload,
    _run,
    derive_daily,
    fixture_reference,
    load_5m,
    load_5m_all,
    session_values,
)

#: The session bar the fixture actually encodes (T1 shape: 09:30 excluded).
_NORMAL_BAR = {"open": 1421.0, "high": 1422.0, "low": 1421.0, "close": 1422.0}


@pytest.mark.parametrize(
    ("path_model", "expected"),
    [("bar_median", 1421.50), ("bar_close", 1422.00)],
)
def test_normal_day_fills_exactly_at_the_recomputed_reference(path_model: str, expected: float) -> None:
    document, _ = _run(_payload(path_model=path_model))

    assert document["schema_version"] == "pt-v1.2"
    assert _SHA_RE.match(document["engine_fingerprint"])
    assert [(fill["symbol"], fill["side"], fill["qty"], fill["price"]) for fill in document["fills"]] == [
        (_SYM, "buy", 100.0, expected)
    ]
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
        (_SYM, "limit_not_marketable")
    ]
    assert document["rejected_orders"][0]["detail"] == "ref 1421.50 > limit 1.00"
    assert [(row["symbol"], row["reason_code"]) for row in document["canceled_orders"]] == [
        (_SYM, CANCELED_REASON_CODE)
    ]
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
    assert [(row["symbol"], row["reason_code"]) for row in document["rejected_orders"]] == [(_SYM, "suspended")]
    assert [(row["symbol"], row["event_type"]) for row in document["events"]] == [(_SYM, "halted")]
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
    assert [(row["symbol"], row["event_type"]) for row in document["events"]] == [(_WITNESS, "halted")]
    assert [(row["symbol"], row["reason_code"]) for row in document["rejected_orders"]] == [(_WITNESS, "suspended")]
    assert document["fills"] == []


# ── D3: a pure-valuation 5m step hashes the daily bars that produced it ──


def test_a_5m_valuation_step_without_orders_hashes_the_daily_bars() -> None:
    def valuation(day: str) -> dict[str, Any]:
        document, _ = _run(
            _payload(
                orders=[],
                from_date=day,
                to_date=day,
                account_state={
                    "cash": 1_000_000.0,
                    "positions": [{"symbol": _SYM, "qty": 100, "avg_cost": 1421.0}],
                },
            )
        )
        return document

    earlier = valuation("2026-10-16")
    later = valuation(_DAY)
    repeated = valuation(_DAY)

    assert _SHA_RE.match(earlier["engine_fingerprint"])
    assert _SHA_RE.match(later["engine_fingerprint"])
    assert earlier["engine_fingerprint"] != later["engine_fingerprint"]
    assert repeated["engine_fingerprint"] == later["engine_fingerprint"]


# ── N3: an auction-only day is a halt, not a provider omission ──


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


def test_an_auction_only_symbol_with_a_daily_bar_is_halted_not_data_not_ready() -> None:
    loader = _AuctionOnlyLoader()
    document, _ = _run(
        _payload(orders=[{"symbol": _WITNESS, "side": "buy", "qty": 100}]),
        loader=loader,
    )

    assert "status" not in document, document
    assert [(row["symbol"], row["event_type"]) for row in document["events"]] == [(_WITNESS, "halted")]
    assert [(row["symbol"], row["reason_code"]) for row in document["rejected_orders"]] == [(_WITNESS, "suspended")]
    assert document["fills"] == []
    assert not any("provider omitted" in warning for warning in document["warnings"])
