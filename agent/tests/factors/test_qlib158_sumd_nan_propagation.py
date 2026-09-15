import numpy as np
import pandas as pd
import pytest

from src.factors.zoo.qlib158 import sumd5, sumd10, sumd20, sumd30, sumd60


@pytest.mark.parametrize(
    ("module", "window"),
    [(sumd5, 5), (sumd10, 10), (sumd20, 20), (sumd30, 30), (sumd60, 60)],
)
def test_sumd_preserves_missing_close_through_window(module, window):
    n = window + 15
    idx = pd.date_range("2025-01-01", periods=n)
    close = pd.DataFrame({"A": np.arange(n, dtype=float) + 100.0}, index=idx)
    gap = window + 3
    close.iloc[gap, 0] = np.nan

    result = module.compute({"close": close})

    assert result.iloc[gap : gap + window + 1, 0].isna().all()
