#!/usr/bin/env python3
"""
Macro Analysis Data Fetcher V3 - Using OKX API and alternative sources
"""

import json
import time
import urllib.request
import ssl

# Create SSL context that doesn't verify (for testing)
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

results = {}

def fetch_json(url, params=None, name=""):
    """Fetch JSON from URL"""
    try:
        if params:
            url = url + "?" + "&".join([f"{k}={v}" for k, v in params.items()])
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json"
        })
        with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
            data = json.loads(resp.read().decode())
            if name:
                print(f"  {name}: OK")
            return data
    except Exception as e:
        print(f"  {name}: Error - {e}")
        return None

# ============================================================
# 1. OKX Market Data (Crypto as macro sentiment proxy)
# ============================================================
print("[1/6] Fetching OKX Crypto Market Data...")

# BTC/USDT ticker
data = fetch_json("https://www.okx.com/api/v5/market/ticker?instId=BTC-USDT", name="BTC-USDT Ticker")
if data and data.get("code") == "0":
    ticker = data["data"][0]
    results["btc"] = {
        "last": float(ticker["last"]),
        "high_24h": float(ticker["high24h"]),
        "low_24h": float(ticker["low24h"]),
        "vol_24h": float(ticker["vol24h"]),
        "vol_ccy_24h": float(ticker["volCcy24h"]),
    }
    print(f"  BTC: ${results['btc']['last']}")

# ETH/USDT ticker
data = fetch_json("https://www.okx.com/api/v5/market/ticker?instId=ETH-USDT", name="ETH-USDT Ticker")
if data and data.get("code") == "0":
    ticker = data["data"][0]
    results["eth"] = {
        "last": float(ticker["last"]),
        "high_24h": float(ticker["high24h"]),
        "low_24h": float(ticker["low24h"]),
    }
    print(f"  ETH: ${results['eth']['last']}")

# BTC/USDT candlestick (1D, last 30 days)
data = fetch_json("https://www.okx.com/api/v5/market/candles?instId=BTC-USDT&bar=1D&limit=30", name="BTC Candlestick")
if data and data.get("code") == "0":
    candles = data["data"]
    if len(candles) > 0:
        first_close = float(candles[-1][4])  # oldest
        last_close = float(candles[0][4])     # newest
        results["btc_30d_return"] = round((last_close / first_close - 1) * 100, 2)
        print(f"  BTC 30-day return: {results['btc_30d_return']}%")

# Funding rate (sentiment indicator)
data = fetch_json("https://www.okx.com/api/v5/public/funding-rate?instId=BTC-USDT-SWAP", name="BTC Funding Rate")
if data and data.get("code") == "0":
    fr = data["data"][0]
    results["btc_funding_rate"] = {
        "funding_rate": float(fr["fundingRate"]),
        "next_funding_time": int(fr["nextFundingTime"]) // 1000,
    }
    print(f"  BTC Funding Rate: {results['btc_funding_rate']['funding_rate']:.6f}")

# Open Interest
data = fetch_json("https://www.okx.com/api/v5/market/open-interest?instType=SWAP", name="Crypto OI")
if data and data.get("code") == "0":
    oi_data = data["data"]
    btc_oi = [x for x in oi_data if x["instId"] == "BTC-USDT-SWAP"]
    if btc_oi:
        results["btc_open_interest"] = float(btc_oi[0]["oiCcy"])
        print(f"  BTC Open Interest: {results['btc_open_interest']:.2f} BTC")

# ============================================================
# 2. OKX Index Data
# ============================================================
print("\n[2/6] Fetching OKX Index Data...")

# USDT/CNY index (China crypto premium)
data = fetch_json("https://www.okx.com/api/v5/market/index-ticker?instId=USDT_CNY", name="USDT/CNY Index")
if data and data.get("code") == "0" and len(data["data"]) > 0:
    ticker = data["data"][0]
    results["usdt_cny"] = {
        "last": float(ticker["last"]),
    }
    print(f"  USDT/CNY Index: {results['usdt_cny']['last']}")

