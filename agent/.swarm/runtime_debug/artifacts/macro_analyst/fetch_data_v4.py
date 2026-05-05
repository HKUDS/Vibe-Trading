#!/usr/bin/env python3
"""
Macro Analysis Data Fetcher V4 - Using working APIs
"""

import json
import urllib.request
import ssl

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

results = {}

def fetch_json(url, name=""):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
            data = json.loads(resp.read().decode())
            if name:
                print(f"  {name}: OK")
            return data
    except Exception as e:
        print(f"  {name}: Error - {str(e)[:80]}")
        return None

# ============================================================
# 1. EXCHANGE RATES (from exchangerate-api.com)
# ============================================================
print("[1/7] Fetching Exchange Rates...")
data = fetch_json("https://api.exchangerate-api.com/v4/latest/USD", name="Exchange Rates")
if data and "rates" in data:
    rates = data["rates"]
    results["exchange_rates"] = {
        "CNY": rates.get("CNY"),
        "CNH": rates.get("CNH"),
        "EUR": rates.get("EUR"),
        "JPY": rates.get("JPY"),
        "GBP": rates.get("GBP"),
        "HKD": rates.get("HKD"),
        "KRW": rates.get("KRW"),
        "SGD": rates.get("SGD"),
        "AUD": rates.get("AUD"),
        "CHF": rates.get("CHF"),
    }
    print(f"  USD/CNY: {rates.get('CNY')}")
    print(f"  USD/CNH: {rates.get('CNH')}")
    print(f"  EUR/USD: {rates.get('EUR')}")
    print(f"  USD/JPY: {rates.get('JPY')}")
    print(f"  USD/HKD: {rates.get('HKD')}")

# ============================================================
# 2. CRYPTOCURRENCY DATA (from CryptoCompare)
# ============================================================
print("\n[2/7] Fetching Crypto Data...")

# BTC
data = fetch_json("https://min-api.cryptocompare.com/data/price?fsym=BTC&tsyms=USD,EUR,CNY", name="BTC")
if data:
    results["btc"] = data
    print(f"  BTC: ${data.get('USD')}")

# ETH
data = fetch_json("https://min-api.cryptocompare.com/data/price?fsym=ETH&tsyms=USD,EUR,CNY", name="ETH")
if data:
    results["eth"] = data
    print(f"  ETH: ${data.get('USD')}")

# ============================================================
# 3. COMMODITIES (from CryptoCompare - they have some commodity data)
# ============================================================
print("\n[3/7] Fetching Additional Crypto/Commodity Data...")

# Gold via PAXG
data = fetch_json("https://min-api.cryptocompare.com/data/price?fsym=PAXG&tsyms=USD", name="PAXG (Gold)")
if data:
    results["paxg"] = data
    print(f"  PAXG (Gold): ${data.get('USD')}")

# ============================================================
# 4. OKX API (try different endpoints)
# ============================================================
print("\n[4/7] Fetching OKX Market Data...")

# BTC-USDT ticker
data = fetch_json("https://www.okx.com/api/v5/market/ticker?instId=BTC-USDT", name="OKX BTC-USDT")
if data and data.get("code") == "0" and data.get("data"):
    t = data["data"][0]
    results["okx_btc"] = {
        "last": float(t["last"]),
        "high24h": float(t["high24h"]),
        "low24h": float(t["low24h"]),
        "vol24h": float(t["vol24h"]),
        "volCcy24h": float(t["volCcy24h"]),
    }
    print(f"  OKX BTC: ${results['okx_btc']['last']}")

# ETH-USDT
data = fetch_json("https://www.okx.com/api/v5/market/ticker?instId=ETH-USDT", name="OKX ETH-USDT")
if data and data.get("code") == "0" and data.get("data"):
    t = data["data"][0]
    results["okx_eth"] = {
        "last": float(t["last"]),
        "high24h": float(t["high24h"]),
        "low24h": float(t["low24h"]),
    }
    print(f"  OKX ETH: ${results['okx_eth']['last']}")

# SOL-USDT
data = fetch_json("https://www.okx.com/api/v5/market/ticker?instId=SOL-USDT", name="OKX SOL-USDT")
if data and data.get("code") == "0" and data.get("data"):
    t = data["data"][0]
    results["okx_sol"] = {
        "last": float(t["last"]),
        "high24h": float(t["high24h"]),
        "low24h": float(t["low24h"]),
    }
    print(f"  OKX SOL: ${results['okx_sol']['last']}")

