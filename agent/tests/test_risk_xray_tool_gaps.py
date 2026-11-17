"""Tool ingestion must preserve gaps before the risk engine sees prices."""

import json
import pandas as pd
import pytest
from backtest.risk_xray import compute_risk_xray
from src.tools.portfolio_risk_tool import PortfolioRiskXrayTool


@pytest.mark.parametrize("bad_close", [None, "invalid", "missing"])
def test_risk_tool_preserves_invalid_price_dates(bad_close):
    dates = pd.bdate_range("2026-01-01", periods=40)
    values = [100.0 + i + (i % 3) for i in range(40)]
    records = [{"date": str(date.date()), "close": value} for date, value in zip(dates, values)]
    if bad_close == "missing":
        del records[20]["close"]
    else:
        records[20]["close"] = bad_close
    expected_values = values.copy()
    expected_values[20] = float("nan")
    expected = compute_risk_xray(pd.DataFrame({"AAA": expected_values}, index=dates), {"AAA": 1.0})
    tool = PortfolioRiskXrayTool(data_fetcher=lambda **kwargs: {"AAA": records})
    actual = json.loads(tool.execute(symbols=["AAA"], start_date="2026-01-01", end_date="2026-04-01"))
    assert actual["status"] == "ok", actual
    assert actual["data"]["inputs"]["return_observations"] == 37
    assert actual["data"]["volatility"] == pytest.approx(expected["volatility"])
