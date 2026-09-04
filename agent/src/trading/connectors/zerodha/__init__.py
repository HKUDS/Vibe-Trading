"""Zerodha Kite Connect trading connector.

Read-only and paper/live account access via the ``kiteconnect`` SDK. A
``broker_sdk`` transport for the Indian equity and F&O markets (NSE/BSE).

Zerodha is India's largest retail broker. Kite Connect exposes historical OHLCV
via ``kite.historical_data`` (capped at 2000 days/request, bars dated at
midnight IST) and quote/positions/orders for live use. For our backtest data
bridge the read path (``get_historical_bars``) is what the ``india_broker``
loader consumes.

Auth: Kite uses a request-token login (api_key + api_secret -> access_token),
or a pre-issued access_token stored in config. The connector is opt-in
(``requires_auth``): it is inert in CI / unconfigured runs.
"""

from __future__ import annotations

__all__ = ["sdk"]
