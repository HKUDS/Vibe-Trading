import numpy as np
import pandas as pd

from src.factors.zoo.gtja191.alpha_064 import compute


def test_gtja191_064_preserves_missing_data():
    n = 80
    idx = pd.date_range("2025-01-01", periods=n)
    close = pd.DataFrame({"A": np.linspace(10.0, 20.0, n), "B": np.linspace(20.0, 12.0, n)}, index=idx)
    volume = pd.DataFrame({"A": np.linspace(1000.0, 2000.0, n), "B": np.linspace(1500.0, 900.0, n)}, index=idx)
    amount = close * volume * 100.0

    close.loc[idx[45], "A"] = np.nan
    result = compute({"close": close, "volume": volume, "amount": amount})

    assert result.loc[idx[45]:, "A"].iloc[:10].isna().any()
    assert result["B"].iloc[40:].notna().any()
