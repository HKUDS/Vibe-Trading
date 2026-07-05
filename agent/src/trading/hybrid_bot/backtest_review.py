# agent/src/trading/hybrid_bot/backtest_review.py
import ccxt
import pandas as pd
import numpy as np
from agent.src.trading.hybrid_bot.signal_engine import calculate_adx, calculate_rsi, evaluate_signals

def review():
    exchange = ccxt.binance({
        'timeout': 15000,
        'enableRateLimit': True
    })
    
    # We analyze the big movers
    coins = ["RE/USDT", "WLD/USDT", "CELO/USDT", "NFP/USDT", "BTC/USDT"]
    print("=============================================================")
    print("BACKTEST HISTORICAL ANALYSIS: YESTERDAY MOVERS")
    print("Checking why we missed big moves. Scanning breakouts (Donchian Cross)...")
    print("=============================================================")
    
    for symbol in coins:
        try:
            # Fetch 150 bars of 15m (~37.5 hours) to cover all of yesterday
            bars = exchange.fetch_ohlcv(symbol, timeframe='15m', limit=150)
            if not bars or len(bars) < 30:
                print(f"Skipping {symbol}: Not enough data.")
                continue
                
            df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            # Drop the active, currently forming candle so bars match the signal engine
            df = df.iloc[:-1]
            df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms')

            # Indicators (EWM is causal, so values at bar i match the engine's view at bar i)
            adx_series = calculate_adx(df)
            rsi_series = calculate_rsi(df['close'])

            # Loop through bars and identify when price crossed the 20-period Donchian Channel
            breakouts = []

            # Start at 30: evaluate_signals needs at least 30 bars of history
            for i in range(30, len(df)):
                current_close = df['close'].iloc[i]
                # Same windows the engine uses: the 20 fully closed bars before bar i
                high_20 = df['high'].iloc[i-20:i].max()
                low_20 = df['low'].iloc[i-20:i].min()

                volume = df['volume'].iloc[i]
                avg_vol = df['volume'].iloc[i-20:i].mean()
                vol_ratio = volume / avg_vol if avg_vol > 0 else 1.0

                adx = adx_series.iloc[i]
                rsi = rsi_series.iloc[i]
                dt = df['datetime'].iloc[i]

                # Check for breakout
                is_long_breakout = current_close > high_20
                is_short_breakout = current_close < low_20

                if is_long_breakout or is_short_breakout:
                    breakout_type = "LONG" if is_long_breakout else "SHORT"
                    # Ask the real engine instead of duplicating its rules,
                    # so this review can never drift out of sync again.
                    sig = evaluate_signals(df.iloc[:i+1])
                    triggered = bool(sig and sig["strategy"].startswith("Momentum"))
                    breakouts.append({
                        "time": dt.strftime("%m-%d %H:%M"),
                        "type": breakout_type,
                        "price": current_close,
                        "vol_ratio": vol_ratio,
                        "adx": adx,
                        "rsi": rsi,
                        "status": "TRIGGERED" if triggered else "FILTERED_OUT"
                    })
            
            print(f"\nAsset: {symbol} | Total Breakout Candidates: {len(breakouts)}")
            if not breakouts:
                print(" No Donchian channel crossings found.")
                continue
                
            # Filter to show a summary of candidates
            df_breakouts = pd.DataFrame(breakouts)
            # Show top 8 breakout candidates by volume ratio to see where the volume was
            df_sorted = df_breakouts.sort_values(by="vol_ratio", ascending=False).head(8)
            
            # Print table
            print(df_sorted.to_string(index=False, columns=["time", "type", "price", "vol_ratio", "adx", "rsi", "status"]))
            
        except Exception as e:
            print(f"Error reviewing {symbol}: {e}")
            
if __name__ == "__main__":
    review()
