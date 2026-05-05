import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

print("=" * 60)
print("MACRO DATA COLLECTION - May 2026")
print("=" * 60)

# Define date ranges
end_date = "2026-05-05"
start_date_1y = "2025-05-01"
start_date_3m = "2026-02-01"
start_date_6m = "2025-11-01"

# ============================================================
# 1. GLOBAL EQUITY INDICES
# ============================================================
print("\n--- Global Equity Indices ---")
indices = {
    "^GSPC": "S&P 500",
    "^IXIC": "NASDAQ Composite",
    "^DJI": "Dow Jones",
    "^HSI": "Hang Seng Index",
    "000001.SS": "Shanghai Composite",
    "399300.SZ": "CSI 300",
    "399006.SZ": "ChiNext",
    "000688.SS": "STAR 50",
    "^N225": "Nikkei 225",
    "^FTSE": "FTSE 100",
}

idx_data = {}
for ticker, name in indices.items():
    try:
        df = yf.download(ticker, start=start_date_1y, end=end_date, progress=False)
        if len(df) > 0:
            latest = df['Close'].iloc[-1]
            prev_close = df['Close'].iloc[-2] if len(df) > 1 else latest
            ytd_start = df.loc[start_date_1y:, 'Close']
            ytd_ret = (latest / ytd_start.iloc[0] - 1) * 100 if len(ytd_start) > 0 else 0
            ret_3m = (latest / df.loc[df.index >= start_date_3m, 'Close'].iloc[0] - 1) * 100 if len(df.loc[df.index >= start_date_3m]) > 0 else 0
            ret_1m = (latest / df.loc[df.index >= "2026-04-01", 'Close'].iloc[0] - 1) * 100 if len(df.loc[df.index >= "2026-04-01"]) > 0 else 0
            idx_data[name] = {
                'latest': latest,
                'ytd_ret': ytd_ret,
                '3m_ret': ret_3m,
                '1m_ret': ret_1m,
                'daily_chg': (latest / prev_close - 1) * 100
            }
            print(f"  {name}: {latest:.2f} | YTD: {ytd_ret:+.2f}% | 3M: {ret_3m:+.2f}% | 1M: {ret_1m:+.2f}%")
    except Exception as e:
        print(f"  {name}: Error - {e}")

# ============================================================
# 2. BOND YIELDS & INTEREST RATES
# ============================================================
print("\n--- Bond Yields & Rates ---")
bond_tickers = {
    "^TNX": "US 10Y Treasury",
    "^FVX": "US 5Y Treasury",
    "^TYX": "US 10Y Treasury (alt)",
    "SH000015.SS": "China 10Y Gov Bond",
    "GB0007979986.L": "UK 10Y Gilt",
    "DE10Y.GBL": "Germany 10Y Bund",
}

for ticker, name in bond_tickers.items():
    try:
        df = yf.download(ticker, start=start_date_3m, end=end_date, progress=False)
        if len(df) > 0:
            latest = df['Close'].iloc[-1]
            print(f"  {name}: {latest:.3f}%")
    except Exception as e:
        print(f"  {name}: Error - {e}")

# Also try specific yield tickers
yield_tickers = {
    "US10Y.YL": "US 10Y Yield",
    "US2Y.YL": "US 2Y Yield",
    "US3M.YL": "US 3M T-Bill",
    "CN10Y.YL": "China 10Y Yield",
}

for ticker, name in yield_tickers.items():
    try:
        df = yf.download(ticker, start=start_date_3m, end=end_date, progress=False)
        if len(df) > 0:
            latest = df['Close'].iloc[-1]
            print(f"  {name}: {latest:.3f}%")
    except Exception as e:
        pass  # Some may not be available

# ============================================================
# 3. FX & DOLLAR INDEX
# ============================================================
print("\n--- FX & Dollar Index ---")
fx_tickers = {
    "DX-Y.NYB": "DXY",
    "CNY=X": "USD/CNY",
    "EURUSD=X": "EUR/USD",
    "JPY=X": "USD/JPY",
    "GBPUSD=X": "GBP/USD",
}

