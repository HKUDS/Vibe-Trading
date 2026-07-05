"""Breakeven-lock clamp checks for the hybrid_bot position monitor.

The breakeven lock must never move a trailing stop backwards (down for LONG,
up for SHORT) when the trail has already passed the breakeven level.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# hybrid_bot modules import each other via `agent.src....`, which needs the repo root.
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent.src.trading.hybrid_bot import runner


class FakeExchange:
    def __init__(self, price: float):
        self.price = price

    def fetch_ticker(self, symbol: str) -> dict:
        return {"last": self.price}


def _run_monitor(tmp_path, monkeypatch, pos: dict, price: float) -> dict:
    monkeypatch.setattr(runner, "POSITIONS_FILE", tmp_path / "positions.json")
    monkeypatch.setattr(runner, "WALLET_FILE", tmp_path / "wallet.json")
    monkeypatch.setattr(runner, "HISTORY_FILE", tmp_path / "history.json")
    monkeypatch.setattr(runner, "SETTINGS_FILE", tmp_path / "settings.json")
    runner.save_positions({"X/USDT": pos})
    runner.monitor_positions(FakeExchange(price))
    return runner.get_positions()["X/USDT"]


def test_breakeven_lock_does_not_lower_long_trailing_stop(tmp_path, monkeypatch):
    pos = {
        "entry_price": 100.0,
        "side": "LONG",
        "trailing_distance": 3.0,
        "stop_loss": 102.0,  # trail already above breakeven level 100.2
        "breakeven_locked": False,
        "position_size": 1000.0,
    }
    updated = _run_monitor(tmp_path, monkeypatch, pos, price=106.0)
    assert updated["breakeven_locked"] is True
    # trail moves to 106 - 3 = 103; breakeven must not clamp it back to 100.2
    assert updated["stop_loss"] == pytest.approx(103.0)


def test_breakeven_lock_does_not_raise_short_trailing_stop(tmp_path, monkeypatch):
    pos = {
        "entry_price": 100.0,
        "side": "SHORT",
        "trailing_distance": 3.0,
        "stop_loss": 97.0,  # trail already below breakeven level 99.8
        "breakeven_locked": False,
        "position_size": 1000.0,
    }
    updated = _run_monitor(tmp_path, monkeypatch, pos, price=93.0)
    assert updated["breakeven_locked"] is True
    # trail moves to 93 + 3 = 96; breakeven must not clamp it back to 99.8
    assert updated["stop_loss"] == pytest.approx(96.0)


def test_breakeven_lock_engages_normally(tmp_path, monkeypatch):
    pos = {
        "entry_price": 100.0,
        "side": "LONG",
        "trailing_distance": 10.0,  # trail stays below entry, breakeven should win
        "stop_loss": 98.5,
        "breakeven_locked": False,
        "position_size": 1000.0,
    }
    updated = _run_monitor(tmp_path, monkeypatch, pos, price=101.3)
    assert updated["breakeven_locked"] is True
    assert updated["stop_loss"] == pytest.approx(100.2)
