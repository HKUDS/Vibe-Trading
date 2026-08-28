"""Inverse-volatility weights over the whole basket, monthly rebalance.

Weight_i proportional to 1 / (63-day std of daily close returns), normalised
to a fully-invested long-only portfolio.  Weights recomputed every 21 trading
days and carried forward in between.  Engine applies the 1-bar execution lag.
"""
from typing import Dict, Optional

import pandas as pd


class SignalEngine:
    def __init__(
        self,
        vol_window: int = 63,
        rebalance_freq: int = 21,
        activation: str = "2019-01-02",
        invest_frac: float = 0.99,
    ):
        self.vol_window = vol_window
        self.rebalance_freq = rebalance_freq
        self.activation = activation
        # Keep a 1% cash buffer: fully-invested rebalance targets leave no
        # capital to pay slippage and the engine refuses the rebalance.
        self.invest_frac = invest_frac

    def generate(self, data_map: Dict[str, pd.DataFrame]) -> Dict[str, pd.Series]:
        closes = pd.DataFrame({code: df["close"] for code, df in data_map.items()})
        vol = closes.pct_change().rolling(self.vol_window).std()
        act = pd.Timestamp(self.activation)
        idx = closes.index
        signals = {code: pd.Series(0.0, index=idx) for code in closes.columns}
        current: Optional[pd.Series] = None
        bars_since = None
        for dt in idx:
            if dt < act:
                continue
            if bars_since is None or bars_since >= self.rebalance_freq:
                row = vol.loc[dt].dropna()
                row = row[row > 0]
                if len(row) == len(closes.columns):
                    inv = 1.0 / row
                    current = self.invest_frac * inv / inv.sum()
                    bars_since = 0
            if current is not None:
                for code, w in current.items():
                    signals[code].at[dt] = float(w)
            if bars_since is not None:
                bars_since += 1
        return signals
