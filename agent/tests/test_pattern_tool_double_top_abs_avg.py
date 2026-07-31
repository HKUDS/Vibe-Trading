"""Regression test for double_top_bottom pattern detection on negative price series.

Locks out a bug where double_top_bottom used `abs(v1 - v2) / avg` instead of
`abs(v1 - v2) / abs(avg)` in the peaks loop, causing false double top detections
for negative price series because division by a negative average yielded a
negative relative difference (< 0.03).
"""

import numpy as np
import pandas as pd
from src.tools.pattern_tool import double_top_bottom


def test_double_top_negative_prices_requires_abs_avg():
    """Prove that double_top_bottom does not falsely flag divergent negative peaks as a double top."""
    # Peak 1 = -100.0, Peak 2 = -1.0. Relative difference is large (~1.96), not a double top.
    prices = pd.Series([-100.0, -100.0, -100.0, -100.0, -100.0, -100.0, -100.0, -50.0, -1.0, -50.0, -100.0])
    res = double_top_bottom(prices, window=2)
    
    # Peak 2 is at index 8. On un-fixed code, res.iloc[8] == 1 (false double top).
    # On fixed code, res.iloc[8] == 0 (no false double top).
    assert res.iloc[8] == 0, f"Expected 0 (no double top for divergent negative peaks), got {res.iloc[8]}"
