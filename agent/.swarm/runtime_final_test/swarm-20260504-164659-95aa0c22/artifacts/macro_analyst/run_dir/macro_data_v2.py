import yfinance as yf
import pandas as pd
import numpy as np
import time
from datetime import datetime, timedelta

print("=" * 60)
print("MACRO DATA COLLECTION - May 2026")
print("=" * 60)

end_date = "2026-05-05"
start_date_1y = "2025-05-01"
start_date_3m = "2026-02-01"
start_date_6m = "2025-11-01"

def fetch_with_retry(ticker, start, end, name="", max_retries=3):
    """Fetch data with retry and delay"""
    for attempt in range(max_retries):
        try:
            time.sleep(1.5)  # Rate limit delay
            df = yf.download(ticker, start=start, end=end, progress=False)
            if len(df) > 0:
                return df
        except Exception as e:
            if "Rate" in str(e) or "429" in str(e):
                wait = 3 * (attempt + 1)
                print(f"  Rate limited, waiting {wait}s... (attempt {attempt+1})")
                time.sleep(wait)
            else:
                return None
    return None

def get_returns(df, label=""):
    """Calculate returns from dataframe"""
    if df is None or len(df) == 0:
        return None, None, None, None
    latest = df['Close'].iloc[-1]
    prev = df['Close'].iloc[-2] if len(df) > 1 else latest
    daily_chg = (latest / prev - 1) * 100
    
    ytd_df = df.loc[df.index >= start_date_1y]
    ytd_ret = (latest / ytd_df['Close'].iloc[0] - 1) * 100 if len(ytd_df) > 0 else 0
    
    q_df = df.loc[df.index >= start_date_3m]
    q_ret = (latest / q_df['Close'].iloc[0] - 1) * 100 if len(q_df) > 0 else 0
    
    m_df = df.loc[df.index >= "2026-04-01"]
    m_ret = (latest / m_df['Close'].iloc[0] - 1) * 100 if len(m_df) > 0 else 0
    
    return latest, ytd_ret, q_ret, m_ret

# ============================================================
# BATCH 1: Global Equity Indices
# ============================================================
print("\n--- Global Equity Indices ---")
indices = [
    ("^GSPC", "S&P 500"),
    ("^IXIC", "NASDAQ Composite"),
    ("^DJI", "Dow Jones"),
    ("^HSI", "Hang Seng"),
    ("000001.SS", "Shanghai Comp"),
    ("399300.SZ", "CSI 300"),
    ("399006.SZ", "ChiNext"),
    ("000688.SS", "STAR 50"),
    ("^N225", "Nikkei 225"),
]

for ticker, name in indices:
    df = fetch_with_retry(ticker, start_date_1y, end_date, name)
    result = get_returns(df)
    if result[0] is not None:
        print(f"  {name}: {result[0]:.2f} | YTD: {result[1]:+.2f}% | 3M: {result[2]:+.2f}% | 1M: {result[3]:+.2f}%")
    else:
        print(f"  {name}: FAILED")

# ============================================================
# BATCH 2: Bond Yields
# ============================================================
print("\n--- Bond Yields ---")
bonds = [
    ("^TNX", "US 10Y Treasury"),
    ("^FVX", "US 5Y Treasury"),
    ("^TYX", "US 30Y Treasury"),
]

for ticker, name in bonds:
    df = fetch_with_retry(ticker, start_date_3m, end_date, name)
    result = get_returns(df)
    if result[0] is not None:
        print(f"  {name}: {result[0]:.3f}%")
    else:
        print(f"  {name}: FAILED")

# ============================================================
# BATCH 3: FX & Dollar
# ============================================================
print("\n--- FX & Dollar Index ---")
fx = [
    ("DX-Y.NYB", "DXY"),
    ("CNY=X", "USD/CNY"),
    ("EURUSD=X", "EUR/USD"),
    ("JPY=X", "USD/JPY"),
]

