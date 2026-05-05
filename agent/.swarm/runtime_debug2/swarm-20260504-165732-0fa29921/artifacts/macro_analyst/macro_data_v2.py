import yfinance as yf
import pandas as pd
import numpy as np
import time
from datetime import datetime

today = datetime(2026, 5, 5)
start_1y = "2025-05-01"
start_3m = "2026-02-01"
start_1m = "2026-04-01"

print("=" * 60)
print("MACRO DATA COLLECTION FOR A-SHARES ANALYSIS")
print(f"Report Date: {today.strftime('%Y-%m-%d')}")
print("=" * 60)

# Batch 1: Major equity indices
print("\n--- BATCH 1: EQUITY INDICES ---")
eq_tickers = ["^SSEC", "^HSI", "^GSPC", "^IXIC"]
eq_data = yf.download(eq_tickers, start=start_1y, end=today.strftime("%Y-%m-%d"), progress=False, group_by='ticker')
time.sleep(2)

for t in eq_tickers:
    try:
        close = eq_data['Close'][t].dropna()
        if len(close) > 0:
            last = close.iloc[-1]
            m1 = (close.iloc[-1] / close.iloc[-22] - 1) * 100 if len(close) > 22 else 0
            m3 = (close.iloc[-1] / close.iloc[-66] - 1) * 100 if len(close) > 66 else 0
            print(f"  {t}: {last:.2f} | 1M: {m1:+.2f}% | 3M: {m3:+.2f}%")
    except Exception as e:
        print(f"  {t}: Error - {e}")

# Batch 2: Bond yields
print("\n--- BATCH 2: BOND YIELDS ---")
yield_tickers = ["^TNX", "^FVX", "DE10Y=X", "JP10Y=X"]
yield_data = yf.download(yield_tickers, start=start_3m, end=today.strftime("%Y-%m-%d"), progress=False, group_by='ticker')
time.sleep(2)

for t in yield_tickers:
    try:
        close = yield_data['Close'][t].dropna()
        if len(close) > 0:
            last = close.iloc[-1]
            first = close.iloc[0]
            chg_bp = (last - first) * 100
            print(f"  {t}: {last:.3f}% | 3M: {chg_bp:+.1f}bp")
    except Exception as e:
        print(f"  {t}: Error - {e}")

# Batch 3: FX
print("\n--- BATCH 3: FX RATES ---")
fx_tickers = ["DX-Y.NYB", "CNY=X", "EURUSD=X", "JPY=X"]
fx_data = yf.download(fx_tickers, start=start_3m, end=today.strftime("%Y-%m-%d"), progress=False, group_by='ticker')
time.sleep(2)

for t in fx_tickers:
    try:
        close = fx_data['Close'][t].dropna()
        if len(close) > 0:
            last = close.iloc[-1]
            first = close.iloc[0]
            chg = (last / first - 1) * 100
            print(f"  {t}: {last:.4f} | 3M: {chg:+.2f}%")
    except Exception as e:
        print(f"  {t}: Error - {e}")

# Batch 4: Commodities
print("\n--- BATCH 4: COMMODITIES ---")
comm_tickers = ["GC=F", "CL=F", "HG=F"]
comm_data = yf.download(comm_tickers, start=start_3m, end=today.strftime("%Y-%m-%d"), progress=False, group_by='ticker')
time.sleep(2)

for t in comm_tickers:
    try:
        close = comm_data['Close'][t].dropna()
        if len(close) > 0:
            last = close.iloc[-1]
            first = close.iloc[0]
            m1 = (close.iloc[-1] / close.iloc[-22] - 1) * 100 if len(close) > 22 else 0
            m3 = (last / first - 1) * 100
            print(f"  {t}: {last:.2f} | 1M: {m1:+.2f}% | 3M: {m3:+.2f}%")
    except Exception as e:
        print(f"  {t}: Error - {e}")

# Batch 5: Volatility & Credit
print("\n--- BATCH 5: VOLATILITY & CREDIT ---")
risk_tickers = ["^VIX", "LQD", "HYG", "TLT", "SHV"]
risk_data = yf.download(risk_tickers, start=start_3m, end=today.strftime("%Y-%m-%d"), progress=False, group_by='ticker')
time.sleep(2)

for t in risk_tickers:
    try:
        close = risk_data['Close'][t].dropna()
        if len(close) > 0:
            last = close.iloc[-1]
            first = close.iloc[0]
            m3 = (last / first - 1) * 100
            print(f"  {t}: {last:.2f} | 3M: {m3:+.2f}%")
    except Exception as e:
        print(f"  {t}: Error - {e}")

# Batch 6: China ETFs
print("\n--- BATCH 6: CHINA ETFs ---")
china_tickers = ["FXI", "MCHI", "KWEB"]
china_data = yf.download(china_tickers, start=start_1m, end=today.strftime("%Y-%m-%d"), progress=False, group_by='ticker')
time.sleep(2)

for t in china_tickers:
    try:
        close = china_data['Close'][t].dropna()
        if len(close) > 0:
            last = close.iloc[-1]
            first = close.iloc[0]
            m1 = (last / first - 1) * 100
            vol = china_data['Volume'][t].iloc[-1]
            avg_vol = china_data['Volume'][t].rolling(5).mean().iloc[-1]
            print(f"  {t}: {last:.2f} | 1M: {m1:+.2f}% | Vol ratio: {vol/avg_vol:.2f}x")
    except Exception as e:
        print(f"  {t}: Error - {e}")

# Batch 7: A-Shares ETFs
print("\n--- BATCH 7: A-SHARES ETFs ---")
ashares_tickers = ["510300.SS", "510050.SS", "512880.SS", "512480.SS"]
ashares_data = yf.download(ashares_tickers, start=start_3m, end=today.strftime("%Y-%m-%d"), progress=False, group_by='ticker')
time.sleep(2)

for t in ashares_tickers:
    try:
        close = ashares_data['Close'][t].dropna()
        if len(close) > 0:
            last = close.iloc[-1]
            first = close.iloc[0]
            m3 = (last / first - 1) * 100
            print(f"  {t}: {last:.3f} | 3M: {m3:+.2f}%")
    except Exception as e:
        print(f"  {t}: Error - {e}")

print("\n" + "=" * 60)
print("DATA COLLECTION COMPLETE")
print("=" * 60)