for ticker, name in fx_tickers.items():
    try:
        df = yf.download(ticker, start=start_date_3m, end=end_date, progress=False)
        if len(df) > 0:
            latest = df['Close'].iloc[-1]
            prev = df['Close'].iloc[-2] if len(df) > 1 else latest
            m_ret = (latest / df.loc[df.index >= "2026-04-01", 'Close'].iloc[0] - 1) * 100 if len(df.loc[df.index >= "2026-04-01"]) > 0 else 0
            print(f"  {name}: {latest:.4f} | 1M: {m_ret:+.2f}%")
    except Exception as e:
        print(f"  {name}: Error - {e}")

# ============================================================
# 4. COMMODITIES
# ============================================================
print("\n--- Commodities ---")
comm_tickers = {
    "GC=F": "Gold",
    "CL=F": "WTI Crude Oil",
    "HG=F": "Copper",
    "SI=F": "Silver",
}

for ticker, name in comm_tickers.items():
    try:
        df = yf.download(ticker, start=start_date_3m, end=end_date, progress=False)
        if len(df) > 0:
            latest = df['Close'].iloc[-1]
            m_ret = (latest / df.loc[df.index >= "2026-04-01", 'Close'].iloc[0] - 1) * 100 if len(df.loc[df.index >= "2026-04-01"]) > 0 else 0
            print(f"  {name}: {latest:.2f} | 1M: {m_ret:+.2f}%")
    except Exception as e:
        print(f"  {name}: Error - {e}")

# ============================================================
# 5. VOLATILITY & RISK INDICATORS
# ============================================================
print("\n--- Volatility & Risk ---")
risk_tickers = {
    "^VIX": "VIX",
    "MOVE": "MOVE Index (Bond Vol)",
    "MOVE.YL": "MOVE Index",
}

for ticker, name in risk_tickers.items():
    try:
        df = yf.download(ticker, start=start_date_3m, end=end_date, progress=False)
        if len(df) > 0:
            latest = df['Close'].iloc[-1]
            print(f"  {name}: {latest:.2f}")
    except Exception as e:
        pass

# ============================================================
# 6. TECH SECTOR DATA
# ============================================================
print("\n--- Tech Sector ---")
tech_tickers = {
    "XLK": "US Tech ETF (XLK)",
    "SOXX": "iShares Semiconductor ETF",
    "SMH": "VanEck Semiconductor ETF",
    "NVDA": "NVIDIA",
    "MSFT": "Microsoft",
    "AAPL": "Apple",
    "AMD": "AMD",
    "0700.HK": "Tencent",
    "9988.HK": "Alibaba",
    "1810.HK": "Xiaomi",
}

for ticker, name in tech_tickers.items():
    try:
        df = yf.download(ticker, start=start_date_6m, end=end_date, progress=False)
        if len(df) > 0:
            latest = df['Close'].iloc[-1]
            m_ret = (latest / df.loc[df.index >= "2026-04-01", 'Close'].iloc[0] - 1) * 100 if len(df.loc[df.index >= "2026-04-01"]) > 0 else 0
            q_ret = (latest / df.loc[df.index >= start_date_3m, 'Close'].iloc[0] - 1) * 100 if len(df.loc[df.index >= start_date_3m]) > 0 else 0
            print(f"  {name}: {latest:.2f} | 1M: {m_ret:+.2f}% | 3M: {q_ret:+.2f}%")
    except Exception as e:
        print(f"  {name}: Error - {e}")

# ============================================================
# 7. A-SHARES TECH ETFs
# ============================================================
print("\n--- A-Shares Tech ETFs ---")
a_share_tech = {
    "512480.SS": "China Semiconductor ETF",
    "159813.SZ": "CSI Computer ETF",
    "515050": "China Tech ETF",
    "512880.SS": "CSI Securities ETF",
    "510300.SS": "CSI 300 ETF",
    "588000.SS": "STAR 50 ETF",
}

