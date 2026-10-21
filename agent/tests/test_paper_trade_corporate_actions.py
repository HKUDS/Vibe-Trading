"""T7-gate corporate-action matrix for the paper_trade engine (Step 4 / T4).

Covers R6/AM-2/VD-6: the frozen clean-ratio set, the triple gate (price /
volume / NAV-continuity), the fail-closed unresolved path (structured
``corporate_action_unresolved`` rejection — never a guessed ratio, never a
silent pass, never a half-day), note-2 scan semantics (a historical split
inside the K=120 lookback never fires), the cn_a call-site exemption, the
union of the detector with the injectable T3 seam, and the skipped-day
semantics (``market_closed_inferred`` + warning, ``suspended`` carry-forward)
extended — not duplicated — from the T3 rejections matrix.  Market data =
the frozen VD-14 fixture ``synthetic_split_4to1.json`` (event 2026-02-02,
476.0 → 119.0, volume 1e6 → 4e6) reused for BOTH hk and us: the detector is
market-agnostic.  Offline: fixture-backed fake loaders only.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

import pandas as pd
import pytest

from src.tools.paper_trade import corporate_actions, engine
from src.tools.paper_trade.data import fetch_market_data
from src.tools.paper_trade.schema import (
    REASON_CODES, AccountState, Order, Position, parse_request,
)

_FIXTURE = Path(__file__).parent / "fixtures" / "paper_trade" / "market" / "synthetic_split_4to1.json"
_SYM = "SYNTH-4TO1"
_PREV = "2026-01-30"  # bar 19, close 476.0, volume 1e6
_EX = "2026-02-02"  # bar 20 = ex-date, close 119.0, volume 4e6 (frozen fixture)
_NEXT = "2026-02-03"  # bar 21, close 119.5


class FakeLoader:
    def __init__(self, frames: dict[str, pd.DataFrame], name: str = "sina") -> None:
        self.name = name
        self._frames = frames

    def is_available(self) -> bool:
        return True

    def fetch(self, codes, start_date, end_date, *, interval="1D", fields=None):
        return {c: self._frames[c] for c in codes if c in self._frames}


class FakeChClient:
    def get_bars(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        return pd.DataFrame()


class FakeCalendarClient:
    def __init__(self, open_days: frozenset[str]) -> None:
        self._open = open_days

    def get_trade_calendar(self, start_date: str, end_date: str) -> pd.DataFrame:
        rows = [
            {"exchange": "SSE", "cal_date": day.strftime("%Y-%m-%d"),
             "is_open": int(day.strftime("%Y-%m-%d") in self._open), "pretrade_date": ""}
            for day in pd.date_range(start_date, end_date)
        ]
        return pd.DataFrame(rows, columns=["exchange", "cal_date", "is_open", "pretrade_date"])


def _fixture_frame() -> pd.DataFrame:
    document = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    frame = pd.DataFrame(document["bars"])
    frame["trade_date"] = pd.to_datetime(frame["date"])
    return frame.set_index("trade_date")[["open", "high", "low", "close", "volume"]]


def _frame(rows: list[tuple[str, float, float]]) -> pd.DataFrame:
    records = [
        {"trade_date": day, "open": close, "high": close, "low": close, "close": close,
         "volume": volume}
        for day, close, volume in rows
    ]
    frame = pd.DataFrame(records)
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    return frame.set_index("trade_date")


def _fetch(market: str, frames: dict[str, pd.DataFrame], from_date: str, to_date: str,
           symbols: list[str] | None = None):
    return fetch_market_data(market, symbols if symbols is not None else list(frames),
                             from_date, to_date, loader=FakeLoader(frames))


def _request(market: str, cash: float, positions: list[dict], orders: list[dict], day: str):
    return parse_request({
        "account_id": "pa_ca", "market": market,
        "account_state": {"cash": cash, "positions": positions},
        "orders": orders, "from_date": day, "to_date": day, "fee_model": {},
    })


def _codes(outcome) -> list[str]:
    return [rejected.reason_code for rejected in outcome.rejected_orders]


# ── The frozen detector contract (pure unit level) ──


def test_frozen_ratio_set_is_exactly_the_contract_set() -> None:
    # R6-1/VD-6: {2,3,4,5,10,3/2} ∪ reciprocals — qty-multiplier semantics.
    assert corporate_actions.CLEAN_QTY_MULTIPLIERS == (
        Fraction(2), Fraction(3), Fraction(4), Fraction(5), Fraction(10), Fraction(3, 2),
        Fraction(1, 2), Fraction(1, 3), Fraction(1, 4), Fraction(1, 5), Fraction(1, 10),
        Fraction(2, 3),
    )
    assert corporate_actions.NAV_CONTINUITY_REL_TOL == Fraction(1, 10000)  # ±0.01% frozen


@pytest.mark.parametrize("mult", corporate_actions.CLEAN_QTY_MULTIPLIERS)
def test_every_frozen_multiplier_classifies_clean(mult: Fraction) -> None:
    # close 60.0 → 60/mult and volume 1200 → 1200×mult are exact decimals for
    # every frozen multiplier, so the triple gate passes with zero slack.
    verdict = corporate_actions.classify_boundary(
        close_before=60.0, close_after=float(Decimal(60) / Decimal(mult.numerator) * Decimal(mult.denominator)),
        volume_before=1200.0,
        volume_after=float(Decimal(1200) * Decimal(mult.numerator) / Decimal(mult.denominator)),
        qty=Decimal(100))
    assert verdict.kind == corporate_actions.KIND_CLEAN
    assert verdict.qty_multiplier == mult


def test_classify_clean_4to1_uses_the_fixture_numbers() -> None:
    verdict = corporate_actions.classify_boundary(
        close_before=476.0, close_after=119.0,
        volume_before=1_000_000.0, volume_after=4_000_000.0, qty=Decimal(100))
    assert verdict.kind == corporate_actions.KIND_CLEAN
    assert verdict.qty_multiplier == Fraction(4)
    assert verdict.observed_ratio == Decimal("0.25")


@pytest.mark.parametrize(("before", "after", "vol_after"), [
    (100.0, 40.0, 2_500_000.0),   # 0.4x crash-shaped, volume "confirms" 2.5x
    (100.0, 250.0, 400_000.0),    # 2.5x jump-shaped, volume "confirms" 0.4x
])
def test_non_clean_large_discontinuity_is_unresolved_never_guessed(
        before: float, after: float, vol_after: float) -> None:
    verdict = corporate_actions.classify_boundary(
        close_before=before, close_after=after,
        volume_before=1_000_000.0, volume_after=vol_after, qty=Decimal(100))
    assert verdict.kind == corporate_actions.KIND_UNRESOLVED
    assert verdict.qty_multiplier is None  # never guess a ratio


def test_clean_price_ratio_with_wrong_volume_is_unresolved() -> None:
    # Exact 0.25 price ratio but volume did NOT move 4x → the same-direction
    # multiple confirmation fails → fail-closed, not a silent split.
    verdict = corporate_actions.classify_boundary(
        close_before=476.0, close_after=119.0,
        volume_before=1_000_000.0, volume_after=1_000_000.0, qty=Decimal(100))
    assert verdict.kind == corporate_actions.KIND_UNRESOLVED


@pytest.mark.parametrize("vol_after", [0.0, float("nan")])
def test_unverifiable_volume_on_a_candidate_fails_closed(vol_after: float) -> None:
    verdict = corporate_actions.classify_boundary(
        close_before=100.0, close_after=50.0,
        volume_before=1000.0, volume_after=vol_after, qty=Decimal(100))
    assert verdict.kind == corporate_actions.KIND_UNRESOLVED


def test_nav_gate_is_the_binding_confirmation_for_held_positions() -> None:
    # Price ratio 119.06/476.0 = 0.250126… passes the 1e-3 price gate but the
    # adjusted NAV drifts 0.05% > the frozen ±0.01% → unresolved when held …
    kwargs = dict(close_before=476.0, close_after=119.06,
                  volume_before=1_000_000.0, volume_after=4_000_000.0)
    held = corporate_actions.classify_boundary(qty=Decimal(100), **kwargs)
    assert held.kind == corporate_actions.KIND_UNRESOLVED
    # … and vacuous for a flat symbol (no ledger to preserve): the price gate
    # (1e-3) governs.  Documented asymmetry — registered in the STEP4 receipt.
    flat = corporate_actions.classify_boundary(qty=Decimal(0), **kwargs)
    assert flat.kind == corporate_actions.KIND_CLEAN
    assert flat.qty_multiplier == Fraction(4)


@pytest.mark.parametrize(("before", "after"), [
    (100.0, 100.0), (100.0, 70.0), (100.0, 140.0), (100.0, 67.0), (100.0, 149.0),
])
def test_neutral_band_moves_are_not_candidates(before: float, after: float) -> None:
    verdict = corporate_actions.classify_boundary(
        close_before=before, close_after=after,
        volume_before=1000.0, volume_after=4000.0, qty=Decimal(100))
    assert verdict.kind == corporate_actions.KIND_NONE


@pytest.mark.parametrize(("before", "after"), [
    (0.0, 100.0), (-5.0, 100.0), (float("nan"), 100.0), (100.0, float("nan")), (100.0, 0.0),
])
def test_missing_or_non_positive_closes_are_insufficient_evidence(
        before: float, after: float) -> None:
    verdict = corporate_actions.classify_boundary(
        close_before=before, close_after=after,
        volume_before=1000.0, volume_after=4000.0, qty=Decimal(100))
    assert verdict.kind == corporate_actions.KIND_NONE  # no event, no crash


# ── Engine integration: the clean 4:1 path (dual market, one fixture) ──


@pytest.mark.parametrize("market", ["hk", "us"])
def test_clean_price_ratio_cannot_authorize_a_ledger_split(market: str) -> None:
    # The fixture resembles a 4:1 split, but the same OHLC/volume can be a
    # crash. It cannot authorize creating 300 additional shares.
    market_data = _fetch(market, {_SYM: _fixture_frame()}, _PREV, _EX)
    outcome = engine.run_day_loop(
        market=market,
        account_state=AccountState(cash=100000.0,
                                   positions=(_position(_SYM, 100, 400.0),)),
        from_date=_PREV, to_date=_EX, orders_by_day={}, market_data=market_data,
    )
    assert outcome.error is not None
    assert outcome.error.code == "PAPER_DATA_NOT_READY"
    assert "cannot establish a split" in outcome.error.message
    assert outcome.fills == ()
    assert outcome.nav_series == ()
    assert outcome.end_state.positions[0].qty == 100


@pytest.mark.parametrize(("market", "fee"), [("hk", 63.71), ("us", 1.96)])
def test_no_sale_of_inferred_extra_shares(market: str, fee: float) -> None:
    # from_date IS the ex-date: the BEFORE bar (2026-01-30) lives in the K=120
    # lookback — the note-2 window requirement.  Selling 400 (the ADJUSTED qty)
    # can only fill if the split applied BEFORE matching; without it the ladder
    # would reject insufficient_position (only 100 held).
    market_data = _fetch(market, {_SYM: _fixture_frame()}, _EX, _EX)
    outcome = engine.match_orders(
        _request(market, 10000.0, [_position_dict(_SYM, 100, 400.0)],
                 [{"symbol": _SYM, "side": "sell", "qty": 400}], _EX),
        market_data=market_data,
    )
    assert outcome.error is not None
    assert outcome.error.code == "PAPER_DATA_NOT_READY"
    assert "cannot establish a split" in outcome.error.message
    assert outcome.fills == ()
    assert outcome.nav_series == ()
    assert outcome.end_state.positions[0].qty == 100


def test_clean_split_run_is_deterministic_and_warning_timestamp_free() -> None:
    market_data = _fetch("us", {_SYM: _fixture_frame()}, _PREV, _EX)
    state = AccountState(cash=100000.0, positions=(_position(_SYM, 100, 400.0),))
    first = engine.run_day_loop(market="us", account_state=state, from_date=_PREV, to_date=_EX,
                                orders_by_day={}, market_data=market_data)
    second = engine.run_day_loop(market="us", account_state=state, from_date=_PREV, to_date=_EX,
                                orders_by_day={}, market_data=market_data)
    assert first.warnings == second.warnings
    assert first.nav_series == second.nav_series
    assert first.end_state == second.end_state
    assert first.data_provenance == second.data_provenance
    for warning in first.warnings:  # VD-7: deterministic English, no timestamps
        assert re.search(r"\d{2}:\d{2}", warning) is None


# ── Engine integration: the fail-closed unresolved path ──


@pytest.mark.parametrize(("rows", "ratio_str"), [
    ([("2026-03-02", 100.0, 1_000_000.0), ("2026-03-03", 40.0, 2_500_000.0)], "0.4"),
    ([("2026-03-02", 100.0, 1_000_000.0), ("2026-03-03", 250.0, 400_000.0)], "2.5"),
])
def test_unresolved_discontinuity_rejects_fail_closed_no_half_day(
        rows: list[tuple[str, float, float]], ratio_str: str) -> None:
    day = rows[-1][0]
    market_data = _fetch("us", {"DIRTY.US": _frame(rows)}, day, day)
    outcome = engine.match_orders(
        _request("us", 100000.0, [_position_dict("DIRTY.US", 100, 90.0)],
                 [{"symbol": "DIRTY.US", "side": "buy", "qty": 10}], day),
        market_data=market_data,
    )
    assert outcome.error is None  # in-band structured rejection, never a crash
    assert _codes(outcome) == ["corporate_action_unresolved"]
    assert outcome.rejected_orders[0].reason_code in REASON_CODES  # frozen vocabulary
    assert "fail-closed" in outcome.rejected_orders[0].detail
    assert outcome.fills == ()
    assert len(outcome.nav_series) == 1  # the day still commits exactly one nav row
    position = outcome.end_state.positions[0]
    assert (position.qty, position.avg_cost) == (100, 90.0)  # NOT adjusted
    assert outcome.nav_series[0].position_value == 100 * rows[-1][1]  # valued at the day's close
    assert outcome.data_provenance.corporate_actions == (
        {"symbol": "DIRTY.US", "date": day, "ratio": ratio_str, "detected": False},)
    assert any("corporate action unresolved" in w and "DIRTY.US" in w for w in outcome.warnings)


def test_clean_ratio_with_wrong_volume_rejects_instead_of_splitting() -> None:
    # Exact 0.25 close ratio but flat volume: the engine must NOT silently
    # apply the split — the symbol's orders reject and the ledger stays put.
    frames = {_SYM: _frame([(_PREV, 476.0, 1_000_000.0), (_EX, 119.0, 1_000_000.0)])}
    market_data = _fetch("us", frames, _EX, _EX)
    outcome = engine.match_orders(
        _request("us", 10000.0, [_position_dict(_SYM, 100, 400.0)],
                 [{"symbol": _SYM, "side": "sell", "qty": 400}], _EX),
        market_data=market_data,
    )
    assert _codes(outcome) == ["corporate_action_unresolved"]
    assert outcome.fills == ()
    position = outcome.end_state.positions[0]
    assert (position.qty, position.avg_cost) == (100, 400.0)
    assert outcome.data_provenance.corporate_actions[0]["detected"] is False


def test_missing_volume_on_a_candidate_day_rejects_fail_closed() -> None:
    frames = {"NOVOL.US": _frame([(_PREV, 100.0, 1000.0), (_EX, 50.0, float("nan"))])}
    market_data = _fetch("us", frames, _EX, _EX)
    outcome = engine.match_orders(
        _request("us", 10000.0, [], [{"symbol": "NOVOL.US", "side": "buy", "qty": 10}], _EX),
        market_data=market_data,
    )
    assert _codes(outcome) == ["corporate_action_unresolved"]
    assert outcome.data_provenance.corporate_actions[0]["detected"] is False


def test_injected_t3_seam_unions_with_detector_output_not_replaced() -> None:
    # DIRTY.US is unresolved by the detector; CLEAN.US is healthy but injected
    # through the T3 seam.  BOTH must reject — the merge is a union.
    frames = {
        "DIRTY.US": _frame([(_PREV, 100.0, 1_000_000.0), (_EX, 40.0, 2_500_000.0)]),
        "CLEAN.US": _frame([(_PREV, 50.0, 1000.0), (_EX, 50.5, 1000.0)]),
    }
    market_data = _fetch("us", frames, _EX, _EX)
    outcome = engine.match_orders(
        _request("us", 100000.0, [],
                 [{"symbol": "DIRTY.US", "side": "buy", "qty": 10},
                  {"symbol": "CLEAN.US", "side": "buy", "qty": 10}], _EX),
        market_data=market_data,
        corporate_action_unresolved_by_day={_EX: ["CLEAN.US"]},
    )
    assert _codes(outcome) == ["corporate_action_unresolved", "corporate_action_unresolved"]
    assert {r.symbol for r in outcome.rejected_orders} == {"DIRTY.US", "CLEAN.US"}
    # Only the detector's symbol lands in provenance; the seam stays injection-only.
    assert [e["symbol"] for e in outcome.data_provenance.corporate_actions] == ["DIRTY.US"]


# ── Note 2: lookback history never fires ──


def test_note2_historical_split_in_lookback_never_fires() -> None:
    # Simulate the day AFTER the ex-date: the 4:1 cliff (2026-02-02) is inside
    # the served K=120 lookback but its AFTER-date is not a simulated day, so
    # there is NO event, NO rejection, and a normal order fills.
    market_data = _fetch("us", {_SYM: _fixture_frame()}, _NEXT, _NEXT)
    assert _EX in market_data.data[_SYM].bar_dates  # the split bar IS served (lookback)
    outcome = engine.match_orders(
        _request("us", 100000.0, [_position_dict(_SYM, 100, 119.0)],
                 [{"symbol": _SYM, "side": "buy", "qty": 10}], _NEXT),
        market_data=market_data,
    )
    assert outcome.error is None
    assert _codes(outcome) == []
    assert outcome.data_provenance.corporate_actions == ()
    assert not any("corporate action" in w for w in outcome.warnings)
    assert outcome.fills[0].price == 119.5
    position = outcome.end_state.positions[0]
    assert position.qty == 110
    assert position.avg_cost == 119.0455  # (100×119 + 10×119.5)/110 → 4dp HALF_UP
    # The untouched 100-share position was NOT split-adjusted (note 2).
    assert outcome.nav_series[0].position_value == pytest.approx(110 * 119.5)


def test_no_prior_bar_means_insufficient_evidence_no_event() -> None:
    frames = {"FIRST.US": _frame([(_EX, 100.0, 1000.0)])}  # first bar of the window
    market_data = _fetch("us", frames, _EX, _EX)
    outcome = engine.match_orders(
        _request("us", 100000.0, [], [{"symbol": "FIRST.US", "side": "buy", "qty": 10}], _EX),
        market_data=market_data,
    )
    assert _codes(outcome) == []
    assert len(outcome.fills) == 1
    assert outcome.data_provenance.corporate_actions == ()


def test_non_positive_prior_close_yields_no_event_not_a_crash() -> None:
    # The prior bar fails the R-V3 sanity gate (negative close): the boundary
    # is skipped as insufficient evidence — no event, no crash; the target bar
    # itself is tradable so the order fills.
    frames = {"NEG.US": _frame([(_PREV, -5.0, 1000.0), (_EX, 100.0, 1000.0)])}
    market_data = _fetch("us", frames, _EX, _EX)
    outcome = engine.match_orders(
        _request("us", 100000.0, [], [{"symbol": "NEG.US", "side": "buy", "qty": 10}], _EX),
        market_data=market_data,
    )
    assert _codes(outcome) == []
    assert len(outcome.fills) == 1
    assert outcome.data_provenance.corporate_actions == ()
    assert any("price sanity" in w for w in outcome.warnings)  # data-layer warning kept


# ── cn_a exemption (call-site) ──


def test_raw_cn_a_is_not_exempt_from_detection() -> None:
    # Raw A-share execution must reject the same unresolved discontinuity
    # as HK/US. It cannot use the former adjusted-series exemption.
    frames = {"600000.SH": _frame([(_PREV, 100.0, 1_000_000.0), (_EX, 40.0, 2_500_000.0)])}
    market_data = fetch_market_data("cn_a", ["600000.SH"], _EX, _EX,
                                    loader=FakeLoader(frames, name="tencent"),
                                    ch_client=FakeChClient())
    outcome = engine.match_orders(
        _request("cn_a", 100000.0, [], [{"symbol": "600000.SH", "side": "buy", "qty": 100}], _EX),
        market_data=market_data,
        calendar_client=FakeCalendarClient(frozenset({_EX})),
    )
    assert outcome.error is None
    assert _codes(outcome) == ["corporate_action_unresolved"]
    assert outcome.fills == ()


# ── Skipped semantics with the CA plan active (extends the T3 matrix) ──


def test_market_closed_inferred_skips_with_warning_while_the_plan_is_active() -> None:
    # hk mid-range all-market zero bar (2026-03-03): skipped
    # market_closed_inferred + mandatory warning, no nav row, its defensive
    # order rejects suspended — and the CA scan (matching days only) adds
    # nothing: the neutral 100.0 → 100.5 boundary is not a candidate.
    frames = {"00700.HK": _frame([("2026-03-02", 100.0, 1_000_000.0),
                                  ("2026-03-04", 100.5, 1_000_000.0)])}
    market_data = _fetch("hk", frames, "2026-03-02", "2026-03-04")
    outcome = engine.run_day_loop(
        market="hk", account_state=AccountState(cash=50000.0),
        from_date="2026-03-02", to_date="2026-03-04",
        orders_by_day={"2026-03-03": (Order("00700.HK", "buy", 100),)},
        market_data=market_data,
    )
    assert outcome.error is None
    assert [(s.date, s.reason) for s in outcome.skipped_days] == [
        ("2026-03-03", "market_closed_inferred")]
    assert any("2026-03-03" in w and "inferred closed" in w for w in outcome.warnings)
    assert _codes(outcome) == ["suspended"]  # never non_trading_day for hk/us
    assert [nav.date for nav in outcome.nav_series] == ["2026-03-02", "2026-03-04"]
    assert outcome.data_provenance.corporate_actions == ()


def test_suspended_symbol_carries_forward_beside_a_clean_split() -> None:
    # Per-symbol independence on the ex-date: SYNTH-4TO1 splits cleanly while
    # HALT.US has no bar (suspended) — its order rejects, its position values
    # at the last close (50.0), and the day still commits ONE nav row.
    frames = {
        _SYM: _fixture_frame(),
        "HALT.US": _frame([(_PREV, 50.0, 1000.0)]),
    }
    market_data = _fetch("us", frames, _PREV, _EX, symbols=[_SYM, "HALT.US"])
    outcome = engine.run_day_loop(
        market="us",
        account_state=AccountState(cash=100000.0, positions=(
            _position(_SYM, 100, 400.0), _position("HALT.US", 100, 48.0))),
        from_date=_PREV, to_date=_EX,
        orders_by_day={_EX: (Order("HALT.US", "buy", 10),)},
        market_data=market_data,
    )
    assert outcome.error is not None
    assert outcome.error.code == "PAPER_DATA_NOT_READY"
    assert "cannot establish a split" in outcome.error.message
    assert outcome.fills == ()
    assert outcome.nav_series == ()
    assert outcome.end_state.positions[0].qty == 100


# ── helpers ──


def _position(symbol: str, qty: float, avg_cost: float) -> Position:
    return Position(symbol=symbol, qty=qty, avg_cost=avg_cost)


def _position_dict(symbol: str, qty: float, avg_cost: float) -> dict:
    return {"symbol": symbol, "qty": qty, "avg_cost": avg_cost}
