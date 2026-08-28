"""Equal-weight buy-and-hold of the whole basket, active from 2019-01-02.

Zero weight during the warmup window so every strategy in the study shares one
run window and becomes comparable from the activation date.
"""
from typing import Dict

import pandas as pd


class SignalEngine:
    def __init__(self, activation: str = "2019-01-02"):
        self.activation = activation

    def generate(self, data_map: Dict[str, pd.DataFrame]) -> Dict[str, pd.Series]:
        n = max(len(data_map), 1)
        w = 1.0 / n
        act = pd.Timestamp(self.activation)
        out: Dict[str, pd.Series] = {}
        for code, df in data_map.items():
            sig = pd.Series(0.0, index=df.index)
            sig[sig.index >= act] = w
            out[code] = sig
        return out
