# agent/src/trading/hybrid_bot/basket_manager.py
import ccxt
import json
import logging
from agent.src.trading.hybrid_bot.config import BASKET_FILE

logger = logging.getLogger(__name__)

# Movers must still be liquid enough to trade: min 24h quote volume in USD
MIN_MOVER_LIQUIDITY = 5_000_000

def select_basket(pairs: list, movers_slots: int, size: int = 20) -> list:
    """
    Blends the basket: (size - movers_slots) coins by absolute 24h volume,
    remaining slots filled by the biggest 24h movers (abs price change).
    Volume-only ranking adds a pumping coin a day late (missed HMSTR +83%);
    movers slots catch it while the move is still young.
    """
    movers_slots = max(0, min(movers_slots, size))
    by_volume = sorted(pairs, key=lambda x: x["volume"], reverse=True)
    basket = [p["symbol"] for p in by_volume[:size - movers_slots]]
    movers = sorted(pairs, key=lambda x: abs(x.get("change") or 0.0), reverse=True)
    for p in movers:
        if len(basket) >= size:
            break
        if p["symbol"] not in basket:
            basket.append(p["symbol"])
    return basket

def update_active_basket() -> list:
    """
    Fetches USDT tickers from Binance and saves the blended top-20
    (volume core + movers slots) to active_basket.json.
    """
    try:
        exchange = ccxt.binance({
            'timeout': 15000,
            'enableRateLimit': True
        })
        logger.info("Fetching markets and tickers from Binance...")
        exchange.load_markets()
        tickers = exchange.fetch_tickers()

        usdt_pairs = []
        stablecoin_keywords = {"USDC", "USD1", "RLUSD", "EUR", "BUSD", "TUSD", "DAI", "FDUSD", "USDP", "GBP", "TRY", "RUB"}
        for symbol, ticker in tickers.items():
            # Filter for USDT contracts/spot pairs that have volume info
            if symbol.endswith("/USDT") and ticker.get("quoteVolume"):
                base_asset = symbol.split("/")[0]
                if base_asset in stablecoin_keywords:
                    continue
                volume = float(ticker["quoteVolume"])
                if volume < MIN_MOVER_LIQUIDITY:
                    continue
                usdt_pairs.append({
                    "symbol": symbol,
                    "volume": volume,
                    "change": float(ticker["percentage"]) if ticker.get("percentage") is not None else 0.0,
                    "last": float(ticker["last"]) if ticker.get("last") else 0.0
                })

        if not usdt_pairs:
            raise ValueError("No USDT trading pairs retrieved from Binance.")

        # Local import to avoid a circular module dependency with runner
        from agent.src.trading.hybrid_bot.runner import get_settings
        movers_slots = int(get_settings().get("basket_movers_slots", 6))

        top_20 = select_basket(usdt_pairs, movers_slots)

        with open(BASKET_FILE, "w") as f:
            json.dump(top_20, f, indent=4)

        logger.info(f"Active basket updated ({20 - movers_slots} by volume + {movers_slots} movers): {top_20}")
        return top_20

    except Exception as e:
        logger.error(f"Failed to dynamically fetch active basket: {e}. Keeping existing or fallback.")
        # If failure, return existing basket if it exists
        if BASKET_FILE.exists():
            try:
                with open(BASKET_FILE, "r") as f:
                    return json.load(f)
            except Exception:
                pass
        return ["BTC/USDT", "ETH/USDT", "SOL/USDT"]

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    update_active_basket()
