# agent/src/trading/hybrid_bot/runner.py
import os
import json
import logging
import threading
import time
import pandas as pd
import numpy as np
import ccxt
from pathlib import Path
from agent.src.trading.hybrid_bot.config import get_basket, BASE_DIR
from agent.src.trading.hybrid_bot.basket_manager import update_active_basket
from agent.src.trading.hybrid_bot.signal_engine import evaluate_signals, signal_quality
from agent.src.trading.hybrid_bot.validator import validate_signal_with_llm

# Setup logging to a dedicated file; prefer the runs volume so logs survive container recreation
log_file = Path("/app/agent/runs/hybrid_runner.log") if Path("/app/agent/runs").exists() else BASE_DIR / "runner.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("hybrid_bot_runner")

# Guards all read-modify-write access to the JSON state files (positions,
# wallet, history). The daemon thread and dashboard background tasks run in
# the same process, so a process-local lock is sufficient.
STATE_LOCK = threading.RLock()

POSITIONS_FILE = Path("/app/agent/runs/hybrid_positions.json") if Path("/app/agent/runs").exists() else BASE_DIR / "active_positions.json"
WALLET_FILE = Path("/app/agent/runs/hybrid_wallet.json") if Path("/app/agent/runs").exists() else BASE_DIR / "wallet.json"
HISTORY_FILE = Path("/app/agent/runs/hybrid_history.json") if Path("/app/agent/runs").exists() else BASE_DIR / "trade_history.json"
SETTINGS_FILE = Path("/app/agent/runs/hybrid_settings.json") if Path("/app/agent/runs").exists() else BASE_DIR / "settings.json"
REJECTED_FILE = Path("/app/agent/runs/hybrid_rejected.json") if Path("/app/agent/runs").exists() else BASE_DIR / "rejected_signals.json"

# Runtime knobs editable from the dashboard. Bounds keep fat-finger input
# from producing nonsense trades.
DEFAULT_SETTINGS = {
    "max_positions": 3,
    "atr_multiplier": 3.0,
    "min_stop_pct": 1.5,
    "position_pct": 10.0,
    "basket_refresh_hours": 24.0,
    "ladder_enabled": False,      # profit ladder: tighten trail as profit grows
    "stale_exit_minutes": 0.0,    # 0 = off: exit if in profit but no new extreme for N minutes
    "time_stop_minutes": 0.0,     # 0 = off: cut trades that never reached min MFE after N minutes
    "time_stop_min_mfe_pct": 0.3, # MFE threshold the trade must reach to escape the time-stop
    "flip_cooldown_hours": 12.0,  # 0 = off: after closing a coin, no opposite-direction entry for N hours
    "short_range_max_pct": 40.0,  # 100 = off: shorts only allowed in the bottom N% of the 24h range
    "marginal_size_factor": 0.5,  # 1.0 = off: size multiplier for signals that barely passed thresholds
    "basket_movers_slots": 6,     # 0 = pure volume ranking: basket slots reserved for biggest 24h movers
    "regime_filter_enabled": True, # counter-regime trades (SHORT in BTC uptrend etc.) sized as marginal
    "paused": False,
}
SETTINGS_BOUNDS = {
    "max_positions": (1, 10),
    "atr_multiplier": (0.5, 10.0),
    "min_stop_pct": (0.1, 10.0),
    "position_pct": (1.0, 100.0),
    "basket_refresh_hours": (1.0, 24.0),
    "stale_exit_minutes": (0.0, 360.0),
    "time_stop_minutes": (0.0, 360.0),
    "time_stop_min_mfe_pct": (0.1, 2.0),
    "flip_cooldown_hours": (0.0, 48.0),
    "short_range_max_pct": (10.0, 100.0),
    "marginal_size_factor": (0.1, 1.0),
    "basket_movers_slots": (0, 15),
}
BOOL_SETTINGS = {"paused", "ladder_enabled", "regime_filter_enabled"}
INT_SETTINGS = {"max_positions", "basket_movers_slots"}

