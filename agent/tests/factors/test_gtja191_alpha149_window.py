"""GTJA alpha 149 regresses over the report's 252-bar window."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.factors.zoo.gtja191 import alpha_149


def _panel(n_bars: int = 300) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(149)
    index = pd.bdate_range("2022-01-03", periods=n_bars)
    bench = pd.Series(100 * np.cumprod(1 + rng.normal(0, 0.01, n_bars)), index=index)
    close = pd.DataFrame(
        {
            "A": 50 * np.cumprod(1 + rng.normal(0, 0.015, n_bars)),
            "B": 20 * np.cumprod(1 + rng.normal(0, 0.02, n_bars)),
        },
        index=index,
    )
    benchmark = pd.DataFrame({col: bench for col in close.columns})
    return {"close": close, "benchmark_close": benchmark}


def test_alpha149_uses_the_252_bar_window_in_its_formula_and_warmup():
    panel = _panel()
    out = alpha_149.compute(panel)

    assert "252)" in alpha_149.__alpha_meta__["formula_latex"]
    assert alpha_149.__alpha_meta__["min_warmup_bars"] == 253
    # One bar is spent on the first return, then 252 returns fill the window.
    assert out.iloc[:252].isna().all().all()
    assert out.iloc[252].notna().all()

    bench = panel["benchmark_close"]["A"]
    down = (bench < bench.shift(1)).astype(float)
    br = (bench.pct_change() * down).iloc[-252:]
    cr = (panel["close"]["A"].pct_change() * down).iloc[-252:]
    expected = np.cov(cr, br, ddof=1)[0, 1] / np.var(br, ddof=1)
    assert out["A"].iloc[-1] == pytest.approx(expected, rel=1e-6)
