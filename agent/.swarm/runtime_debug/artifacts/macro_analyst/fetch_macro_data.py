#!/usr/bin/env python3
"""
Macro Analysis Data Fetcher for A-Shares Market
Fetches global macro indicators, A-shares indices, and key market data.
"""

import yfinance as yf
import pandas as pd
import json
from datetime import datetime, timedelta

# Set date range - last 12 months for trend analysis
end_date = "2026-05-05"
start_date = "2025-05-01"

print("=" * 80)
print("MACRO DATA FETCHER FOR A-SHARES ANALYSIS")
print(f"Date Range: {start_date} to {end_date}")
print("=" * 80)

results = {}

# ============================================================
# 1. A-SHARES INDICES
# ============================================================
print("\n[1/8] Fetching A-Shares Indices...")
a_shares = {
    "SSE_Composite": "000001.SS",
    "CSI_300": "000300.SS",
    "SZSE_Component": "399001.SZ",
    "CSI_500": "000905.SS",
    "STAR_50": "000688.SS",
}

try:
    a_shares_data = yf.download(list(a_shares.values()), start=start_date, end=end_date, progress=False)
    for name, ticker in a_shares.items():
        if ticker in a_shares_data.columns.get_level_values(0).unique():
            latest = a_shares_data.loc[a_shares_data.index[-1]]
            results[f"a_shares_{name}"] = {
                "latest_close": round(latest['Close'], 2),
                "latest_date": str(a_shares_data.index[-1].date()),
            }
            if len(a_shares_data) > 0:
                first_close = a_shares_data[ticker]['Close'].iloc[0]
                last_close = a_shares_data[ticker]['Close'].iloc[-1]
                results[f"a_shares_{name}"]["return_12m_pct"] = round((last_close / first_close - 1) * 100, 2)
            print(f"  {name}: {results[f'a_shares_{name}']['latest_close']} (12M: {results[f'a_shares_{name}'].get('return_12m_pct', 'N/A')}%)")
        else:
            print(f"  {name}: Data not available via yfinance")
except Exception as e:
    print(f"  Error fetching A-shares: {e}")

# ============================================================
# 2. GLOBAL MACRO INDICATORS
# ============================================================
print("\n[2/8] Fetching Global Macro Indicators...")

# US Treasury yields
try:
    us10y = yf.download("^TNX", start=start_date, end=end_date, progress=False)
    if len(us10y) > 0:
        latest = us10y.iloc[-1]
        results["us10y_yield"] = {
            "latest": round(latest['Close'], 3),
            "date": str(us10y.index[-1].date()),
        }
        print(f"  US 10Y Yield: {results['us10y_yield']['latest']}%")
except Exception as e:
    print(f"  Error fetching US 10Y: {e}")

# China 10Y Government Bond Yield
try:
    cn10y = yf.download("CGB10Y=X", start=start_date, end=end_date, progress=False)
    if len(cn10y) > 0:
        latest = cn10y.iloc[-1]
        results["cn10y_yield"] = {
            "latest": round(latest['Close'], 3),
            "date": str(cn10y.index[-1].date()),
        }
        print(f"  China 10Y Yield: {results['cn10y_yield']['latest']}%")
except Exception as e:
    print(f"  Error fetching China 10Y: {e}")

# DXY (US Dollar Index)
try:
    dxy = yf.download("DX-Y.NYB", start=start_date, end=end_date, progress=False)
    if len(dxy) == 0:
        dxy = yf.download("DX=F", start=start_date, end=end_date, progress=False)
    if len(dxy) > 0:
        latest = dxy.iloc[-1]
        results["dxy"] = {
            "latest": round(latest['Close'], 2),
            "date": str(dxy.index[-1].date()),
        }
        print(f"  DXY: {results['dxy']['latest']}")
except Exception as e:
    print(f"  Error fetching DXY: {e}")

# USD/CNY
try:
    usdcny = yf.download("CNY=X", start=start_date, end=end_date, progress=False)
    if len(usdcny) > 0:
        latest = usdcny.iloc[-1]
        results["usdcny"] = {
            "latest": round(latest['Close'], 4),
            "date": str(usdcny.index[-1].date()),
        }
        print(f"  USD/CNY: {results['usdcny']['latest']}")
except Exception as e:
    print(f"  Error fetching USD/CNY: {e}")

