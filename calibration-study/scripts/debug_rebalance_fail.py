"""Probe: find the bar where _execute_target_rebalance runs out of capital.

Monkeypatches the engine (repo code untouched) to print timestamp, equity,
cash, and the planned order book right before the failing rebalance.
Run from the agent/ directory:
    python ../calibration-study/scripts/debug_rebalance_fail.py <run_dir>
"""
import sys
from pathlib import Path

import backtest.engines.base as eb

orig = eb.BaseEngine._execute_target_rebalance


def patched(self, target_weights, data_map, ts, equity, codes):
    try:
        return orig(self, target_weights, data_map, ts, equity, codes)
    except ValueError as e:
        print(f"FAIL at ts={ts} equity={equity:.2f} capital(cash)={self.capital:.2f}")
        pos_notional = 0.0
        for sym, p in self.positions.items():
            print(f"  pos {sym}: size={p.size:.4f} dir={p.direction}")
        print(f"  targets: { {k: round(v, 4) for k, v in target_weights.items() if v} }")
        raise


eb.BaseEngine._execute_target_rebalance = patched

from backtest.runner import main  # noqa: E402

main(Path(sys.argv[1]))
