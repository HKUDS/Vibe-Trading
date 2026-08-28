"""Task 1 + Task 2 factor study on the S&P 500 universe.

Uses only repo tooling for the heavy lifting:
  - panel loading:   src.tools.alpha_bench_tool._load_universe_panel (cached)
  - factor compute:  src.factors.registry (academic zoo)
  - IC / quantiles:  src.tools.factor_analysis_tool.run_factor_analysis
  - costs:           backtest.factor_costs.rebalance_cost
  - purged CV:       src.quantlib.crossvalidation.group_purged_kfold_splits

Custom code here only stitches those pieces together (monthly-rebalance
portfolio construction, Sharpe arithmetic, plots) — the built-in `alpha bench`
does not produce quantile curves, long-short Sharpe, or cost-aware numbers.

Run from the agent/ directory:
    python ../calibration-study/scripts/task1_task2_factor_study.py
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from backtest.factor_costs import rebalance_cost
from src.factors.registry import get_default_registry
from src.quantlib.crossvalidation import group_purged_kfold_splits
from src.tools.alpha_bench_tool import _compute_forward_returns, _load_universe_panel
from src.tools.factor_analysis_tool import run_factor_analysis

ROOT = Path("/home/rucha/HKU-personal-hedge-fund/calibration-study")
ART = ROOT / "artifacts"
PERIOD = "2010-2025"
FACTORS = ["academic_carhart_mom", "academic_bab"]
PRIMARY = "academic_carhart_mom"
SLIPPAGE_BPS = 15.0  # retail assumption: 15 bps per side (10-20 bps range midpoint)
REBAL_FREQ = 21  # trading days ~ monthly
ANN = 252


def sharpe(daily: pd.Series) -> float:
    daily = daily.dropna()
    if len(daily) < 2 or daily.std() == 0:
        return float("nan")
    return float(daily.mean() / daily.std() * np.sqrt(ANN))


def ic_stats(factor: pd.DataFrame, fwd: pd.DataFrame) -> dict:
    from src.factors.factor_analysis_core import compute_ic_series

    ic = compute_ic_series(factor, fwd)
    t = float(ic.mean() / ic.std() * np.sqrt(len(ic))) if len(ic) > 1 else float("nan")
    return {
        "ic_mean": float(ic.mean()),
        "ic_std": float(ic.std()),
        "ir": float(ic.mean() / ic.std()) if ic.std() else float("nan"),
        "ic_positive_ratio": float((ic > 0).mean()),
        "ic_count": int(len(ic)),
        "t_stat": t,
    }


def monthly_portfolio(
    factor: pd.DataFrame,
    close_rets: pd.DataFrame,
    long_short: bool,
    offset: int = 0,
    quantile: float = 0.2,
) -> dict:
    """Monthly-rebalanced quantile portfolio with repo cost model.

    Selection at rebalance date t uses factor values at t; the weights take
    effect the NEXT trading day (t+1 execution, matching the engine's 1-bar
    lag). Weights are held constant between rebalances (weight-space model,
    drift ignored). Costs: `rebalance_cost` with slippage_bps per side,
    adv_value=None (infinite liquidity assumed), fixed impact model, and for
    long-short the US borrow rate on the short leg.
    """
    dates = factor.index
    rebal_idx = list(range(offset, len(dates), REBAL_FREQ))
    weights = pd.DataFrame(0.0, index=dates, columns=factor.columns)
    current = pd.Series(0.0, index=factor.columns)
    cost_by_date: dict[pd.Timestamp, float] = {}
    turnovers = []
    for k, i in enumerate(rebal_idx):
        dt = dates[i]
        row = factor.loc[dt].dropna()
        if len(row) < 50:
            continue
        n_q = max(int(len(row) * quantile), 1)
        ranked = row.sort_values()
        target = pd.Series(0.0, index=factor.columns)
        longs = ranked.index[-n_q:]
        target[longs] = 1.0 / n_q
        if long_short:
            shorts = ranked.index[:n_q]
            target[shorts] = -1.0 / n_q
        pc, _ = rebalance_cost(
            target_weights=target,
            current_weights=current,
            capital=1.0,
            periods_per_year=int(ANN / REBAL_FREQ),
            adv_value=None,
            impact_model="fixed",
            slippage_bps=SLIPPAGE_BPS,
            borrow_market="US" if long_short else None,
        )
        turnovers.append(float((target - current).abs().sum()))
        cost_by_date[dt] = float(pc.total_cost)
        # weights effective from the next trading day
        start = i + 1
        end = rebal_idx[k + 1] + 1 if k + 1 < len(rebal_idx) else len(dates)
        if start < len(dates):
            weights.iloc[start:min(end, len(dates))] = target.values
        current = target
    gross = (weights * close_rets.reindex(dates).fillna(0.0)).sum(axis=1)
    costs = pd.Series(0.0, index=dates)
    for dt, c in cost_by_date.items():
        # charge the cost on the execution day (day after selection)
        loc = dates.get_loc(dt)
        if loc + 1 < len(dates):
            costs.iloc[loc + 1] = c
    net = gross - costs
    return {
        "gross_ann_ret": float((1 + gross).prod() ** (ANN / len(gross)) - 1),
        "net_ann_ret": float((1 + net).prod() ** (ANN / len(net)) - 1),
        "gross_sharpe": sharpe(gross),
        "net_sharpe": sharpe(net),
        "ann_turnover": float(np.mean(turnovers) * ANN / REBAL_FREQ) if turnovers else 0.0,
        "total_cost_drag_ann": float(sum(cost_by_date.values()) * ANN / len(gross)),
        "_gross_series": gross,
        "_net_series": net,
    }


def main() -> None:
    ART.mkdir(exist_ok=True)
    panel = _load_universe_panel("sp500", PERIOD, use_cache=True)
    meta = panel.get("_meta", {})
    fwd = _compute_forward_returns(panel)
    close = panel["close"]
    close_rets = close.pct_change(fill_method=None)
    reg = get_default_registry()

    summary: dict = {"panel_meta": {k: str(v) for k, v in meta.items()}}

    # ---------------- Task 1: IC, quantiles, long-short Sharpe ----------------
    for fid in FACTORS:
        fdir = ART / "task1" / fid
        fdir.mkdir(parents=True, exist_ok=True)
        factor = reg.compute(fid, panel)
        factor.to_csv(fdir / "factor.csv")
        fwd.to_csv(fdir / "fwd_ret.csv")
        res = json.loads(
            run_factor_analysis(
                str(fdir / "factor.csv"), str(fdir / "fwd_ret.csv"), str(fdir), n_groups=5
            )
        )
        ge = pd.read_csv(fdir / "group_equity.csv", index_col=0, parse_dates=True)
        gret = ge.pct_change()
        ls_daily = gret["Group_5"] - gret["Group_1"]
        res["long_short_sharpe_daily_quantiles_frictionless"] = sharpe(ls_daily)
        res["group_final_nav"] = {c: float(ge[c].iloc[-1]) for c in ge.columns}
        res["group_sharpe"] = {c: sharpe(gret[c]) for c in ge.columns}
        res["group_ann_vol"] = {
            c: float(gret[c].std() * np.sqrt(ANN)) for c in ge.columns
        }
        summary.setdefault("task1", {})[fid] = {
            k: v for k, v in res.items() if not k.startswith("_")
        }
        # plots
        ic = pd.read_csv(fdir / "ic_series.csv", index_col=0, parse_dates=True)["IC"]
        fig, ax = plt.subplots(2, 1, figsize=(10, 8))
        ic.rolling(63).mean().plot(ax=ax[0], title=f"{fid}: 63d rolling mean IC")
        ax[0].axhline(0, color="k", lw=0.5)
        ge.plot(ax=ax[1], title=f"{fid}: quantile group equity (frictionless, daily)")
        ax[1].set_yscale("log")
        fig.tight_layout()
        fig.savefig(fdir / "ic_and_groups.png", dpi=120)
        plt.close(fig)

    # ---------------- Task 2 on the primary factor ----------------
    factor = reg.compute(PRIMARY, panel)
    t2: dict = {}

    # Baseline monthly portfolios, gross and net of costs
    for tag, ls in [("long_short", True), ("long_only_top_quintile", False)]:
        r = monthly_portfolio(factor, close_rets, long_short=ls)
        t2[f"baseline_{tag}"] = {k: v for k, v in r.items() if not k.startswith("_")}
        eq = (1 + r["_net_series"]).cumprod()
        eqg = (1 + r["_gross_series"]).cumprod()
        fig, ax = plt.subplots(figsize=(10, 5))
        eqg.plot(ax=ax, label="gross")
        eq.plot(ax=ax, label=f"net ({SLIPPAGE_BPS:.0f} bps/side)")
        ax.legend()
        ax.set_title(f"{PRIMARY} {tag} monthly-rebalance equity")
        fig.tight_layout()
        fig.savefig(ART / "task2" / f"{tag}_equity.png", dpi=120)
        plt.close(fig)

    # Perturbation: shift the rebalance schedule by one trading day
    r = monthly_portfolio(factor, close_rets, long_short=True, offset=1)
    t2["shifted_rebalance_long_short"] = {
        k: v for k, v in r.items() if not k.startswith("_")
    }

    # Perturbation: half samples
    halves = {
        "2010_2017": factor.loc[:"2017-12-31"],
        "2018_2025": factor.loc["2018-01-01":],
    }
    for tag, f_half in halves.items():
        fwd_half = fwd.loc[f_half.index]
        rets_half = close_rets.loc[f_half.index]
        stats = ic_stats(f_half, fwd_half)
        port = monthly_portfolio(f_half, rets_half, long_short=True)
        t2[f"half_{tag}"] = {
            "ic": stats,
            "long_short_net": {k: v for k, v in port.items() if not k.startswith("_")},
        }

    # Purged CV: per-fold out-of-sample IC on date groups
    from src.factors.factor_analysis_core import compute_ic_series

    ic_all = compute_ic_series(factor, fwd)
    dates = ic_all.index
    folds = []
    for split in group_purged_kfold_splits(
        list(dates), n_folds=5, embargo_fraction=0.01
    ):
        test_dates = dates[split.test]
        ic_fold = ic_all.loc[test_dates]
        folds.append(
            {
                "test_start": str(test_dates.min().date()),
                "test_end": str(test_dates.max().date()),
                "ic_mean": float(ic_fold.mean()),
                "t_stat": float(
                    ic_fold.mean() / ic_fold.std() * np.sqrt(len(ic_fold))
                ),
            }
        )
    t2["purged_cv_5fold"] = folds

    summary["task2"] = t2
    (ART / "task12_summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2)[:4000])


if __name__ == "__main__":
    (ART / "task2").mkdir(parents=True, exist_ok=True)
    main()