# VIX
try:
    vix = yf.download("^VIX", start=start_date, end=end_date, progress=False)
    if len(vix) > 0:
        latest = vix.iloc[-1]
        results["vix"] = {
            "latest": round(latest['Close'], 2),
            "date": str(vix.index[-1].date()),
        }
        print(f"  VIX: {results['vix']['latest']}")
except Exception as e:
    print(f"  Error fetching VIX: {e}")

# Gold
try:
    gold = yf.download("GC=F", start=start_date, end=end_date, progress=False)
    if len(gold) > 0:
        latest = gold.iloc[-1]
        results["gold"] = {
            "latest": round(latest['Close'], 2),
            "date": str(gold.index[-1].date()),
        }
        print(f"  Gold: ${results['gold']['latest']}/oz")
except Exception as e:
    print(f"  Error fetching Gold: {e}")

# Oil (WTI)
try:
    oil = yf.download("CL=F", start=start_date, end=end_date, progress=False)
    if len(oil) > 0:
        latest = oil.iloc[-1]
        results["oil_wti"] = {
            "latest": round(latest['Close'], 2),
            "date": str(oil.index[-1].date()),
        }
        print(f"  WTI Oil: ${results['oil_wti']['latest']}/bbl")
except Exception as e:
    print(f"  Error fetching Oil: {e}")

# Copper
try:
    copper = yf.download("HG=F", start=start_date, end=end_date, progress=False)
    if len(copper) > 0:
        latest = copper.iloc[-1]
        results["copper"] = {
            "latest": round(latest['Close'], 2),
            "date": str(copper.index[-1].date()),
        }
        print(f"  Copper: ${results['copper']['latest']}/lb")
except Exception as e:
    print(f"  Error fetching Copper: {e}")

# ============================================================
# 3. US MARKET INDICES (for comparison)
# ============================================================
print("\n[3/8] Fetching US Market Indices...")
us_indices = {
    "S&P_500": "^GSPC",
    "NASDAQ": "^IXIC",
    "Dow_Jones": "^DJI",
}

try:
    us_data = yf.download(list(us_indices.values()), start=start_date, end=end_date, progress=False)
    for name, ticker in us_indices.items():
        if ticker in us_data.columns.get_level_values(0).unique():
            latest = us_data.loc[us_data.index[-1]]
            results[f"us_{name}"] = {
                "latest_close": round(latest['Close'], 2),
                "latest_date": str(us_data.index[-1].date()),
            }
            if len(us_data) > 0:
                first_close = us_data[ticker]['Close'].iloc[0]
                last_close = us_data[ticker]['Close'].iloc[-1]
                results[f"us_{name}"]["return_12m_pct"] = round((last_close / first_close - 1) * 100, 2)
            print(f"  {name}: {results[f'us_{name}']['latest_close']} (12M: {results[f'us_{name}'].get('return_12m_pct', 'N/A')}%)")
except Exception as e:
    print(f"  Error fetching US indices: {e}")

# ============================================================
# 4. HK MARKET (Hang Seng - proxy for China exposure)
# ============================================================
print("\n[4/8] Fetching HK Market...")
try:
    hsi = yf.download("^HSI", start=start_date, end=end_date, progress=False)
    if len(hsi) > 0:
        latest = hsi.iloc[-1]
        results["hsi"] = {
            "latest_close": round(latest['Close'], 2),
            "date": str(hsi.index[-1].date()),
        }
        first_close = hsi['Close'].iloc[0]
        last_close = hsi['Close'].iloc[-1]
        results["hsi"]["return_12m_pct"] = round((last_close / first_close - 1) * 100, 2)
        print(f"  Hang Seng: {results['hsi']['latest_close']} (12M: {results['hsi']['return_12m_pct']}%)")
except Exception as e:
    print(f"  Error fetching HSI: {e}")

# ============================================================
# 5. KEY ETFs for sector/flow analysis
# ============================================================
print("\n[5/8] Fetching Key ETFs...")
etfs = {
    "SPY": "SPY",
    "TLT": "TLT",
    "EEM": "EEM",
    "FXI": "FXI",
    "MCHI": "MCHI",
}

