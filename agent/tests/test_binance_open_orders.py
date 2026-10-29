"""Exercise the real CCXT all-symbol guard without calling a broker (#2090)."""

import ccxt
import pytest

from src.trading.connectors.binance import sdk


@pytest.fixture
def exchange(monkeypatch):
    monkeypatch.setattr(sdk, "getproxies", lambda: {})
    client = sdk._exchange(sdk.BinanceConfig())
    client.set_markets([{
        "id": "BTCUSDT", "symbol": "BTC/USDT", "base": "BTC", "quote": "USDT",
        "type": "spot", "spot": True, "swap": False, "future": False,
        "option": False, "contract": False, "linear": None, "inverse": None,
    }])
    monkeypatch.setattr(sdk, "_exchange", lambda _config: client)
    return client


def test_all_symbol_read_reaches_the_endpoint_and_returns_the_resting_order(exchange, monkeypatch):
    calls = []

    def read(params):
        calls.append(params)
        return [{"symbol": "BTCUSDT", "orderId": 17, "price": "100.0", "origQty": "1.0",
                 "executedQty": "0.0", "status": "NEW", "side": "BUY", "type": "LIMIT",
                 "time": 1700000000000}]

    monkeypatch.setattr(exchange, "privateGetOpenOrders", read)
    result = sdk.get_open_orders(sdk.BinanceConfig())
    assert calls == [{}]
    assert len(result["open_orders"]) == 1
    assert result["open_orders"][0]["order_id"] == "17"
    assert result["open_orders"][0]["symbol"] == "BTC/USDT"
    assert exchange.enableRateLimit is True


@pytest.mark.parametrize("error", [ccxt.AuthenticationError, ccxt.NetworkError, ccxt.RateLimitExceeded, ccxt.ExchangeError])
def test_real_read_failures_are_not_reported_as_an_empty_order_book(exchange, monkeypatch, error):
    def read(_params):
        raise error("synthetic broker failure")

    monkeypatch.setattr(exchange, "privateGetOpenOrders", read)
    with pytest.raises(error, match="synthetic broker failure"):
        sdk.get_open_orders(sdk.BinanceConfig())
