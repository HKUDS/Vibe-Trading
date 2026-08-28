"""Task 3: compare the semiconductor-basket strategies from their run artifacts.

Reads each run's artifacts/equity.csv + metrics.csv, restricts to the common
active window (activation 2019-01-02 onward), and reports CAGR, vol, Sharpe,
max drawdown (full window and calendar-2022), turnover, and an equity chart.

Run from anywhere:
    calibration-study/.venv/bin/python calibration-study/scripts/task3_compare.py
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path("/home/rucha/HKU-personal-hedge-fund/calibration-study")
RUNS = {
    "buy_and_hold": ROOT / "runs" / "semis_bh",
    "ma200_trend": ROOT / "runs" / "semis_ma200",
    "mom_12_1_top_half": ROOT / "runs" / "semis_mom",
    "inverse_vol": ROOT / "runs" / "semis_invvol",
}
ACTIVATION = "2019-01-02"
ANN = 252


def metrics_from_equity(eq: pd.Series) -> dict:
    eq = eq.loc[ACTIVATION:]
    eq = eq / eq.iloc[0]
    rets = eq.pct_change().dropna()
    years = len(rets) / ANN
    dd = eq / eq.cummax() - 1
    dd22 = dd.loc["2022-01-01":"2022-12-31"]
    return {
        "start": str(eq.index[0].date()),
        "end": str(eq.index[-1].date()),
        "total_return": float(eq.iloc[-1] - 1),
        "cagr": float(eq.iloc[-1] ** (1 / years) - 1),
        "ann_vol": float(rets.std() * np.sqrt(ANN)),
        "sharpe_rf0": float(rets.mean() / rets.std() * np.sqrt(ANN)),
        "max_drawdown": float(dd.min()),
        "max_drawdown_2022": float(dd22.min()) if len(dd22) else float("nan"),
    }


def main() -> None:
    out: dict = {}
    fig, ax = plt.subplots(figsize=(11, 6))
    for name, run in RUNS.items():
        eq_df = pd.read_csv(
            run / "artifacts" / "equity.csv", index_col=0, parse_dates=True
        )
        eq = eq_df["equity"]
        m = metrics_from_equity(eq)
        met = pd.read_csv(run / "artifacts" / "metrics.csv").iloc[0]
        m["engine_avg_turnover_daily"] = float(met["avg_turnover"])
        m["engine_total_turnover"] = float(met["total_turnover"])
        m["engine_trade_count"] = int(met["trade_count"])
        m["engine_sharpe_full_window"] = float(met["sharpe"])
        card = json.loads((run / "run_card.json").read_text())
        m["data_sources"] = card.get("data_sources")
        out[name] = m
        (eq.loc[ACTIVATION:] / eq.loc[ACTIVATION:].iloc[0]).plot(ax=ax, label=name)
    ax.set_yscale("log")
    ax.set_title(
        "Semiconductor basket, 2019+ (net of 10 bps/side slippage, adjusted prices)"
    )
    ax.legend()
    fig.tight_layout()
    fig.savefig(ROOT / "artifacts" / "task3_equity_curves.png", dpi=120)

    (ROOT / "artifacts" / "task3_summary.json").write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
