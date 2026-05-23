"""Short-only ensemble WITHOUT regime gate — BBB experiment."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "runs" / "_templates" / "signal_engine_short_ungated.py"
STRESS_MULT = 3.0

RUNS = [
    ("shortung_bull",          "ensemble_bull"),
    ("shortung_bear2022",      "ensemble_bear2022"),
    ("shortung_bear2018",      "ensemble_bear2018"),
    ("shortung_covid_altbull", "oos_covid_altbull"),
    ("shortung_post_ftx",      "oos_post_ftx"),
]


def build(new_name, src_name, stress=False):
    src = ROOT / "runs" / src_name
    suffix = "_stress" if stress else ""
    dst = ROOT / "runs" / f"{new_name}{suffix}"
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    (dst / "code").mkdir()
    shutil.copy(TEMPLATE, dst / "code" / "signal_engine.py")
    shutil.copytree(src / "factor_data", dst / "factor_data")
    cfg = json.loads((src / "config.json").read_text())
    if stress:
        cfg["maker_rate"] = round(cfg["maker_rate"] * STRESS_MULT, 6)
        cfg["taker_rate"] = round(cfg["taker_rate"] * STRESS_MULT, 6)
        cfg["slippage"] = round(cfg["slippage"] * STRESS_MULT, 6)
    (dst / "config.json").write_text(json.dumps(cfg, indent=2))
    print(f"  built {dst.relative_to(ROOT)}  stress={stress}")


def main():
    for new_name, src in RUNS:
        build(new_name, src, stress=False)
        build(new_name, src, stress=True)


if __name__ == "__main__":
    main()
