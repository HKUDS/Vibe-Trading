"""
research/lib/indicators.py
──────────────────────────
Computes a config-driven indicator pool from OHLCV candle data.

Uses the ``ta`` pure-Python library (no TA-Lib C compilation required).
All indicators are causal (rolling/past-only, no look-ahead).

Usage
-----
    from lib.indicators import compute_indicator_pool
    from pipeline.config import load_config

    cfg = load_config()
    indicators = compute_indicator_pool(candles_df, cfg)
    # returns dict[str, pd.Series]
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Import TA library — prefer pandas_ta if available; fall back to `ta`.
# The `ta` package (pip install ta) is a pure-Python TA library that does
# NOT require TA-Lib.  pandas_ta is also pure-Python but requires numpy<2
# (removed np.NaN) and Python>=3.12 on newer releases.
# ---------------------------------------------------------------------------
try:
    import pandas_ta as _pta  # type: ignore[import]
    _USE_PTA = True
except ImportError:  # noqa: BLE001
    _USE_PTA = False

try:
    import ta as _ta  # noqa: F401  # type: ignore[import]
    import ta.momentum as _ta_mom
    import ta.trend as _ta_trend
    import ta.volatility as _ta_vol
    import ta.volume as _ta_vol2
    _USE_TA = True
except ImportError:  # noqa: BLE001
    _USE_TA = False

if TYPE_CHECKING:
    from pipeline.config import ResearchConfig


# ─── Internal helpers ─────────────────────────────────────────────────────────

def _align(series: pd.Series, index: pd.Index) -> pd.Series:
    """Ensure *series* has the same index as *candles* (reset if lengths match)."""
    if len(series) == len(index) and not series.index.equals(index):
        series = series.copy()
        series.index = index
    return series


# ─── Indicator computation functions ─────────────────────────────────────────

def _rsi_14(candles: pd.DataFrame) -> pd.Series:
    close = candles["close"]
    if _USE_PTA:
        return _pta.rsi(close, length=14)
    if _USE_TA:
        return _ta_mom.RSIIndicator(close=close, window=14).rsi()
    # fallback: Wilder's smoothed RSI
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, min_periods=14).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def _macd_diff(candles: pd.DataFrame) -> pd.Series:
    close = candles["close"]
    if _USE_PTA:
        result = _pta.macd(close, fast=12, slow=26, signal=9)
        return result["MACDh_12_26_9"]
    if _USE_TA:
        return _ta_trend.MACD(close=close, window_slow=26, window_fast=12, window_sign=9).macd_diff()
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal = macd_line.ewm(span=9, adjust=False).mean()
    return macd_line - signal


def _roc_10(candles: pd.DataFrame) -> pd.Series:
    close = candles["close"]
    if _USE_PTA:
        return _pta.roc(close, length=10)
    if _USE_TA:
        return _ta_mom.ROCIndicator(close=close, window=10).roc()
    return close.pct_change(periods=10) * 100


def _stoch_k(candles: pd.DataFrame) -> pd.Series:
    high, low, close = candles["high"], candles["low"], candles["close"]
    if _USE_PTA:
        result = _pta.stoch(high, low, close, k=14, d=3)
        return result["STOCHk_14_3_3"]
    if _USE_TA:
        return _ta_mom.StochasticOscillator(
            high=high, low=low, close=close, window=14, smooth_window=3
        ).stoch()
    lowest_low = low.rolling(14).min()
    highest_high = high.rolling(14).max()
    k = 100 * (close - lowest_low) / (highest_high - lowest_low).replace(0, np.nan)
    return k.rolling(3).mean()


def _ema_cross_9_21(candles: pd.DataFrame) -> pd.Series:
    close = candles["close"]
    if _USE_PTA:
        ema9 = _pta.ema(close, length=9)
        ema21 = _pta.ema(close, length=21)
    elif _USE_TA:
        ema9 = _ta_trend.EMAIndicator(close=close, window=9).ema_indicator()
        ema21 = _ta_trend.EMAIndicator(close=close, window=21).ema_indicator()
    else:
        ema9 = close.ewm(span=9, adjust=False).mean()
        ema21 = close.ewm(span=21, adjust=False).mean()
    return ema9 - ema21


def _sma_cross_10_30(candles: pd.DataFrame) -> pd.Series:
    close = candles["close"]
    if _USE_PTA:
        sma10 = _pta.sma(close, length=10)
        sma30 = _pta.sma(close, length=30)
    elif _USE_TA:
        sma10 = _ta_trend.SMAIndicator(close=close, window=10).sma_indicator()
        sma30 = _ta_trend.SMAIndicator(close=close, window=30).sma_indicator()
    else:
        sma10 = close.rolling(10).mean()
        sma30 = close.rolling(30).mean()
    return sma10 - sma30


def _adx_14(candles: pd.DataFrame) -> pd.Series:
    high, low, close = candles["high"], candles["low"], candles["close"]
    if _USE_PTA:
        result = _pta.adx(high, low, close, length=14)
        return result["ADX_14"]
    if _USE_TA:
        return _ta_trend.ADXIndicator(high=high, low=low, close=close, window=14).adx()
    # Wilder smoothed ATR-based ADX fallback
    tr = pd.concat(
        [high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1
    ).max(axis=1)
    atr = tr.ewm(alpha=1 / 14, min_periods=14).mean()
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0)
    plus_di = 100 * plus_dm.ewm(alpha=1 / 14, min_periods=14).mean() / atr.replace(0, np.nan)
    minus_di = 100 * minus_dm.ewm(alpha=1 / 14, min_periods=14).mean() / atr.replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1 / 14, min_periods=14).mean()


def _atr_14(candles: pd.DataFrame) -> pd.Series:
    high, low, close = candles["high"], candles["low"], candles["close"]
    if _USE_PTA:
        return _pta.atr(high, low, close, length=14)
    if _USE_TA:
        return _ta_vol.AverageTrueRange(high=high, low=low, close=close, window=14).average_true_range()
    tr = pd.concat(
        [high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1
    ).max(axis=1)
    return tr.rolling(14).mean()


def _bb_width_20(candles: pd.DataFrame) -> pd.Series:
    close = candles["close"]
    if _USE_PTA:
        result = _pta.bbands(close, length=20)
        return result["BBB_20_2.0"]
    if _USE_TA:
        bb = _ta_vol.BollingerBands(close=close, window=20, window_dev=2)
        # bandwidth = (upper - lower) / middle  — same as BBB in pandas-ta
        return bb.bollinger_wband()
    sma = close.rolling(20).mean()
    std = close.rolling(20).std()
    upper = sma + 2 * std
    lower = sma - 2 * std
    return (upper - lower) / sma.replace(0, np.nan)


def _rolling_std_20(candles: pd.DataFrame) -> pd.Series:
    return candles["close"].rolling(20).std()


def _obv(candles: pd.DataFrame) -> pd.Series:
    close, volume = candles["close"], candles["volume"]
    if _USE_PTA:
        return _pta.obv(close, volume)
    if _USE_TA:
        return _ta_vol2.OnBalanceVolumeIndicator(close=close, volume=volume).on_balance_volume()
    direction = close.diff().apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
    return (direction * volume).cumsum()


def _mfi_14(candles: pd.DataFrame) -> pd.Series:
    high, low, close, volume = (
        candles["high"], candles["low"], candles["close"], candles["volume"]
    )
    if _USE_PTA:
        return _pta.mfi(high, low, close, volume, length=14)
    if _USE_TA:
        return _ta_vol2.MFIIndicator(
            high=high, low=low, close=close, volume=volume, window=14
        ).money_flow_index()
    typical_price = (high + low + close) / 3
    money_flow = typical_price * volume
    prev_tp = typical_price.shift(1)
    pos_flow = money_flow.where(typical_price > prev_tp, 0).rolling(14).sum()
    neg_flow = money_flow.where(typical_price < prev_tp, 0).rolling(14).sum()
    mfr = pos_flow / neg_flow.replace(0, np.nan)
    return 100 - 100 / (1 + mfr)


def _volume_zscore_20(candles: pd.DataFrame) -> pd.Series:
    volume = candles["volume"]
    return (volume - volume.rolling(20).mean()) / volume.rolling(20).std()


# ─── Dispatch table ───────────────────────────────────────────────────────────

_INDICATOR_DISPATCH: dict[str, object] = {
    "rsi_14": _rsi_14,
    "macd_diff": _macd_diff,
    "roc_10": _roc_10,
    "stoch_k": _stoch_k,
    "ema_cross_9_21": _ema_cross_9_21,
    "sma_cross_10_30": _sma_cross_10_30,
    "adx_14": _adx_14,
    "atr_14": _atr_14,
    "bb_width_20": _bb_width_20,
    "rolling_std_20": _rolling_std_20,
    "obv": _obv,
    "mfi_14": _mfi_14,
    "volume_zscore_20": _volume_zscore_20,
}


# ─── Public API ───────────────────────────────────────────────────────────────

def compute_indicator_pool(
    candles: pd.DataFrame,
    config: "ResearchConfig",
) -> dict[str, pd.Series]:
    """Compute a config-driven indicator pool from OHLCV candle data.

    Parameters
    ----------
    candles:
        DataFrame with columns ``open``, ``high``, ``low``, ``close``, ``volume``.
        Index must be a DatetimeIndex (UTC).
    config:
        A ``ResearchConfig`` instance.  ``config.indicator_pool`` determines
        which indicators are computed.

    Returns
    -------
    dict[str, pd.Series]
        Keys are indicator short names; values are pd.Series aligned to
        ``candles.index``.  All indicators are causal (no look-ahead).
    """
    if not config.indicator_pool:
        return {}

    result: dict[str, pd.Series] = {}

    for name in config.indicator_pool:
        if name not in _INDICATOR_DISPATCH:
            print(f"[indicators] WARNING: unknown indicator '{name}' — skipping.")
            continue

        try:
            series: pd.Series = _INDICATOR_DISPATCH[name](candles)  # type: ignore[operator]

            if not isinstance(series, pd.Series):
                raise TypeError(
                    f"Expected pd.Series from '{name}', got {type(series).__name__}"
                )

            series = _align(series, candles.index)
            series.name = name
            result[name] = series

        except Exception as exc:  # noqa: BLE001
            print(f"[indicators] WARNING: failed to compute '{name}': {exc} — skipping.")

    return result