# Profit ladder tiers: at >= fav pct, trail shrinks to multiple x ATR
LADDER_TIERS = [(0.08, 0.5), (0.05, 1.0), (0.03, 1.5)]

def get_settings() -> dict:
    with STATE_LOCK:
        settings = dict(DEFAULT_SETTINGS)
        if SETTINGS_FILE.exists():
            try:
                with open(SETTINGS_FILE, "r") as f:
                    settings.update(json.load(f))
            except Exception:
                pass
        return settings

def save_settings(settings: dict):
    with STATE_LOCK:
        with open(SETTINGS_FILE, "w") as f:
            json.dump(settings, f, indent=4)

def validate_settings(updates: dict) -> dict:
    """
    Validates a partial settings update. Returns the validated subset.
    Raises ValueError on unknown keys, non-numeric values, or out-of-bounds input.
    """
    validated = {}
    for key, value in updates.items():
        if key in BOOL_SETTINGS:
            validated[key] = bool(value)
            continue
        if key not in SETTINGS_BOUNDS:
            raise ValueError(f"Unknown setting: {key}")
        lo, hi = SETTINGS_BOUNDS[key]
        try:
            value = int(value) if key in INT_SETTINGS else float(value)
        except (TypeError, ValueError):
            raise ValueError(f"{key} must be a number")
        if not (lo <= value <= hi):
            raise ValueError(f"{key} must be between {lo} and {hi}")
        validated[key] = value
    return validated

def update_settings(updates: dict) -> dict:
    with STATE_LOCK:
        settings = get_settings()
        settings.update(validate_settings(updates))
        save_settings(settings)
        return settings

def get_positions() -> dict:
    with STATE_LOCK:
        if not POSITIONS_FILE.exists():
            return {}
        try:
            with open(POSITIONS_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}

def save_positions(positions: dict):
    with STATE_LOCK:
        with open(POSITIONS_FILE, "w") as f:
            json.dump(positions, f, indent=4)

