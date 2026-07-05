# agent/src/trading/hybrid_bot/check_indicators.py
import ccxt
import pandas as pd
import numpy as np
from tabulate import tabulate
from agent.src.trading.hybrid_bot.config import get_basket
from agent.src.trading.hybrid_bot.signal_engine import (
    calculate_adx,
    calculate_rsi,
    ADX_TREND_THRESHOLD,
    TREND_VOL_RATIO,
    SQUEEZE_VOL_RATIO,
)

def check():
    exchange = ccxt.binance({
        'timeout': 15000,
        'enableRateLimit': True
    })
    
    basket = get_basket()[:10]  # Check top 10 coins
    print(f"Checking current metrics for top {len(basket)} assets in the basket...")
    
    table_data = []
    
    for symbol in basket:
        try:
            bars = exchange.fetch_ohlcv(symbol, timeframe='15m', limit=100)
            if not bars or len(bars) < 30:
                continue
                
            df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            # Drop the active, currently forming candle so metrics match the signal engine
            df = df.iloc[:-1]

            adx_series = calculate_adx(df)
            rsi_series = calculate_rsi(df['close'])
            
            adx = adx_series.iloc[-1]
            rsi = rsi_series.iloc[-1]
            current_close = df['close'].iloc[-1]
            
            volume = df['volume']
            avg_vol = volume.iloc[-21:-1].mean()
            vol_ratio = volume.iloc[-1] / avg_vol if avg_vol > 0 else 1.0
            
            high_20 = df['high'].iloc[-21:-1].max()
            low_20 = df['low'].iloc[-21:-1].min()
            
            # Check conditions
            regime = "TRENDING" if adx > ADX_TREND_THRESHOLD else "RANGING"
            req_ratio = TREND_VOL_RATIO if adx > ADX_TREND_THRESHOLD else SQUEEZE_VOL_RATIO
            
            # Distance to Donchian bounds (pct)
            dist_high = ((high_20 - current_close) / current_close) * 100
            dist_low = ((current_close - low_20) / current_close) * 100
            
            table_data.append([
                symbol,
                f"{current_close:.4f}",
                f"{adx:.1f} ({regime})",
                f"{rsi:.1f}",
                f"{vol_ratio:.2f}x (Req: {req_ratio:.1f}x)",
                f"{dist_high:.2f}%" if dist_high > 0 else "BROKEN",
                f"{dist_low:.2f}%" if dist_low > 0 else "BROKEN"
            ])
        except Exception as e:
            table_data.append([symbol, "Error", "-", "-", "-", "-", "-"])
            
    headers = ["Asset", "Last Price", "ADX (Regime)", "RSI", "Vol Ratio", "Dist to High", "Dist to Low"]
    print(tabulate(table_data, headers=headers, tablefmt="grid"))

if __name__ == "__main__":
    check()
