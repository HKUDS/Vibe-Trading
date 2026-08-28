"""200-day moving-average trend filter on the equal-weight basket index.

Basket index = cumulative product of the cross-sectional mean of daily close
returns.  When the index closes above its 200-day simple moving average the
strategy holds the equal-weight basket; otherwise it holds cash.  The engine
itself applies the 1-bar execution lag (next-bar open), so signals may use
same-bar closes without lookahead.
"""
from typing import Dict

import pandas as pd


class SignalEngine:
    def __init__(
        self,
        ma_window: int = 200,
        activation: str = "2019-01-02",
        invest_frac: float = 0.99,
    ):
        self.ma_window = ma_window
        self.activation = activation
        # Keep a 1% cash buffer: fully-invested rebalance targets leave no
        # capital to pay slippage and the engine refuses the rebalance.
        self.invest_frac = invest_frac

    def generate(self, data_map: Dict[str, pd.DataFrame]) -> Dict[str, pd.Series]:
        closes = pd.DataFrame({code: df["close"] for code, df in data_map.items()})
        rets = closes.pct_change()
        basket = (1.0 + rets.mean(axis=1).fillna(0.0)).cumprod()
        ma = basket.rolling(self.ma_window).mean()
        in_market = (basket > ma).astype(float)
        act = pd.Timestamp(self.activation)
        in_market[in_market.index < act] = 0.0
        n = max(len(data_map), 1)
        w = in_market * self.invest_frac / n
        out: Dict[str, pd.Series] = {}
        for code, df in data_map.items():
            out[code] = w.reindex(df.index).fillna(0.0)
        return out
