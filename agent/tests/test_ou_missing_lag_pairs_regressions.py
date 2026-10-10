import numpy as np
import pandas as pd
import pytest
from src.quantlib.timeseries import fit_ornstein_uhlenbeck


def test_ou_only_fits_adjacent_observed_pairs():
    values = pd.Series([1.0, 2.0, 1.5, np.nan, 9.0, 6.0, 4.0, 3.0])
    pairs = pd.concat({"curr": values, "lag": values.shift()}, axis=1).dropna()
    design = np.column_stack([np.ones(len(pairs)), pairs["lag"]])
    a, b = np.linalg.lstsq(design, pairs["curr"], rcond=None)[0]
    actual = fit_ornstein_uhlenbeck(values)
    assert actual["ar1_a"] == pytest.approx(a)
    assert actual["ar1_b"] == pytest.approx(b)


def test_ou_rejects_sample_with_no_three_adjacent_pairs():
    with pytest.raises(ValueError, match="3 lag pairs"):
        fit_ornstein_uhlenbeck(pd.Series([1.0, np.nan, 2.0, np.nan, 3.0, np.nan, 4.0]))


def test_quantlib_tool_refuses_insufficient_adjacent_ou_pairs():
    import json
    from src.tools.quantlib_tool import QuantlibCallTool

    result = json.loads(
        QuantlibCallTool().execute(
            action="call",
            module="timeseries",
            function="fit_ornstein_uhlenbeck",
            kwargs={
                "series": {
                    "__series__": {"values": [1.0, None, 2.0, None, 3.0, None, 4.0]}
                }
            },
        )
    )
    assert result["ok"] is False
    assert "3 lag pairs" in result["error"]
