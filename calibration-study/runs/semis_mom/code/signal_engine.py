"""12-1 cross-sectional momentum, long-only top half, monthly rebalance.

Momentum score at t = close[t-21] / close[t-252] - 1 (skip the most recent
month, standard 12-1 construction).  Every 21 trading days the top half of the
basket (4 of 8 names) is held equal-weight; targets are carried forward
between rebalances.  Engine applies the 1-bar execution lag.
"""
from typing import Dict, List

import pandas as pd


class SignalEngine:
    def __init__(
        self,
        lookback: int = 252,
        skip: int = 21,
        rebalance_freq: int = 21,
        top_n: int = 4,
        activation: str = "2019-01-02",
        invest_frac: float = 0.99,
    ):
        self.lookback = lookback
        self.skip = skip
        self.rebalance_freq = rebalance_freq
        self.top_n = top_n
        self.activation = activation
        # Keep a 1% cash buffer: fully-invested rebalance targets leave no
        # capital to pay slippage and the engine refuses the rebalance.
        self.invest_frac = invest_frac

    def generate(self, data_map: Dict[str, pd.DataFrame]) -> Dict[str, pd.Series]:
        closes = pd.DataFrame({code: df["close"] for code, df in data_map.items()})
        mom = closes.shift(self.skip) / closes.shift(self.lookback) - 1.0
        act = pd.Timestamp(self.activation)
        idx = closes.index
        signals = {code: pd.Series(0.0, index=idx) for code in closes.columns}
        selected: List[str] = []
        bars_since = None
        for i, dt in enumerate(idx):
            if dt < act:
                continue
            if bars_since is None or bars_since >= self.rebalance_freq:
                row = mom.loc[dt].dropna()
                if len(row) >= self.top_n:
                    selected = list(row.sort_values(ascending=False).index[: self.top_n])
                    bars_since = 0
            if selected:
                w = self.invest_frac / len(selected)
                for code in selected:
                    signals[code].at[dt] = w
            if bars_since is not None:
                bars_since += 1
        return signals