# BTC-USDT-SWAP funding rate
data = fetch_json("https://www.okx.com/api/v5/public/funding-rate?instId=BTC-USDT-SWAP", name="OKX BTC Funding")
if data and data.get("code") == "0" and data.get("data"):
    fr = data["data"][0]
    results["okx_btc_funding"] = {
        "funding_rate": float(fr["fundingRate"]),
    }
    print(f"  OKX BTC Funding Rate: {results['okx_btc_funding']['funding_rate']:.6f}")

# ============================================================
# 5. OKX Candlestick Data (for trend analysis)
# ============================================================
print("\n[5/7] Fetching OKX Candlestick Data...")

# BTC 1D candles (last 30 days)
data = fetch_json("https://www.okx.com/api/v5/market/candles?instId=BTC-USDT&bar=1D&limit=30", name="OKX BTC 1D Candles")
if data and data.get("code") == "0" and data.get("data"):
    candles = data["data"]
    if len(candles) >= 2:
        # candles are in reverse chronological order
        oldest = candles[-1]
        newest = candles[0]
        open_price = float(oldest[1])
        close_price = float(newest[4])
        results["btc_30d"] = {
            "period_open": open_price,
            "period_close": close_price,
            "return_pct": round((close_price / open_price - 1) * 100, 2),
        }
        print(f"  BTC 30-day: {results['btc_30d']['return_pct']}%")

# BTC 1W candles (last 12 weeks)
data = fetch_json("https://www.okx.com/api/v5/market/candles?instId=BTC-USDT&bar=1W&limit=12", name="OKX BTC 1W Candles")
if data and data.get("code") == "0" and data.get("data"):
    candles = data["data"]
    if len(candles) >= 2:
        oldest = candles[-1]
        newest = candles[0]
        open_price = float(oldest[1])
        close_price = float(newest[4])
        results["btc_12w"] = {
            "period_open": open_price,
            "period_close": close_price,
            "return_pct": round((close_price / open_price - 1) * 100, 2),
        }
        print(f"  BTC 12-week: {results['btc_12w']['return_pct']}%")

# ============================================================
# 6. OKX Ticker for all major instruments
# ============================================================
print("\n[6/7] Fetching OKX All Tickers...")

data = fetch_json("https://www.okx.com/api/v5/market/tickers?instType=SPOT", name="OKX SPOT Tickers")
if data and data.get("code") == "0" and data.get("data"):
    tickers = data["data"]
    # Find key pairs
    key_pairs = ["BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "DOGE-USDT"]
    for pair in key_pairs:
        for t in tickers:
            if t["instId"] == pair:
                results[f"okx_spot_{pair.replace('-', '_')}"] = {
                    "last": float(t["last"]),
                    "vol24h": float(t["vol24h"]),
                    "volCcy24h": float(t["volCcy24h"]),
                }
                print(f"  {pair}: ${float(t['last']):.2f}, Vol: ${float(t['volCcy24h']):.0f}")
                break

# ============================================================
# 7. OKX SWAP Tickers (for derivatives sentiment)
# ============================================================
print("\n[7/7] Fetching OKX SWAP Tickers...")

data = fetch_json("https://www.okx.com/api/v5/market/tickers?instType=SWAP", name="OKX SWAP Tickers")
if data and data.get("code") == "0" and data.get("data"):
    tickers = data["data"]
    key_pairs = ["BTC-USDT-SWAP", "ETH-USDT-SWAP"]
    for pair in key_pairs:
        for t in tickers:
            if t["instId"] == pair:
                results[f"okx_swap_{pair.replace('-', '_')}"] = {
                    "last": float(t["last"]),
                    "last_fill_px": float(t["lastFillPx"]) if t.get("lastFillPx") else None,
                    "open_interest": float(t["oiCcy"]) if t.get("oiCcy") else None,
                }
                print(f"  {pair}: ${float(t['last']):.2f}, OI: {float(t['oiCcy']):.2f} BTC")
                break

# ============================================================
# SUMMARY
# ============================================================
print("\n" + "=" * 80)
print("COMPLETE DATA SUMMARY")
print("=" * 80)
print(json.dumps(results, indent=2, default=str))

with open("macro_data.json", "w") as f:
    json.dump(results, f, indent=2, default=str)

print("\nData saved to macro_data.json")
