# agent/src/trading/hybrid_bot/backtest_simulator.py
import ccxt
import pandas as pd
import numpy as np
import time
from tabulate import tabulate
from agent.src.trading.hybrid_bot.config import get_basket
from agent.src.trading.hybrid_bot.signal_engine import (
    calculate_adx,
    calculate_rsi,
    ADX_TREND_THRESHOLD,
    TREND_VOL_RATIO,
    SQUEEZE_VOL_RATIO
)

def fetch_30d_data(exchange, symbol):
    """
    Fetches the last 30 days of 15m OHLCV data from Binance.
    30 days * 24h * 4 bars = 2880 bars. We fetch in chunks.
    """
    now_ms = int(time.time() * 1000)
    start_ms = now_ms - (30 * 24 * 60 * 60 * 1000)
    
    all_bars = []
    since = start_ms
    limit = 1000
    
    while since < now_ms:
        try:
            bars = exchange.fetch_ohlcv(symbol, timeframe='15m', since=since, limit=limit)
            if not bars:
                break
            all_bars.extend(bars)
            since = bars[-1][0] + 1
            time.sleep(0.05) # Respect Binance rate limits
        except Exception as e:
            print(f"Error fetching {symbol}: {e}")
            break
            
    df = pd.DataFrame(all_bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df = df.drop_duplicates(subset=['timestamp']).sort_values('timestamp').reset_index(drop=True)
    df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms')
    return df

def calculate_atr_series(df, period=14):
    high = df['high']
    low = df['low']
    close = df['close']
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()
    return atr.fillna(0.0)

def run_backtest(days=30):
    exchange = ccxt.binance({
        'timeout': 15000,
        'enableRateLimit': True
    })
    
    basket = get_basket()
    print(f"=============================================================")
    print(f"STARTING VIBE-TRADING HYBRID BOT BACKTEST SIMULATOR")
    print(f"Sepet: {len(basket)} Kripto Varlık")
    print(f"Süre: Son {days} Gün | Zaman Dilimi: 15m")
    print(f"=============================================================")
    
    # 1. Download data
    print("\n[1/3] Tarihsel veriler Binance'den indiriliyor...")
    data_dict = {}
    for idx, symbol in enumerate(basket):
        print(f"  ({idx+1}/{len(basket)}) {symbol} indiriliyor...")
        df = fetch_30d_data(exchange, symbol)
        if len(df) < 50:
            print(f"    ⚠️ Yetersiz veri ({len(df)} bar), atlanıyor.")
            continue
        data_dict[symbol] = df
        
    if not data_dict:
        print("❌ Hiçbir coin verisi indirilemedi. Backtest durduruldu.")
        return
        
    # 2. Pre-calculate indicators for speed
    print("\n[2/3] İndikatörler hesaplanıyor...")
    for symbol, df in data_dict.items():
        df['adx'] = calculate_adx(df)
        df['rsi'] = calculate_rsi(df['close'])
        df['atr'] = calculate_atr_series(df)
        
        # Donchian channel limits of the past 20 bars (shifted by 1 to represent closed bars)
        df['high_20'] = df['high'].shift(1).rolling(20).max()
        df['low_20'] = df['low'].shift(1).rolling(20).min()
        
        # 20-period average volume (shifted by 1)
        df['avg_vol'] = df['volume'].shift(1).rolling(20).mean()
        df['vol_ratio'] = df['volume'] / df['avg_vol'].replace(0, np.nan)
        df['vol_ratio'] = df['vol_ratio'].fillna(1.0)
        
    # Find all unique timestamps aligned across download
    all_timestamps = set()
    for df in data_dict.values():
        all_timestamps.update(df['timestamp'].tolist())
    sorted_timestamps = sorted(list(all_timestamps))
    
    # Align dataframes for index-based step-by-step lookup
    aligned_data = {}
    for symbol, df in data_dict.items():
        # Reindex to have consistent timestamps (fill missing values with forward fill)
        df_indexed = df.set_index('timestamp').reindex(sorted_timestamps).ffill().bfill()
        df_indexed['datetime'] = pd.to_datetime(df_indexed.index, unit='ms')
        aligned_data[symbol] = df_indexed
        
    print(f"  Toplam hizalanmış zaman adımı: {len(sorted_timestamps)} (15 dakikalık bar)")
    
    # 3. Simulate trading
    print("\n[3/3] Backtest simülasyonu çalıştırılıyor...")
    
    wallet_balance = 10000.0
    initial_balance = 10000.0
    positions = {} # symbol: position_details
    history = []
    
    # Loop over time steps (skip first 30 bars to allow indicator smoothing)
    for step_idx in range(30, len(sorted_timestamps)):
        current_ts = sorted_timestamps[step_idx]
        current_dt = pd.to_datetime(current_ts, unit='ms')
        
        # A. Check active positions for stop-loss hits or trailing updates
        for symbol, pos in list(positions.items()):
            df_sym = aligned_data[symbol]
            bar = df_sym.loc[current_ts]
            
            high = float(bar['high'])
            low = float(bar['low'])
            open_p = float(bar['open'])
            close_p = float(bar['close'])
            
            entry_price = pos['entry_price']
            side = pos['side']
            trailing_distance = pos['trailing_distance']
            stop_loss = pos['stop_loss']
            breakeven_locked = pos['breakeven_locked']
            position_size = pos['position_size']
            leverage = pos['leverage']
            
            # exit checks
            exited = False
            exit_price = 0.0
            
            if side == "LONG":
                # Check stop loss hit (we check Low of the current bar)
                if low <= stop_loss:
                    # In a gap down, stop-loss might execute at open price if open is lower
                    exit_price = min(stop_loss, open_p)
                    exited = True
                else:
                    # Update trailing stop
                    new_stop = high - trailing_distance
                    if new_stop > stop_loss:
                        stop_loss = new_stop
                    
                    # Update breakeven lock
                    perf = (high - entry_price) / entry_price
                    if perf >= 0.012 and not breakeven_locked:
                        stop_loss = max(stop_loss, entry_price * 1.002)
                        breakeven_locked = True
                        
            elif side == "SHORT":
                # Check stop loss hit (we check High of the current bar)
                if high >= stop_loss:
                    exit_price = max(stop_loss, open_p)
                    exited = True
                else:
                    # Update trailing stop
                    new_stop = low + trailing_distance
                    if new_stop < stop_loss:
                        stop_loss = new_stop
                        
                    # Update breakeven lock
                    perf = (entry_price - low) / entry_price
                    if perf >= 0.012 and not breakeven_locked:
                        stop_loss = min(stop_loss, entry_price * 0.998)
                        breakeven_locked = True
                        
            if exited:
                # Performance and P&L
                perf_pct = (exit_price - entry_price) / entry_price if side == "LONG" else (entry_price - exit_price) / entry_price
                position_value = position_size * leverage
                
                # Deduct fees (0.05% entry + 0.05% exit = 0.1% total notional)
                fees = position_value * 0.001
                net_pnl = (perf_pct * position_value) - fees
                
                wallet_balance += net_pnl
                
                history.append({
                    "symbol": symbol,
                    "side": side,
                    "entry_time": pos["entry_time"],
                    "exit_time": current_dt.strftime("%Y-%m-%d %H:%M"),
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "perf_pct": perf_pct * 100,
                    "net_pnl": net_pnl,
                    "fees": fees
                })
                
                del positions[symbol]
            else:
                # Update stop-loss in state
                pos['stop_loss'] = stop_loss
                pos['breakeven_locked'] = breakeven_locked
                
        # B. Scan for new entries if positions are open slots (< 3)
        if len(positions) < 3:
            signals_found = []
            
            for symbol in basket:
                if symbol in positions:
                    continue
                    
                df_sym = aligned_data[symbol]
                
                # Fetch metrics at index i-1 (which represents the closed candle)
                prev_ts = sorted_timestamps[step_idx - 1]
                bar_closed = df_sym.loc[prev_ts]
                
                adx = float(bar_closed['adx'])
                rsi = float(bar_closed['rsi'])
                current_close = float(bar_closed['close'])
                high_20 = float(bar_closed['high_20'])
                low_20 = float(bar_closed['low_20'])
                vol_ratio = float(bar_closed['vol_ratio'])
                atr = float(bar_closed['atr'])
                
                # Skip if indicators aren't ready
                if np.isnan(adx) or np.isnan(rsi) or np.isnan(high_20) or np.isnan(atr) or atr <= 0:
                    continue
                    
                is_long_breakout = current_close > high_20
                is_short_breakout = current_close < low_20
                
                # Technical strategy evaluation
                sig_type = None
                strategy = ""
                
                if is_long_breakout or is_short_breakout:
                    sig_type = "LONG" if is_long_breakout else "SHORT"
                    
                    if adx > ADX_TREND_THRESHOLD and vol_ratio >= TREND_VOL_RATIO:
                        strategy = "Momentum (Trending)"
                    elif adx <= ADX_TREND_THRESHOLD and vol_ratio >= SQUEEZE_VOL_RATIO:
                        strategy = "Momentum (Squeeze)"
                    else:
                        sig_type = None # Filtered out
                elif adx <= ADX_TREND_THRESHOLD:
                    if rsi < 20:
                        sig_type = "LONG"
                        strategy = "Mean Reversion"
                    elif rsi > 80:
                        sig_type = "SHORT"
                        strategy = "Mean Reversion"
                        
                if sig_type:
                    signals_found.append({
                        "symbol": symbol,
                        "signal": sig_type,
                        "strategy": strategy,
                        "close": current_close,
                        "vol_ratio": vol_ratio,
                        "atr": atr
                    })
                    
            if signals_found:
                # Sort signals by volume ratio (highest first)
                signals_found.sort(key=lambda x: x["vol_ratio"], reverse=True)
                
                # Execute best signal
                best = signals_found[0]
                sym = best["symbol"]
                
                # Double check to prevent duplicate entries
                if sym not in positions and len(positions) < 3:
                    entry_p = best["close"]
                    atr_val = best["atr"]
                    sig = best["signal"]
                    
                    min_dist = entry_p * 0.015
                    trailing_dist = max(3 * atr_val, min_dist)
                    
                    stop_l = entry_p - trailing_dist if sig == "LONG" else entry_p + trailing_dist
                    pos_size = round(wallet_balance * 0.1, 2)
                    
                    positions[sym] = {
                        "entry_price": entry_p,
                        "side": sig,
                        "trailing_distance": trailing_dist,
                        "stop_loss": stop_l,
                        "breakeven_locked": False,
                        "position_size": pos_size,
                        "leverage": 2.0,
                        "entry_time": current_dt.strftime("%Y-%m-%d %H:%M")
                    }
                    
    # 4. Simulation Finished, print report
    print("\n=============================================================")
    print("BACKTEST RESULTS / BACKTEST SONUÇLARI")
    print("=============================================================")
    
    total_trades = len(history)
    if total_trades == 0:
        print("❌ Simülasyon süresince hiçbir işleme girilmedi.")
        return
        
    df_history = pd.DataFrame(history)
    
    wins = df_history[df_history['net_pnl'] > 0]
    losses = df_history[df_history['net_pnl'] <= 0]
    
    win_rate = (len(wins) / total_trades) * 100
    total_pnl_usd = wallet_balance - initial_balance
    total_pnl_pct = (total_pnl_usd / initial_balance) * 100
    
    gross_profit = wins['net_pnl'].sum()
    gross_loss = abs(losses['net_pnl'].sum())
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
    
    # Calculate drawdown series
    equity_curve = [initial_balance]
    temp_bal = initial_balance
    for trade in history:
        temp_bal += trade['net_pnl']
        equity_curve.append(temp_bal)
        
    equity_series = pd.Series(equity_curve)
    cum_max = equity_series.cummax()
    drawdowns = (cum_max - equity_series) / cum_max * 100
    max_dd = drawdowns.max()
    
    stats = [
        ["Initial Wallet Balance", f"$ {initial_balance:.2f}"],
        ["Final Wallet Balance", f"$ {wallet_balance:.2f}"],
        ["Total Net Profit/Loss", f"$ {total_pnl_usd:.2f} ({total_pnl_pct:+.2f}%)"],
        ["Total Trades Executed", f"{total_trades}"],
        ["Win Rate / Başarı Oranı", f"{win_rate:.1f}% ({len(wins)} Wins / {len(losses)} Losses)"],
        ["Profit Factor / Kâr Faktörü", f"{profit_factor:.2f}"],
        ["Max Portfolio Drawdown", f"{max_dd:.2f}%"],
        ["Average Trade Net P&L", f"$ {df_history['net_pnl'].mean():.2f} ({df_history['perf_pct'].mean():+.2f}%)"],
        ["Max Win Trade", f"$ {df_history['net_pnl'].max():.2f} ({df_history['perf_pct'].max():+.2f}%)"],
        ["Max Loss Trade", f"$ {df_history['net_pnl'].min():.2f} ({df_history['perf_pct'].min():+.2f}%)"]
    ]
    print(tabulate(stats, headers=["Metric", "Value"], tablefmt="grid"))
    
    print("\nTRADES LOG / İŞLEM DETAYLARI (Son 20 İşlem):")
    cols_to_print = ["symbol", "side", "entry_time", "exit_time", "entry_price", "exit_price", "perf_pct", "net_pnl"]
    headers_print = ["Symbol", "Side", "Entry Time", "Exit Time", "Entry Px", "Exit Px", "Perf %", "Net P&L ($)"]
    
    # Format trade items for console printing
    trade_list_print = []
    for t in history[-20:]:
        trade_list_print.append([
            t["symbol"],
            t["side"],
            t["entry_time"],
            t["exit_time"],
            f"{t['entry_price']:.4f}" if t['entry_price'] < 1 else f"{t['entry_price']:.2f}",
            f"{t['exit_price']:.4f}" if t['exit_price'] < 1 else f"{t['exit_price']:.2f}",
            f"{t['perf_pct']:+.2f}%",
            f"${t['net_pnl']:+.2f}"
        ])
    print(tabulate(trade_list_print, headers=headers_print, tablefmt="simple"))
    
if __name__ == "__main__":
    run_backtest(30)
