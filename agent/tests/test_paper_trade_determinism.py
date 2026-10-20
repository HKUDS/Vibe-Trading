"""T1 gate — pt-v1.1 wire determinism goldens (Step 5 / T5).

Three markets, one golden group each: the exact wire bytes that
``wire.dumps_payload(wire.build_success_payload(...))`` produces for a
fixture-backed single-day orders run, frozen under
``agent/tests/fixtures/paper_trade/golden/``.  The determinism claim (R1-1):
the same input run twice yields byte-identical JSON, an identical sha256, and
bytes equal to the frozen golden.  Fee/cash/nav values inside each scenario
are the hand-computed cents already pinned by the T3 goldens
(test_paper_trade_golden_*.py), so a golden is self-verifying, not circular.

The error path is deterministic too: an AM-5 in-band PAPER_DATA_NOT_READY
envelope built twice from the same not-ready input is byte-identical.

Offline by construction: fake loaders / fake CH client / fake calendar
client, no network (``--disable-socket`` hard gate), no clock (every date is
an injected literal).
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pandas as pd
import pytest

from src.tools.paper_trade import engine, wire
from src.tools.paper_trade.data import fetch_market_data
from src.tools.paper_trade.schema import (
    DateRange,
    ErrorEnvelope,
    load_contract_schema,
    parse_request,
    validate_payload,
)
from src.tools.paper_trade.state_hash import effective_fee_model, state_hash

_GOLDEN_DIR = Path(__file__).parent / "fixtures" / "paper_trade" / "golden"
_MARKET_DIR = Path(__file__).parent / "fixtures" / "paper_trade" / "market"
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")

_CN_A_DAY = "2026-10-20"  # Tuesday
_CN_A_PREV = "2026-10-19"
_HK_US_DAY = "2026-10-16"  # Friday; last bar of both recorded fixtures

# §4 terminal default fee models (state_hash._DEFAULT_FEE_MODELS, frozen).
_CN_A_FEES = {
    "commission_rate": 0.00025,
    "commission_min": 5.0,
    "stamp_tax_sell": 0.0005,
    "transfer_fee": 0.00001,
}
_HK_FEES = {
    "commission_rate": 0.0003,
    "commission_min": 3.0,
    "stamp_tax_rate": 0.001,
    "regulatory_levy_rate": 0.00003,
}
_US_FEES = {
    "commission_per_share": 0.0049,
    "commission_min": 0.99,
    "sec_fee_rate": 0.0,
}


class FakeChClient:
    def __init__(self, frames: dict[str, pd.DataFrame]) -> None:
        self._frames = frames

    def get_bars(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        return self._frames.get(ts_code, pd.DataFrame())


class FakeLoader:
    def __init__(self, frames: dict[str, pd.DataFrame], name: str) -> None:
        self.name = name
        self._frames = frames

    def is_available(self) -> bool:
        return True

    def fetch(self, codes, start_date, end_date, *, interval="1D", fields=None):
        return {c: self._frames[c] for c in codes if c in self._frames}


class FakeCalendarClient:
    """cn_a CH trade_calendar truth: exactly the open days given."""

    def __init__(self, open_days: tuple[str, ...]) -> None:
        self._open = set(open_days)

    def get_trade_calendar(self, start_date: str, end_date: str) -> pd.DataFrame:
        rows = [
            {"exchange": "SSE", "cal_date": day.strftime("%Y-%m-%d"),
             "is_open": int(day.strftime("%Y-%m-%d") in self._open), "pretrade_date": ""}
            for day in pd.date_range(start_date, end_date)
        ]
        return pd.DataFrame(rows, columns=["exchange", "cal_date", "is_open", "pretrade_date"])


def _frame(rows: list[tuple[str, float]]) -> pd.DataFrame:
    records = [
        {"trade_date": day, "open": close, "high": close, "low": close, "close": close,
         "volume": 1000.0}
        for day, close in rows
    ]
    frame = pd.DataFrame(records)
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    return frame.set_index("trade_date")


def _recorded_frame(filename: str) -> pd.DataFrame:
    document = json.loads((_MARKET_DIR / filename).read_text(encoding="utf-8"))
    frame = pd.DataFrame(document["bars"])
    frame["trade_date"] = pd.to_datetime(frame["date"])
    return frame.set_index("trade_date")[["open", "high", "low", "close", "volume"]]


def _payload(account_id: str, market: str, cash: float, orders: list[dict], day: str,
             fees: dict[str, float]) -> dict:
    return {
        "account_id": account_id,
        "market": market,
        "account_state": {"cash": cash, "positions": []},
        "orders": orders,
        "from_date": day,
        "to_date": day,
        "fee_model": dict(fees),
    }


def _run_to_wire_text(payload: dict, market_data, calendar_client=None) -> str:
    request = parse_request(payload)
    outcome = engine.match_orders(
        request, market_data=market_data, calendar_client=calendar_client
    )
    assert outcome.error is None, outcome.error
    result = wire.assemble_result(
        request, outcome, raw_account_state=payload["account_state"]
    )
    return wire.dumps_payload(wire.build_success_payload(result))


# ── Per-market scenarios (fresh fakes on every call — full-pipeline reruns) ──


def _scenario_cn_a() -> tuple[str, dict]:
    # Merged AM-9 frame: CH leg serves T-1 (10-19 close 1418.0), tencent leg
    # serves the target day (10-20 close 1421.0).  Buy 100 → fee 36.95,
    # cash 57863.05, nav 199963.05 (hand-computed in test_paper_trade_golden_cn_a).
    payload = _payload("pa_golden_cn_a", "cn_a", 200000.0,
                       [{"symbol": "600519.SH", "side": "buy", "qty": 100}],
                       _CN_A_DAY, _CN_A_FEES)
    market_data = fetch_market_data(
        "cn_a", ["600519.SH"], _CN_A_DAY, _CN_A_DAY,
        loader=FakeLoader({"600519.SH": _frame([(_CN_A_DAY, 1421.0)])}, "tencent"),
        ch_client=FakeChClient({"600519.SH": _frame([(_CN_A_PREV, 1418.0)])}),
    )
    return _run_to_wire_text(payload, market_data,
                             FakeCalendarClient((_CN_A_DAY,))), payload


def _scenario_hk() -> tuple[str, dict]:
    # Recorded tencent fixture (raw caliber), target 2026-10-16 close 417.8.
    # Buy 100 → fee 55.79, cash 58164.21, nav 99944.21 (golden_hk hand math).
    payload = _payload("pa_golden_hk", "hk", 100000.0,
                       [{"symbol": "00700.HK", "side": "buy", "qty": 100}],
                       _HK_US_DAY, _HK_FEES)
    market_data = fetch_market_data(
        "hk", ["00700.HK"], _HK_US_DAY, _HK_US_DAY,
        loader=FakeLoader({"00700.HK": _recorded_frame("hk_00700_tencent.json")}, "tencent"),
    )
    return _run_to_wire_text(payload, market_data), payload


def _scenario_us() -> tuple[str, dict]:
    # Recorded sina fixture (raw caliber), target 2026-10-16 close 343.46.
    # Buy 10 → fee 0.99 (minimum dominates), cash 46564.41, nav 49999.01.
    payload = _payload("pa_golden_us", "us", 50000.0,
                       [{"symbol": "AAPL.US", "side": "buy", "qty": 10}],
                       _HK_US_DAY, _US_FEES)
    market_data = fetch_market_data(
        "us", ["AAPL.US"], _HK_US_DAY, _HK_US_DAY,
        loader=FakeLoader({"AAPL.US": _recorded_frame("us_AAPL_sina.json")}, "sina"),
    )
    return _run_to_wire_text(payload, market_data), payload


_SCENARIOS = {"cn_a": _scenario_cn_a, "hk": _scenario_hk, "us": _scenario_us}
_GOLDEN_FILES = {
    "cn_a": "cn_a_orders_single_day.json",
    "hk": "hk_orders_single_day.json",
    "us": "us_orders_single_day.json",
}
_MARKETS = sorted(_SCENARIOS)


def _manifest() -> dict:
    return json.loads((_GOLDEN_DIR / "MANIFEST.json").read_text(encoding="utf-8"))


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ── T1: double-run byte/sha parity ──


@pytest.mark.parametrize("market", _MARKETS)
def test_double_run_produces_identical_bytes_and_sha(market: str) -> None:
    first_text, _ = _SCENARIOS[market]()
    second_text, _ = _SCENARIOS[market]()
    assert first_text == second_text
    assert _sha256(first_text.encode("utf-8")) == _sha256(second_text.encode("utf-8"))


# ── T1: frozen golden bytes + manifest sha ──


@pytest.mark.parametrize("market", _MARKETS)
def test_wire_bytes_match_the_frozen_golden(market: str) -> None:
    text, _ = _SCENARIOS[market]()
    golden_bytes = (_GOLDEN_DIR / _GOLDEN_FILES[market]).read_bytes()
    assert text.encode("utf-8") == golden_bytes
    entry = next(g for g in _manifest()["goldens"] if g["file"] == _GOLDEN_FILES[market])
    assert _sha256(golden_bytes) == entry["sha256"]
    assert len(golden_bytes) == entry["bytes"]


def test_golden_manifest_covers_exactly_the_three_markets() -> None:
    files = {g["file"] for g in _manifest()["goldens"]}
    assert files == set(_GOLDEN_FILES.values())
    assert {g["market"] for g in _manifest()["goldens"]} == {"cn_a", "hk", "us"}
    for golden in _manifest()["goldens"]:
        assert _SHA_RE.match(golden["sha256"])


# ── Golden content is self-verifying (hand-computed cents, frozen echoes) ──


@pytest.mark.parametrize("market", _MARKETS)
def test_golden_carries_the_frozen_contract_echoes(market: str) -> None:
    text, payload = _SCENARIOS[market]()
    doc = json.loads(text)
    assert doc["schema_version"] == "pt-v1.1"
    assert doc["tool"] == "paper_trade_step"
    assert doc["account_id"] == payload["account_id"]
    assert doc["market"] == market
    assert doc["range"] == {"from": payload["from_date"], "to": payload["to_date"]}
    assert _SHA_RE.match(doc["received_state_hash"])
    assert doc["effective_fee_model"] == effective_fee_model(market, payload["fee_model"])
    assert all(fill["reason"] == "" for fill in doc["fills"])  # VD-15 orders mode
    # AM-4-1: the hash equals sha256(JCS(coverage object)) computed by hand.
    assert doc["received_state_hash"] == state_hash({
        "account_id": payload["account_id"],
        "market": market,
        "account_state": payload["account_state"],
        "fee_model": effective_fee_model(market, payload["fee_model"]),
        "from_date": payload["from_date"],
        "to_date": payload["to_date"],
    })


def test_cn_a_golden_embeds_hand_computed_cents_and_merged_provenance() -> None:
    doc = json.loads(_SCENARIOS["cn_a"]()[0])
    fill = doc["fills"][0]
    assert (fill["trade_date"], fill["symbol"], fill["side"]) == (_CN_A_DAY, "600519.SH", "buy")
    assert (fill["qty"], fill["price"], fill["fee"]) == (100.0, 1421.0, 36.95)
    assert doc["end_state"] == {
        "cash": 57863.05,
        "positions": [{"symbol": "600519.SH", "qty": 100.0, "avg_cost": 1421.0}],
    }
    assert doc["nav_series"] == [
        {"date": _CN_A_DAY, "nav": 199963.05, "cash": 57863.05, "position_value": 142100.0}
    ]
    assert doc["rejected_orders"] == [] and doc["skipped_days"] == [] and doc["warnings"] == []
    # AM-9 merged-frame provenance + VD-11 heuristic band token.
    assert doc["data_provenance"] == {
        "source": "clickhouse+tencent(merged)",
        "ch_as_of": _CN_A_PREV,
        "network_as_of": _CN_A_DAY,
        "bars_as_of": _CN_A_DAY,
        "limit_provenance": [f"600519.SH@{_CN_A_DAY}:limits:heuristic"],
    }


def test_hk_golden_embeds_hand_computed_cents_and_lot_warning() -> None:
    doc = json.loads(_SCENARIOS["hk"]()[0])
    fill = doc["fills"][0]
    assert (fill["qty"], fill["price"], fill["fee"]) == (100.0, 417.8, 55.79)
    assert doc["end_state"]["cash"] == 58164.21
    assert doc["nav_series"][0] == {
        "date": _HK_US_DAY, "nav": 99944.21, "cash": 58164.21, "position_value": 41780.0
    }
    # The lot-assumption diagnostic keys on the board-lot mechanism's
    # normalized symbol spelling (0700.HK), as pinned by the T3 hk golden.
    assert doc["warnings"] == [
        "lot assumption: 0700.HK sized on the default 100-share board lot "
        "(no lot table entry)"
    ]
    prov = doc["data_provenance"]
    assert prov["source"] == "tencent"
    assert prov["bars_as_of"] == _HK_US_DAY and prov["network_as_of"] == _HK_US_DAY
    assert "ch_as_of" not in prov and "limit_provenance" not in prov


def test_us_golden_embeds_hand_computed_cents() -> None:
    doc = json.loads(_SCENARIOS["us"]()[0])
    fill = doc["fills"][0]
    assert (fill["qty"], fill["price"], fill["fee"]) == (10.0, 343.46, 0.99)
    assert doc["end_state"]["cash"] == 46564.41
    assert doc["nav_series"][0] == {
        "date": _HK_US_DAY, "nav": 49999.01, "cash": 46564.41, "position_value": 3434.6
    }
    assert doc["warnings"] == []
    prov = doc["data_provenance"]
    assert prov["source"] == "sina" and prov["bars_as_of"] == _HK_US_DAY
    assert "ch_as_of" not in prov and "limit_provenance" not in prov


# ── AM-5 error path determinism (in-band envelope, never transport) ──


def _not_ready_envelope_text() -> str:
    # cn_a target day with no bar on either leg → PAPER_DATA_NOT_READY.
    payload = _payload("pa_golden_cn_a", "cn_a", 200000.0,
                       [{"symbol": "600519.SH", "side": "buy", "qty": 100}],
                       _CN_A_DAY, _CN_A_FEES)
    request = parse_request(payload)
    market_data = fetch_market_data(
        "cn_a", ["600519.SH"], _CN_A_DAY, _CN_A_DAY,
        loader=FakeLoader({"600519.SH": _frame([(_CN_A_PREV, 1418.0)])}, "tencent"),
        ch_client=FakeChClient({}),
    )
    outcome = engine.match_orders(
        request, market_data=market_data, calendar_client=FakeCalendarClient((_CN_A_DAY,))
    )
    assert outcome.error is not None
    assert outcome.error.code == "PAPER_DATA_NOT_READY"
    envelope = ErrorEnvelope(
        code=outcome.error.code,
        account_id=request.account_id,
        market=request.market,
        range=DateRange(from_=request.from_date, to=request.to_date),
        message=outcome.error.message,
        received_state_hash=wire.received_state_hash_from_payload(payload),
    )
    return wire.dumps_payload(wire.build_error_payload(envelope))


def test_error_envelope_bytes_are_deterministic_and_schema_valid() -> None:
    first = _not_ready_envelope_text()
    second = _not_ready_envelope_text()
    assert first == second
    assert _sha256(first.encode("utf-8")) == _sha256(second.encode("utf-8"))
    doc = json.loads(first)
    assert doc["status"] == "error"
    assert doc["code"] == "PAPER_DATA_NOT_READY"
    assert doc["account_id"] == "pa_golden_cn_a"  # verbatim even on error (AM-4-4)
    assert _SHA_RE.match(doc["received_state_hash"])  # state was parseable
    assert "target bar 2026-10-20 not available" in doc["message"]
    assert validate_payload(doc, load_contract_schema("error_envelope")) == []