# ============================================================
# 3. OKX Market Tickers for major pairs
# ============================================================
print("\n[3/6] Fetching Major OKX Tickers...")

pairs = ["BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT"]
for pair in pairs:
    data = fetch_json(f"https://www.okx.com/api/v5/market/ticker?instId={pair}", name=pair)
    if data and data.get("code") == "0" and len(data["data"]) > 0:
        t = data["data"][0]
        results[f"okx_{pair.replace('-', '_')}"] = {
            "last": float(t["last"]),
            "open_24h": float(t["open24h"]),
            "change_pct_24h": float(t["sodUtc0"]) if "sodUtc0" in t else None,
        }
        change = float(t["last"]) / float(t["open24h"]) - 1 if float(t["open24h"]) > 0 else 0
        print(f"  {pair}: ${float(t['last']):.2f} (24h: {change*100:.2f}%)")

# ============================================================
# 4. Try Yahoo Finance with single batch
# ============================================================
print("\n[4/6] Attempting Yahoo Finance (single batch)...")

try:
    import yfinance as yf
    
    # Try a small batch first
    tickers = yf.Tickers("SPY TLT EEM FXI MCHI")
    time.sleep(2)
    
    # Get latest prices
    for ticker_name, ticker_obj in tickers.tickers.items():
        try:
            info = ticker_obj.info
            if info:
                price = info.get("currentPrice", info.get("regularMarketPrice"))
                if price:
                    results[f"yf_{ticker_name}"] = {"price": round(price, 2)}
                    print(f"  {ticker_name}: ${price:.2f}")
        except:
            pass
except Exception as e:
    print(f"  Yahoo Finance error: {e}")

# ============================================================
# 5. Try fetching key indices via alternative method
# ============================================================
print("\n[5/6] Fetching Key Indices via yfinance Tickers...")

try:
    import yfinance as yf
    time.sleep(3)
    
    # Try individual tickers
    indices = {
        "SSE": "000001.SS",
        "CSI300": "000300.SS",
        "HSI": "^HSI",
        "SPX": "^GSPC",
        "US10Y": "^TNX",
        "DXY": "DX-Y.NYB",
        "USDCNY": "CNY=X",
        "GOLD": "GC=F",
        "OIL": "CL=F",
    }
    
    for name, ticker in indices.items():
        try:
            time.sleep(1)
            t = yf.Ticker(ticker)
            hist = t.history(period="5d")
            if len(hist) > 0:
                latest = hist.iloc[-1]
                results[f"idx_{name}"] = {
                    "price": round(latest['Close'], 4),
                    "date": str(hist.index[-1].date()),
                }
                print(f"  {name}: {results[f'idx_{name}']['price']}")
        except Exception as e:
            print(f"  {name}: Error - {str(e)[:50]}")
except Exception as e:
    print(f"  Batch error: {e}")

# ============================================================
# 6. Try to get macro data from public APIs
# ============================================================
print("\n[6/6] Fetching Macro Data from Public APIs...")

# FRED API for US data (public, no key needed for basic)
fred_endpoints = {
    "DFF": "Federal Funds Rate",
    "DGS10": "US 10Y Treasury",
    "DGS2": "US 2Y Treasury",
    "DEXUSDCNY": "USD/CNY",
    "DTWEXB": "Trade Weighted USD",
    "GOLDAMGBD228NLBM": "Gold Price",
    "DCOILWTICO": "WTI Oil",
}

for symbol, name in fred_endpoints.items():
    data = fetch_json(f"https://api.stlouisfed.org/fred/series/observations?series_id={symbol}&api_key=demo&file_type=json&limit=1", name=name)
    if data and "observations" in data and data["observations"]:
        obs = data["observations"][0]
        if obs.get("value") != ".":
            results[f"fred_{symbol}"] = {
                "value": float(obs["value"]),
                "date": obs.get("date", "N/A"),
            }
            print(f"  {name}: {obs['value']}")

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
