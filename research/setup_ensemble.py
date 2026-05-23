"""Build ensemble S2+S3+S4 (gated by v1c) runs for bull / bear2022 / bear2018."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

TEMPLATE = ROOT / "runs" / "_templates" / "signal_engine_ensemble_gated.py"
REGIME_PARQUET = ROOT / "research" / "regime_labels.parquet"

RUNS = [
    ("ensemble_bull",     "s2_baseline",  "2024-05-14", "2026-05-13", 1.5),
    ("ensemble_bear2022", "s2_bear",      "2021-11-08", "2022-12-31", 1.5),
    ("ensemble_bear2018", "s2_bear2018",  "2018-02-01", "2018-12-30", 1.5),
]


def build(run_name, src_name, start, end, leverage, regime_full):
    src = ROOT / "runs" / src_name
    dst = ROOT / "runs" / run_name
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
    cfg["leverage"] = leverage
    (dst / "config.json").write_text(json.dumps(cfg, indent=2))
    print(f"  built {dst.relative_to(ROOT)}  bear%={(rg['regime']=='bear').mean()*100:.1f}")


def main():
    regime = pd.read_parquet(REGIME_PARQUET)
    for run_name, src, s, e, lev in RUNS:
        build(run_name, src, s, e, lev, regime)
    print("\nDone. Run each with:")
    for run_name, *_ in RUNS:
        print(f"  python -m backtest.runner runs/{run_name}")


if __name__ == "__main__":
    main()
