"""Buy-and-hold: constant full-weight long signal for every symbol."""
from typing import Dict

import pandas as pd


class SignalEngine:
    def generate(self, data_map: Dict[str, pd.DataFrame]) -> Dict[str, pd.Series]:
        n = max(len(data_map), 1)
        w = 1.0 / n
        return {code: pd.Series(w, index=df.index) for code, df in data_map.items()}
