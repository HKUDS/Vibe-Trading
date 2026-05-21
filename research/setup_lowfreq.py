"""Build low-frequency ensemble runs (persistence 4/72) + stress variants."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "runs" / "_templates" / "signal_engine_ensemble_lowfreq.py"
REGIME_PARQUET = ROOT / "research" / "regime_labels.parquet"

RUNS = [
    ("ensemble_lowfreq_bull",     "s2_baseline", "2024-05-14", "2026-05-13"),
    ("ensemble_lowfreq_bear2022", "s2_bear",     "2021-11-08", "2022-12-31"),
    ("ensemble_lowfreq_bear2018", "s2_bear2018", "2018-02-01", "2018-12-30"),
]

STRESS_MULT = 3.0


def build(run_name, src_name, start, end, regime_full, stress=False):
    src = ROOT / "runs" / src_name
    suffix = "_stress" if stress else ""
    dst = ROOT / "runs" / f"{run_name}{suffix}"
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)

    (dst / "code").mkdir()
    shutil.copy(TEMPLATE, dst / "code" / "signal_engine.py")

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
    print(f"  built {dst.relative_to(ROOT)}  stress={stress}")


def main():
    regime = pd.read_parquet(REGIME_PARQUET)
    for run_name, src, s, e in RUNS:
        build(run_name, src, s, e, regime, stress=False)
        build(run_name, src, s, e, regime, stress=True)


if __name__ == "__main__":
    main()
