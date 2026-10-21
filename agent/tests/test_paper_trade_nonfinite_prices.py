"""Non-finite feed prices must not reach matching or ledger valuation."""

import json

import pandas as pd
import pytest

from src.tools.paper_trade.tool import run_paper_trade_step


@pytest.mark.parametrize("column", ["open", "high", "low", "close"])
@pytest.mark.parametrize("value", [float("inf"), float("-inf"), float("nan")])
def test_nonfinite_price_rejects_order_and_keeps_finite_valuation(column, value):
    frame = pd.DataFrame(
        {
            "open": [100.0, 100.0],
            "high": [100.0, 100.0],
            "low": [100.0, 100.0],
            "close": [100.0, 100.0],
            "volume": [1000.0, 1000.0],
        },
        index=pd.to_datetime(["2026-10-19", "2026-10-20"]),
    )
    frame.loc[pd.Timestamp("2026-10-20"), column] = value

    class Loader:
        name = "fixture"

        def fetch(self, *args, **kwargs):
            return {"AAPL": frame}

    result = json.loads(
        run_paper_trade_step(
            {
                "account_id": "finite-prices",
                "market": "us",
                "account_state": {
                    "cash": 1000,
                    "positions": [{"symbol": "AAPL", "qty": 1, "avg_cost": 80}],
                },
                "from_date": "2026-10-20",
                "to_date": "2026-10-20",
                "orders": [{"symbol": "AAPL", "side": "sell", "qty": 1}],
            },
            loader=Loader(),
            ch_client=None,
            calendar_client=None,
            limits_client=None,
        )
    )
    assert result["fills"] == []
    assert result["rejected_orders"][0]["reason_code"] == "suspended"
    assert result["end_state"]["cash"] == 1000
    assert result["nav_series"][0]["nav"] == 1100
    json.dumps(result, allow_nan=False)