for ticker, name in a_share_tech.items():
    try:
        df = yf.download(ticker, start=start_date_6m, end=end_date, progress=False)
        if len(df) > 0:
            latest = df['Close'].iloc[-1]
            m_ret = (latest / df.loc[df.index >= "2026-04-01", 'Close'].iloc[0] - 1) * 100 if len(df.loc[df.index >= "2026-04-01"]) > 0 else 0
            q_ret = (latest / df.loc[df.index >= start_date_3m, 'Close'].iloc[0] - 1) * 100 if len(df.loc[df.index >= start_date_3m]) > 0 else 0
            print(f"  {name}: {latest:.3f} | 1M: {m_ret:+.2f}% | 3M: {q_ret:+.2f}%")
    except Exception as e:
        print(f"  {name}: Error - {e}")

# ============================================================
# 8. KEY US MACRO ETFs (as proxies)
# ============================================================
print("\n--- Macro Proxies ---")
macro_proxies = {
    "TLT": "US 20Y Treasury Bond ETF",
    "IEI": "US 3-7Y Treasury ETF",
    "SHY": "US 1-3Y Treasury ETF",
    "LQD": "US Investment Grade Corp Bond",
    "HYG": "US High Yield Bond",
    "EEM": "Emerging Markets ETF",
    "FXI": "China Large Cap ETF",
    "KWEB": "China Internet ETF",
    "MCHI": "MSCI China ETF",
}

for ticker, name in macro_proxies.items():
    try:
        df = yf.download(ticker, start=start_date_6m, end=end_date, progress=False)
        if len(df) > 0:
            latest = df['Close'].iloc[-1]
            m_ret = (latest / df.loc[df.index >= "2026-04-01", 'Close'].iloc[0] - 1) * 100 if len(df.loc[df.index >= "2026-04-01"]) > 0 else 0
            q_ret = (latest / df.loc[df.index >= start_date_3m, 'Close'].iloc[0] - 1) * 100 if len(df.loc[df.index >= start_date_3m]) > 0 else 0
            print(f"  {name}: {latest:.2f} | 1M: {m_ret:+.2f}% | 3M: {q_ret:+.2f}%")
    except Exception as e:
        print(f"  {name}: Error - {e}")

# ============================================================
# 9. FED FUNDS RATE PROXY
# ============================================================
print("\n--- Fed Rate Proxies ---")
fed_proxies = {
    "FVX=F": "US 5Y Note Yield",
    "EDZ": "Eurodollar Futures (proxy)",
}

for ticker, name in fed_proxies.items():
    try:
        df = yf.download(ticker, start=start_date_3m, end=end_date, progress=False)
        if len(df) > 0:
            latest = df['Close'].iloc[-1]
            print(f"  {name}: {latest:.3f}")
    except Exception as e:
        pass

# Try T-Bill rate
try:
    tbill = yf.download("BAX", start=start_date_3m, end=end_date, progress=False)
    if len(tbill) > 0:
        print(f"  T-Bill (BAX): {tbill['Close'].iloc[-1]:.2f}")
except:
    pass

# ============================================================
# 10. CREDIT SPREADS
# ============================================================
print("\n--- Credit Spreads ---")
try:
    lqd = yf.download("LQD", start=start_date_3m, end=end_date, progress=False)
    hyg = yf.download("HYG", start=start_date_3m, end=end_date, progress=False)
    if len(lqd) > 0 and len(hyg) > 0:
        lqd_latest = lqd['Close'].iloc[-1]
        hyg_latest = hyg['Close'].iloc[-1]
        print(f"  LQD (IG): {lqd_latest:.2f}")
        print(f"  HYG (HY): {hyg_latest:.2f}")
        print(f"  HY/IG ratio: {hyg_latest/lqd_latest:.4f}")
except Exception as e:
    print(f"  Credit spread error: {e}")

print("\n" + "=" * 60)
print("DATA COLLECTION COMPLETE")
print("=" * 60)
