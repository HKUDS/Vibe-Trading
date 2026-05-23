"""Persistence sweep on ensemble engine — confirm 3/48 is a plateau.

For each (win, hits) config × 3 regimes × {base, stress}:
1. Build a tmp run dir with patched signal_engine.py
2. Run backtest
3. Collect Sharpe / Return / DD / trade count

Output: research/persistence_sweep.md
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "runs" / "_templates" / "signal_engine_ensemble_gated.py"
REGIME_PARQUET = ROOT / "research" / "regime_labels.parquet"
SWEEP_ROOT = ROOT / "runs" / "_sweep"

PERIODS = [
    ("bull",     "s2_baseline", "2024-05-14", "2026-05-13"),
    ("bear2022", "s2_bear",     "2021-11-08", "2022-12-31"),
    ("bear2018", "s2_bear2018", "2018-02-01", "2018-12-30"),
]

CONFIGS = [
    (24, 2),
    (36, 2),
    (48, 2),
    (36, 3),
    (48, 3),
    (60, 3),
    (48, 4),
    (72, 4),
]

STRESS_MULT = 3.0


def patch_engine(template_text: str, win: int, hits: int) -> str:
    t = template_text
    t = t.replace("self.PERSISTENCE_WIN = 24", f"self.PERSISTENCE_WIN = {win}")
    t = t.replace("self.PERSISTENCE_HITS = 2", f"self.PERSISTENCE_HITS = {hits}")
    return t


def build_one(period_name, src_name, start, end, win, hits, stress, regime_full, template_text):
    src = ROOT / "runs" / src_name
    tag = f"w{win}h{hits}" + ("_stress" if stress else "")
    dst = SWEEP_ROOT / f"{period_name}_{tag}"
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    (dst / "code").mkdir()
    (dst / "code" / "signal_engine.py").write_text(patch_engine(template_text, win, hits), encoding="utf-8")
    (dst / "factor_data").mkdir()
    shutil.copy(src / "factor_data" / "funding.parquet", dst / "factor_data" / "funding.parquet")
    shutil.copy(src / "factor_data" / "fng.parquet", dst / "factor_data" / "fng.parquet")
    rg = regime_full.loc[start:end][["regime"]]
    rg.to_parquet(dst / "factor_data" / "regime.parquet")
    cfg = json.loads((src / "config.json").read_text())
    cfg["start_date"] = start
    cfg["end_date"] = end
    cfg["leverage"] = 1.5
    if stress:
        cfg["maker_rate"] = round(cfg["maker_rate"] * STRESS_MULT, 6)
        cfg["taker_rate"] = round(cfg["taker_rate"] * STRESS_MULT, 6)
        cfg["slippage"] = round(cfg["slippage"] * STRESS_MULT, 6)
    (dst / "config.json").write_text(json.dumps(cfg, indent=2))
    return dst


def run_one(run_dir: Path) -> dict:
    proc = subprocess.run(
        [sys.executable, "-m", "backtest.runner", str(run_dir)],
        capture_output=True, text=True, cwd=str(ROOT),
    )
    if proc.returncode != 0:
        return {"sharpe": None, "ret": None, "dd": None, "trades": None, "err": proc.stderr[-200:]}
    metrics_path = run_dir / "artifacts" / "metrics.csv"
    if not metrics_path.exists():
        return {"sharpe": None, "ret": None, "dd": None, "trades": None, "err": "no metrics"}
    m = pd.read_csv(metrics_path)
    row = m.iloc[0]
    return {
        "sharpe": float(row["sharpe"]),
        "ret": float(row["total_return"]),
        "dd": float(row["max_drawdown"]),
        "trades": int(row["trade_count"]),
    }


def main():
    SWEEP_ROOT.mkdir(parents=True, exist_ok=True)
    template_text = TEMPLATE.read_text(encoding="utf-8")
    regime = pd.read_parquet(REGIME_PARQUET)

    rows = []
    for period_name, src_name, start, end in PERIODS:
        for win, hits in CONFIGS:
            for stress in (False, True):
                run_dir = build_one(period_name, src_name, start, end, win, hits, stress, regime, template_text)
                res = run_one(run_dir)
                rows.append({
                    "period": period_name, "win": win, "hits": hits,
                    "stress": stress, **res,
                })
                tag = f"{period_name} w{win}h{hits}{'_stress' if stress else ''}"
                if res.get("sharpe") is None:
                    print(f"  {tag}  ERROR  {res.get('err', '')[:80]}")
                else:
                    print(f"  {tag}  Sharpe={res['sharpe']:+.2f}  Ret={res['ret']*100:+.1f}%  DD={res['dd']*100:.1f}%  Trades={res['trades']}")

    df = pd.DataFrame(rows)
    out_csv = ROOT / "research" / "persistence_sweep.csv"
    df.to_csv(out_csv, index=False)
    print(f"\nSaved {out_csv.relative_to(ROOT)}")

    print("\n=== Sharpe sum across 3 regimes per config ===")
    print(f"{'win/hits':>10s}  {'base sum':>10s}  {'stress sum':>11s}  {'(base bull / b22 / b18)':>30s}")
    for win, hits in CONFIGS:
        sub = df[(df.win == win) & (df.hits == hits)]
        base_sum = sub[~sub.stress]["sharpe"].sum()
        stress_sum = sub[sub.stress]["sharpe"].sum()
        per = sub[~sub.stress].set_index("period")["sharpe"]
        print(f"  {win}/{hits:<6d}  {base_sum:+9.2f}  {stress_sum:+10.2f}  "
              f"{per.get('bull', 0):+.2f} / {per.get('bear2022', 0):+.2f} / {per.get('bear2018', 0):+.2f}")


if __name__ == "__main__":
    main()
