from __future__ import annotations

import pandas as pd

SCREEN_ZSCORE_DAYS = 30   # 30-day rolling window = 720 bars at 1H
SCREEN_MOM_HOURS   = 24   # momentum lookback in hours
OI_MOM_HOURS       = 72   # OI momentum lookback in hours


def _rolling_z(s: pd.Series, window_h: int) -> pd.Series:
    m = s.rolling(window_h, min_periods=window_h // 2).mean()
    sd = s.rolling(window_h, min_periods=window_h // 2).std()
    return (s - m) / (sd + 1e-9)


def basis_factors(perp_close: pd.Series, spot_close: pd.Series) -> dict[str, pd.Series]:
    spot = spot_close.reindex(perp_close.index, method="ffill")
    basis_rel = (perp_close - spot) / spot
    basis_z = _rolling_z(basis_rel, SCREEN_ZSCORE_DAYS * 24)
    basis_mom = basis_rel - basis_rel.shift(SCREEN_MOM_HOURS)
    return {"basis_rel": basis_rel, "basis_z": basis_z, "basis_mom": basis_mom}


def funding_factors(funding_on_candle: pd.Series) -> dict[str, pd.Series]:
    funding_z = _rolling_z(funding_on_candle, SCREEN_ZSCORE_DAYS * 24)
    funding_mom = funding_on_candle - funding_on_candle.shift(SCREEN_MOM_HOURS)
    return {"funding_z": funding_z, "funding_mom": funding_mom}


def oi_factors(oi_on_candle: pd.Series, close: pd.Series) -> dict[str, pd.Series]:
    oi_z = _rolling_z(oi_on_candle, SCREEN_ZSCORE_DAYS * 24)
    oi_price_divergence = oi_on_candle.pct_change(24) * close.pct_change(24)
    oi_mom = oi_on_candle.pct_change(OI_MOM_HOURS)
    return {"oi_z": oi_z, "oi_price_divergence": oi_price_divergence, "oi_mom": oi_mom}
