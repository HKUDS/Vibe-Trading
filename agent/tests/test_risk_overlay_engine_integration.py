"""Engine integration: synthetic OHLCV + risk_overlay + hft_costs + fail-closed gate.

Exercises the live BaseEngine path (not just unit helpers) so regressions in
pre-fill overlay wiring, ADV dollar-volume sources, replace-mode fill
slippage, and risk-first config enforcement are caught end-to-end.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from backtest.engines.global_equity import GlobalEquityEngine
from backtest.hft_config_gate import enforce_risk_first_config


def _ohlcv_book(n: int = 80, seed: int = 7) -> dict[str, pd.DataFrame]:
    """Two-name synthetic OHLCV panel with volume + amount."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2024-01-02", periods=n)
    out: dict[str, pd.DataFrame] = {}
    for code, start in (("AAA.US", 100.0), ("BBB.US", 50.0)):
        rets = rng.normal(0.0005, 0.012, size=n)
        # Inject a drawdown window so kill / CVaR overlays have something to do.
        rets[35:48] = -0.025
        close = start * np.cumprod(1.0 + rets)
        open_ = np.concatenate([[start], close[:-1]])
        high = np.maximum(open_, close) * 1.01
        low = np.minimum(open_, close) * 0.99
        # Deep wick so OHLC stops can fire without close-only breach.
        wick_i = min(40, n - 1)
        low[wick_i] = close[wick_i] * 0.90
        volume = rng.integers(8_000, 20_000, size=n).astype(float)
        amount = close * volume
        out[code] = pd.DataFrame(
            {
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
                "amount": amount,
            },
            index=idx,
        )
    return out


class _FakeLoader:
    def __init__(self, data_map: dict[str, pd.DataFrame]) -> None:
        self._data_map = data_map

    def fetch(self, *args, **kwargs):
        return {k: v.copy() for k, v in self._data_map.items()}


class _FlipSignal:
    """High-turnover long/short flip book to stress participation + costs."""

    def __init__(self, codes: list[str]) -> None:
        self._codes = codes

    def generate(self, data_map):
        out = {}
        for i, code in enumerate(self._codes):
            idx = data_map[code].index
            n = len(idx)
            # Alternate ±0.6 with a phase offset per name.
            sig = np.where((np.arange(n) + i) % 2 == 0, 0.6, -0.6)
            out[code] = pd.Series(sig, index=idx)
        return out


def _base_config(codes: list[str]) -> dict:
    return {
        "codes": codes,
        "start_date": "2024-01-01",
        "end_date": "2024-12-31",
        "interval": "1D",
        "source": "yahoo",
        "initial_cash": 1_000_000,
        "tags": ["hft", "short_horizon"],
        "risk_overlay": {
            "enabled": True,
            "max_gross_leverage": 1.0,
            "max_net_exposure": 0.5,
            "max_name_weight": 0.55,
            "max_turnover": 0.4,
            "max_drawdown_kill": 0.08,
            "kill_cooldown_bars": 3,
            "kill_reset_drawdown": 0.02,
            "stop_loss": 0.05,
            "ohlc_stop": True,
            "inventory_mean_reversion": 0.2,
            "partial_fill_rate": 0.7,
            "max_portfolio_cvar": 0.04,
            "cvar_lookback": 25,
        },
        "hft_costs": {
            "enabled": True,
            "spread_bps": 3.0,
            "impact_coeff": 10.0,
            "impact_power": 0.5,
            "adverse_selection_bps": 2.0,
            "participation_cap": 0.35,
            "max_adv_participation": 0.15,
            "adv_lookback": 10,
            "fill_slippage_mode": "replace",
        },
        "validation": {
            "risk_adjusted_ranking": {
                "objective": "sharpe_dd_penalty",
                "max_dd_limit": 0.2,
                "min_psr": 0.0,
            }
        },
    }


def test_engine_ohlcv_overlay_hft_replace_and_artifacts(tmp_path: Path) -> None:
    data = _ohlcv_book()
    codes = list(data.keys())
    config = _base_config(codes)
    engine = GlobalEquityEngine({"initial_cash": 1_000_000, "slippage_us": 0.01}, market="us")
    metrics = engine.run_backtest(
        config,
        _FakeLoader(data),
        _FlipSignal(codes),
        tmp_path,
    )

    assert metrics.get("final_value") is not None
    assert metrics.get("trade_count", 0) >= 1
    assert metrics.get("hft_costs_enabled") is True
    assert metrics.get("hft_fill_slippage_mode") == "replace"
    assert metrics.get("hft_dollar_volume_sources")
    assert all(v == "volume" for v in metrics["hft_dollar_volume_sources"].values())
    # Overlay diagnostics persisted.
    assert (tmp_path / "artifacts" / "risk_overlay.json").exists()
    assert (tmp_path / "artifacts" / "hft_costs.json").exists()
    # Participation / ADV clips should fire on this flip book.
    assert (metrics.get("hft_participation_clips") or 0) >= 1 or (
        metrics.get("hft_adv_participation_clips") or 0
    ) >= 1