for ticker, name in fx:
    df = fetch_with_retry(ticker, start_date_3m, end_date, name)
    result = get_returns(df)
    if result[0] is not None:
        print(f"  {name}: {result[0]:.4f} | 1M: {result[3]:+.2f}%")
    else:
        print(f"  {name}: FAILED")

# ============================================================
# BATCH 4: Commodities
# ============================================================
print("\n--- Commodities ---")
comms = [
    ("GC=F", "Gold"),
    ("CL=F", "WTI Crude"),
    ("HG=F", "Copper"),
]

for ticker, name in comms:
    df = fetch_with_retry(ticker, start_date_3m, end_date, name)
    result = get_returns(df)
    if result[0] is not None:
        print(f"  {name}: {result[0]:.2f} | 1M: {result[3]:+.2f}%")
    else:
        print(f"  {name}: FAILED")

# ============================================================
# BATCH 5: Volatility
# ============================================================
print("\n--- Volatility ---")
vix_df = fetch_with_retry("^VIX", start_date_3m, end_date, "VIX")
result = get_returns(vix_df)
if result[0] is not None:
    print(f"  VIX: {result[0]:.2f}")
else:
    print("  VIX: FAILED")

# ============================================================
# BATCH 6: Tech Sector
# ============================================================
print("\n--- Tech Sector ---")
tech = [
    ("XLK", "US Tech ETF"),
    ("SOXX", "Semiconductor ETF"),
    ("SMH", "VanEck Semi ETF"),
    ("NVDA", "NVIDIA"),
    ("MSFT", "Microsoft"),
    ("AAPL", "Apple"),
    ("AMD", "AMD"),
    ("0700.HK", "Tencent"),
    ("9988.HK", "Alibaba"),
    ("1810.HK", "Xiaomi"),
]

for ticker, name in tech:
    df = fetch_with_retry(ticker, start_date_6m, end_date, name)
    result = get_returns(df)
    if result[0] is not None:
        print(f"  {name}: {result[0]:.2f} | 1M: {result[3]:+.2f}% | 3M: {result[2]:+.2f}%")
    else:
        print(f"  {name}: FAILED")

# ============================================================
# BATCH 7: A-Shares Tech ETFs
# ============================================================
print("\n--- A-Shares Tech ETFs ---")
ashare_tech = [
    ("512480.SS", "China Semi ETF"),
    ("159813.SZ", "CSI Computer ETF"),
    ("515050.SS", "China Tech ETF"),
    ("510300.SS", "CSI 300 ETF"),
    ("588000.SS", "STAR 50 ETF"),
]

for ticker, name in ashare_tech:
    df = fetch_with_retry(ticker, start_date_6m, end_date, name)
    result = get_returns(df)
    if result[0] is not None:
        print(f"  {name}: {result[0]:.3f} | 1M: {result[3]:+.2f}% | 3M: {result[2]:+.2f}%")
    else:
        print(f"  {name}: FAILED")

# ============================================================
# BATCH 8: Macro Proxies
# ============================================================
print("\n--- Macro Proxies ---")
macro = [
    ("TLT", "US 20Y Treasury ETF"),
    ("IEI", "US 3-7Y Treasury ETF"),
    ("SHY", "US 1-3Y Treasury ETF"),
    ("LQD", "IG Corp Bond"),
    ("HYG", "High Yield Bond"),
    ("EEM", "Emerging Markets"),
    ("FXI", "China Large Cap"),
    ("KWEB", "China Internet"),
    ("MCHI", "MSCI China"),
]

for ticker, name in macro:
    df = fetch_with_retry(ticker, start_date_6m, end_date, name)
    result = get_returns(df)
    if result[0] is not None:
        print(f"  {name}: {result[0]:.2f} | 1M: {result[3]:+.2f}% | 3M: {result[2]:+.2f}%")
    else:
        print(f"  {name}: FAILED")

print("\n" + "=" * 60)
print("DATA COLLECTION COMPLETE")
print("=" * 60)
