# agent/src/trading/hybrid_bot/signal_engine.py
import pandas as pd
import numpy as np

# Dual-regime thresholds — single source of truth, also used by the
# diagnostic tools (check_indicators, backtest_review).
ADX_TREND_THRESHOLD = 25.0
TREND_VOL_RATIO = 2.0      # breakout volume required in a trending regime
SQUEEZE_VOL_RATIO = 3.0    # breakout volume required in a ranging regime (squeeze launch)

def calculate_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Calculates the Average Directional Index (ADX) from High/Low/Close data.
    """
    df = df.copy()
    high = df['high']
    low = df['low']
    close = df['close']
    
    # Calculate True Range (TR)
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    
    # Directional Movement (+DM and -DM)
    up_move = high.diff(1)
    down_move = low.shift(1) - low
    
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    
    # Smooth using Wilder's EMA smoothing technique
    tr_smoothed = tr.ewm(alpha=1/period, adjust=False).mean()
    plus_dm_smoothed = pd.Series(plus_dm).ewm(alpha=1/period, adjust=False).mean()
    minus_dm_smoothed = pd.Series(minus_dm).ewm(alpha=1/period, adjust=False).mean()
    
    # Directional Indicators (+DI and -DI)
    plus_di = 100 * (plus_dm_smoothed / tr_smoothed.replace(0, np.nan))
    minus_di = 100 * (minus_dm_smoothed / tr_smoothed.replace(0, np.nan))
    
    # Directional Index (DX) and ADX
    dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan))
    adx = dx.ewm(alpha=1/period, adjust=False).mean()
    
    return adx.fillna(0.0)

def calculate_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """
    Calculates the Relative Strength Index (RSI).
    """
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).ewm(alpha=1/period, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50.0)

def signal_quality(sig: dict) -> str:
    """
    'strong' if the signal clears its thresholds with comfortable margin,
    'marginal' if it barely passed. Marginal entries have a documented losing
    record (NEAR#1 short, ALLO) and get reduced position size.
    """
    if not sig["strategy"].startswith("Momentum"):
        return "marginal"  # mean reversion is counter-trend by nature
    m = sig["metrics"]
    required = TREND_VOL_RATIO if "Trending" in sig["strategy"] else SQUEEZE_VOL_RATIO
    if m["volume_ratio"] < required * 1.2:
        return "marginal"
    if "Trending" in sig["strategy"] and m["adx"] < ADX_TREND_THRESHOLD + 5:
        return "marginal"
    return "strong"

def evaluate_signals(df: pd.DataFrame) -> dict | None:
    """
    Analyzes historical data and generates signals based on a Dual-Regime Breakout Filter.
    1. Trending Breakout (ADX > 25): Enters breakouts on vol_ratio >= 2.0x.
    2. Squeeze Breakout (ADX <= 25): Enters breakouts only on extreme vol_ratio >= 3.0x (bypasses ADX lag).
    3. Mean Reversion (ADX <= 25): Enters reversals on extreme RSI (<20 or >80).
    """
    if len(df) < 30:
        return None
        
    close = df['close']
    volume = df['volume']
    
    adx_series = calculate_adx(df)
    rsi_series = calculate_rsi(close)
    
    adx = adx_series.iloc[-1]
    rsi = rsi_series.iloc[-1]
    current_close = close.iloc[-1]
    
    # Calculate volume ratio
    avg_vol = volume.iloc[-21:-1].mean()
    vol_ratio = volume.iloc[-1] / avg_vol if avg_vol > 0 else 1.0
    
    # 20-period Donchian boundaries
    high_20 = df['high'].iloc[-21:-1].max()
    low_20 = df['low'].iloc[-21:-1].min()
    
    # Check for breakout candidates
    is_long_breakout = current_close > high_20
    is_short_breakout = current_close < low_20
    
    # Case A: Breakout Candidates
    if is_long_breakout or is_short_breakout:
        signal_type = "LONG" if is_long_breakout else "SHORT"
        
        # 1. Trending Breakout (High Trend Environment)
        if adx > ADX_TREND_THRESHOLD and vol_ratio >= TREND_VOL_RATIO:
            return {
                "signal": signal_type,
                "strategy": "Momentum Breakout (Trending)",
                "metrics": {
                    "adx": float(adx),
                    "rsi": float(rsi),
                    "close": float(current_close),
                    "volume_ratio": float(vol_ratio)
                },
                "reason": f"Trending Breakout: {signal_type} of 20-period channel with {vol_ratio:.2f}x volume expansion (ADX={adx:.2f})."
            }
            
        # 2. Squeeze Breakout (Low Trend, High Force Launch Environment - Bypasses ADX lag)
        elif adx <= ADX_TREND_THRESHOLD and vol_ratio >= SQUEEZE_VOL_RATIO:
            return {
                "signal": signal_type,
                "strategy": "Momentum Breakout (Squeeze)",
                "metrics": {
                    "adx": float(adx),
                    "rsi": float(rsi),
                    "close": float(current_close),
                    "volume_ratio": float(vol_ratio)
                },
                "reason": f"Squeeze Breakout: Early {signal_type} trend launch with massive {vol_ratio:.2f}x volume explosion under low volatility (ADX={adx:.2f})."
            }
            
    # Case B: Mean Reversion Reversals (Only allowed in Ranging Environment ADX <= 25)
    if adx <= ADX_TREND_THRESHOLD:
        if rsi < 20:
            return {
                "signal": "LONG",
                "strategy": "Mean Reversion",
                "metrics": {
                    "adx": float(adx),
                    "rsi": float(rsi),
                    "close": float(current_close),
                    "volume_ratio": float(vol_ratio)
                },
                "reason": f"Mean Reversion Reversal: RSI ({rsi:.2f}) reached oversold region (< 20) under ranging market (ADX={adx:.2f})."
            }
        elif rsi > 80:
            return {
                "signal": "SHORT",
                "strategy": "Mean Reversion",
                "metrics": {
                    "adx": float(adx),
                    "rsi": float(rsi),
                    "close": float(current_close),
                    "volume_ratio": float(vol_ratio)
                },
                "reason": f"Mean Reversion Reversal: RSI ({rsi:.2f}) reached overbought region (> 80) under ranging market (ADX={adx:.2f})."
            }
            
    return None
