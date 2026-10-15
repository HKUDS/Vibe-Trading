"""Swing-based skill engines must not trade on pivots before they are confirmed.

A centred rolling extreme at bar ``t`` needs the next ``swing_window`` bars to
exist, so a signal stamped on the pivot bar itself reads the future. Signals
must land on the confirmation bar, and truncating the history after bar ``t``
must not change any signal on or before ``t``.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

SKILLS_ROOT = Path(__file__).resolve().parents[1] / "src" / "skills"


def _load(skill: str):
    path = SKILLS_ROOT / skill / "example_signal_engine.py"
    spec = importlib.util.spec_from_file_location(f"_causality_{skill.replace('-', '_')}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _frame(seed: int, bars: int = 320) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(0, 1.5, bars))
    index = pd.date_range("2024-01-01", periods=bars, freq="D")
    return pd.DataFrame(
        {
            "open": close,
            "high": close + rng.uniform(0.2, 1.0, bars),
            "low": close - rng.uniform(0.2, 1.0, bars),
            "close": close,
            "volume": 1.0,
        },
        index=index,
    )


def _engines():
    elliott = _load("elliott-wave").SignalEngine(swing_window=3, fib_tolerance=0.6, min_wave_bars=1)
    harmonic = _load("harmonic").SignalEngine(swing_window=3, tol=0.3)
    harmonic.use_pyharmonics = False
    return {"elliott-wave": elliott, "harmonic": harmonic}


@pytest.mark.parametrize("skill", ["elliott-wave", "harmonic"])
def test_truncating_history_never_changes_earlier_signals(skill):
    engine = _engines()[skill]
    emitted = 0
    for seed in range(6):
        frame = _frame(seed)
        full = engine.generate({"X": frame})["X"]
        emitted += int((full != 0).sum())
        for cut in range(40, len(frame), 17):
            head = engine.generate({"X": frame.iloc[: cut + 1]})["X"]
            pd.testing.assert_series_equal(head, full.iloc[: cut + 1])
    assert emitted > 0


def test_harmonic_signal_bar_is_the_pivot_confirmation_bar():
    module = _load("harmonic")
    found = 0
    for seed in range(6):
        frame = _frame(seed)
        for pattern in module._detect_patterns_fallback(frame, swing_window=3, tol=0.3):
            pivot = frame.index.get_loc(pattern["d"][0])
            assert frame.index.get_loc(pattern["d_index"]) == pivot + 3
            found += 1
    assert found > 0

