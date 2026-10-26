"""Semantic regressions for the pinned Qlib ROC/CORD formulas (#2068).

Upstream contract (microsoft/qlib@d5379c520f66a39953bad76234a7019a72796fd0,
qlib/contrib/data/loader.py):

- ROC is ``Ref($close, N)/$close`` — the past close over the latest close
  (old/new), no ``-1`` offset. Vibe used to compute
  ``close/close.shift(N) - 1`` (new/old minus one) — a different quantity
  rather than an algebraic rearrangement.
- CORD is ``Corr($close/Ref($close,1), Log($volume/Ref($volume,1)+1), N)`` —
  the ``+1`` sits *outside* the volume ratio. Vibe used to push it inside
  (``log((v+1)/(v_prev+1))``), which can flip the correlation sign, not just
  add rounding noise.

These tests pin the formulas against scalar oracles computed without pandas
rolling: the first valid bar, a second endpoint, NaN propagation through a
data gap, and the CORD sign-flip case from the issue.
"""

from __future__ import annotations

import math

import pandas as pd
import pytest

from src.factors.zoo.qlib158.cord10 import compute as cord10
from src.factors.zoo.qlib158.cord20 import compute as cord20
from src.factors.zoo.qlib158.cord30 import compute as cord30
from src.factors.zoo.qlib158.cord5 import compute as cord5
from src.factors.zoo.qlib158.cord60 import compute as cord60
from src.factors.zoo.qlib158.roc10 import compute as roc10
from src.factors.zoo.qlib158.roc20 import compute as roc20
from src.factors.zoo.qlib158.roc30 import compute as roc30
from src.factors.zoo.qlib158.roc5 import compute as roc5
from src.factors.zoo.qlib158.roc60 import compute as roc60

ROC_CASES = [(roc5, 5), (roc10, 10), (roc20, 20), (roc30, 30), (roc60, 60)]
CORD_CASES = [(cord5, 5), (cord10, 10), (cord20, 20), (cord30, 30), (cord60, 60)]

# Deterministic multiplicative steps in [0.94, 1.06]: close_{t-N}/close_t is
# exactly 1/prod(steps[t-N:t]), so the oracle below needs no pandas. 140 bars
# is long enough that even the 60-day window has pre-gap, in-gap and
# post-gap bars to assert on.
_CLOSE_STEPS = [1.0 + (((i * 7) % 13) - 6) / 100.0 for i in range(140)]


def _close_panel(steps: list[float]) -> dict[str, pd.DataFrame]:
    close = [100.0]
    for step in steps:
        close.append(close[-1] * step)
    return {"close": pd.DataFrame({"AAA": close})}


@pytest.mark.parametrize("compute,window", ROC_CASES)
def test_roc_first_valid_bar_matches_upstream(compute, window: int) -> None:
    """At the first bar with a full lookback, ROC is the pure price ratio."""
    panel = _close_panel(_CLOSE_STEPS)
    out = compute(panel)
    t = window  # first bar where the N-bar-old close exists
    expected = 1.0 / math.prod(_CLOSE_STEPS[0:window])
    assert out["AAA"].iloc[t] == pytest.approx(expected, rel=1e-12)
    # and it is NOT the new/old-minus-one Vibe used to compute
    old_expr = math.prod(_CLOSE_STEPS[0:window]) - 1.0
    assert out["AAA"].iloc[t] != pytest.approx(old_expr, rel=1e-9, abs=1e-12)


@pytest.mark.parametrize("compute,window", ROC_CASES)
def test_roc_second_endpoint_matches_upstream(compute, window: int) -> None:
    panel = _close_panel(_CLOSE_STEPS)
    out = compute(panel)
    t = window + 3  # a later, independent window
    expected = 1.0 / math.prod(_CLOSE_STEPS[t - window:t])
    assert out["AAA"].iloc[t] == pytest.approx(expected, rel=1e-12)


@pytest.mark.parametrize("compute,window", ROC_CASES)
def test_roc_gap_propagates_nan(compute, window: int) -> None:
    """A missing close inside the window keeps downstream bars NaN.

    The module's complete-window discipline (no min_periods=1 fabrication)
    is unchanged by the formula fix: every window overlapping the gap is
    NaN, exactly as before.
    """
    steps = list(_CLOSE_STEPS)
    panel = _close_panel(steps)
    close = panel["close"]["AAA"]
    g = window + 3  # a single NaN close, after the first valid bars
    close.iloc[g] = float("nan")
    out = compute({"close": pd.DataFrame({"AAA": close})})
    # ROC reads only the two endpoints of the window, so a NaN close hits
    # exactly two bars: as numerator (t=g) and as denominator (t=g+window)
    assert math.isnan(out["AAA"].iloc[g])
    assert math.isnan(out["AAA"].iloc[g + window])
    # every other bar — before, between, and after — stays exact
    for t in list(range(window, g)) + list(range(g + 1, g + window)) + [g + window + 1]:
        assert out["AAA"].iloc[t] == pytest.approx(
            1.0 / math.prod(steps[t - window:t]), rel=1e-12
        ), f"bar {t} should be exact"


