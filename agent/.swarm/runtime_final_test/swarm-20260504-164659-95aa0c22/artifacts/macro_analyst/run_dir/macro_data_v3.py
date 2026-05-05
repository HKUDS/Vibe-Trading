import yfinance as yf
import pandas as pd
import numpy as np
import time

print("MACRO DATA COLLECTION - Batch 1")

end_date = "2026-05-05"
start_6m = "2025-11-01"
start_3m = "2026-02-01"

# Batch download - yfinance can handle multiple tickers at once
tickers_batch1 = "^GSPC ^IXIC ^DJI ^HSI 000001.SS 399300.SZ 399006.SZ 000688.SS ^N225".split()
tickers_batch2 = "^TNX ^FVX ^TYX".split()
tickers_batch3 = "DX-Y.NYB CNY=X EURUSD=X JPY=X".split()
tickers_batch4 = "GC=F CL=F HG=F ^VIX".split()
tickers_batch5 = "XLK SOXX SMH NVDA MSFT AAPL AMD 0700.HK 9988.HK 1810.HK".split()
tickers_batch6 = "512480.SS 159813.SZ 515050.SS 510300.SS 588000.SS".split()
tickers_batch7 = "TLT IEI SHY LQD HYG EEM FXI KWEB MCHI".split()

def get_stats(df):
    if df is None or len(df) == 0:
        return None
    latest = df['Close'].iloc[-1]
    prev = df['Close'].iloc[-2] if len(df) > 1 else latest
    daily = (latest/prev - 1)*100
    q_df = df.loc[df.index >= start_3m]
    q_ret = (latest/q_df['Close'].iloc[0]-1)*100 if len(q_df)>0 else 0
    m_df = df.loc[df.index >= "2026-04-01"]
    m_ret = (latest/m_df['Close'].iloc[0]-1)*100 if len(m_df)>0 else 0
    return latest, daily, q_ret, m_ret

# Batch 1: Indices
print("\n=== Global Indices ===")
try:
    data = yf.download(tickers_batch1, start="2025-05-01", end=end_date, group_by='ticker', progress=False)
    names = ["S&P500", "NASDAQ", "Dow", "HangSeng", "ShanghaiComp", "CSI300", "ChiNext", "STAR50", "Nikkei"]
    for i, t in enumerate(tickers_batch1):
        try:
            col = t if t in data.columns.get_level_values(0) else None
            if col:
                df = data[col]
                s = get_stats(df)
                if s:
                    print(f"  {names[i]}: {s[0]:.2f} | 1M: {s[3]:+.2f}% | 3M: {s[2]:+.2f}%")
        except:
            pass
except Exception as e:
    print(f"  Batch1 error: {e}")

time.sleep(2)

# Batch 2: Bonds
print("\n=== Bond Yields ===")
try:
    data = yf.download(tickers_batch2, start=start_3m, end=end_date, group_by='ticker', progress=False)
    names = ["US10Y", "US5Y", "US30Y"]
    for i, t in enumerate(tickers_batch2):
        try:
            col = t if t in data.columns.get_level_values(0) else None
            if col:
                df = data[col]
                s = get_stats(df)
                if s:
                    print(f"  {names[i]}: {s[0]:.3f}%")
        except:
            pass
except Exception as e:
    print(f"  Batch2 error: {e}")

time.sleep(2)

# Batch 3: FX
print("\n=== FX ===")
try:
    data = yf.download(tickers_batch3, start=start_3m, end=end_date, group_by='ticker', progress=False)
    names = ["DXY", "USD/CNY", "EUR/USD", "USD/JPY"]
    for i, t in enumerate(tickers_batch3):
        try:
            col = t if t in data.columns.get_level_values(0) else None
            if col:
                df = data[col]
                s = get_stats(df)
                if s:
                    print(f"  {names[i]}: {s[0]:.4f} | 1M: {s[3]:+.2f}%")
        except:
            pass
except Exception as e:
    print(f"  Batch3 error: {e}")

time.sleep(2)

# Batch 4: Commodities + VIX
print("\n=== Commodities & VIX ===")
try:
    data = yf.download(tickers_batch4, start=start_3m, end=end_date, group_by='ticker', progress=False)
    names = ["Gold", "WTI", "Copper", "VIX"]
    for i, t in enumerate(tickers_batch4):
        try:
            col = t if t in data.columns.get_level_values(0) else None
            if col:
                df = data[col]
                s = get_stats(df)
                if s:
                    print(f"  {names[i]}: {s[0]:.2f} | 1M: {s[3]:+.2f}%")
        except:
            pass
except Exception as e:
    print(f"  Batch4 error: {e}")

time.sleep(2)

# Batch 5: Tech
print("\n=== Tech Sector ===")
try:
    data = yf.download(tickers_batch5, start=start_6m, end=end_date, group_by='ticker', progress=False)
    names = ["XLK", "SOXX", "SMH", "NVDA", "MSFT", "AAPL", "AMD", "Tencent", "Alibaba", "Xiaomi"]
    for i, t in enumerate(tickers_batch5):
        try:
            col = t if t in data.columns.get_level_values(0) else None
            if col:
                df = data[col]
                s = get_stats(df)
                if s:
                    print(f"  {names[i]}: {s[0]:.2f} | 1M: {s[3]:+.2f}% | 3M: {s[2]:+.2f}%")
        except:
            pass
except Exception as e:
    print(f"  Batch5 error: {e}")

time.sleep(2)

# Batch 6: A-Shares Tech ETFs
print("\n=== A-Shares Tech ETFs ===")
try:
    data = yf.download(tickers_batch6, start=start_6m, end=end_date, group_by='ticker', progress=False)
    names = ["ChinaSemi", "CSIComp", "ChinaTech", "CSI300", "STAR50"]
    for i, t in enumerate(tickers_batch6):
        try:
            col = t if t in data.columns.get_level_values(0) else None
            if col:
                df = data[col]
                s = get_stats(df)
                if s:
                    print(f"  {names[i]}: {s[0]:.3f} | 1M: {s[3]:+.2f}% | 3M: {s[2]:+.2f}%")
        except:
            pass
except Exception as e:
    print(f"  Batch6 error: {e}")

time.sleep(2)

# Batch 7: Macro Proxies
print("\n=== Macro Proxies ===")
try:
    data = yf.download(tickers_batch7, start=start_6m, end=end_date, group_by='ticker', progress=False)
    names = ["TLT", "IEI", "SHY", "LQD", "HYG", "EEM", "FXI", "KWEB", "MCHI"]
    for i, t in enumerate(tickers_batch7):
        try:
            col = t if t in data.columns.get_level_values(0) else None
            if col:
                df = data[col]
                s = get_stats(df)
                if s:
                    print(f"  {names[i]}: {s[0]:.2f} | 1M: {s[3]:+.2f}% | 3M: {s[2]:+.2f}%")
        except:
            pass
except Exception as e:
    print(f"  Batch7 error: {e}")

print("\n=== DATA COLLECTION COMPLETE ===")
