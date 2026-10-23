"""T6 gate — determinism, ledger invariants and fixture integrity for 5m.

What this suite pins, all through the stateless tool surface:

* the same input produces BYTE-identical JSON on two independent runs, and
  two different sessions produce different ``engine_fingerprint`` values
  (the fingerprint folds in bar evidence, D3);
* cash and position conservation under the engine's exact 2dp arithmetic,
  every fill fee non-negative;
* every fill price equals the reference recomputed here from the CSV;
* every rejected order carries a frozen reason code and, in 5m mode, exactly
  one emergency-cancel row;
* a halted session leaves the ledger and the marks alone;
* an auction-window label is excluded from the session bar and reported;
* the fixture manifest indexes every committed file and matches its bytes.

The persistent runner/adapter suite lives with the persistence layer on the
follow-up ``paper-trade-v12-persistence`` branch.

Offline: fixtures via ``paper_trade_5m_fixtures``, no network.
"""

from __future__ import annotations

import hashlib
import json
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import pandas as pd

from src.tools.paper_trade.schema import CANCELED_REASON_CODE, REASON_CODES
from src.tools.paper_trade.tool import run_paper_trade_step
from tests.paper_trade_5m_fixtures import (
    FIXTURE_ROOT,
    FixtureCalendar,
    FixtureLoader,
    fixture_files,
    fixture_manifest,
    fixture_reference,
    load_5m,
)

_DAY = "2026-10-20"
_PRIOR = "2026-10-16"
_HALTED = "2026-10-19"
_SYM = "600519.SH"
_WITNESS = "000001.SZ"
_CENT = Decimal("0.01")
_FEES = {
    "commission_rate": 0.00025,
    "commission_min": 5.0,
    "stamp_tax_sell": 0.0005,
    "transfer_fee": 0.00001,
}


def _payload(day: str = _DAY, **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "account_id": "pa_5m_golden",
        "market": "cn_a",
        "account_state": {"cash": 1_000_000.0, "positions": []},
        "orders": [{"symbol": _SYM, "side": "buy", "qty": 100}],
        "from_date": day,
        "to_date": day,
        "fee_model": dict(_FEES),
        "interval": "5m",
    }
    base.update(overrides)
    return base


def _run(payload: dict[str, Any], *, loader: Any = None) -> tuple[str, dict[str, Any]]:
    loader = FixtureLoader() if loader is None else loader
    raw = run_paper_trade_step(
        payload,
        loader=loader,
        ch_client=None,
        calendar_client=FixtureCalendar((payload["to_date"],)),
        limits_client=None,
    )
    return raw, json.loads(raw)


def _money(value: Any) -> Decimal:
    return Decimal(str(value))


def _notional(fill: dict[str, Any]) -> Decimal:
    return (_money(fill["qty"]) * _money(fill["price"])).quantize(_CENT, rounding=ROUND_HALF_UP)


def test_the_same_input_yields_byte_identical_documents() -> None:
    first, document = _run(_payload())
    second, _ = _run(_payload())

    assert isinstance(first, str)
    assert first == second
    assert hashlib.sha256(first.encode("utf-8")).hexdigest() == hashlib.sha256(second.encode("utf-8")).hexdigest()
    assert document["engine_fingerprint"] == json.loads(second)["engine_fingerprint"]
    assert len(document["fills"]) == 1


def test_two_sessions_have_different_engine_fingerprints() -> None:
    _, prior = _run(_payload(_PRIOR))
    _, today = _run(_payload(_DAY))

    assert prior["engine_fingerprint"] != today["engine_fingerprint"]
    assert prior["fills"][0]["price"] == 1419.50
    assert today["fills"][0]["price"] == 1421.50


def test_cash_and_positions_are_conserved_and_every_fee_is_non_negative() -> None:
    orders = [
        {"symbol": _SYM, "side": "buy", "qty": 100},
        {"symbol": _SYM, "side": "buy", "qty": 200},
        {"symbol": _SYM, "side": "sell", "qty": 100},
        {"symbol": _SYM, "side": "buy", "qty": 150},
        {"symbol": _SYM, "side": "buy", "qty": 100, "limit": 1.0},
        {"symbol": _SYM, "side": "sell", "qty": 10_000},
    ]
    start_cash = Decimal("1000000.00")
    _, document = _run(
        _payload(
            orders=orders,
            account_state={
                "cash": 1_000_000.0,
                "positions": [{"symbol": _SYM, "qty": 200, "avg_cost": 1420.0}],
            },
        )
    )

    cash = start_cash
    bought = Decimal("0")
    sold = Decimal("0")
    for fill in document["fills"]:
        fee = _money(fill["fee"])
        assert fee >= 0
        if fill["side"] == "buy":
            cash -= _notional(fill) + fee
            bought += _money(fill["qty"])
        else:
            cash += _notional(fill) - fee
            sold += _money(fill["qty"])

    assert _money(document["end_state"]["cash"]) == cash
    held = {row["symbol"]: _money(row["qty"]) for row in document["end_state"]["positions"]}
    assert held == {_SYM: Decimal("200") + bought - sold} == {_SYM: Decimal("400")}
    assert [fill["side"] for fill in document["fills"]] == ["buy", "buy", "sell"]
    assert len(document["rejected_orders"]) == 3


