"""T6 gate — ``paper_trade_step`` tool entry + MCP wrapper (Step 6).

Covers the registration seam end to end, offline: the orders-mode success
document, the in-band ``PAPER_DATA_NOT_READY`` envelope, ``INVALID_REQUEST``
for every malformed-input class (shape parse, the tool-owned orders XOR
strategy_path gate, a reversed range, the AM-3 single-day rule), the AM-4-1
rule that ``received_state_hash`` covers the RAW account_state (an added key
breaks it, an int/float respelling does not), the single degraded error-envelope
case (a malformed ``market`` echoed verbatim, T5 decision 5), the strategy_path
routing into the lazily-imported T7 ``strategy_exec.run_strategy_path`` (fake,
including the ``strategy_universe`` prefetch seam and its orders-mode absence),
the strategy_path end-to-end universe regression (a cash-only account + the
golden fixture's declared ``UNIVERSE`` must prefetch and fill), and the
hand-written MCP wrapper (payload build + delegation + description).

The research-only red line is asserted statically: the tool module carries no
scoped ``trading_*`` connector surface and no order-placement call.

Offline by construction: fake loader / fake CH client / fake calendar client,
no network (``--disable-socket`` hard gate), no clock (every date injected).
"""

from __future__ import annotations

import json
import re
import sys
import types
from pathlib import Path

import pandas as pd
import pytest

from src.config.paths import get_runtime_root
from src.tools.paper_trade import engine, state_hash
from src.tools.paper_trade import tool as tool_module
from src.tools.paper_trade.schema import (
    MARKETS,
    load_contract_schema,
    validate_payload,
)
from src.tools.paper_trade.tool import PaperTradeStepTool, run_paper_trade_step

_CN_A_DAY = "2026-10-20"  # Tuesday
_CN_A_PREV = "2026-10-19"
_HK_DAY = "2026-10-16"  # Friday
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")

# The T7 synthetic fixture day (index 39: close 128.5, sma5 127.5, sma20
# 123.75 — the golden SMA cross) and the §4 us default fee matrix (AM-4-3).
_US_DAY = "2026-03-02"
_US_FEES = {"commission_per_share": 0.0049, "commission_min": 0.99, "sec_fee_rate": 0.0}
_FIXTURES = Path(__file__).parent / "fixtures" / "paper_trade"
_SYNTH_FIXTURE = _FIXTURES / "market" / "synthetic_split_4to1.json"
_GOLDEN_STRATEGY = _FIXTURES / "strategies" / "golden_sample_sma.py"

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


