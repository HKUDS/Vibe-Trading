"""Cost stress test — clone ensemble runs with 3x slippage + 3x fees."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SOURCES = ["ensemble_bull", "ensemble_bear2022", "ensemble_bear2018"]
STRESS_MULT = 3.0


def stress(src_name: str) -> None:
    src = ROOT / "runs" / src_name
    dst = ROOT / "runs" / f"{src_name}_stress"
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)

    cfg_path = dst / "config.json"
    cfg = json.loads(cfg_path.read_text())
    cfg["maker_rate"] = round(cfg["maker_rate"] * STRESS_MULT, 6)
    cfg["taker_rate"] = round(cfg["taker_rate"] * STRESS_MULT, 6)
    cfg["slippage"] = round(cfg["slippage"] * STRESS_MULT, 6)
    cfg_path.write_text(json.dumps(cfg, indent=2))
    print(f"  built {dst.relative_to(ROOT)}  maker={cfg['maker_rate']} taker={cfg['taker_rate']} slip={cfg['slippage']}")


def main() -> None:
    for s in SOURCES:
        stress(s)


if __name__ == "__main__":
    main()