def test_every_fill_price_is_the_reference_recomputed_from_the_csv() -> None:
    for path_model in ("bar_median", "bar_close"):
        _, document = _run(
            _payload(
                path_model=path_model,
                orders=[
                    {"symbol": _SYM, "side": "buy", "qty": 100},
                    {"symbol": _SYM, "side": "buy", "qty": 200},
                ],
            )
        )
        expected = float(fixture_reference(_SYM, _DAY, path_model))
        assert [fill["price"] for fill in document["fills"]] == [expected, expected]


def test_every_rejection_is_frozen_and_emergency_canceled() -> None:
    orders = [
        {"symbol": _SYM, "side": "buy", "qty": 150},
        {"symbol": _SYM, "side": "buy", "qty": 100, "limit": 1.0},
        {"symbol": _SYM, "side": "sell", "qty": 100},
        {"symbol": _SYM, "side": "sell", "qty": 10_000},
    ]
    _, document = _run(_payload(orders=orders))

    assert document["fills"] == []
    assert len(document["rejected_orders"]) == len(orders)
    assert {row["reason_code"] for row in document["rejected_orders"]} == {
        "lot_size",
        "limit_not_marketable",
        "insufficient_position",
    }
    for row in document["rejected_orders"]:
        assert row["reason_code"] in REASON_CODES
        assert row["reason_code"]
    assert [(row["symbol"], row["side"], row["qty"]) for row in document["canceled_orders"]] == [
        (row["symbol"], row["side"], row["qty"]) for row in document["rejected_orders"]
    ]
    assert {row["reason_code"] for row in document["canceled_orders"]} == {CANCELED_REASON_CODE}


def test_halted_session_carries_the_marks_forward_untouched() -> None:
    _, document = _run(
        _payload(
            _HALTED,
            orders=[{"symbol": _SYM, "side": "buy", "qty": 100}],
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
    assert [(row["symbol"], row["event_type"]) for row in document["events"]] == [(_SYM, "halted")]
    assert document["nav_series"] == [
        {
            "date": _HALTED,
            "nav": 1_152_020.0,
            "cash": 1_000_000.0,
            "position_value": 152_020.0,
        }
    ]
    assert document["end_state"]["cash"] == 1_000_000.0
    assert {row["symbol"]: (row["qty"], row["avg_cost"]) for row in document["end_state"]["positions"]} == {
        _SYM: (100.0, 1421.0),
        _WITNESS: (1000.0, 10.0),
    }


class _AuctionLoader(FixtureLoader):
    """Serves the committed day plus one synthetic 14:58 auction-window label."""

    def __init__(self, symbol: str, frame: pd.DataFrame) -> None:
        super().__init__()
        self._symbol = symbol
        self._frame = frame

    def fetch(self, codes, start_date, end_date, *, interval="1D", fields=None):
        if str(interval).lower() in ("5m", "5min", "5"):
            ordered = tuple(str(code) for code in codes)
            self.calls.append((ordered, start_date, end_date, str(interval)))
            return {self._symbol: self._frame} if self._symbol in ordered else {}
        return super().fetch(codes, start_date, end_date, interval=interval, fields=fields)


def test_auction_window_label_is_excluded_and_reported() -> None:
    extra = pd.DataFrame(
        [{"open": 99.0, "high": 99.0, "low": 99.0, "close": 99.0, "volume": 1.0}],
        index=pd.DatetimeIndex([pd.Timestamp(f"{_DAY} 14:58:00")], name="bar_time"),
    )
    tainted = pd.concat([load_5m(_SYM, _DAY), extra]).sort_index()
    _, clean = _run(_payload())
    _, document = _run(_payload(), loader=_AuctionLoader(_SYM, tainted))

    assert [(row["symbol"], row["event_type"]) for row in document["events"]] == [(_SYM, "auction_window")]
    assert "14:58" in document["events"][0]["detail"]
    assert document["fills"][0]["price"] == clean["fills"][0]["price"] == 1421.50


def test_manifest_indexes_every_fixture_and_matches_its_bytes() -> None:
    manifest = fixture_manifest()
    listed = {entry["file"]: entry for entry in manifest["fixtures"]}
    on_disk = {path.relative_to(FIXTURE_ROOT).as_posix() for path in fixture_files()}

    assert set(listed) == on_disk
    assert manifest["schema"] == "paper_trade.five_minute_fixture_manifest/v1"
    for relative, entry in listed.items():
        data = (FIXTURE_ROOT / relative).read_bytes()
        assert hashlib.sha256(data).hexdigest() == entry["sha256"], relative
        assert data.count(b"\n") == entry["rows"] + 1
        assert entry["continuous_rows"] in (0, 48)
    assert listed[f"{_SYM}/{_HALTED}.csv"]["continuous_rows"] == 0