class FakeChClient:
    def __init__(self, frames: dict[str, pd.DataFrame]) -> None:
        self._frames = frames

    def get_bars(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        return self._frames.get(ts_code, pd.DataFrame())


class FakeLoader:
    def __init__(self, frames: dict[str, pd.DataFrame], name: str = "tencent") -> None:
        self.name = name
        self._frames = frames

    def is_available(self) -> bool:
        return True

    def fetch(self, codes, start_date, end_date, *, interval="1D", fields=None):
        return {c: self._frames[c] for c in codes if c in self._frames}


class FakeCalendarClient:
    """cn_a CH trade_calendar truth: exactly the given days are open."""

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


def _payload(**overrides) -> dict:
    base = {
        "account_id": "pa_t6",
        "market": "cn_a",
        "account_state": {"cash": 200000.0, "positions": []},
        "orders": [{"symbol": "600519.SH", "side": "buy", "qty": 100}],
        "from_date": _CN_A_DAY,
        "to_date": _CN_A_DAY,
        "fee_model": dict(_CN_A_FEES),
    }
    base.update(overrides)
    return base


def _cn_a_fakes(*, target_bar: float | None = 1421.0, prev_bar: float | None = 1418.0):
    """Fake loader/ch/calendar for a cn_a run; ``None`` omits that leg's bar."""
    loader_frames = {"600519.SH": _frame([(_CN_A_DAY, target_bar)])} if target_bar else {}
    ch_frames = {"600519.SH": _frame([(_CN_A_PREV, prev_bar)])} if prev_bar else {}
    return {
        "loader": FakeLoader(loader_frames, "tencent"),
        "ch_client": FakeChClient(ch_frames),
        "calendar_client": FakeCalendarClient((_CN_A_DAY,)),
        "limits_client": None,  # heuristic band (the cn_a golden path)
    }


# ── orders-mode success document ──


def test_orders_mode_returns_the_success_document() -> None:
    text = run_paper_trade_step(_payload(), **_cn_a_fakes())
    doc = json.loads(text)
    assert doc["schema_version"] == "pt-v1.1"
    assert doc["tool"] == "paper_trade_step"
    assert doc["account_id"] == "pa_t6"
    assert doc["market"] == "cn_a"
    assert doc["range"] == {"from": _CN_A_DAY, "to": _CN_A_DAY}
    assert _SHA_RE.match(doc["received_state_hash"])
    # Hand-computed cn_a cents (the T3/T5 golden): buy 100 @ 1421.0, fee 36.95.
    assert doc["fills"][0] == {
        "trade_date": _CN_A_DAY, "symbol": "600519.SH", "side": "buy",
        "qty": 100.0, "price": 1421.0, "fee": 36.95, "reason": "",
    }
    assert doc["end_state"]["cash"] == 57863.05
    assert doc["data_provenance"]["source"] == "clickhouse+tencent(merged)"
    assert validate_payload(doc, load_contract_schema("result")) == []


def test_success_document_is_byte_deterministic_across_runs() -> None:
    first = run_paper_trade_step(_payload(), **_cn_a_fakes())
    second = run_paper_trade_step(_payload(), **_cn_a_fakes())
    assert first == second


# ── AM-5 in-band PAPER_DATA_NOT_READY envelope ──


def test_target_day_without_a_bar_returns_in_band_not_ready() -> None:
    # Neither leg serves the target day → readiness fails → in-band envelope.
    fakes = _cn_a_fakes(target_bar=None, prev_bar=1418.0)
    doc = json.loads(run_paper_trade_step(_payload(), **fakes))
    assert doc["status"] == "error"
    assert doc["code"] == "PAPER_DATA_NOT_READY"
    assert doc["account_id"] == "pa_t6"  # verbatim even on error (AM-4-4)
    assert doc["market"] == "cn_a"
    assert doc["range"] == {"from": _CN_A_DAY, "to": _CN_A_DAY}
    assert _SHA_RE.match(doc["received_state_hash"])  # state was parseable
    assert f"target bar {_CN_A_DAY} not available" in doc["message"]
    assert validate_payload(doc, load_contract_schema("error_envelope")) == []


# ── INVALID_REQUEST: shape parse, semantic gate, range rules ──


def test_malformed_market_is_invalid_request_echoed_verbatim() -> None:
    doc = json.loads(run_paper_trade_step(_payload(market="xyz")))
    assert doc["status"] == "error"
    assert doc["code"] == "INVALID_REQUEST"
    # T5 decision 5: the raw malformed market is echoed verbatim (honest
    # reporting), so the envelope's own market enum is the single degraded
    # case — the only validation error is the market enum.
    assert doc["market"] == "xyz"
    assert "market must be one of" in doc["message"]
    # market not in MARKETS → the coverage object is not computable → hash omitted.
    assert "received_state_hash" not in doc
    errors = validate_payload(doc, load_contract_schema("error_envelope"))
    assert errors and all("market" in e for e in errors)


def test_missing_account_id_is_invalid_request_with_empty_echo() -> None:
    payload = _payload()
    del payload["account_id"]
    doc = json.loads(run_paper_trade_step(payload))
    assert doc["code"] == "INVALID_REQUEST"
    assert doc["account_id"] == ""  # non-string degrades to "" (never leaks)
    assert "account_id" in doc["message"]


def test_non_dict_payload_is_invalid_request() -> None:
    doc = json.loads(run_paper_trade_step(["not", "an", "object"]))
    assert doc["code"] == "INVALID_REQUEST"
    assert doc["account_id"] == "" and doc["market"] == ""
    assert "received_state_hash" not in doc


def test_both_orders_and_strategy_path_violates_the_xor_gate() -> None:
    payload = _payload(strategy_path="agent/strategies/x.py")
    doc = json.loads(run_paper_trade_step(payload))
    assert doc["code"] == "INVALID_REQUEST"
    assert "got both" in doc["message"]
    assert doc["account_id"] == "pa_t6" and doc["market"] == "cn_a"


def test_neither_orders_nor_strategy_path_violates_the_xor_gate() -> None:
    payload = _payload(orders=None)
    doc = json.loads(run_paper_trade_step(payload))
    assert doc["code"] == "INVALID_REQUEST"
    assert "got neither" in doc["message"]


def test_reversed_range_is_invalid_request() -> None:
    # hk avoids the cn_a connector; fetch_market_data guards from > to first.
    payload = _payload(market="hk", from_date=_HK_DAY, to_date="2026-10-15",
                       fee_model=dict(_HK_FEES),
                       orders=[{"symbol": "00700.HK", "side": "buy", "qty": 100}])
    doc = json.loads(run_paper_trade_step(payload))
    assert doc["code"] == "INVALID_REQUEST"
    assert "from_date" in doc["message"] and "to_date" in doc["message"]


def test_orders_mode_multiday_is_invalid_request() -> None:
    # AM-3 single-day gate lives in the engine and surfaces as in-band material.
    payload = _payload(market="hk", from_date="2026-10-15", to_date=_HK_DAY,
                       fee_model=dict(_HK_FEES),
                       orders=[{"symbol": "00700.HK", "side": "buy", "qty": 100}])
    loader = FakeLoader({"00700.HK": _frame([("2026-10-15", 416.0), (_HK_DAY, 417.8)])}, "tencent")
    doc = json.loads(run_paper_trade_step(payload, loader=loader))
    assert doc["code"] == "INVALID_REQUEST"
    assert "from_date == to_date" in doc["message"]


# ── AM-4-1: received_state_hash covers the RAW account_state ──


def _hk_success_hash(account_state: dict) -> str:
    payload = _payload(market="hk", account_state=account_state, from_date=_HK_DAY,
                       to_date=_HK_DAY, fee_model=dict(_HK_FEES),
                       orders=[{"symbol": "00700.HK", "side": "buy", "qty": 100}])
    loader = FakeLoader({"00700.HK": _frame([(_HK_DAY, 417.8)])}, "tencent")
    doc = json.loads(run_paper_trade_step(payload, loader=loader))
    assert "received_state_hash" in doc, doc
    return doc["received_state_hash"]


def test_added_account_state_key_changes_the_hash() -> None:
    base = _hk_success_hash({"cash": 100000.0, "positions": []})
    with_extra = _hk_success_hash({"cash": 100000.0, "positions": [], "note": "llm-added"})
    assert base != with_extra  # the raw value is hashed, not the parsed reconstruction


def test_int_float_respelling_does_not_change_the_hash() -> None:
    as_float = _hk_success_hash({"cash": 100000.0, "positions": []})
    as_int = _hk_success_hash({"cash": 100000, "positions": []})
    assert as_float == as_int  # JCS number canonicalization (state_hash)


# ── strategy_path routing into the lazily-imported T7 module ──


def test_strategy_path_routes_to_run_strategy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded: dict = {}

    def _fake_run_strategy_path(**kwargs):
        recorded.update(kwargs)
        request = kwargs["request"]
        return engine.MatchOutcome(
            end_state=request.account_state,
            effective_fee_model=state_hash.effective_fee_model(request.market, dict(request.fee_model)),
            data_provenance=kwargs["market_data"].provenance,
        )

    universe_calls: list = []

    def _fake_strategy_universe(path):
        universe_calls.append(path)
        return ()

    fake_module = types.ModuleType("src.tools.paper_trade.strategy_exec")
    fake_module.run_strategy_path = _fake_run_strategy_path
    fake_module.strategy_universe = _fake_strategy_universe
    monkeypatch.setitem(sys.modules, "src.tools.paper_trade.strategy_exec", fake_module)

    payload = _payload(market="hk", orders=None, strategy_path="agent/strategies/x.py",
                       from_date=_HK_DAY, to_date=_HK_DAY, fee_model=dict(_HK_FEES),
                       account_state={"cash": 100000.0,
                                      "positions": [{"symbol": "00700.HK", "qty": 100, "avg_cost": 400.0}]})
    loader = FakeLoader({"00700.HK": _frame([(_HK_DAY, 417.8)])}, "tencent")
    doc = json.loads(run_paper_trade_step(payload, loader=loader, timeout_seconds=12.5))

    # The T7 seam receives exactly the contracted kwargs.
    assert set(recorded) == {
        "request", "market_data", "calendar_client", "limits_client",
        "corporate_action_unresolved_by_day", "hk_lot_sizes", "timeout_seconds",
    }
    assert recorded["request"].strategy_path == "agent/strategies/x.py"
    assert recorded["timeout_seconds"] == 12.5
    assert recorded["calendar_client"] is None  # hk zero-calendar (AM-6)
    # The universe prefetch seam was consulted exactly once, with the request's
    # strategy_path; a () declaration keeps the positions-only fetch universe.
    assert universe_calls == ["agent/strategies/x.py"]
    assert recorded["market_data"].symbols == ("00700.HK",)
    # The fake outcome is assembled into the success document.
    assert doc["tool"] == "paper_trade_step" and doc["market"] == "hk"
    assert validate_payload(doc, load_contract_schema("result")) == []


def test_orders_mode_never_consults_strategy_universe(monkeypatch: pytest.MonkeyPatch) -> None:
    # The UNIVERSE prefetch is strategy_path-mode ONLY: orders mode derives its
    # universe from positions ∪ orders and must never touch the T7 module (the
    # fake below lacks run_strategy_path entirely, so any import of it fails).
    def _boom(path):
        raise AssertionError("orders mode must not consult strategy_universe")

    fake_module = types.ModuleType("src.tools.paper_trade.strategy_exec")
    fake_module.strategy_universe = _boom
    monkeypatch.setitem(sys.modules, "src.tools.paper_trade.strategy_exec", fake_module)

    payload = _payload(market="hk", from_date=_HK_DAY, to_date=_HK_DAY,
                       fee_model=dict(_HK_FEES),
                       orders=[{"symbol": "00700.HK", "side": "buy", "qty": 100}])
    loader = FakeLoader({"00700.HK": _frame([(_HK_DAY, 417.8)])}, "tencent")
    doc = json.loads(run_paper_trade_step(payload, loader=loader))
    assert "status" not in doc  # success document, not an error envelope
    assert doc["fills"][0]["symbol"] == "00700.HK"


# ── strategy_path end-to-end: declared UNIVERSE prefetch (T6×T7 integration) ──


def _synth_frame() -> pd.DataFrame:
    document = json.loads(_SYNTH_FIXTURE.read_text(encoding="utf-8"))
    frame = pd.DataFrame(document["bars"])
    frame["trade_date"] = pd.to_datetime(frame["date"])
    return frame.set_index("trade_date")[["open", "high", "low", "close", "volume"]]


def test_strategy_path_cash_only_account_fills_via_declared_universe() -> None:
    # The end-to-end regression for the universe gap: a cash-only account (no
    # positions) + strategy_path (no orders) prefetched an EMPTY universe, so
    # the golden SMA strategy saw no symbols and the call "succeeded" with
    # zero fills.  The fixture's declared UNIVERSE = ("SYNTH-4TO1",) must
    # reach the fetch universe through the real T6 → T7 → engine chain (no
    # strategy_exec fake here; the child really spawns).
    root = get_runtime_root() / "strategies"
    root.mkdir(parents=True, exist_ok=True)
    strategy = root / "golden_sample_sma.py"
    strategy.write_text(_GOLDEN_STRATEGY.read_text(encoding="utf-8"), encoding="utf-8")

    payload = _payload(
        market="us", orders=None, strategy_path=str(strategy),
        account_state={"cash": 50000.0, "positions": []},
        from_date=_US_DAY, to_date=_US_DAY, fee_model=dict(_US_FEES),
    )
    loader = FakeLoader({"SYNTH-4TO1": _synth_frame()}, "sina")
    doc = json.loads(run_paper_trade_step(payload, loader=loader))

    assert "status" not in doc, doc  # success document, not an error envelope
    # Hand-computed us golden: close 128.5, fee max(100×0.0049, 0.99) = 0.99;
    # cash 50000 − 12850.00 − 0.99 = 37099.01 (mirrors the direct T7 gate).
    assert doc["fills"] == [{
        "trade_date": _US_DAY, "symbol": "SYNTH-4TO1", "side": "buy",
        "qty": 100.0, "price": 129.0, "fee": 0.99,
        "reason": "golden sma5 127.5000 > sma20 123.7500",
    }]
    assert doc["end_state"]["cash"] == 37099.01
    assert [(p["symbol"], p["qty"]) for p in doc["end_state"]["positions"]] == [
        ("SYNTH-4TO1", 100.0)]
    assert validate_payload(doc, load_contract_schema("result")) == []


# ── the hand-written MCP wrapper (VD-12) ──


def _mcp_wrapper():
    import mcp_server

    return mcp_server, (
        getattr(mcp_server.paper_trade_step, "fn", None)
        or getattr(mcp_server.paper_trade_step, "__wrapped__", mcp_server.paper_trade_step)
    )


def test_mcp_wrapper_builds_the_payload_and_delegates(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def _recorder(payload, **kwargs):
        captured["payload"] = payload
        captured["kwargs"] = kwargs
        return "SENTINEL"

    monkeypatch.setattr(tool_module, "run_paper_trade_step", _recorder)
    _mcp_server, wrapper = _mcp_wrapper()
    out = wrapper(
        account_id="pa_mcp", market="hk",
        account_state={"cash": 1.0, "positions": []},
        from_date=_HK_DAY, to_date=_HK_DAY,
        orders=[{"symbol": "00700.HK", "side": "buy", "qty": 100}],
        fee_model={"commission_min": 3.0},
    )
    assert out == "SENTINEL"
    payload = captured["payload"]
    assert payload["account_id"] == "pa_mcp" and payload["market"] == "hk"
    assert payload["orders"] == [{"symbol": "00700.HK", "side": "buy", "qty": 100}]
    assert payload["fee_model"] == {"commission_min": 3.0}
    # Optional keys absent from the call are absent from the payload (never null).
    assert "strategy_path" not in payload


def test_mcp_wrapper_omits_absent_optional_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def _recorder(payload, **kwargs):
        captured["payload"] = payload
        return "X"

    monkeypatch.setattr(tool_module, "run_paper_trade_step", _recorder)
    _mcp_server, wrapper = _mcp_wrapper()
    wrapper(account_id="a", market="us", account_state={"cash": 0.0, "positions": []},
            from_date=_HK_DAY, to_date=_HK_DAY)
    payload = captured["payload"]
    assert "orders" not in payload and "strategy_path" not in payload and "fee_model" not in payload


def test_mcp_wrapper_description_carries_the_frozen_phrase() -> None:
    mcp_server, _wrapper = _mcp_wrapper()
    phrase = "deterministic paper-trading matching engine; never places real orders"
    assert phrase in (mcp_server.paper_trade_step.__doc__ or "")
    assert phrase in PaperTradeStepTool.description


def test_mcp_wrapper_end_to_end_matches_the_core_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    # Drive the real wrapper → real core for hk, stubbing only the network leg.
    from src.tools.paper_trade import data as data_layer

    monkeypatch.setattr(data_layer, "_resolve_network_loader",
                        lambda *_a, **_k: FakeLoader({"00700.HK": _frame([(_HK_DAY, 417.8)])}, "tencent"))
    _mcp_server, wrapper = _mcp_wrapper()
    via_wrapper = wrapper(
        account_id="pa_e2e", market="hk",
        account_state={"cash": 100000.0, "positions": []},
        from_date=_HK_DAY, to_date=_HK_DAY,
        orders=[{"symbol": "00700.HK", "side": "buy", "qty": 100}],
        fee_model=dict(_HK_FEES),
    )
    via_core = run_paper_trade_step(
        {"account_id": "pa_e2e", "market": "hk",
         "account_state": {"cash": 100000.0, "positions": []},
         "from_date": _HK_DAY, "to_date": _HK_DAY,
         "orders": [{"symbol": "00700.HK", "side": "buy", "qty": 100}],
         "fee_model": dict(_HK_FEES)},
        loader=FakeLoader({"00700.HK": _frame([(_HK_DAY, 417.8)])}, "tencent"),
    )
    assert via_wrapper == via_core
    assert json.loads(via_wrapper)["fills"][0]["fee"] == 55.79  # hk golden cents


# ── research-only red line (REQUIREMENTS R1) ──


def test_tool_module_exposes_no_trading_connector_or_order_surface() -> None:
    source = Path(tool_module.__file__).read_text(encoding="utf-8")
    scoped = re.compile(r"trading_(account|orders|positions|quote|history|check|connections|select|place|cancel)")
    assert not scoped.search(source)
    assert "place_order" not in source and "cancel_order" not in source


def test_tool_is_registered_readonly_and_available() -> None:
    tool = PaperTradeStepTool()
    assert tool.name == "paper_trade_step"
    assert tool.is_readonly is True
    assert tool.check_available() is True
    assert tool.parameters["required"] == [
        "account_id", "market", "account_state", "from_date", "to_date",
    ]
    assert set(tool.parameters["properties"]["market"]["enum"]) == set(MARKETS)


def test_execute_delegates_the_kwargs_payload_to_the_core(monkeypatch: pytest.MonkeyPatch) -> None:
    # execute() carries no injection seams, so stub the core to prove the
    # BaseTool hands its kwargs through as the raw payload dict (offline).
    captured: dict = {}

    def _recorder(payload, **kwargs):
        captured["payload"] = payload
        return "DOC"

    monkeypatch.setattr(tool_module, "run_paper_trade_step", _recorder)
    out = PaperTradeStepTool().execute(
        account_id="a", market="hk", account_state={"cash": 0.0, "positions": []},
        from_date=_HK_DAY, to_date=_HK_DAY, orders=[],
    )
    assert out == "DOC"
    assert captured["payload"]["account_id"] == "a"
    assert captured["payload"]["market"] == "hk"
    assert captured["payload"]["orders"] == []