def get_wallet() -> dict:
    with STATE_LOCK:
        if not WALLET_FILE.exists():
            initial = {"balance": 10000.0, "initial_balance": 10000.0}
            save_wallet(initial)
            return initial
        try:
            with open(WALLET_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {"balance": 10000.0, "initial_balance": 10000.0}

def save_wallet(wallet: dict):
    with STATE_LOCK:
        with open(WALLET_FILE, "w") as f:
            json.dump(wallet, f, indent=4)

def get_history() -> list:
    with STATE_LOCK:
        if not HISTORY_FILE.exists():
            save_history([])
            return []
        try:
            with open(HISTORY_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return []

def save_history(history: list):
    with STATE_LOCK:
        with open(HISTORY_FILE, "w") as f:
            json.dump(history, f, indent=4)

def calculate_atr(df: pd.DataFrame, period: int = 14) -> float:
    high = df['high']
    low = df['low']
    close = df['close']
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(period).mean().iloc[-1]
    return float(atr) if not np.isnan(atr) else 0.0

def execute_position_exit(symbol: str, exit_price: float, pos: dict) -> float:
    """
    Computes net P&L in USD, updates the wallet balance, and writes to trade history.
    Returns the net P&L percentage for logging.
    """
    entry_price = pos['entry_price']
    side = pos['side']
    entry_time = pos.get('entry_time', 'N/A')
    position_size = pos.get('position_size', 1000.0)
    leverage = pos.get('leverage', 2.0)
    
    # Performance calculations
    perf = (exit_price - entry_price) / entry_price if side == "LONG" else (entry_price - exit_price) / entry_price
    position_value = position_size * leverage
    
    # 0.05% fee for entry and exit each
    entry_fee = position_value * 0.0005
    exit_fee = position_value * 0.0005
    fees = entry_fee + exit_fee
    
    gross_pnl = perf * position_value
    net_pnl = gross_pnl - fees

    # Max favorable excursion + entry context, for post-trade analysis
    peak_price = pos.get('peak_price')
    mfe_pct = None
    if peak_price is not None:
        mfe = (peak_price - entry_price) / entry_price if side == "LONG" else (entry_price - peak_price) / entry_price
        mfe_pct = round(mfe * 100, 2)
    
    # Update Wallet
    wallet = get_wallet()
    wallet['balance'] = round(wallet['balance'] + net_pnl, 2)
    save_wallet(wallet)
    
    # Update History
    history = get_history()
    trade_record = {
        "symbol": symbol,
        "side": side,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "performance_pct": round(perf * 100, 2),
        "net_pnl_usd": round(net_pnl, 2),
        "fees_usd": round(fees, 2),
        "entry_time": entry_time,
        "exit_time": time.strftime("%Y-%m-%d %H:%M:%S")
    }
    if mfe_pct is not None:
        trade_record["max_favorable_pct"] = mfe_pct
    for key in ("strategy", "quality", "entry_adx", "entry_vol_ratio", "entry_range_pos"):
        if key in pos:
            trade_record[key] = pos[key]
    history.append(trade_record)
    save_history(history)
    
    logger.info(f"💥 Recorded trade exit for {symbol}: Net P&L: ${net_pnl:.2f} ({perf*100:.2f}%)")
    return perf

def monitor_positions(exchange: ccxt.Exchange):
    """
    Checks active positions and updates their trailing stop or executes exit if triggered.
    Holds STATE_LOCK for the whole pass so a concurrent scan cannot add a
    position that this snapshot-then-overwrite cycle would silently erase.
    """
    with STATE_LOCK:
        positions = get_positions()
        if not positions:
            return

        logger.info(f"Monitoring {len(positions)} active positions...")
        settings = get_settings()
        updated_positions = {}

        for symbol, pos in positions.items():
            try:
                ticker = exchange.fetch_ticker(symbol)
                current_price = float(ticker['last'])

                entry_price = pos['entry_price']
                side = pos['side']
                trailing_distance = pos['trailing_distance']
                stop_loss = pos['stop_loss']
                breakeven_locked = pos.get('breakeven_locked', False)

                logger.info(f"Position {side} {symbol} | Entry: {entry_price:.6g} | Current: {current_price:.6g} | Stop: {stop_loss:.6g}")

                # Calculate price performance
                perf = (current_price - entry_price) / entry_price if side == "LONG" else (entry_price - current_price) / entry_price

                # Track the favorable extreme (for ladder tiers and staleness clock)
                atr = pos.get('atr', trailing_distance / 3.0)
                peak_price = pos.get('peak_price', entry_price)
                peak_time = pos.get('peak_time', 0.0)
                is_new_extreme = current_price > peak_price if side == "LONG" else current_price < peak_price
                if is_new_extreme:
                    peak_price = current_price
                    peak_time = time.time()
                elif peak_time == 0.0:
                    peak_time = time.time()
                fav = (peak_price - entry_price) / entry_price if side == "LONG" else (entry_price - peak_price) / entry_price

                # Profit ladder (opt-in): the further in profit, the tighter the trail
                effective_trail = trailing_distance
                if settings.get("ladder_enabled"):
                    for tier_fav, tier_mult in LADDER_TIERS:
                        if fav >= tier_fav:
                            effective_trail = min(trailing_distance, max(tier_mult * atr, entry_price * 0.005))
                            break

                # Trigger exit checks
                if side == "LONG":
                    # Check stop loss hit
                    if current_price <= stop_loss:
                        execute_position_exit(symbol, current_price, pos)
                        continue # Exited, do not save

                    # Update trailing stop on new high
                    new_stop = current_price - effective_trail
                    if new_stop > stop_loss:
                        stop_loss = new_stop
                        logger.info(f"📈 Trailing Stop updated for {symbol} LONG to {stop_loss:.6g}")

                    # Breakeven lock triggers at +1.2%; never move an already higher trail back down
                    if perf >= 0.012 and not breakeven_locked:
                        stop_loss = max(stop_loss, entry_price * 1.002) # cover fees
                        breakeven_locked = True
                        logger.info(f"🔒 Breakeven lock activated for {symbol} LONG at {stop_loss:.6g}")

                elif side == "SHORT":
                    # Check stop loss hit
                    if current_price >= stop_loss:
                        execute_position_exit(symbol, current_price, pos)
                        continue # Exited, do not save

                    # Update trailing stop on new low
                    new_stop = current_price + effective_trail
                    if new_stop < stop_loss:
                        stop_loss = new_stop
                        logger.info(f"📉 Trailing Stop updated for {symbol} SHORT to {stop_loss:.6g}")

                    # Breakeven lock triggers at +1.2%; never move an already lower trail back up
                    if perf >= 0.012 and not breakeven_locked:
                        stop_loss = min(stop_loss, entry_price * 0.998) # cover fees
                        breakeven_locked = True
                        logger.info(f"🔒 Breakeven lock activated for {symbol} SHORT at {stop_loss:.6g}")

                # Staleness exit (opt-in): in profit but no new extreme for N minutes
                stale_min = settings.get("stale_exit_minutes", 0)
                if stale_min and perf > 0.01 and peak_time and (time.time() - peak_time) > stale_min * 60:
                    logger.info(f"⌛ Stale profit exit for {symbol} {side}: +{perf*100:.2f}% but no new extreme for {stale_min:.0f}m")
                    execute_position_exit(symbol, current_price, pos)
                    continue

                # Time-stop (opt-in): a breakout thesis is immediate — if the trade never
                # reached the minimum MFE after N minutes, the thesis is dead; cut it.
                ts_min = settings.get("time_stop_minutes", 0)
                if ts_min and fav < settings.get("time_stop_min_mfe_pct", 0.3) / 100:
                    try:
                        entry_epoch = time.mktime(time.strptime(pos.get('entry_time', ''), "%Y-%m-%d %H:%M:%S"))
                    except (ValueError, OverflowError):
                        entry_epoch = None
                    if entry_epoch and (time.time() - entry_epoch) >= ts_min * 60:
                        logger.info(f"⏱ Time-stop exit for {symbol} {side}: MFE {fav*100:.2f}% below threshold after {ts_min:.0f}m")
                        execute_position_exit(symbol, current_price, pos)
                        continue

                # Save updated position state
                pos['stop_loss'] = stop_loss
                pos['breakeven_locked'] = breakeven_locked
                pos['peak_price'] = peak_price
                pos['peak_time'] = peak_time
                updated_positions[symbol] = pos

            except Exception as e:
                logger.error(f"Error monitoring position for {symbol}: {e}")
                updated_positions[symbol] = pos

        save_positions(updated_positions)

def record_rejected_signal(trigger: dict, reason: str):
    """
    Records a rejected signal with its reason class so missed trades can be
    replayed later (counterfactual P&L) and the LLM gate's value measured.
    """
    if "429" in reason or "quota" in reason.lower():
        reason_class = "quota"
    elif reason.startswith("Validation process failed"):
        reason_class = "error"
    else:
        reason_class = "news"
    record = {
        "symbol": trigger["symbol"],
        "side": trigger["signal"],
        "strategy": trigger["strategy"],
        "entry_price": trigger["close"],
        "atr": trigger["atr"],
        "metrics": trigger["metrics"],
        "reason_class": reason_class,
        "reason": reason,
        "time": time.strftime("%Y-%m-%d %H:%M:%S")
    }
    with STATE_LOCK:
        rejected = []
        if REJECTED_FILE.exists():
            try:
                with open(REJECTED_FILE, "r") as f:
                    rejected = json.load(f)
            except Exception:
                rejected = []
        rejected.append(record)
        with open(REJECTED_FILE, "w") as f:
            json.dump(rejected, f, indent=4)
    return record

def in_flip_cooldown(symbol: str, signal_type: str, hours: float) -> bool:
    """
    True if the most recent closed trade on this symbol was in the OPPOSITE
    direction and exited less than `hours` ago. Blocks same-day flip-flopping
    on one coin's noise (NEAR long->short cost -$40).
    """
    if not hours:
        return False
    for trade in reversed(get_history()):
        if trade.get("symbol") != symbol:
            continue
        if trade.get("side") == signal_type:
            return False  # same direction re-entry is allowed
        try:
            exit_epoch = time.mktime(time.strptime(trade.get("exit_time", ""), "%Y-%m-%d %H:%M:%S"))
        except (ValueError, OverflowError):
            return False
        return (time.time() - exit_epoch) < hours * 3600
    return False

def detect_regime(closes) -> str:
    """'up' when the last close is above the EMA20 of the series, else 'down'."""
    s = pd.Series(list(closes), dtype=float)
    ema20 = s.ewm(span=20, adjust=False).mean().iloc[-1]
    return "up" if float(s.iloc[-1]) > float(ema20) else "down"

def range_position_pct(df: pd.DataFrame) -> float:
    """Where the last close sits inside the ~24h range: 0 = at the low, 100 = at the high."""
    day = df.tail(96)  # 96 x 15m = 24h
    d_hi = float(day['high'].max())
    d_lo = float(day['low'].min())
    close = float(df['close'].iloc[-1])
    if d_hi <= d_lo:
        return 50.0
    return (close - d_lo) / (d_hi - d_lo) * 100

def close_position(exchange: ccxt.Exchange, symbol: str) -> dict | None:
    """
    Manually closes an open position at the current market price.
    Returns the closed position dict, or None if no such position exists.
    """
    with STATE_LOCK:
        positions = get_positions()
        pos = positions.pop(symbol, None)
        if pos is None:
            return None
        ticker = exchange.fetch_ticker(symbol)
        exit_price = float(ticker['last'])
        execute_position_exit(symbol, exit_price, pos)
        save_positions(positions)
        logger.info(f"🖐 Manually closed {pos['side']} {symbol} at {exit_price:.6g}")
        return pos

def scan_markets(exchange: ccxt.Exchange = None):
    """
    Scans the dynamic basket for new entries. 
    1. Evaluates all coins in the basket first to identify triggers.
    2. Sorts triggers by volume expansion ratio (highest volume ratio first).
    3. Selects only the SINGLE best trigger to validate and execute (correlation defense).
    4. Applies an optimized stop loss (ATR multiple with a minimum pct buffer, from settings).
    """
    settings = get_settings()
    if settings.get("paused"):
        logger.info("Bot is paused. Skipping scan for new entries.")
        return

    logger.info("Starting Vibe-Trading Hybrid Bot scan cycle...")

    if exchange is None:
        exchange = ccxt.binance({
            'timeout': 15000,
            'enableRateLimit': True
        })

    # Market regime from BTC 4h vs EMA20: counter-regime entries get demoted to marginal size
    regime = None
    if settings.get("regime_filter_enabled"):
        try:
            btc_bars = exchange.fetch_ohlcv("BTC/USDT", timeframe='4h', limit=30)
            regime = detect_regime([b[4] for b in btc_bars[:-1]])
            logger.info(f"🌐 Market regime (BTC 4h vs EMA20): {regime.upper()}")
        except Exception as e:
            logger.error(f"Failed to determine market regime: {e}")

    positions = get_positions()

    # If we already have max positions, skip scanning for new entries
    if len(positions) >= settings["max_positions"]:
        logger.info(f"Max active positions reached ({settings['max_positions']}). Skipping scan for new entries.")
        return
        
    basket = get_basket()
    logger.info(f"Scanning basket of {len(basket)} coins: {basket}")
    
    signals_found = []
    
    for symbol in basket:
        if symbol in positions:
            continue
            
        try:
            logger.info(f"Fetching 15m OHLCV bars for {symbol}...")
            bars = exchange.fetch_ohlcv(symbol, timeframe='15m', limit=100)
            if not bars or len(bars) < 30:
                logger.warning(f"Not enough bar data for {symbol}.")
                continue
                
            df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            # Drop the active, currently forming candle so we only evaluate fully closed bars
            df = df.iloc[:-1]
            
            sig = evaluate_signals(df)
            if sig:
                # Flip cooldown: don't trade a coin's noise in both directions the same day
                if in_flip_cooldown(symbol, sig["signal"], settings.get("flip_cooldown_hours", 0)):
                    logger.info(f"🧊 Flip cooldown: skipping {sig['signal']} {symbol} (recent opposite-direction exit).")
                    continue
                # Range gate: shorting near the top of the 24h range is a proven trap (NEAR#1, TRX)
                rng_pos = range_position_pct(df)
                if sig["signal"] == "SHORT" and rng_pos > settings.get("short_range_max_pct", 100):
                    logger.info(f"🚧 Range gate: skipping SHORT {symbol} at {rng_pos:.0f}% of 24h range (max {settings['short_range_max_pct']:.0f}%).")
                    continue
                atr = calculate_atr(df)
                signals_found.append({
                    "symbol": symbol,
                    "signal": sig["signal"],
                    "strategy": sig["strategy"],
                    "metrics": sig["metrics"],
                    "reason": sig["reason"],
                    "atr": atr,
                    "close": float(df['close'].iloc[-1]),
                    "range_pos": round(rng_pos, 1)
                })
        except Exception as e:
            logger.error(f"Error fetching/evaluating signals for {symbol}: {e}")

    if not signals_found:
        logger.info("No technical triggers detected in this scan cycle.")
        logger.info("Scan cycle completed.")
        return
        
    # Sort signals by volume ratio (highest first) to find the most powerful breakout
    signals_found.sort(key=lambda x: x["metrics"]["volume_ratio"], reverse=True)
    logger.info(f"Detected {len(signals_found)} technical triggers. Selection pool sorted by volume ratio:")
    for item in signals_found:
        logger.info(f" - {item['symbol']}: {item['signal']} (Vol Ratio: {item['metrics']['volume_ratio']:.2f}x)")
        
    # Pick the SINGLE best trigger to execute (avoids multiple entries at the exact same minute)
    best_trigger = signals_found[0]
    symbol = best_trigger["symbol"]
    signal_type = best_trigger["signal"]
    reason = best_trigger["reason"]
    atr = best_trigger["atr"]
    entry_price = best_trigger["close"]
    
    logger.info(f"🎯 Selected best trigger for execution: {symbol} {signal_type} | Reason: {reason}")
    
    try:
        validation = validate_signal_with_llm(
            symbol=symbol,
            signal_type=signal_type,
            context_notes=reason
        )
        
        if validation.get("decision") == "APPROVE":
            logger.info(f"✅ LLM APPROVED trade for {symbol}. Executing entry...")

            # Enter at the live market price, not the trigger-candle close (paper honesty:
            # the candle closed 30s+ ago, plus LLM latency — the close is stale by now)
            try:
                live_price = float(exchange.fetch_ticker(symbol)['last'])
                if live_price > 0:
                    entry_price = live_price
            except Exception as e:
                logger.warning(f"Could not fetch live entry price for {symbol}, using candle close: {e}")

            # Widen stop loss distance to N x ATR with a minimum pct buffer (from settings)
            min_dist = entry_price * settings["min_stop_pct"] / 100
            trailing_dist = max(settings["atr_multiplier"] * atr, min_dist) if atr > 0 else min_dist
            
            if signal_type == "LONG":
                stop_loss = entry_price - trailing_dist
            else:
                stop_loss = entry_price + trailing_dist
                
            with STATE_LOCK:
                positions = get_positions()
                if len(positions) >= settings["max_positions"]:
                    logger.warning("Max positions reached mid-loop. Cancelling trade entry.")
                    return
                if symbol in positions:
                    logger.warning(f"Position for {symbol} already open (concurrent scan). Cancelling duplicate entry.")
                    return

                wallet = get_wallet()
                quality = signal_quality(best_trigger)
                if regime and ((regime == "up" and signal_type == "SHORT") or (regime == "down" and signal_type == "LONG")):
                    quality = "marginal"
                    logger.info(f"🌐 Counter-regime {signal_type} in {regime.upper()} market -> sized as marginal.")
                size_factor = settings.get("marginal_size_factor", 0.5) if quality == "marginal" else 1.0
                position_size = round(wallet['balance'] * settings["position_pct"] / 100 * size_factor, 2)

                positions[symbol] = {
                    "entry_price": entry_price,
                    "side": signal_type,
                    "trailing_distance": trailing_dist,
                    "stop_loss": stop_loss,
                    "breakeven_locked": False,
                    "position_size": position_size,
                    "leverage": 2.0,
                    "atr": atr,
                    "peak_price": entry_price,
                    "peak_time": time.time(),
                    "strategy": best_trigger["strategy"],
                    "quality": quality,
                    "entry_adx": round(best_trigger["metrics"]["adx"], 2),
                    "entry_vol_ratio": round(best_trigger["metrics"]["volume_ratio"], 2),
                    "entry_range_pos": best_trigger.get("range_pos"),
                    "entry_time": time.strftime("%Y-%m-%d %H:%M:%S")
                }
                save_positions(positions)
            logger.info(f"🛒 Entered {signal_type} on {symbol} at {entry_price:.6g} with Stop Loss: {stop_loss:.6g} | Size: ${position_size} ({quality})")
        else:
            reason_text = str(validation.get('reason'))
            logger.info(f"❌ LLM REJECTED trade for {symbol}. Reason: {reason_text}")
            record_rejected_signal(best_trigger, reason_text)
            
    except Exception as e:
        logger.error(f"Error executing trade entry for {symbol}: {e}")
            
    logger.info("Scan cycle completed.")

def run_daemon():
    """
    Continuous background worker loop.
    1. Monitors active positions every 30 seconds (high frequency trailing stop & SL management).
    2. Dynamically updates active basket every 24 hours.
    3. Triggers market scan for new entries only when a new 15-minute bar closes.
    """
    logger.info("Initializing Hybrid Bot Daemon loop (polling every 30 seconds)...")
    
    exchange = ccxt.binance({
        'timeout': 15000,
        'enableRateLimit': True
    })
    
    last_bar_time = None
    last_basket_update = 0.0
    
    while True:
        try:
            # 1. Monitor active positions (near real-time trailing-stop management)
            monitor_positions(exchange)
                
            # 2. Dynamic basket update (interval from settings, default 24h)
            now = time.time()
            if now - last_basket_update > get_settings()["basket_refresh_hours"] * 3600:
                logger.info("Triggering scheduled 24h active basket update...")
                try:
                    update_active_basket()
                except Exception as e:
                    logger.error(f"Failed to update active basket: {e}")
                last_basket_update = now
                
            # 3. Check for new 15m candle completion using BTC/USDT as indicator
            logger.debug("Checking for new candle completion...")
            bars = exchange.fetch_ohlcv("BTC/USDT", timeframe='15m', limit=2)
            if bars and len(bars) >= 2:
                # The second to last bar is the latest completed closed bar.
                # (The last element of fetch_ohlcv is the active, currently forming candle).
                latest_closed_bar_time = bars[-2][0]
                
                if last_bar_time is None:
                    # Cache on startup, run initial scan
                    last_bar_time = latest_closed_bar_time
                    logger.info(f"Initial 15m bar timestamp cached: {pd.to_datetime(last_bar_time, unit='ms')}. Running startup scan...")
                    scan_markets(exchange)
                elif latest_closed_bar_time != last_bar_time:
                    logger.info(f"🔔 New 15m candle completed: {pd.to_datetime(latest_closed_bar_time, unit='ms')}. Running scan...")
                    last_bar_time = latest_closed_bar_time
                    scan_markets(exchange)
                    
        except Exception as e:
            logger.error(f"Error in daemon loop: {e}")
            
        time.sleep(30)

if __name__ == "__main__":
    run_daemon()
