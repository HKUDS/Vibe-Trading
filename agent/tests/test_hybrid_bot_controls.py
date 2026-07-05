"""Checks for hybrid_bot dashboard controls: runtime settings, pause flag,
manual position close, and the equity curve builder."""

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


def _patch_state_files(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "POSITIONS_FILE", tmp_path / "positions.json")
    monkeypatch.setattr(runner, "WALLET_FILE", tmp_path / "wallet.json")
    monkeypatch.setattr(runner, "HISTORY_FILE", tmp_path / "history.json")
    monkeypatch.setattr(runner, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(runner, "REJECTED_FILE", tmp_path / "rejected.json")


def test_record_rejected_signal_classifies_and_appends(tmp_path, monkeypatch):
    _patch_state_files(tmp_path, monkeypatch)
    trigger = {
        "symbol": "X/USDT", "signal": "LONG", "strategy": "Momentum Breakout (Squeeze)",
        "close": 1.23, "atr": 0.01,
        "metrics": {"adx": 20.0, "rsi": 60.0, "close": 1.23, "volume_ratio": 3.1},
    }
    r1 = runner.record_rejected_signal(trigger, "Error code: 429 - quota exceeded")
    r2 = runner.record_rejected_signal(trigger, "Validation process failed, rejecting as a safety default: boom")
    r3 = runner.record_rejected_signal(trigger, "Coin was hacked 10 minutes ago.")
    assert (r1["reason_class"], r2["reason_class"], r3["reason_class"]) == ("quota", "error", "news")

    import json
    saved = json.loads((tmp_path / "rejected.json").read_text())
    assert len(saved) == 3
    assert saved[0]["entry_price"] == 1.23
    assert saved[2]["side"] == "LONG"


def test_settings_defaults_and_roundtrip(tmp_path, monkeypatch):
    _patch_state_files(tmp_path, monkeypatch)
    assert runner.get_settings() == runner.DEFAULT_SETTINGS

    updated = runner.update_settings({"max_positions": 5, "paused": True})
    assert updated["max_positions"] == 5
    assert updated["paused"] is True
    # persisted
    assert runner.get_settings()["max_positions"] == 5


def test_settings_validation_rejects_bad_input():
    with pytest.raises(ValueError):
        runner.validate_settings({"max_positions": 0})  # below bound
    with pytest.raises(ValueError):
        runner.validate_settings({"atr_multiplier": 99})  # above bound
    with pytest.raises(ValueError):
        runner.validate_settings({"min_stop_pct": "abc"})  # not a number
    with pytest.raises(ValueError):
        runner.validate_settings({"unknown_key": 1})
    with pytest.raises(ValueError):
        runner.validate_settings({"basket_refresh_hours": 0.5})  # below bound


def test_close_position_exits_and_updates_state(tmp_path, monkeypatch):
    _patch_state_files(tmp_path, monkeypatch)
    runner.save_wallet({"balance": 10000.0, "initial_balance": 10000.0})
    runner.save_positions({
        "X/USDT": {
            "entry_price": 100.0,
            "side": "LONG",
            "trailing_distance": 3.0,
            "stop_loss": 97.0,
            "breakeven_locked": False,
            "position_size": 1000.0,
            "leverage": 2.0,
        }
    })

    closed = runner.close_position(FakeExchange(110.0), "X/USDT")

    assert closed is not None and closed["side"] == "LONG"
    assert runner.get_positions() == {}
    history = runner.get_history()
    assert len(history) == 1
    # perf 10% on $2000 notional = $200 gross, minus 0.1% fees ($2) = $198
    assert history[0]["net_pnl_usd"] == pytest.approx(198.0)
    assert runner.get_wallet()["balance"] == pytest.approx(10198.0)


def test_close_position_unknown_symbol_returns_none(tmp_path, monkeypatch):
    _patch_state_files(tmp_path, monkeypatch)
    assert runner.close_position(FakeExchange(1.0), "NOPE/USDT") is None


def test_scan_markets_skips_when_paused(tmp_path, monkeypatch):
    _patch_state_files(tmp_path, monkeypatch)
    runner.update_settings({"paused": True})

    class BoomExchange:
        def fetch_ohlcv(self, *args, **kwargs):
            raise AssertionError("exchange must not be touched while paused")

        def fetch_ticker(self, *args, **kwargs):
            raise AssertionError("exchange must not be touched while paused")

    runner.scan_markets(BoomExchange())  # must return before any exchange call
    assert runner.get_positions() == {}


def _run_monitor(tmp_path, monkeypatch, pos: dict, price: float):
    _patch_state_files(tmp_path, monkeypatch)
    runner.save_wallet({"balance": 10000.0, "initial_balance": 10000.0})
    runner.save_positions({"X/USDT": pos})
    runner.monitor_positions(FakeExchange(price))
    return runner.get_positions()


def test_profit_ladder_tightens_trail(tmp_path, monkeypatch):
    positions = _run_monitor(tmp_path, monkeypatch, {
        "entry_price": 100.0, "side": "LONG", "trailing_distance": 9.0,
        "stop_loss": 91.0, "breakeven_locked": False,
        "position_size": 1000.0, "atr": 3.0,
    }, price=106.0)
    # ladder off by default: trail stays 9 -> stop = 106-9 = 97... but BE lock lifts to 100.2
    assert positions["X/USDT"]["stop_loss"] == pytest.approx(100.2)

    import time as _time
    runner.update_settings({"ladder_enabled": True})
    runner.save_positions({"X/USDT": {
        "entry_price": 100.0, "side": "LONG", "trailing_distance": 9.0,
        "stop_loss": 91.0, "breakeven_locked": False,
        "position_size": 1000.0, "atr": 3.0,
        "peak_price": 100.0, "peak_time": _time.time(),
    }})
    runner.monitor_positions(FakeExchange(106.0))
    # fav 6% -> tier 1.0 x ATR = 3 -> stop = 106-3 = 103 (beats BE 100.2)
    assert runner.get_positions()["X/USDT"]["stop_loss"] == pytest.approx(103.0)


def test_stale_profit_exit(tmp_path, monkeypatch):
    import time as _time
    _patch_state_files(tmp_path, monkeypatch)
    runner.save_wallet({"balance": 10000.0, "initial_balance": 10000.0})
    runner.update_settings({"stale_exit_minutes": 30})
    runner.save_positions({"X/USDT": {
        "entry_price": 100.0, "side": "LONG", "trailing_distance": 9.0,
        "stop_loss": 100.2, "breakeven_locked": True,
        "position_size": 1000.0, "atr": 3.0,
        "peak_price": 103.0, "peak_time": _time.time() - 3600,  # peak 1h ago
    }})
    runner.monitor_positions(FakeExchange(102.0))  # +2% but stale
    assert runner.get_positions() == {}
    history = runner.get_history()
    assert len(history) == 1
    # exited at market 102: perf 2% on $2000 - $2 fees = $38
    assert history[0]["net_pnl_usd"] == pytest.approx(38.0)


def test_time_stop_cuts_never_working_trade(tmp_path, monkeypatch):
    import time as _time
    _patch_state_files(tmp_path, monkeypatch)
    runner.save_wallet({"balance": 10000.0, "initial_balance": 10000.0})
    runner.update_settings({"time_stop_minutes": 60})
    entry_time = _time.strftime("%Y-%m-%d %H:%M:%S", _time.localtime(_time.time() - 7200))
    runner.save_positions({"X/USDT": {
        "entry_price": 100.0, "side": "SHORT", "trailing_distance": 3.0,
        "stop_loss": 103.0, "breakeven_locked": False, "position_size": 1000.0,
        "atr": 1.0, "peak_price": 100.0, "peak_time": _time.time() - 7200,
        "entry_time": entry_time,
    }})
    runner.monitor_positions(FakeExchange(100.5))  # 2h in, MFE ~0 -> cut
    assert runner.get_positions() == {}

    # a trade that DID reach the MFE threshold must never be time-stopped
    runner.save_positions({"Y/USDT": {
        "entry_price": 100.0, "side": "LONG", "trailing_distance": 3.0,
        "stop_loss": 97.0, "breakeven_locked": False, "position_size": 1000.0,
        "atr": 1.0, "peak_price": 101.0, "peak_time": _time.time() - 3600,
        "entry_time": entry_time,
    }})
    runner.monitor_positions(FakeExchange(100.1))
    assert "Y/USDT" in runner.get_positions()


def test_flip_cooldown(tmp_path, monkeypatch):
    import time as _time
    _patch_state_files(tmp_path, monkeypatch)
    recent = _time.strftime("%Y-%m-%d %H:%M:%S", _time.localtime(_time.time() - 3600))
    old = _time.strftime("%Y-%m-%d %H:%M:%S", _time.localtime(_time.time() - 24 * 3600))
    runner.save_history([
        {"symbol": "OLD/USDT", "side": "LONG", "exit_time": old},
        {"symbol": "X/USDT", "side": "LONG", "exit_time": recent},
    ])
    assert runner.in_flip_cooldown("X/USDT", "SHORT", 12) is True    # opposite, 1h ago
    assert runner.in_flip_cooldown("X/USDT", "LONG", 12) is False    # same direction ok
    assert runner.in_flip_cooldown("OLD/USDT", "SHORT", 12) is False # opposite but 24h ago
    assert runner.in_flip_cooldown("NEW/USDT", "SHORT", 12) is False # never traded
    assert runner.in_flip_cooldown("X/USDT", "SHORT", 0) is False    # knob off


def test_range_position_pct():
    import pandas as pd
    rows = [{"high": 110.0, "low": 90.0, "close": 100.0}] * 50
    rows.append({"high": 110.0, "low": 90.0, "close": 108.0})  # near the top
    df = pd.DataFrame(rows)
    assert runner.range_position_pct(df) == pytest.approx(90.0)  # (108-90)/(110-90)
    rows[-1] = {"high": 110.0, "low": 90.0, "close": 92.0}
    df = pd.DataFrame(rows)
    assert runner.range_position_pct(df) == pytest.approx(10.0)


def test_signal_quality_classifier():
    from agent.src.trading.hybrid_bot.signal_engine import signal_quality
    trending = lambda adx, vol: {"strategy": "Momentum Breakout (Trending)", "metrics": {"adx": adx, "volume_ratio": vol}}
    squeeze = lambda vol: {"strategy": "Momentum Breakout (Squeeze)", "metrics": {"adx": 15.0, "volume_ratio": vol}}
    assert signal_quality(trending(26.8, 2.05)) == "marginal"   # NEAR#1 profile
    assert signal_quality(trending(43.4, 2.51)) == "strong"     # HMSTR profile
    assert signal_quality(trending(44.9, 2.3)) == "marginal"    # vol margin too thin
    assert signal_quality(squeeze(3.03)) == "marginal"          # ALLO profile
    assert signal_quality(squeeze(4.11)) == "strong"            # TLM profile
    assert signal_quality({"strategy": "Mean Reversion", "metrics": {"adx": 10, "volume_ratio": 1.0}}) == "marginal"


def test_exit_records_mfe_and_entry_context(tmp_path, monkeypatch):
    _patch_state_files(tmp_path, monkeypatch)
    runner.save_wallet({"balance": 10000.0, "initial_balance": 10000.0})
    pos = {
        "entry_price": 100.0, "side": "LONG", "position_size": 1000.0, "leverage": 2.0,
        "peak_price": 105.0, "quality": "strong", "strategy": "Momentum Breakout (Trending)",
        "entry_adx": 30.0, "entry_vol_ratio": 2.6, "entry_range_pos": 85.0,
    }
    runner.execute_position_exit("X/USDT", 102.0, pos)
    rec = runner.get_history()[0]
    assert rec["max_favorable_pct"] == pytest.approx(5.0)
    assert rec["quality"] == "strong"
    assert rec["entry_range_pos"] == 85.0


def test_build_report(tmp_path, monkeypatch):
    _patch_state_files(tmp_path, monkeypatch)
    from agent.src.trading.hybrid_bot import report
    runner.save_wallet({"balance": 10100.0, "initial_balance": 10000.0})
    runner.save_history([
        {"symbol": "A/USDT", "side": "LONG", "net_pnl_usd": 200.0, "quality": "strong"},
        {"symbol": "B/USDT", "side": "SHORT", "net_pnl_usd": -100.0, "quality": "marginal"},
    ])
    r = report.build_report()
    assert r["closed_trades"] == 2
    assert r["win_rate_pct"] == 50.0
    assert r["profit_factor"] == pytest.approx(2.0)
    assert r["by_side"]["SHORT"]["net_usd"] == -100.0
    assert r["by_quality"]["marginal"]["count"] == 1


def test_select_basket_blends_volume_and_movers():
    from agent.src.trading.hybrid_bot.basket_manager import select_basket
    pairs = (
        [{"symbol": f"VOL{i}/USDT", "volume": 1000 - i, "change": 1.0} for i in range(20)]
        + [{"symbol": "PUMP/USDT", "volume": 10, "change": 83.0}]   # HMSTR profile: low volume, huge move
    )
    basket = select_basket(pairs, movers_slots=4)
    assert "PUMP/USDT" in basket           # mover slot catches it despite low volume
    assert len(basket) == 20
    assert basket[0] == "VOL0/USDT"        # volume core preserved
    # pure-volume mode misses the pump
    assert "PUMP/USDT" not in select_basket(pairs, movers_slots=0)


def test_detect_regime():
    up = list(range(80, 121))     # rising closes -> last above EMA20
    down = list(range(120, 79, -1))
    assert runner.detect_regime(up) == "up"
    assert runner.detect_regime(down) == "down"


def test_equity_curve_and_dependency_free_html():
    pytest.importorskip("fastapi")  # dashboard needs fastapi (installed in the Docker image)
    from agent.src.trading.hybrid_bot.dashboard import build_equity_curve, index_page

    points = build_equity_curve(10000.0, [
        {"net_pnl_usd": 100.0, "exit_time": "t1"},
        {"net_pnl_usd": -50.0, "exit_time": "t2"},
    ])
    assert [p["balance"] for p in points] == [10000.0, 10100.0, 10050.0]

    html = index_page()
    assert 'id="equity-chart"' in html
    # CSP goal: fully self-contained page, no external CDNs or fonts
    assert "cdn.tailwindcss.com" not in html
    assert "fonts.googleapis.com" not in html
