"""Regression test for head_and_shoulders pattern detection on negative price series.

Locks out a bug where head_and_shoulders used `abs(lv - rv) / avg` instead of
`abs(lv - rv) / abs(avg)` in the shoulder-symmetry check, causing false
detections for negative price series because division by a negative average
yielded a negative relative difference (< 0.05).
"""

import pandas as pd
from src.tools.pattern_tool import head_and_shoulders


def test_head_and_shoulders_negative_prices_requires_abs_avg():
    """Prove that head_and_shoulders does not falsely flag asymmetric negative shoulders."""
    # Left shoulder = -100, head = -10, right shoulder = -50. Shoulders are
    # far from symmetric, so this must not be flagged as a valid pattern.
    prices = pd.Series([-200.0, -100.0, -200.0, -10.0, -200.0, -50.0, -200.0])
    res = head_and_shoulders(prices, window=1)

    assert (
        res.iloc[3] == 0
    ), f"Expected 0 (no pattern for asymmetric negative shoulders), got {res.iloc[3]}"
