import numpy as np
import pandas as pd
import pytest
from src.quantlib.factormodel import portfolio_style_exposure


@pytest.mark.parametrize("missing", [np.nan, np.inf, -np.inf])
def test_incomplete_exposure_rows_are_reported_as_unmatched(missing):
    exposures = pd.DataFrame(
        {"value": [2.0, missing], "size": [3.0, 4.0]}, index=["a", "b"]
    )
    actual = portfolio_style_exposure(pd.Series({"a": 0.6, "b": 0.4}), exposures)
    assert actual["value"] == pytest.approx(1.2)
    assert actual["size"] == pytest.approx(1.8)
    assert actual["unmatched_weight"] == pytest.approx(0.4)


def test_benchmark_missing_exposures_are_also_reported():
    exposures = pd.DataFrame({"value": [2.0, np.nan]}, index=["a", "b"])
    actual = portfolio_style_exposure(
        pd.Series({"a": 1.0}), exposures, benchmark=pd.Series({"b": 1.0})
    )
    assert actual["value"] == 2.0
    assert actual["unmatched_weight"] == 1.0


def test_quantlib_tool_reports_unmeasured_style_weight():
    import json
    from src.tools.quantlib_tool import QuantlibCallTool

    result = json.loads(
        QuantlibCallTool().execute(
            action="call",
            module="factormodel",
            function="portfolio_style_exposure",
            kwargs={
                "holdings": {"a": 1.0},
                "exposures": {
                    "__dataframe__": {
                        "index": ["a"],
                        "columns": ["value"],
                        "data": [[None]],
                    }
                },
            },
        )
    )
    assert result["ok"] is True
    encoded = result["result"]["__series__"]
    values = dict(zip(encoded["index"], encoded["values"]))
    assert values["unmatched_weight"] == 1.0
