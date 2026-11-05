"""Cross-market strategy example: vol-adjusted dual-MA with per-market parameters.

Supports any combination of A-shares, crypto, US/HK/Canada equity, forex, and futures.
The CompositeEngine handles calendar alignment, market rules, and shared capital.
"""

import re

import numpy as np
import pandas as pd


# Per-market indicator parameters
MARKET_PARAMS = {
    "a_share":    {"ma_fast": 5,  "ma_slow": 20, "vol_lookback": 20},
    "crypto":     {"ma_fast": 7,  "ma_slow": 25, "vol_lookback": 14},
    "us_equity":  {"ma_fast": 10, "ma_slow": 50, "vol_lookback": 20},
    "hk_equity":  {"ma_fast": 10, "ma_slow": 50, "vol_lookback": 20},
    "ca_equity":  {"ma_fast": 10, "ma_slow": 50, "vol_lookback": 20},
    "forex":      {"ma_fast": 10, "ma_slow": 30, "vol_lookback": 20},
    "futures":    {"ma_fast": 5,  "ma_slow": 20, "vol_lookback": 20},
}

# ``(regex source, ignore case, market)`` triples. Keeping them as literals
# means import runs no calls; ``_detect_market`` compiles on demand and the
# ``re`` module caches the compiled pattern internally.
_MARKET_PATTERNS = (
    (r"^\d{6}\.(SZ|SH|BJ)$", True, "a_share"),
    (r"^[A-Z]+\.US$", True, "us_equity"),
    (r"^\d{3,5}\.HK$", True, "hk_equity"),
    (r"^[A-Z0-9&.\-]+\.(TO|V)$", True, "ca_equity"),
    (r"^[A-Z]+-USDT$", True, "crypto"),
    (r"^[A-Z]+/USDT$", True, "crypto"),
    (r"^[A-Z]{3}/[A-Z]{3}$", False, "forex"),
    (r"^[A-Z]{6}\.FX$", False, "forex"),
)


class SignalEngine:
    def generate(self, data_map: dict) -> dict:
        # Step 1: raw signals per market
        raw_signals = {}
        for code, df in data_map.items():
            market = self._detect_market(code)
            params = MARKET_PARAMS.get(market, MARKET_PARAMS["a_share"])
            raw_signals[code] = self._market_signal(df, params)

        # Step 2: volatility-adjusted weights
        return self._vol_adjust(raw_signals, data_map)

    def _detect_market(self, code: str) -> str:
        for source, ignore_case, market in _MARKET_PATTERNS:
            if re.match(source, code, re.IGNORECASE if ignore_case else 0):
                return market
        return "a_share"

    def _market_signal(self, df: pd.DataFrame, params: dict) -> pd.Series:
        close = df["close"]
        ma_fast = close.rolling(params["ma_fast"]).mean()
        ma_slow = close.rolling(params["ma_slow"]).mean()

        sig = pd.Series(0.0, index=df.index)
        sig[ma_fast > ma_slow] = 1.0
        sig[ma_fast < ma_slow] = -1.0
        return sig

    def _vol_adjust(self, signals: dict, data_map: dict) -> dict:
        vols = {}
        for code, df in data_map.items():
            ret = df["close"].pct_change(fill_method=None).dropna()
            vols[code] = (
                ret.rolling(20).std().iloc[-1]
                if len(ret) > 20
                else ret.std()
            )

        inv_vols = {c: 1.0 / (v + 1e-10) for c, v in vols.items()}
        total_inv = sum(inv_vols.values())

        adjusted = {}
        n = len(signals)
        for code, sig in signals.items():
            weight = inv_vols[code] / total_inv * n
            adjusted[code] = (sig * weight).clip(-1.0, 1.0)
        return adjusted
