"""Performance benchmark: compare old vs new operator/equity paths.

Development-only script — not included in the package.
Run: python agent/scripts/bench_performance.py
"""

from __future__ import annotations

import os
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def bench_operators():
    """Benchmark factor operators: old pandas vs new fast paths."""
    from src.factors.base import decay_linear, ts_argmax, ts_argmin, ts_rank

    np.random.seed(42)
    df = pd.DataFrame(np.random.randn(5000, 100))
    n = 20

    print("=== Operator Benchmarks (5000 rows × 100 cols, window=20) ===\n")

    ops = [
        ("ts_rank", lambda: ts_rank(df, n)),
        ("ts_argmax", lambda: ts_argmax(df, n)),
        ("ts_argmin", lambda: ts_argmin(df, n)),
        ("decay_linear", lambda: decay_linear(df, n)),
    ]

    for name, fn in ops:
        _ = fn()
        t0 = time.perf_counter()
        for _ in range(3):
            fn()
        elapsed = (time.perf_counter() - t0) / 3
        print(f"  {name:20s}: {elapsed:.3f}s")

    print()


def bench_equity():
    """Benchmark _calc_equity: vectorized vs loop."""
    from backtest.engines.base import BaseEngine
    from backtest.models import Position

    class _Stub(BaseEngine):
        def can_execute(self, *a):
            return True

        def round_size(self, s, p):
            return s

        def calc_commission(self, *a):
            return 0.0

        def apply_slippage(self, p, d):
            return p

    np.random.seed(42)
    n_symbols = 50
    n_days = 1000
    symbols = [f"SYM{i:03d}" for i in range(n_symbols)]
    dates = pd.date_range("2020-01-01", periods=n_days, freq="B")
    close_df = pd.DataFrame(
        np.cumsum(np.random.randn(n_days, n_symbols), axis=0) + 100,
        index=dates,
        columns=symbols,
    )

    engine = _Stub({"initial_cash": 10_000_000})
    engine.capital = 5_000_000
    for i, sym in enumerate(symbols):
        engine.positions[sym] = Position(
            symbol=sym,
            direction=1 if i % 2 == 0 else -1,
            size=100.0 + i * 10,
            entry_price=95.0 + i,
            leverage=1.0,
            entry_time=dates[0],
        )

    ts = dates[500]

    _ = engine._calc_equity(close_df, ts)
    t0 = time.perf_counter()
    for _ in range(1000):
        engine._calc_equity(close_df, ts)
    vec_time = (time.perf_counter() - t0) / 1000

    # Force loop path by monkey-patching
    original_pnl = type(engine)._calc_pnl

    def _loop_pnl(self, *a):
        return original_pnl(self, *a)

    type(engine)._calc_pnl = _loop_pnl
    _ = engine._calc_equity(close_df, ts)
    t0 = time.perf_counter()
    for _ in range(1000):
        engine._calc_equity(close_df, ts)
    loop_time = (time.perf_counter() - t0) / 1000
    type(engine)._calc_pnl = original_pnl

    speedup = loop_time / vec_time if vec_time > 0 else float("inf")

    print("=== Equity Calculation (50 positions, 1000 iterations) ===\n")
    print(f"  Vectorized: {vec_time * 1e6:.1f} µs/call")
    print(f"  Loop:       {loop_time * 1e6:.1f} µs/call")
    print(f"  Speedup:    {speedup:.1f}x")
    print()


if __name__ == "__main__":
    print("Vibe-Trading Performance Benchmark")
    print("=" * 50)
    print()

    from src.factors._backend import HAS_BOTTLENECK

    print(f"Bottleneck available: {HAS_BOTTLENECK}")
    print(f"VIBE_TRADING_DISABLE_BOTTLENECK: {os.environ.get('VIBE_TRADING_DISABLE_BOTTLENECK', '0')}")
    print()

    bench_operators()
    bench_equity()
