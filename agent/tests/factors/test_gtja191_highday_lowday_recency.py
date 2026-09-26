"""Semantic tests for ``zoo/gtja191/alpha_103``, ``alpha_133``, ``alpha_177``.

These factors are the report's HIGHDAY/LOWDAY-based Aroon-style oscillators:
a high or low that happened *today* must score near 100, one that happened at
the oldest edge of the window must score near 0. ``ts_argmax``/``ts_argmin``
are 0-based from the start of the window (index ``n-1`` is the most recent
bar), and this repo's documented rebase to the report's day-count convention
(``n - ts_argmax``) cancels algebraically against the formula's own
``n - HIGHDAY`` term, leaving the raw index scaled by ``100/n``.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.factors.zoo.gtja191.alpha_103 import compute as alpha_103
from src.factors.zoo.gtja191.alpha_133 import compute as alpha_133
from src.factors.zoo.gtja191.alpha_177 import compute as alpha_177

N = 20


def _panel_with_extreme_at(offset_from_end: int) -> dict[str, pd.DataFrame]:
    """A 20-bar window whose low and high both sit at ``offset_from_end``.

    ``offset_from_end=0`` puts the extreme on the most recent bar (today);
    ``offset_from_end=N-1`` puts it on the oldest bar in the window.
    """
    close = [100.0] * N
    low = [90.0] * N
    high = [110.0] * N
    idx = N - 1 - offset_from_end
    low[idx] = 1.0
    high[idx] = 1000.0
    return {
        "close": pd.DataFrame({"AAA": close}),
        "low": pd.DataFrame({"AAA": low}),
        "high": pd.DataFrame({"AAA": high}),
    }


def test_alpha_103_scores_a_todays_low_near_the_maximum() -> None:
    panel = _panel_with_extreme_at(offset_from_end=0)
    out = alpha_103(panel)
    assert out["AAA"].iloc[-1] == pytest.approx(95.0)


def test_alpha_103_scores_the_oldest_low_near_the_minimum() -> None:
    panel = _panel_with_extreme_at(offset_from_end=N - 1)
    out = alpha_103(panel)
    assert out["AAA"].iloc[-1] == pytest.approx(0.0)


def test_alpha_177_scores_todays_high_near_the_maximum() -> None:
    panel = _panel_with_extreme_at(offset_from_end=0)
    out = alpha_177(panel)
    assert out["AAA"].iloc[-1] == pytest.approx(95.0)


def test_alpha_177_scores_the_oldest_high_near_the_minimum() -> None:
    panel = _panel_with_extreme_at(offset_from_end=N - 1)
    out = alpha_177(panel)
    assert out["AAA"].iloc[-1] == pytest.approx(0.0)


def test_alpha_133_is_the_difference_of_the_two_recency_scores() -> None:
    panel = _panel_with_extreme_at(offset_from_end=0)
    out = alpha_133(panel)
    # Both the high and the low sit on today's bar, so the Aroon-up and
    # Aroon-down terms are equal and cancel.
    assert out["AAA"].iloc[-1] == pytest.approx(0.0)
