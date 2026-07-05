# agent/src/trading/hybrid_bot/config.py
import os
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
BASKET_FILE = BASE_DIR / "active_basket.json"

def get_basket() -> list[str]:
    if not BASKET_FILE.exists():
        # Fallback to default liquid coins if the selector hasn't run yet
        return [
            "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT",
            "ADA/USDT", "DOGE/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT"
        ]
    try:
        with open(BASKET_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
