#!/usr/bin/env python3
"""
Macro Analysis Data Fetcher for A-Shares Market - V2 with rate limiting
"""

import yfinance as yf
import pandas as pd
import json
import time

end_date = "2026-05-05"
start_date = "2025-05-01"
recent_start = "2026-04-01"

results = {}

def fetch_with_delay(ticker, start=start_date, end=end_date, name=None):
    """Fetch data with delay to avoid rate limiting"""
    time.sleep(1.5)
    try:
        data = yf.download(ticker, start=start, end=end, progress=False)
        if len(data) > 0:
            latest = data.iloc[-1]
            result = {
                "latest": round(latest['Close'], 4) if 'Close' in data.columns else None,
                "date": str(data.index[-1].date()),
            }
            if len(data) > 1:
                first_close = data['Close'].iloc[0]
                last_close = data['Close'].iloc[-1]
                result["return_12m_pct"] = round((last_close / first_close - 1) * 100, 2)
            return result
    except Exception as e:
        print(f"  Error fetching {ticker}: {e}")
    return None

# ============================================================
# 1. A-SHARES INDICES (using individual fetches with delays)
# ============================================================
print("[1/9] Fetching A-Shares Indices...")
a_shares = {
    "SSE_Composite": "000001.SS",
    "CSI_300": "000300.SS",
    "SZSE_Component": "399001.SZ",
    "CSI_500": "000905.SS",
    "STAR_50": "000688.SS",
}

for name, ticker in a_shares.items():
    result = fetch_with_delay(ticker)
    if result:
        results[f"a_shares_{name}"] = result
        print(f"  {name}: {result['latest']} (12M: {result.get('return_12m_pct', 'N/A')}%)")
    else:
        print(f"  {name}: Failed")

# ============================================================
# 2. GLOBAL MACRO INDICATORS
# ============================================================
print("\n[2/9] Fetching Global Macro Indicators...")

# US 10Y Yield
result = fetch_with_delay("^TNX")
if result:
    results["us10y_yield"] = result
    print(f"  US 10Y Yield: {result['latest']}%")

# China 10Y Government Bond Yield
result = fetch_with_delay("CGB10Y=X")
if result:
    results["cn10y_yield"] = result
    print(f"  China 10Y Yield: {result['latest']}%")

# DXY
result = fetch_with_delay("DX-Y.NYB")
if not result:
    result = fetch_with_delay("DX-Y.NYB")
if result:
    results["dxy"] = result
    print(f"  DXY: {result['latest']}")

# USD/CNY
result = fetch_with_delay("CNY=X")
if result:
    results["usdcny"] = result
    print(f"  USD/CNY: {result['latest']}")

# VIX
result = fetch_with_delay("^VIX")
if result:
    results["vix"] = result
    print(f"  VIX: {result['latest']}")

# Gold
result = fetch_with_delay("GC=F")
if result:
    results["gold"] = result
    print(f"  Gold: ${result['latest']}/oz")

# Oil WTI
result = fetch_with_delay("CL=F")
if result:
    results["oil_wti"] = result
    print(f"  WTI Oil: ${result['latest']}/bbl")

# Copper
result = fetch_with_delay("HG=F")
if result:
    results["copper"] = result
    print(f"  Copper: ${result['latest']}/lb")

# Silver
result = fetch_with_delay("SI=F")
if result:
    results["silver"] = result
    print(f"  Silver: ${result['latest']}/oz")

# ============================================================
# 3. US MARKET INDICES
# ============================================================
print("\n[3/9] Fetching US Market Indices...")
us_indices = {
    "S&P_500": "^GSPC",
    "NASDAQ": "^IXIC",
    "Dow_Jones": "^DJI",
}

for name, ticker in us_indices.items():
    result = fetch_with_delay(ticker)
    if result:
        results[f"us_{name}"] = result
        print(f"  {name}: {result['latest']} (12M: {result.get('return_12m_pct', 'N/A')}%)")

# ============================================================
# 4. HK MARKET
# ============================================================
print("\n[4/9] Fetching HK Market...")
result = fetch_with_delay("^HSI")
if result:
    results["hsi"] = result
    print(f"  Hang Seng: {result['latest']} (12M: {result.get('return_12m_pct', 'N/A')}%)")

# ============================================================
# 5. KEY ETFs
# ============================================================
print("\n[5/9] Fetching Key ETFs...")
etfs = {
    "SPY": "SPY",
    "TLT": "TLT",
    "EEM": "EEM",
    "FXI": "FXI",
    "MCHI": "MCHI",
}

for name, ticker in etfs.items():
    result = fetch_with_delay(ticker)
    if result:
        results[f"etf_{name}"] = result
        print(f"  {name}: {result['latest']} (12M: {result.get('return_12m_pct', 'N/A')}%)")

# ============================================================
# 6. Interest Rate Indicators
# ============================================================
print("\n[6/9] Fetching Interest Rate Indicators...")

# US 2Y Yield
result = fetch_with_delay("^FVX")
if result:
    results["us2y_yield"] = result
    print(f"  US 2Y Yield: {result['latest']}%")

# US 3M T-Bill
result = fetch_with_delay("^IRX")
if result:
    results["us3m_tbill"] = result
    print(f"  US 3M T-Bill: {result['latest']}%")

# ============================================================
# 7. China ETFs for sentiment
# ============================================================
print("\n[7/9] Fetching China-related instruments...")

# KWEB (China internet)
result = fetch_with_delay("KWEB")
if result:
    results["etf_KWEB"] = result
    print(f"  KWEB: {result['latest']} (12M: {result.get('return_12m_pct', 'N/A')}%)")

# PGJ (China tech)
result = fetch_with_delay("PGJ")
if result:
    results["etf_PGJ"] = result
    print(f"  PGJ: {result['latest']} (12M: {result.get('return_12m_pct', 'N/A')}%)")

# ============================================================
# 8. RECENT TRENDS (30-day)
# ============================================================
print("\n[8/9] Calculating Recent Trends (30-day)...")

# CSI 300 30-day
result = fetch_with_delay("000300.SS", start=recent_start, end=end_date)
if result:
    results["csi300_30d_return"] = result.get("return_12m_pct", "N/A")
    print(f"  CSI 300 30-day return: {result.get('return_12m_pct', 'N/A')}%")

# S&P 500 30-day
result = fetch_with_delay("^GSPC", start=recent_start, end=end_date)
if result:
    results["sp500_30d_return"] = result.get("return_12m_pct", "N/A")
    print(f"  S&P 500 30-day return: {result.get('return_12m_pct', 'N/A')}%")

# DXY 30-day
result = fetch_with_delay("DX-Y.NYB", start=recent_start, end=end_date)
if not result:
    result = fetch_with_delay("DX-Y.NYB", start=recent_start, end=end_date)
if result:
    results["dxy_30d_return"] = result.get("return_12m_pct", "N/A")
    print(f"  DXY 30-day change: {result.get('return_12m_pct', 'N/A')}%")

# ============================================================
# 9. BOND YIELD CURVE
# ============================================================
print("\n[9/9] Fetching Yield Curve Data...")

# US 5Y
result = fetch_with_delay("^FYX")
if result:
    results["us5y_yield"] = result
    print(f"  US 5Y Yield: {result['latest']}%")

# US 30Y
result = fetch_with_delay("^TYX")
if result:
    results["us30y_yield"] = result
    print(f"  US 30Y Yield: {result['latest']}%")

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