def test_engine_amount_fallback_when_volume_missing(tmp_path: Path) -> None:
    data = _ohlcv_book(n=50, seed=3)
    for frame in data.values():
        frame.drop(columns=["volume"], inplace=True)
    codes = list(data.keys())
    config = _base_config(codes)
    config["hft_costs"]["max_adv_participation"] = 0.1
    engine = GlobalEquityEngine({"initial_cash": 1_000_000}, market="us")
    metrics = engine.run_backtest(
        config,
        _FakeLoader(data),
        _FlipSignal(codes),
        tmp_path,
    )
    sources = metrics.get("hft_dollar_volume_sources") or {}
    assert sources
    assert all(v == "amount" for v in sources.values())
    assert (metrics.get("hft_adv_participation_clips") or 0) >= 1


def test_engine_adv_fallback_notional_when_no_volume_or_amount(tmp_path: Path) -> None:
    data = _ohlcv_book(n=45, seed=11)
    for frame in data.values():
        frame.drop(columns=["volume", "amount"], inplace=True)
    codes = list(data.keys())
    config = _base_config(codes)
    config["hft_costs"]["adv_fallback_notional"] = 50_000.0  # tight ADV → clips
    config["hft_costs"]["max_adv_participation"] = 0.05
    engine = GlobalEquityEngine({"initial_cash": 1_000_000}, market="us")
    metrics = engine.run_backtest(
        config,
        _FakeLoader(data),
        _FlipSignal(codes),
        tmp_path,
    )
    sources = metrics.get("hft_dollar_volume_sources") or {}
    assert all(v == "fallback_notional" for v in sources.values())
    assert (metrics.get("hft_adv_participation_clips") or 0) >= 1


def test_fail_closed_return_only_exits(tmp_path: Path) -> None:
    data = _ohlcv_book(n=30, seed=1)
    codes = list(data.keys())
    config = _base_config(codes)
    config["objective"] = "pnl"  # return-only — must fail closed
    engine = GlobalEquityEngine({"initial_cash": 1_000_000}, market="us")
    with pytest.raises(SystemExit) as excinfo:
        engine.run_backtest(
            config,
            _FakeLoader(data),
            _FlipSignal(codes),
            tmp_path,
        )
    assert excinfo.value.code == 1


def test_replace_mode_cheaper_than_additive_on_same_book(tmp_path: Path) -> None:
    """With large native US slippage, replace must not stack HFT on top."""
    data = _ohlcv_book(n=40, seed=5)
    codes = list(data.keys())

    def _run(mode: str, run_dir: Path) -> float:
        cfg = _base_config(codes)
        cfg["hft_costs"]["fill_slippage_mode"] = mode
        # Disable ADV/participation clips so fill path dominates the comparison.
        cfg["hft_costs"].pop("participation_cap", None)
        cfg["hft_costs"].pop("max_adv_participation", None)
        cfg["risk_overlay"] = {
            "enabled": True,
            "max_gross_leverage": 1.0,
            "max_drawdown_kill": 0.5,  # effectively off
        }
        engine = GlobalEquityEngine(
            {"initial_cash": 1_000_000, "slippage_us": 0.02},
            market="us",
        )
        m = engine.run_backtest(cfg, _FakeLoader(data), _FlipSignal(codes), run_dir)
        return float(m["final_value"])

    replace_fv = _run("replace", tmp_path / "replace")
    additive_fv = _run("additive", tmp_path / "additive")
    # Additive stacks 2% native + ~5 bps HFT → worse fills → lower final value.
    assert replace_fv > additive_fv


def test_inject_defaults_set_replace_and_fallback() -> None:
    cfg = enforce_risk_first_config({"interval": "1m", "codes": ["AAPL.US"]})
    assert cfg["hft_costs"]["fill_slippage_mode"] == "replace"
    assert cfg["hft_costs"]["adv_fallback_notional"] == 5_000_000.0
    assert cfg.get("_risk_first_enforced") is True
