"""T8 gate — paper-trade performance budget (REQUIREMENTS §7 T8, plan §T8).

Budgets (fixture environment; live-network latency is out of scope — the RM
E2E measures that separately):

* single day, single account, 10 positions + 10 orders: < 60s;
* 5-trading-day catch-up: < 300s in BOTH accepted forms — five sequential
  orders-mode single-day calls threading ``end_state`` → ``account_state``
  (AM-3/RM-2), AND one strategy_path call spanning the five days.  The
  strategy form runs the REAL executor: one spawned child per call (~4s
  startup) inside the budget — never faked (plan §T8).

Deterministic and offline: injected fake loaders serve synthetic flat frames
(zero network — the ``--disable-socket`` hard gate covers this file), every
date is injected, the tool reads no clock.  Budgets are asserted with
``time.perf_counter()``, never merely printed.  All tests carry the
registered ``slow`` marker (pyproject.toml): optional to select via ``-m
slow``, mandatory at the delivery gate, re-run quarterly against rot.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pandas as pd
import pytest

from src.config.paths import get_runtime_root
from src.tools.paper_trade.tool import run_paper_trade_step

pytestmark = pytest.mark.slow

_SINGLE_DAY_BUDGET_S = 60.0
_CATCHUP_BUDGET_S = 300.0

_MARKET = "us"
_ACCOUNT = "pa_perf"
_SYM = "PERF-00.US"
_SYMBOLS = tuple(f"PERF-{i:02d}.US" for i in range(10))

# Five consecutive trading days (Mon..Fri, us zero-calendar: served bars on
# every weekday make all five matching days — no market_closed_inferred skip).
_CATCHUP_DAYS = ("2026-03-02", "2026-03-03", "2026-03-04", "2026-03-05", "2026-03-06")
_SINGLE_DAY = _CATCHUP_DAYS[-1]

# §4 us default fee matrix, injected explicitly (AM-4-3).  Every scheduled
# qty prices at flat 100.0, so each fee = max(qty×0.0049, 0.99) = 0.99.
_FEE_MODEL = {"commission_per_share": 0.0049, "commission_min": 0.99, "sec_fee_rate": 0.0}

# The 5-day order schedule, shared by BOTH catch-up forms so they exercise
# identical matching work: buy 100 / sell 40 / buy 60 / sell 20 / sell 100.
_SCHEDULE = (
    [{"symbol": _SYM, "side": "buy", "qty": 100}],
    [{"symbol": _SYM, "side": "sell", "qty": 40}],
    [{"symbol": _SYM, "side": "buy", "qty": 60}],
    [{"symbol": _SYM, "side": "sell", "qty": 20}],
    [{"symbol": _SYM, "side": "sell", "qty": 100}],
)
_FINAL_CASH = 99995.05  # 100000 −10000.99 +3999.01 −6000.99 +1999.01 +9999.01


class FakeLoader:
    """Fixture-environment network leg: serves pre-built frames, zero I/O."""

    def __init__(self, frames: dict[str, pd.DataFrame], name: str = "sina") -> None:
        self.name = name
        self._frames = frames

    def is_available(self) -> bool:
        return True

    def fetch(self, codes, start_date, end_date, *, interval="1D", fields=None):
        return {c: self._frames[c] for c in codes if c in self._frames}


def _flat_frames(symbols: tuple[str, ...], end_day: str, *, bars: int = 130) -> dict[str, pd.DataFrame]:
    """Per-symbol flat 100.0 frame: ``bars`` business days ending ``end_day``.

    Flat closes keep the T4 detector silent (close-to-close ratio 1.0 — no
    clean split ratio, no unresolved discontinuity) and cover the frozen
    K=120 lookback window (VD-6/B3), mirroring the production fetch shape.
    """
    days = pd.bdate_range(end=end_day, periods=bars)
    frame = pd.DataFrame(
        {"trade_date": days, "open": 100.0, "high": 100.0, "low": 100.0,
         "close": 100.0, "volume": 10000.0}
    ).set_index("trade_date")
    return {symbol: frame for symbol in symbols}


def _payload(**overrides) -> dict:
    base = {
        "account_id": _ACCOUNT,
        "market": _MARKET,
        "account_state": {"cash": 100000.0, "positions": []},
        "from_date": _SINGLE_DAY,
        "to_date": _SINGLE_DAY,
        "fee_model": dict(_FEE_MODEL),
    }
    base.update(overrides)
    return base


def test_single_day_ten_positions_ten_orders_under_budget() -> None:
    # T8 gate form 1: single day, single account, ≤10 positions + ≤10 orders.
    payload = _payload(
        account_state={
            "cash": 1000000.0,
            "positions": [{"symbol": s, "qty": 100, "avg_cost": 100.0} for s in _SYMBOLS],
        },
        orders=[{"symbol": s, "side": "sell", "qty": 50} for s in _SYMBOLS],
    )
    loader = FakeLoader(_flat_frames(_SYMBOLS, _SINGLE_DAY))

    started = time.perf_counter()
    doc = json.loads(run_paper_trade_step(payload, loader=loader))
    elapsed = time.perf_counter() - started

    assert elapsed < _SINGLE_DAY_BUDGET_S, (
        f"single-day step took {elapsed:.2f}s, budget {_SINGLE_DAY_BUDGET_S}s")
    assert "status" not in doc, doc  # success document, not an error envelope
    assert len(doc["fills"]) == 10
    assert all(f["side"] == "sell" and f["qty"] == 50.0 and f["price"] == 100.0
               for f in doc["fills"])
    # 1000000 + 10×(50×100.0 − 0.99); every position keeps 50 shares.
    assert doc["end_state"]["cash"] == 1049990.1
    assert sorted(p["qty"] for p in doc["end_state"]["positions"]) == [50.0] * 10


def test_five_day_orders_catchup_under_budget() -> None:
    # T8 gate form 2a: five sequential single-day orders-mode calls (AM-3),
    # threading day k−1's end_state into day k's account_state (RM-2) over
    # the JSON wire shape — the mechanical catch-up RM performs.
    loader = FakeLoader(_flat_frames((_SYM,), _CATCHUP_DAYS[-1]))
    state: dict = {"cash": 100000.0, "positions": []}
    docs: list[dict] = []

    started = time.perf_counter()
    for day, orders in zip(_CATCHUP_DAYS, _SCHEDULE, strict=True):
        doc = json.loads(run_paper_trade_step(
            _payload(account_state=state, orders=orders, from_date=day, to_date=day),
            loader=loader))
        assert "status" not in doc, doc
        docs.append(doc)
        state = {
            "cash": doc["end_state"]["cash"],
            "positions": [dict(p) for p in doc["end_state"]["positions"]],
        }
    elapsed = time.perf_counter() - started

    assert elapsed < _CATCHUP_BUDGET_S, (
        f"5-day orders catch-up took {elapsed:.2f}s, budget {_CATCHUP_BUDGET_S}s")
    assert [len(doc["fills"]) for doc in docs] == [1, 1, 1, 1, 1]
    assert [doc["range"]["from"] for doc in docs] == list(_CATCHUP_DAYS)
    assert docs[-1]["end_state"]["cash"] == _FINAL_CASH
    assert docs[-1]["end_state"]["positions"] == []


_STRATEGY_SOURCE = '''"""Date-keyed 5-day schedule strategy (T8 perf gate, strategy_path form)."""

UNIVERSE = ("PERF-00.US",)

_SCHEDULE = {
    "2026-03-02": [{"symbol": "PERF-00.US", "side": "buy", "qty": 100, "reason": "perf d1"}],
    "2026-03-03": [{"symbol": "PERF-00.US", "side": "sell", "qty": 40, "reason": "perf d2"}],
    "2026-03-04": [{"symbol": "PERF-00.US", "side": "buy", "qty": 60, "reason": "perf d3"}],
    "2026-03-05": [{"symbol": "PERF-00.US", "side": "sell", "qty": 20, "reason": "perf d4"}],
    "2026-03-06": [{"symbol": "PERF-00.US", "side": "sell", "qty": 100, "reason": "perf d5"}],
}


class SignalEngine:
    def generate_signals(self, ctx, trade_date):
        return _SCHEDULE.get(trade_date, [])
'''


def test_five_day_strategy_path_single_call_under_budget() -> None:
    # T8 gate form 2b: ONE strategy_path call over the five trading days.
    # The real T7 executor runs — one spawned child (~4s startup) inside the
    # budget.  The declared UNIVERSE prefetches the cash-only account's
    # symbol (T6×T7 integration convention).
    root = get_runtime_root() / "strategies"
    root.mkdir(parents=True, exist_ok=True)
    strategy = root / "perf_schedule_5day.py"
    strategy.write_text(_STRATEGY_SOURCE, encoding="utf-8")

    loader = FakeLoader(_flat_frames((_SYM,), _CATCHUP_DAYS[-1]))
    payload = _payload(
        strategy_path=str(strategy),
        from_date=_CATCHUP_DAYS[0], to_date=_CATCHUP_DAYS[-1],
    )

    started = time.perf_counter()
    doc = json.loads(run_paper_trade_step(payload, loader=loader))
    elapsed = time.perf_counter() - started

    assert elapsed < _CATCHUP_BUDGET_S, (
        f"5-day strategy_path call took {elapsed:.2f}s, budget {_CATCHUP_BUDGET_S}s")
    assert "status" not in doc, doc
    assert [f["trade_date"] for f in doc["fills"]] == list(_CATCHUP_DAYS)
    assert [f["reason"] for f in doc["fills"]] == [
        "perf d1", "perf d2", "perf d3", "perf d4", "perf d5"]
    assert len(doc["nav_series"]) == 5
    assert doc["end_state"]["cash"] == _FINAL_CASH
    assert doc["end_state"]["positions"] == []


def test_strategy_file_resides_in_the_fixture_sandbox() -> None:
    # Guard for the perf form 2b prerequisite: the runtime root is the
    # conftest-sandboxed ~/.vibe-trading (VIBE_TRADING_HOME popped, HOME
    # redirected), never the user's real home.
    assert Path(get_runtime_root()).is_relative_to(Path.home())
    assert get_runtime_root().name == ".vibe-trading"
    assert "vibe-trading-test-home-" in str(Path.home())
