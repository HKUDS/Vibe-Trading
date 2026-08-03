"""Hard invariants for risk overlay, HFT costs, and fail-closed gates.

These are the non-negotiable properties the risk-first stack must keep:
  - replace-mode fill haircut ≤ additive (no double-count path is cheaper)
  - exposure caps hold after vol / CVaR / governor scaling
  - kill-switch is monotone through cooldown (stays flat)
  - fail-closed gate always rejects return-only objectives
  - turnover cost feedback never increases |Δw|
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

from backtest.engines.base import BaseEngine  # may be abstract — use fill helper
from backtest.hft_config_gate import (
    enforce_risk_first_config,
    inject_risk_first_defaults,
    validate_risk_first_config,
)
from backtest.hft_costs import HftCostModel, apply_hft_fill_slippage
from backtest.risk_overlay import RiskOverlayConfig, apply_risk_overlay

settings.register_profile("vibe-invariants", max_examples=40, deadline=None)
settings.load_profile("vibe-invariants")


_weight_rows = st.integers(min_value=2, max_value=4).flatmap(
    lambda n: st.lists(
        st.lists(
            st.floats(min_value=-1.5, max_value=1.5, allow_nan=False, allow_infinity=False),
            min_size=n,
            max_size=n,
        ),
        min_size=25,
        max_size=80,
    )
)


def _frames(rows):
    n_bars = len(rows)
    n_names = len(rows[0])
    idx = pd.RangeIndex(n_bars)
    cols = [f"S{i}" for i in range(n_names)]
    pos = pd.DataFrame(rows, index=idx, columns=cols)
    rng = np.random.default_rng(0)
    rets = pd.DataFrame(rng.normal(0.0, 0.01, size=(n_bars, n_names)), index=idx, columns=cols)
    return pos, rets


# ---------------------------------------------------------------------------
# replace ≤ additive haircut
# ---------------------------------------------------------------------------


@given(
    st.floats(min_value=1.0, max_value=10_000.0, allow_nan=False, allow_infinity=False),
    st.sampled_from([-1, 1]),
    st.floats(min_value=0.0, max_value=50.0, allow_nan=False, allow_infinity=False),
    st.floats(min_value=0.0, max_value=50.0, allow_nan=False, allow_infinity=False),
    st.floats(min_value=0.0, max_value=0.01, allow_nan=False, allow_infinity=False),
)
def test_replace_haircut_leq_additive(price, direction, spread, adverse, native_slip):
    """Replace uses only HFT bps; additive stacks native slip → worse or equal fill."""
    model = HftCostModel(spread_bps=spread, adverse_selection_bps=adverse, impact_coeff=0.0)
    hft_only = apply_hft_fill_slippage(price, direction, model=model)
    # Engine additive path: native slip then HFT on top.
    signed = 1 if direction >= 0 else -1
    slipped = price * (1.0 + signed * native_slip)
    additive = apply_hft_fill_slippage(slipped, direction, model=model)

    if direction >= 0:
        # Buys: higher price is worse; replace ≤ additive.
        assert hft_only <= additive + 1e-9
        assert hft_only >= price - 1e-9
    else:
        # Sells: lower price is worse; replace ≥ additive.
        assert hft_only >= additive - 1e-9
        assert hft_only <= price + 1e-9


def test_replace_mode_flag_skips_native_in_execution_price():
    """BaseEngine._execution_price replace path must equal pure HFT haircut."""

    class _Toy(BaseEngine):
        def __init__(self):
            self.config = {}
            self._hft_cost_model = HftCostModel(
                spread_bps=10.0,
                adverse_selection_bps=5.0,
                impact_coeff=0.0,
                fill_slippage_mode="replace",
            )

        def can_execute(self, symbol, direction, bar):  # noqa: ANN001
            return True

        def round_size(self, raw_size: float, price: float) -> float:
            return raw_size

        def calc_commission(self, size, price, direction, is_open):  # noqa: ANN001
            return 0.0

        def apply_slippage(self, price: float, direction: int) -> float:
            return price * (1.0 + (1 if direction >= 0 else -1) * 0.01)

    toy = object.__new__(_Toy)
    _Toy.__init__(toy)
    px = toy._execution_price(100.0, 1)
    pure = apply_hft_fill_slippage(100.0, 1, model=toy._hft_cost_model)
    assert px == pytest.approx(pure)
    assert px < toy.apply_slippage(100.0, 1)  # replace ignored the 1% native slip


# ---------------------------------------------------------------------------
# exposure caps survive vol / CVaR scale
# ---------------------------------------------------------------------------


@given(
    _weight_rows,
    st.floats(min_value=0.2, max_value=0.9, allow_nan=False, allow_infinity=False),
    st.floats(min_value=0.05, max_value=0.5, allow_nan=False, allow_infinity=False),
)
def test_caps_hold_after_vol_and_cvar_scale(rows, gross_cap, net_cap):
    """Vol targeting must never leave gross/net above configured caps."""
    pos, rets = _frames(rows)
    name_cap = min(0.45, gross_cap)
    cfg = RiskOverlayConfig(
        vol_target=0.05,  # often scales UP from quiet synthetic noise
        vol_lookback=10,
        max_gross_leverage=gross_cap,
        max_net_exposure=net_cap,
        max_name_weight=name_cap,
        max_portfolio_cvar=0.01,
        cvar_lookback=15,
        bars_per_year=252,
    )
    out, diag = apply_risk_overlay(pos, rets, config=cfg)
    assert diag["applied"] is True
    assert float(out.abs().sum(axis=1).max()) <= gross_cap + 1e-6
    assert float(out.sum(axis=1).abs().max()) <= net_cap + 1e-6
    assert float(out.abs().max().max()) <= name_cap + 1e-6


@given(_weight_rows)
def test_turnover_cost_feedback_never_increases_delta(rows):
    pos, rets = _frames(rows)
    cfg = RiskOverlayConfig(
        turnover_cost_feedback=0.0001,
        turnover_cost_bps=50.0,
        bars_per_year=252,
    )
    out, diag = apply_risk_overlay(pos, rets, config=cfg)
    if diag.get("turnover_cost_clips", 0) == 0:
        return  # property vacuous on this draw
    raw_to = float(pos.diff().abs().sum(axis=1).iloc[1:].mean())
    out_to = float(out.diff().abs().sum(axis=1).iloc[1:].mean())
    assert out_to <= raw_to + 1e-9


# ---------------------------------------------------------------------------
# kill-switch monotonicity
# ---------------------------------------------------------------------------


def test_kill_switch_cooldown_stays_flat():
    n = 120
    idx = pd.RangeIndex(n)
    # Steady losses so DD trips quickly.
    rets = pd.DataFrame({"A": np.full(n, -0.02), "B": np.full(n, -0.02)}, index=idx)
    pos = pd.DataFrame({"A": 0.5, "B": 0.5}, index=idx)
    cooldown = 8
    cfg = RiskOverlayConfig(
        max_drawdown_kill=0.05,
        kill_cooldown_bars=cooldown,
        bars_per_year=252,
    )
    out, diag = apply_risk_overlay(pos, rets, config=cfg)
    assert diag["kill_events"] >= 1
    # Find first all-flat bar after activity — subsequent cooldown bars stay flat.
    gross = out.abs().sum(axis=1).to_numpy()
    kill_idxs = np.where(gross < 1e-12)[0]
    assert len(kill_idxs) >= cooldown
    # Contiguous flat run of at least cooldown length.
    run = 1
    max_run = 1
    for i in range(1, len(gross)):
        if gross[i] < 1e-12 and gross[i - 1] < 1e-12:
            run += 1
            max_run = max(max_run, run)
        else:
            run = 1 if gross[i] < 1e-12 else 0
    assert max_run >= cooldown


# ---------------------------------------------------------------------------
# fail-closed gate
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "objective",
    ["return", "total_return", "pnl", "raw_return", "profit", "cumret", "mean_return"],
)
def test_fail_closed_rejects_return_only_always(objective: str) -> None:
    cfg = {
        "interval": "1m",
        "risk_overlay": {"max_drawdown_kill": 0.1, "max_gross_leverage": 1.0},
        "hft_costs": {"enabled": True, "spread_bps": 1.0, "fill_slippage_mode": "replace"},
        "validation": {
            "risk_adjusted_ranking": {
                "objective": objective,
                "max_dd_limit": 0.15,
            }
        },
    }
    result = validate_risk_first_config(cfg, require_hft_costs=True)
    assert result["ok"] is False
    assert any("return-only" in e for e in result["errors"])


def test_fail_closed_rejects_additive_fill_mode_when_hft_required() -> None:
    cfg = inject_risk_first_defaults({"interval": "1m"}, short_horizon=True)
    cfg["hft_costs"] = {
        "enabled": True,
        "spread_bps": 2.0,
        "fill_slippage_mode": "additive",
    }
    result = validate_risk_first_config(cfg, require_hft_costs=True)
    assert result["ok"] is False
    assert any("fill_slippage_mode" in e for e in result["errors"])


def test_inject_coerces_replace_and_sobol() -> None:
    cfg = inject_risk_first_defaults(
        {
            "interval": "5m",
            "hft_costs": {"enabled": True, "spread_bps": 1.0},  # mode missing → replace
            "validation": {"monte_carlo_paths": {"method": "gbm", "n_paths": 1000}},
        },
        short_horizon=True,
    )
    assert cfg["hft_costs"]["fill_slippage_mode"] == "replace"
    assert cfg["validation"]["monte_carlo_paths"]["sampling"] == "sobol"
    assert cfg["validation"]["risk_adjusted_ranking"].get("min_dsr") is not None
    assert "walk_forward_risk_gated" in cfg["validation"]
    out = enforce_risk_first_config(cfg, inject=False)
    assert out.get("_risk_first_enforced") is True

    # Explicit additive must survive inject (research A/B); gate rejects when required.
    cfg_add = inject_risk_first_defaults(
        {
            "interval": "5m",
            "hft_costs": {"enabled": True, "spread_bps": 1.0, "fill_slippage_mode": "additive"},
        },
        short_horizon=True,
    )
    assert cfg_add["hft_costs"]["fill_slippage_mode"] == "additive"


# ---------------------------------------------------------------------------
# correlation cluster + vol governor smoke
# ---------------------------------------------------------------------------


def test_corr_cluster_cap_reduces_gross_on_fused_book() -> None:
    n = 100
    idx = pd.RangeIndex(n)
    rng = np.random.default_rng(7)
    # Two highly correlated names + one independent.
    common = rng.normal(0.0, 0.01, size=n)
    rets = pd.DataFrame(
        {
            "A": common + rng.normal(0.0, 0.001, size=n),
            "B": common + rng.normal(0.0, 0.001, size=n),
            "C": rng.normal(0.0, 0.01, size=n),
        },
        index=idx,
    )
    pos = pd.DataFrame({"A": 0.5, "B": 0.5, "C": 0.2}, index=idx)
    cfg = RiskOverlayConfig(
        max_corr_cluster_gross=0.4,
        corr_cluster_threshold=0.5,
        corr_lookback=30,
        bars_per_year=252,
    )
    out, diag = apply_risk_overlay(pos, rets, config=cfg)
    assert diag["corr_cluster_clips"] >= 1
    # Late bars (warm corr) should keep A+B cluster gross ≤ 0.4.
    late = out.iloc[40:]
    cluster_gross = late[["A", "B"]].abs().sum(axis=1)
    assert float(cluster_gross.max()) <= 0.4 + 1e-6


def test_vol_governor_only_downscales_on_spike() -> None:
    n = 200
    idx = pd.RangeIndex(n)
    rets = pd.DataFrame({"A": 0.001}, index=idx)
    rets.iloc[120:160] = -0.04  # vol spike window
    pos = pd.DataFrame({"A": 1.0}, index=idx)
    cfg = RiskOverlayConfig(
        vol_target=0.15,
        vol_lookback=10,
        vol_governor_lookback=60,
        vol_governor_spike_ratio=1.2,
        bars_per_year=252,
    )
    out, diag = apply_risk_overlay(pos, rets, config=cfg)
    assert diag["vol_governor_scales"] >= 1
    # During/after spike the governor should shrink below a pure vol-target book.
    cfg_no_gov = RiskOverlayConfig(
        vol_target=0.15,
        vol_lookback=10,
        bars_per_year=252,
    )
    out_plain, _ = apply_risk_overlay(pos, rets, config=cfg_no_gov)
    assert float(out.iloc[140:180].abs().mean().mean()) <= float(
        out_plain.iloc[140:180].abs().mean().mean()
    ) + 1e-9
