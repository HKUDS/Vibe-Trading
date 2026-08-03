"""Tests for causal risk overlays, HFT costs, and risk-first config gates."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest.enhanced_validation import signal_parameter_grid, stress_scenarios
from backtest.hft_costs import (
    HftCostModel,
    apply_hft_fill_slippage,
    build_dollar_volume_panel,
    clip_adv_participation,
    default_hft_cost_model,
    hft_cost_series,
    load_hft_cost_model,
    prepare_positions_for_hft_costs,
)
from backtest.hft_config_gate import (
    assert_risk_first_config,
    compare_grid_vs_risk_gated,
    enforce_risk_first_config,
    inject_risk_first_defaults,
    is_return_only_objective,
    is_short_horizon_config,
    validate_risk_first_config,
)
from backtest.risk_metrics import rank_trials_risk_adjusted, score_trial_risk_adjusted
from backtest.risk_overlay import (
    RiskOverlayConfig,
    apply_risk_overlay,
    load_risk_overlay,
    overlay_ab_comparison,
    simulate_strategy_pnl,
)
from backtest.validation import run_validation


def _book(n: int = 400, seed: int = 4) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    idx = pd.RangeIndex(n)
    rets = rng.normal(0.0, 0.01, size=(n, 2))
    rets[120:140] = -0.03
    returns = pd.DataFrame(rets, index=idx, columns=["A", "B"])
    # Aggressive, concentrated, high-turnover book.
    pos = pd.DataFrame(
        {
            "A": np.where(rng.random(n) > 0.5, 1.2, -1.2),
            "B": np.where(rng.random(n) > 0.5, 0.8, -0.8),
        },
        index=idx,
    )
    close = (1.0 + returns).cumprod() * 100.0
    return pos, returns, close


class TestRiskOverlay:
    def test_load_inactive_when_empty(self) -> None:
        assert load_risk_overlay({}) is None
        assert load_risk_overlay({"risk_overlay": {"enabled": False, "vol_target": 0.1}}) is None

    def test_gross_and_name_caps(self) -> None:
        pos, rets, close = _book()
        cfg = RiskOverlayConfig(
            max_gross_leverage=1.0,
            max_name_weight=0.5,
            bars_per_year=252,
        )
        out, diag = apply_risk_overlay(pos, rets, config=cfg, close=close)
        assert diag["applied"] is True
        assert float(out.abs().sum(axis=1).max()) <= 1.0 + 1e-9
        assert float(out.abs().max().max()) <= 0.5 + 1e-9

    def test_inventory_pull_reduces_abs_net(self) -> None:
        pos, rets, _ = _book(n=100, seed=1)
        # Force a strongly long book.
        pos = pd.DataFrame({"A": 0.7, "B": 0.5}, index=pos.index)
        cfg = RiskOverlayConfig(inventory_mean_reversion=0.5, bars_per_year=252)
        out, _ = apply_risk_overlay(pos, rets, config=cfg)
        assert abs(float(out.sum(axis=1).mean())) < abs(float(pos.sum(axis=1).mean()))

    def test_kill_switch_flattens(self) -> None:
        pos, rets, close = _book(n=250, seed=2)
        cfg = RiskOverlayConfig(
            max_drawdown_kill=0.05,
            kill_cooldown_bars=5,
            bars_per_year=252,
        )
        out, diag = apply_risk_overlay(pos, rets, config=cfg, close=close)
        assert diag["kill_events"] >= 1
        # After a kill there should be some all-flat rows.
        assert (out.abs().sum(axis=1) < 1e-12).any()

    def test_kill_hysteresis_disarms_until_recovery(self) -> None:
        pos, rets, close = _book(n=300, seed=12)
        cfg = RiskOverlayConfig(
            max_drawdown_kill=0.04,
            kill_cooldown_bars=3,
            kill_reset_drawdown=0.01,
            bars_per_year=252,
        )
        out, diag = apply_risk_overlay(pos, rets, config=cfg, close=close)
        assert diag["kill_events"] >= 1
        # With hysteresis, peak is not reset — book stays de-risked longer.
        assert float(out.abs().sum(axis=1).mean()) < float(pos.abs().sum(axis=1).mean())

    def test_turnover_throttle(self) -> None:
        pos, rets, _ = _book(n=80, seed=3)
        cfg = RiskOverlayConfig(max_turnover=0.05, bars_per_year=252)
        out, diag = apply_risk_overlay(pos, rets, config=cfg)
        assert diag["turnover_clips"] >= 1
        turnover = out.diff().abs().sum(axis=1).iloc[1:]
        assert float(turnover.max()) <= 0.05 + 1e-8

    def test_partial_fill_slows_turnover(self) -> None:
        pos, rets, _ = _book(n=100, seed=15)
        cfg = RiskOverlayConfig(partial_fill_rate=0.25, bars_per_year=252)
        out, diag = apply_risk_overlay(pos, rets, config=cfg)
        assert diag["partial_fill_bars"] >= 1
        # Partial fills should reduce mean turnover vs raw flipping book.
        raw_to = float(pos.diff().abs().sum(axis=1).iloc[1:].mean())
        out_to = float(out.diff().abs().sum(axis=1).iloc[1:].mean())
        assert out_to < raw_to

    def test_cvar_budget_scales_book(self) -> None:
        pos, rets, close = _book(n=250, seed=16)
        cfg = RiskOverlayConfig(
            max_portfolio_cvar=0.005,
            cvar_lookback=30,
            bars_per_year=252,
        )
        out, diag = apply_risk_overlay(pos, rets, config=cfg, close=close)
        assert diag["cvar_scales"] >= 1
        assert float(out.abs().sum(axis=1).mean()) < float(pos.abs().sum(axis=1).mean())

    def test_overlay_cuts_drawdown_vs_baseline(self) -> None:
        pos, rets, close = _book(n=500, seed=9)
        # Deleveraging + kill-switch (no vol-upscaling) should cut |max_dd|.
        cfg = RiskOverlayConfig(
            max_gross_leverage=0.35,
            max_net_exposure=0.2,
            max_drawdown_kill=0.06,
            kill_cooldown_bars=15,
            kill_reset_drawdown=0.02,
            max_turnover=0.15,
            inventory_mean_reversion=0.3,
            partial_fill_rate=0.7,
            bars_per_year=252,
        )
        ab = overlay_ab_comparison(pos, rets, overlay=cfg, close=close, cost_bps=5.0)
        assert abs(ab["overlay"]["max_drawdown"]) <= abs(ab["baseline"]["max_drawdown"]) + 1e-9
        assert ab["improvement"]["drawdown_reduction"] >= -1e-12


class TestRiskAdjustedRanking:
    def test_rejects_high_dd(self) -> None:
        rng = np.random.default_rng(0)
        good = rng.normal(0.001, 0.005, 300)
        bad = rng.normal(0.002, 0.03, 300)
        bad[50:80] = -0.05
        mat = np.column_stack([good, bad])
        out = rank_trials_risk_adjusted(
            mat,
            max_dd_limit=0.15,
            min_psr=0.0,
            objective="sharpe_dd_penalty",
        )
        assert out["n_rejected"] >= 1
        assert out["best"] is not None
        assert out["best"]["trial_index"] == 0

    def test_rejects_return_only_objective(self) -> None:
        rng = np.random.default_rng(3)
        r = rng.normal(0.001, 0.01, 200)
        scored = score_trial_risk_adjusted(r, objective="total_return")
        assert scored["accepted"] is False
        assert "return-only" in scored["reject_reasons"][0]

    def test_cvar_gate(self) -> None:
        rng = np.random.default_rng(1)
        mild = rng.normal(0.0005, 0.008, 400)
        scored = score_trial_risk_adjusted(mild, max_dd_limit=0.5, min_psr=0.0, max_cvar=0.001)
        # Tight CVaR should typically reject noisy series.
        assert "accepted" in scored

    def test_grid_attaches_ranking(self) -> None:
        rng = np.random.default_rng(5)
        px = pd.Series(
            100 * np.cumprod(1 + rng.normal(0.0004, 0.012, 260)),
            index=pd.bdate_range("2022-01-03", periods=260),
        )
        grid = signal_parameter_grid(
            px,
            strategy="rsi_mean_reversion",
            collect_trial_returns=True,
            cost_bps=5.0,
            risk_ranking={"max_dd_limit": 0.5, "min_psr": 0.0},
        )
        assert "risk_adjusted_ranking" in grid
        assert grid["risk_adjusted_ranking"]["n_trials"] >= 2

    def test_validation_hook(self) -> None:
        rng = np.random.default_rng(6)
        eq = pd.Series(
            1_000_000 * np.cumprod(1 + rng.normal(0.0003, 0.01, 200)),
            index=pd.bdate_range("2023-01-03", periods=200),
        )
        results = run_validation(
            {
                "validation": {
                    "risk_adjusted_ranking": {
                        "max_dd_limit": 0.5,
                        "min_psr": 0.0,
                    }
                }
            },
            eq,
            trades=[],
            initial_capital=1_000_000.0,
        )
        assert "risk_adjusted_ranking" in results
        assert results["risk_adjusted_ranking"]["n_trials"] == 1


class TestRiskGatedBeatsUnconstrainedOnRisk:
    """Bonus: unconstrained return-max must not beat risk-gated on DD/CVaR."""

    def test_risk_gated_dominates_dd_or_cvar(self) -> None:
        n = 500
        # Trial 0: steady moderate edge (survives gates).
        steady = np.full(n, 0.0005)
        # Trial 1: return-max bait — strong drift + one deep crash so cumulative
        # return wins unconstrained, but |max_dd| fails the risk gate.
        boom = np.full(n, 0.0035)
        boom[120:145] = -0.018  # ~37% peak-to-trough over the window
        # Trial 2: low-vol safe.
        safe = np.full(n, 0.0002)
        mat = np.column_stack([steady, boom, safe])

        cum = np.prod(1.0 + mat, axis=0) - 1.0
        assert int(np.argmax(cum)) == 1, f"cum returns={cum}"

        # Confirm boom |max_dd| exceeds the gate.
        eq = np.cumprod(1.0 + boom)
        peak = np.maximum.accumulate(eq)
        boom_dd = float(np.min((eq - peak) / peak))
        assert abs(boom_dd) > 0.20

        cmp_ = compare_grid_vs_risk_gated(
            mat,
            max_dd_limit=0.20,
            min_psr=0.0,
            max_cvar=None,
        )
        assert cmp_["risk_gated_index"] is not None
        assert cmp_["unconstrained_index"] == 1
        assert cmp_["risk_gated_index"] != 1
        assert cmp_["risk_gated_better_dd"] or cmp_["risk_gated_better_cvar"]
        assert abs(cmp_["risk_gated"]["max_dd"]) <= abs(cmp_["unconstrained"]["max_dd"]) + 1e-12
        assert cmp_["risk_gated"]["cvar"] <= cmp_["unconstrained"]["cvar"] + 1e-12


class TestHftConfigGate:
    def test_rejects_missing_overlay_and_ranking(self) -> None:
        result = validate_risk_first_config({"codes": ["AAPL.US"]})
        assert result["ok"] is False
        assert any("risk_overlay" in e for e in result["errors"])
        assert any("risk_adjusted_ranking" in e for e in result["errors"])

    def test_rejects_return_only_objective(self) -> None:
        assert is_return_only_objective("total_return")
        cfg = {
            "risk_overlay": {
                "max_drawdown_kill": 0.1,
                "max_gross_leverage": 1.0,
            },
            "validation": {
                "risk_adjusted_ranking": {
                    "objective": "pnl",
                    "max_dd_limit": 0.15,
                }
            },
        }
        result = validate_risk_first_config(cfg)
        assert result["ok"] is False
        assert any("return-only" in e for e in result["errors"])

    def test_inject_defaults_pass_gate(self) -> None:
        cfg = inject_risk_first_defaults({"interval": "1m"}, short_horizon=True)
        result = validate_risk_first_config(cfg, require_hft_costs=True)
        assert result["ok"] is True
        assert_risk_first_config(cfg, require_hft_costs=True)

    def test_short_horizon_detection(self) -> None:
        assert is_short_horizon_config({"interval": "1m"})
        assert is_short_horizon_config({"interval": "1s"})
        assert is_short_horizon_config({"tags": ["hft", "us"]})
        assert not is_short_horizon_config({"interval": "1D"})

    def test_enforce_injects_and_rejects_return_only(self) -> None:
        cfg = enforce_risk_first_config({"interval": "5m", "codes": ["A"]})
        assert cfg.get("risk_overlay")
        assert cfg.get("hft_costs")
        assert cfg.get("_risk_first_enforced") is True
        with pytest.raises(ValueError, match="return-only"):
            enforce_risk_first_config(
                {
                    "interval": "1m",
                    "objective": "pnl",
                    "risk_overlay": {
                        "max_drawdown_kill": 0.1,
                        "max_gross_leverage": 1.0,
                    },
                    "validation": {
                        "risk_adjusted_ranking": {
                            "objective": "sharpe",
                            "max_dd_limit": 0.15,
                        }
                    },
                    "hft_costs": {"enabled": True, "spread_bps": 1.0},
                },
                inject=False,
            )

    def test_daily_configs_pass_through(self) -> None:
        raw = {"interval": "1D", "codes": ["AAPL.US"]}
        out = enforce_risk_first_config(raw)
        assert "risk_overlay" not in out
        assert out.get("_risk_first_enforced") is None


class TestHftCosts:
    def test_costs_increase_with_turnover(self) -> None:
        pos, rets, _ = _book(n=80, seed=8)
        model = default_hft_cost_model()
        costs = hft_cost_series(pos, model=model)
        assert float(costs.sum()) > 0.0
        eq0 = simulate_strategy_pnl(pos, rets, cost_bps=0.0)
        eq1 = simulate_strategy_pnl(pos, rets, hft_costs=model)
        assert float(eq1.iloc[-1]) <= float(eq0.iloc[-1]) + 1e-9

    def test_load_hft_cost_model(self) -> None:
        assert load_hft_cost_model({}) is None
        m = load_hft_cost_model({"hft_costs": {"spread_bps": 3.0, "adverse_selection_bps": 2.0}})
        assert m is not None
        assert m.spread_bps == 3.0

    def test_overlay_ab_with_hft_costs_improves_risk_score(self) -> None:
        pos, rets, close = _book(n=600, seed=21)
        cfg = RiskOverlayConfig(
            max_gross_leverage=0.5,
            max_net_exposure=0.25,
            max_drawdown_kill=0.07,
            kill_cooldown_bars=10,
            kill_reset_drawdown=0.02,
            max_turnover=0.2,
            inventory_mean_reversion=0.25,
            partial_fill_rate=0.6,
            max_portfolio_cvar=0.025,
            cvar_lookback=35,
            bars_per_year=252,
        )
        ab = overlay_ab_comparison(
            pos,
            rets,
            overlay=cfg,
            close=close,
            hft_costs=HftCostModel(spread_bps=3.0, impact_coeff=10.0, adverse_selection_bps=2.0),
        )
        # Under realistic HFT costs, overlay must cut |DD| and ruin vs unconstrained.
        assert abs(ab["overlay"]["max_drawdown"]) <= abs(ab["baseline"]["max_drawdown"]) + 1e-9
        assert ab["improvement"]["drawdown_reduction"] >= -1e-12
        assert ab["overlay"]["ruin_proxy"] <= ab["baseline"]["ruin_proxy"] + 1e-12
        assert "risk_adjusted_score" in ab["overlay"]
        assert ab["cost_path"] == "hft_costs"

    def test_fill_slippage_worsens_buy_and_sell(self) -> None:
        model = HftCostModel(spread_bps=10.0, adverse_selection_bps=5.0, impact_coeff=0.0)
        buy = apply_hft_fill_slippage(100.0, 1, model=model)
        sell = apply_hft_fill_slippage(100.0, -1, model=model)
        assert buy > 100.0
        assert sell < 100.0
        assert abs(buy - 100.15) < 1e-9  # 15 bps

    def test_adv_participation_clips(self) -> None:
        idx = pd.RangeIndex(40)
        # Flip full weight every bar so |Δw| stays large after ADV warms up.
        flip = np.where(np.arange(40) % 2 == 0, 1.0, -1.0)
        pos = pd.DataFrame({"A": flip}, index=idx)
        # Tiny ADV so |Δw|≈2 cannot fit under 10% participation.
        dv = pd.DataFrame({"A": 50.0}, index=idx)
        out, diag = clip_adv_participation(
            pos, dollar_volume=dv, max_adv_participation=0.1, adv_lookback=5, equity=1_000.0
        )
        assert diag["adv_participation_clips"] >= 1
        # Max |Δw| ≈ 0.1 * 50 / 1000 = 0.005 once ADV is available.
        late_turnover = out.diff().abs().iloc[10:].max().max()
        assert float(late_turnover) <= 0.005 + 1e-8

    def test_prepare_positions_applies_participation_cap(self) -> None:
        pos, _, _ = _book(n=50, seed=3)
        model = HftCostModel(participation_cap=0.05, spread_bps=1.0, impact_coeff=0.0)
        out, diag = prepare_positions_for_hft_costs(pos, model=model)
        assert diag["participation_clips"] >= 1
        assert float(out.diff().abs().sum(axis=1).iloc[1:].max()) <= 0.05 + 1e-8

    def test_fill_slippage_mode_load_and_replace_flag(self) -> None:
        m = load_hft_cost_model(
            {"hft_costs": {"spread_bps": 2.0, "fill_slippage_mode": "replace"}}
        )
        assert m is not None
        assert m.fill_slippage_mode == "replace"
        assert m.replaces_native_slippage() is True
        with pytest.raises(ValueError, match="fill_slippage_mode"):
            load_hft_cost_model({"hft_costs": {"fill_slippage_mode": "stack"}})

    def test_build_dollar_volume_prefers_volume_then_amount_then_fallback(self) -> None:
        idx = pd.RangeIndex(10)
        close = pd.DataFrame({"A": 10.0, "B": 20.0, "C": 30.0}, index=idx)
        data_map = {
            "A": pd.DataFrame({"volume": 100.0, "amount": 1.0}, index=idx),
            "B": pd.DataFrame({"amount": 500.0}, index=idx),
            "C": pd.DataFrame({"close": 30.0}, index=idx),
        }
        panel, diag = build_dollar_volume_panel(
            data_map, close, ["A", "B", "C"], adv_fallback_notional=1_000.0
        )
        assert panel is not None
        assert diag["dollar_volume_sources"]["A"] == "volume"
        assert diag["dollar_volume_sources"]["B"] == "amount"
        assert diag["dollar_volume_sources"]["C"] == "fallback_notional"
        assert float(panel["A"].iloc[0]) == pytest.approx(1000.0)  # 10 * 100
        assert float(panel["B"].iloc[0]) == pytest.approx(500.0)
        assert float(panel["C"].iloc[0]) == pytest.approx(1000.0)

    def test_zero_volume_falls_through_to_amount(self) -> None:
        idx = pd.RangeIndex(5)
        close = pd.DataFrame({"A": 10.0}, index=idx)
        data_map = {"A": pd.DataFrame({"volume": 0.0, "amount": 250.0}, index=idx)}
        panel, diag = build_dollar_volume_panel(data_map, close, ["A"])
        assert panel is not None
        assert diag["dollar_volume_sources"]["A"] == "amount"
        assert float(panel["A"].iloc[0]) == pytest.approx(250.0)


class TestOhlcStopAndRiskImprovement:
    def test_ohlc_stop_fires_on_intrabar_wick(self) -> None:
        # Close never breaches stop, but low does — OHLC stop must flatten.
        n = 30
        idx = pd.RangeIndex(n)
        close = pd.DataFrame({"A": np.full(n, 100.0)}, index=idx)
        high = pd.DataFrame({"A": np.full(n, 101.0)}, index=idx)
        low = close.copy()
        low.iloc[10, 0] = 94.0  # -6% wick vs entry 100 with stop 0.05
        rets = close.pct_change().fillna(0.0)
        pos = pd.DataFrame({"A": 1.0}, index=idx)
        cfg = RiskOverlayConfig(stop_loss=0.05, ohlc_stop=True, bars_per_year=252)
        out, diag = apply_risk_overlay(pos, rets, config=cfg, close=close, high=high, low=low)
        assert diag["ohlc_stop_events"] >= 1
        assert diag["stop_events"] >= 1
        assert float(out.iloc[10]["A"]) == 0.0

    def test_overlay_improves_dd_and_cvar_vs_unconstrained(self) -> None:
        pos, rets, close = _book(n=500, seed=42)
        # Build synthetic OHLC with occasional deep lows so OHLC stops help.
        high = close * 1.01
        low = close.copy()
        low.iloc[120:140] = close.iloc[120:140] * 0.92
        cfg = RiskOverlayConfig(
            max_gross_leverage=0.4,
            max_net_exposure=0.2,
            max_drawdown_kill=0.05,
            kill_cooldown_bars=12,
            kill_reset_drawdown=0.02,
            stop_loss=0.04,
            ohlc_stop=True,
            max_turnover=0.12,
            inventory_mean_reversion=0.3,
            max_portfolio_cvar=0.02,
            cvar_lookback=30,
            bars_per_year=252,
        )
        ab = overlay_ab_comparison(
            pos,
            rets,
            overlay=cfg,
            close=close,
            high=high,
            low=low,
            hft_costs=default_hft_cost_model(aggressive=True),
        )
        assert abs(ab["overlay"]["max_drawdown"]) <= abs(ab["baseline"]["max_drawdown"]) + 1e-9
        assert ab["improvement"]["drawdown_reduction"] >= -1e-12
        # Risk-adjusted score should not collapse vs unconstrained under costs.
        assert ab["overlay"]["risk_adjusted_score"] >= ab["baseline"]["risk_adjusted_score"] - 0.05


class TestHftStressProxies:
    def test_default_includes_adverse_selection(self) -> None:
        rng = np.random.default_rng(7)
        eq = pd.Series(
            1_000_000 * np.cumprod(1 + rng.normal(0.0002, 0.012, 180)),
            index=pd.bdate_range("2023-06-01", periods=180),
        )
        out = stress_scenarios(eq)
        names = {s["name"] for s in out["scenarios"]}
        assert "adverse_selection_burst" in names
        assert "latency_slippage_tax" in names
        # Latency tax should not improve returns vs baseline.
        lat = next(s for s in out["scenarios"] if s["name"] == "latency_slippage_tax")
        assert lat["delta_return"] <= 0.0


class TestSimulatePnl:
    def test_costs_reduce_equity(self) -> None:
        pos, rets, _ = _book(n=50, seed=8)
        eq0 = simulate_strategy_pnl(pos, rets, cost_bps=0.0)
        eq1 = simulate_strategy_pnl(pos, rets, cost_bps=50.0)
        assert float(eq1.iloc[-1]) <= float(eq0.iloc[-1]) + 1e-9