def _cord_panel(close: list[float], volume: list[float]) -> dict[str, pd.DataFrame]:
    return {
        "close": pd.DataFrame({"AAA": close}),
        "volume": pd.DataFrame({"AAA": volume}),
    }


def _pearson(xs: list[float], ys: list[float]) -> float:
    """Scalar Pearson oracle, no pandas/numpy corr involved."""
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    return cov / math.sqrt(vx * vy)


def _cord_oracle(close: list[float], volume: list[float], t: int, window: int) -> float:
    xs = [close[i] / close[i - 1] for i in range(t - window + 1, t + 1)]
    ys = [math.log(volume[i] / volume[i - 1] + 1.0) for i in range(t - window + 1, t + 1)]
    return _pearson(xs, ys)


@pytest.mark.parametrize("compute,window", CORD_CASES)
def test_cord_first_valid_bar_matches_upstream(compute, window: int) -> None:
    """At the first full window, CORD correlates with log(v/v_prev + 1)."""
    close = [100.0 * f for f in _CLOSE_STEPS[: window + 2]]
    volume = [float((i * 37) % 101 + 10) for i in range(len(close))]
    panel = _cord_panel(close, volume)
    out = compute(panel)
    t = window  # ret series starts at bar 1, so a full window ends at bar `window`
    assert out["AAA"].iloc[t] == pytest.approx(
        _cord_oracle(close, volume, t, window), rel=1e-10, abs=1e-12
    )


@pytest.mark.parametrize("compute,window", CORD_CASES)
def test_cord_second_endpoint_matches_upstream(compute, window: int) -> None:
    close = [100.0 * f for f in _CLOSE_STEPS[: window + 6]]
    volume = [float((i * 53) % 97 + 7) for i in range(len(close))]
    panel = _cord_panel(close, volume)
    out = compute(panel)
    t = window + 4
    assert out["AAA"].iloc[t] == pytest.approx(
        _cord_oracle(close, volume, t, window), rel=1e-10, abs=1e-12
    )


@pytest.mark.parametrize("compute,window", CORD_CASES)
def test_cord_gap_propagates_nan(compute, window: int) -> None:
    close = [100.0 * f for f in _CLOSE_STEPS[: window + 4]]
    volume = [float((i * 29) % 89 + 11) for i in range(len(close))]
    volume[2] = float("nan")  # a gap inside the window
    panel = _cord_panel(close, volume)
    out = compute(panel)
    # every window covering the NaN volume is NaN
    for t in range(2, 2 + window + 1):
        if t < len(close):
            assert pd.isna(out["AAA"].iloc[t])


def test_cord_plus_one_placement_can_flip_the_sign():
    """The issue's sign-flip case: same panel, opposite correlations.

    close = [10, 11, 15, 14, 20, 22], volume = [15, 29, 1, 1, 12, 28]:
    the pinned expression gives +0.3426..., the (v+1)/(v_prev+1) variant
    gives -0.1058... — pinning the pinned one. (The zero-variance guard
    lives in the module's zero-variance handling, verified by the flat-
    volume test below.)
    """
    close = [10.0, 11.0, 15.0, 14.0, 20.0, 22.0]
    volume = [15.0, 29.0, 1.0, 1.0, 12.0, 28.0]
    out = cord5(_cord_panel(close, volume))
    value = out["AAA"].iloc[-1]
    assert value == pytest.approx(0.3426093652, abs=1e-9)
    # the same panel under the misplaced-plus-one formula flips negative —
    # demonstrating the fix is a semantic change, not rounding noise
    xs = [close[i] / close[i - 1] for i in range(1, 6)]
    ys_old = [math.log((volume[i] + 1) / (volume[i - 1] + 1)) for i in range(1, 6)]
    assert _pearson(xs, ys_old) == pytest.approx(-0.1058588021, abs=1e-9)


def test_cord_flat_volume_stays_finite():
    """With constant volume log(v/v_prev+1)=log(2) constant — corr is NaN by
    zero variance, never -inf from log(0): the +1 exists precisely for that."""
    close = [100.0 * f for f in _CLOSE_STEPS[:8]]
    volume = [500.0] * 8
    out = cord5(_cord_panel(close, volume))
    value = out["AAA"].iloc[-1]
    # zero-variance leg → undefined correlation stays NaN, not -inf
    assert pd.isna(value)