try:
    etf_data = yf.download(list(etfs.values()), start=start_date, end=end_date, progress=False)
    for name, ticker in etfs.items():
        if ticker in etf_data.columns.get_level_values(0).unique():
            latest = etf_data.loc[etf_data.index[-1]]
            results[f"etf_{name}"] = {
                "latest_close": round(latest['Close'], 2),
                "date": str(etf_data.index[-1].date()),
            }
            if len(etf_data) > 0:
                first_close = etf_data[ticker]['Close'].iloc[0]
                last_close = etf_data[ticker]['Close'].iloc[-1]
                results[f"etf_{name}"]["return_12m_pct"] = round((last_close / first_close - 1) * 100, 2)
            print(f"  {name}: {results[f'etf_{name}']['latest_close']} (12M: {results[f'etf_{name}'].get('return_12m_pct', 'N/A')}%)")
except Exception as e:
    print(f"  Error fetching ETFs: {e}")

# ============================================================
# 6. Interest Rate Indicators
# ============================================================
print("\n[6/8] Fetching Interest Rate Indicators...")

# US 2Y yield
try:
    us2y = yf.download("^FVX", start=start_date, end=end_date, progress=False)
    if len(us2y) > 0:
        latest = us2y.iloc[-1]
        results["us2y_yield"] = {
            "latest": round(latest['Close'], 3),
            "date": str(us2y.index[-1].date()),
        }
        print(f"  US 2Y Yield: {results['us2y_yield']['latest']}%")
except Exception as e:
    print(f"  Error fetching US 2Y: {e}")

# US 3M T-Bill
try:
    tb3m = yf.download("^IRX", start=start_date, end=end_date, progress=False)
    if len(tb3m) > 0:
        latest = tb3m.iloc[-1]
        results["us3m_tbill"] = {
            "latest": round(latest['Close'], 3),
            "date": str(tb3m.index[-1].date()),
        }
        print(f"  US 3M T-Bill: {results['us3m_tbill']['latest']}%")
except Exception as e:
    print(f"  Error fetching T-Bill: {e}")

# ============================================================
# 7. Additional Commodities
# ============================================================
print("\n[7/8] Fetching Additional Commodities...")

try:
    silver = yf.download("SI=F", start=start_date, end=end_date, progress=False)
    if len(silver) > 0:
        latest = silver.iloc[-1]
        results["silver"] = {
            "latest": round(latest['Close'], 2),
            "date": str(silver.index[-1].date()),
        }
        print(f"  Silver: ${results['silver']['latest']}/oz")
except Exception as e:
    print(f"  Error fetching Silver: {e}")

# ============================================================
# 8. RECENT PRICE TRENDS (last 30 days for momentum)
# ============================================================
print("\n[8/8] Calculating Recent Trends (30-day)...")
recent_start = "2026-04-01"

try:
    csi300_recent = yf.download("000300.SS", start=recent_start, end=end_date, progress=False)
    if len(csi300_recent) > 0:
        first = csi300_recent['Close'].iloc[0]
        last = csi300_recent['Close'].iloc[-1]
        results["csi300_30d_return"] = round((last / first - 1) * 100, 2)
        print(f"  CSI 300 30-day return: {results['csi300_30d_return']}%")
except Exception as e:
    print(f"  Error: {e}")

try:
    sp500_recent = yf.download("^GSPC", start=recent_start, end=end_date, progress=False)
    if len(sp500_recent) > 0:
        first = sp500_recent['Close'].iloc[0]
        last = sp500_recent['Close'].iloc[-1]
        results["sp500_30d_return"] = round((last / first - 1) * 100, 2)
        print(f"  S&P 500 30-day return: {results['sp500_30d_return']}%")
except Exception as e:
    print(f"  Error: {e}")

try:
    dxy_recent = yf.download("DX-Y.NYB", start=recent_start, end=end_date, progress=False)
    if len(dxy_recent) == 0:
        dxy_recent = yf.download("DX=F", start=recent_start, end=end_date, progress=False)
    if len(dxy_recent) > 0:
        first = dxy_recent['Close'].iloc[0]
        last = dxy_recent['Close'].iloc[-1]
        results["dxy_30d_return"] = round((last / first - 1) * 100, 2)
        print(f"  DXY 30-day change: {results['dxy_30d_return']}%")
except Exception as e:
    print(f"  Error: {e}")

# ============================================================
# SUMMARY OUTPUT
# ============================================================
print("\n" + "=" * 80)
print("DATA SUMMARY")
print("=" * 80)
print(json.dumps(results, indent=2, default=str))

# Save to file for reference
with open("macro_data.json", "w") as f:
    json.dump(results, f, indent=2, default=str)

print("\nData saved to macro_data.json")
