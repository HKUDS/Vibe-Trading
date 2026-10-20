"""T4 gate (orders form): 3 sequential single-day calls thread state (AM-3).

Day k's ``account_state`` = day k-1's ``end_state`` converted to the wire
shape ``{cash, positions:[{symbol,qty,avg_cost}]}`` — the mechanical
threading RM performs for orders-mode catch-up (AM-3/RM-2).  The chain-hash
assertion is R7-5's catch-up check computed IN THE TEST (T5 owns the
``received_state_hash`` wire field; ``MatchOutcome`` deliberately does not
carry it): the hash over call k's injected state / effective fee model /
dates must equal ``sha256(JCS(day k-1 end_state as account_state shape))``
under the same frozen AM-4-1 coverage object.
Market = us (T+0), frame = the frozen ``synthetic_split_4to1`` fixture's
post-split region (2026-02-03..05, closes 119.5/120.0/120.5) — which also
implicitly exercises note 2: the 4:1 cliff (2026-02-02) sits inside every
call's K=120 lookback and must never fire.

The T4-gate strategy_path form (T7) lives at the bottom: ONE call over three
trading days whose range spans a weekend (2026-02-05..09), the same order
schedule threaded through the engine's internal day chaining, and the
byte-identical replay obligation (sha256 over the canonical outcome dump)
that only this form carries.
Offline: fixture-backed fake loader.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path

import pandas as pd

from src.config.paths import get_runtime_root
from src.tools.paper_trade import engine, state_hash, strategy_exec
from src.tools.paper_trade.data import fetch_market_data
from src.tools.paper_trade.schema import parse_request

_FIXTURE = Path(__file__).parent / "fixtures" / "paper_trade" / "market" / "synthetic_split_4to1.json"
_SYM = "SYNTH-4TO1"
_ACCOUNT = "pa_multiday"
_MARKET = "us"

# §4 us default fee matrix, injected explicitly (AM-4-3: RM always injects).
_FEE_MODEL = {
    "commission_per_share": 0.0049,
    "commission_min": 0.99,
    "sec_fee_rate": 0.0,
}

_DAYS = ("2026-02-03", "2026-02-04", "2026-02-05")
_ORDERS = (
    [{"symbol": _SYM, "side": "buy", "qty": 100}],
    [{"symbol": _SYM, "side": "sell", "qty": 50}, {"symbol": _SYM, "side": "buy", "qty": 20}],
    [{"symbol": _SYM, "side": "sell", "qty": 70}],
)


class FakeLoader:
    def __init__(self, frames: dict[str, pd.DataFrame], name: str = "sina") -> None:
        self.name = name
        self._frames = frames

    def is_available(self) -> bool:
        return True

    def fetch(self, codes, start_date, end_date, *, interval="1D", fields=None):
        return {c: self._frames[c] for c in codes if c in self._frames}


def _fixture_frame() -> pd.DataFrame:
    document = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    frame = pd.DataFrame(document["bars"])
    frame["trade_date"] = pd.to_datetime(frame["date"])
    return frame.set_index("trade_date")[["open", "high", "low", "close", "volume"]]


def _fetch(day: str):
    return fetch_market_data(_MARKET, [_SYM], day, day,
                             loader=FakeLoader({_SYM: _fixture_frame()}))


def _state_shape(end_state) -> dict:
    # end_state → account_state wire shape (the exact conversion RM threads).
    return {
        "cash": end_state.cash,
        "positions": [
            {"symbol": p.symbol, "qty": p.qty, "avg_cost": p.avg_cost}
            for p in end_state.positions
        ],
    }


def _effective_fee_model() -> dict:
    return state_hash.effective_fee_model(_MARKET, dict(_FEE_MODEL))


def _hash(account_state: dict, day: str) -> str:
    return state_hash.compute_received_state_hash(
        account_id=_ACCOUNT, market=_MARKET, account_state=account_state,
        fee_model=_effective_fee_model(), from_date=day, to_date=day,
    )


def _run_sequence() -> list[tuple[str, dict, object]]:
    # Returns [(day, injected_state, outcome)] for the 3-call catch-up chain.
    runs: list[tuple[str, dict, object]] = []
    state: dict = {"cash": 50000.0, "positions": []}
    for day, orders in zip(_DAYS, _ORDERS):
        request = parse_request({
            "account_id": _ACCOUNT, "market": _MARKET, "account_state": state,
            "orders": orders, "from_date": day, "to_date": day,
            "fee_model": dict(_FEE_MODEL),
        })
        outcome = engine.match_orders(request, market_data=_fetch(day))
        assert outcome.error is None
        runs.append((day, state, outcome))
        # Wire round-trip: the next call's state is the JSON-parsed end_state
        # (proves JCS stability across serialization, not just in-memory).
        state = json.loads(json.dumps(_state_shape(outcome.end_state)))
    return runs


def test_chain_hash_equals_prior_end_state_under_the_frozen_coverage() -> None:
    runs = _run_sequence()
    assert [day for day, _, _ in runs] == list(_DAYS)
    for k in (1, 2):
        day, injected, _ = runs[k]
        prev_shape = _state_shape(runs[k - 1][2].end_state)
        # R7-5 chain check: call k's hash over the injected state ≡ the hash
        # over day k-1's end_state in the account_state shape.
        assert _hash(injected, day) == _hash(prev_shape, day)
        # Literal JCS form: sha256(JCS(end_state as account_state shape)).
        assert state_hash.state_hash(injected) == state_hash.state_hash(prev_shape)
        assert injected == prev_shape  # threading is lossless (float round-trip)


def test_three_day_ledger_continuity_hand_computed() -> None:
    first, second, third = (outcome for _, _, outcome in _run_sequence())

    # Day 1 (2026-02-03, close 119.5): buy 100 → notional 11950.00, fee
    # max(100×0.0049, 0.99) = 0.99; cash 50000 − 11950.99 = 38049.01.
    assert [(f.side, f.qty, f.price, f.fee) for f in first.fills] == [
        ("buy", 100, 119.5, 0.99)]
    assert first.end_state.cash == 38049.01
    assert first.end_state.positions[0].qty == 100
    assert first.end_state.positions[0].avg_cost == 119.5
    assert [(n.date, n.nav) for n in first.nav_series] == [("2026-02-03", 49999.01)]

    # Day 2 (close 120.0): sell 50 → +6000.00 − 0.99; buy 20 → −2400.00 − 0.99;
    # cash 38049.01 + 5999.01 − 2400.99 = 41647.03; qty 70, avg_cost
    # (50×119.5 + 20×120.0)/70 = 8375/70 = 119.642857… → 4dp HALF_UP 119.6429.
    assert [(f.side, f.qty, f.price, f.fee) for f in second.fills] == [
        ("sell", 50, 120.0, 0.99), ("buy", 20, 120.0, 0.99)]
    assert second.rejected_orders == ()
    assert second.end_state.cash == 41647.03
    assert second.end_state.positions[0].qty == 70
    assert second.end_state.positions[0].avg_cost == 119.6429
    assert [(n.date, n.nav) for n in second.nav_series] == [("2026-02-04", 50047.03)]

    # Day 3 (close 120.5): sell 70 → +8435.00 − 0.99; cash 41647.03 + 8434.01
    # = 50081.04; the position closes out (zero-qty rows dropped).
    assert [(f.side, f.qty, f.price, f.fee) for f in third.fills] == [
        ("sell", 70, 120.5, 0.99)]
    assert third.end_state.cash == 50081.04
    assert third.end_state.positions == ()
    assert [(n.date, n.nav) for n in third.nav_series] == [("2026-02-05", 50081.04)]

    for outcome in (first, second, third):
        assert outcome.skipped_days == ()
        # Note 2: the 2026-02-02 split sits in every call's lookback and the
        # detector never fires on it — no events, no rejections, no warnings.
        assert outcome.data_provenance.corporate_actions == ()
        assert not any("corporate action" in w for w in outcome.warnings)


def test_sequence_replay_is_deterministic() -> None:
    first_run = _run_sequence()
    second_run = _run_sequence()
    for (_, _, a), (_, _, b) in zip(first_run, second_run):
        assert a.fills == b.fills
        assert a.rejected_orders == b.rejected_orders
        assert a.nav_series == b.nav_series
        assert a.end_state == b.end_state
        assert a.warnings == b.warnings
        assert a.data_provenance == b.data_provenance
        assert a.effective_fee_model == b.effective_fee_model == _effective_fee_model()


# ── T4-gate strategy_path form (T7): ONE call, 3 trading days, weekend inside ──

_STRATEGY_SCHEDULE_SOURCE = '''"""Date-keyed schedule strategy (T4 gate, strategy_path form)."""

_SCHEDULE = {
    "2026-02-05": [{"symbol": "SYNTH-4TO1", "side": "buy", "qty": 100, "reason": "form day 1"}],
    "2026-02-06": [
        {"symbol": "SYNTH-4TO1", "side": "sell", "qty": 50, "reason": "form day 2 exit"},
        {"symbol": "SYNTH-4TO1", "side": "buy", "qty": 20, "reason": "form day 2 re-entry"},
    ],
    "2026-02-09": [{"symbol": "SYNTH-4TO1", "side": "sell", "qty": 70, "reason": "form day 3"}],
}


class SignalEngine:
    def generate_signals(self, ctx, trade_date):
        return _SCHEDULE.get(trade_date, [])
'''


def _install_strategy(name: str, source: str) -> str:
    # The T7 path policy only admits <runtime_root>/strategies; the conftest
    # HOME sandbox makes that a per-session temp dir.
    root = get_runtime_root() / "strategies"
    root.mkdir(parents=True, exist_ok=True)
    path = root / name
    path.write_text(source, encoding="utf-8")
    return str(path)


def _run_strategy_form():
    request = parse_request({
        "account_id": _ACCOUNT, "market": _MARKET,
        "account_state": {"cash": 50000.0, "positions": []},
        "from_date": "2026-02-05", "to_date": "2026-02-09",
        "strategy_path": _install_strategy("multiday_form.py", _STRATEGY_SCHEDULE_SOURCE),
        "fee_model": dict(_FEE_MODEL),
    })
    market_data = fetch_market_data(_MARKET, [_SYM], "2026-02-05", "2026-02-09",
                                    loader=FakeLoader({_SYM: _fixture_frame()}))
    return strategy_exec.run_strategy_path(request=request, market_data=market_data)


def _canonical_sha(outcome) -> str:
    # test_run_card.py:330-353 instrument: sha256 over the canonical JSON dump.
    document = {
        "fills": [dataclasses.astuple(fill) for fill in outcome.fills],
        "rejected": [dataclasses.astuple(item) for item in outcome.rejected_orders],
        "nav": [dataclasses.astuple(point) for point in outcome.nav_series],
        "skipped": [dataclasses.astuple(item) for item in outcome.skipped_days],
        "end_state": dataclasses.astuple(outcome.end_state),
        "warnings": list(outcome.warnings),
        "provenance": dataclasses.astuple(outcome.data_provenance),
        "fee_model": outcome.effective_fee_model,
        "error": dataclasses.astuple(outcome.error) if outcome.error is not None else None,
    }
    text = json.dumps(document, sort_keys=True, default=str,
                      separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_strategy_path_single_call_three_day_form() -> None:
    outcome = _run_strategy_form()
    assert outcome.error is None
    # One call, three matching days (02-05 Thu, 02-06 Fri, 02-09 Mon); the
    # weekend is inside the range and implicit for us — no skip rows, nav
    # continues across it.  Closes 120.5/121.0/121.5; hand-computed chain:
    # d1 −12050.99 → 37949.01; d2 +6049.01 −2420.99 → 41577.03 (70 @ 120.6429);
    # d3 +8504.01 → 50081.04 — identical to the orders-form chain above, but
    # threaded INSIDE the single call (previous day's end_state = next day's
    # input, R1-2).
    assert [(f.trade_date, f.side, f.qty, f.price, f.fee) for f in outcome.fills] == [
        ("2026-02-05", "buy", 100, 120.5, 0.99),
        ("2026-02-06", "sell", 50, 121.0, 0.99),
        ("2026-02-06", "buy", 20, 121.0, 0.99),
        ("2026-02-09", "sell", 70, 121.5, 0.99),
    ]
    # VD-15/B2 strategy mode: the strategy's reason text reaches every fill.
    assert [f.reason for f in outcome.fills] == [
        "form day 1", "form day 2 exit", "form day 2 re-entry", "form day 3"]
    assert outcome.end_state.cash == 50081.04
    assert outcome.end_state.positions == ()
    assert [(n.date, n.nav) for n in outcome.nav_series] == [
        ("2026-02-05", 49999.01), ("2026-02-06", 50047.03), ("2026-02-09", 50081.04)]
    assert outcome.skipped_days == ()
    assert outcome.rejected_orders == ()
    # Note 2 in strategy mode: the 4:1 cliff (2026-02-02) sits inside the
    # K=120 lookback and never fires — no events, no rejections, no warnings.
    assert outcome.data_provenance.corporate_actions == ()
    assert not any("corporate action" in w for w in outcome.warnings)
    assert outcome.effective_fee_model == _effective_fee_model()


def test_strategy_path_replay_is_byte_identical() -> None:
    # The byte-identical replay obligation rides THIS form only (plan §T4
    # gate): two full runs — separate spawned children, separate fetches —
    # must produce the same sha256 over the canonical outcome dump.
    assert _canonical_sha(_run_strategy_form()) == _canonical_sha(_run_strategy_form())
