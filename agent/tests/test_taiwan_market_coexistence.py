"""Pin Taiwan support alongside upstream Japan and mainland Yahoo routes."""

from unittest.mock import patch

import pytest

from backtest.loaders import yahoo_loader, yfinance_loader


def test_yahoo_market_registration_preserves_all_three_markets():
    assert {"a_share", "jp_equity", "taiwan_equity"} <= yahoo_loader.DataLoader.markets
    assert {"jp_equity", "taiwan_equity"} <= yfinance_loader.DataLoader.markets


@pytest.mark.parametrize(
    "symbol,currency",
    [("7203.T", "JPY"), ("601398.SH", "CNY"), ("000001.SZ", "CNY"),
     ("2330.TW", "TWD"), ("6488.TWO", "TWD")],
)
def test_yahoo_fetch_preserves_each_market_and_original_identity(symbol, currency):
    rows = [{"trade_date": 1704153600, "open": 10.0, "high": 12.0,
             "low": 9.0, "close": 11.0, "volume": 1000}]
    with patch("backtest.loaders.yahoo_loader.yahoo_client.get_chart",
               return_value=(rows, currency)) as chart:
        result = yahoo_loader.DataLoader().fetch([symbol], "2024-01-01", "2024-01-31")

    assert list(result) == [symbol]
    assert result[symbol]["close"].tolist() == [11.0]
    assert result[symbol].attrs["quote_currency"] == currency
    chart.assert_called_once()
    assert chart.call_args.args[0] == symbol
