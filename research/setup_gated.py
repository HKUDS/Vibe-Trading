"""Build gated S2 runs across 3 regimes — bull / bear2022 / bear2018.

Copies funding + F&G from the existing baseline run for each period, adds
regime.parquet (sliced from research/regime_labels.parquet), uses gated
signal_engine.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

TEMPLATE = ROOT / "runs" / "_templates" / "signal_engine_s2_gated.py"
REGIME_PARQUET = ROOT / "research" / "regime_labels.parquet"

# (run_name, source_run_dir, start, end)
RUNS = [
    ("s2_gated_bull",     "s2_baseline",  "2024-05-14", "2026-05-13"),
    ("s2_gated_bear2022", "s2_bear",      "2021-11-08", "2022-12-31"),
    ("s2_gated_bear2018", "s2_bear2018",  "2018-02-01", "2018-12-30"),
]


def build(run_name: str, src_name: str, start: str, end: str, regime_full: pd.DataFrame) -> None:
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

    src_cfg = json.loads((src / "config.json").read_text())
    src_cfg["start_date"] = start
    src_cfg["end_date"] = end
    (dst / "config.json").write_text(json.dumps(src_cfg, indent=2))

    print(f"  built {dst.relative_to(ROOT)}  regime rows={len(rg)}  bear%={(rg['regime']=='bear').mean()*100:.1f}")


def main() -> None:
    regime = pd.read_parquet(REGIME_PARQUET)
    for run_name, src, s, e in RUNS:
        build(run_name, src, s, e, regime)
    print("\nDone. Run each with:")
    for run_name, *_ in RUNS:
        print(f"  python -m backtest.runner runs/{run_name}")


if __name__ == "__main__":
    main()
