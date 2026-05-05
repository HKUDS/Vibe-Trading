import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# ============================================================
# Macro Data Collection Script for A-Shares Analysis
# ============================================================

today = datetime(2026, 5, 5)
start_1y = "2025-05-01"
start_3m = "2026-02-01"
start_1m = "2026-04-01"

print("=" * 60)
print("MACRO DATA COLLECTION FOR A-SHARES ANALYSIS")
print(f"Report Date: {today.strftime('%Y-%m-%d')}")
print("=" * 60)

# -----------------------------------------------------------
# 1. EQUITY INDICES
# -----------------------------------------------------------
print("\n--- 1. EQUITY INDICES ---")
equities = {
    "^SSEC": "Shanghai Composite",
    "000001.SS": "Shanghai Composite (alt)",
    "^HSI": "Hang Seng Index",
    "^GSPC": "S&P 500",
    "^IXIC": "NASDAQ Composite",
    "^STOXX50E": "EURO STOXX 50",
}

# Try multiple tickers for CSI 300
csi300_candidates = ["000300.SS", "^CSPC", "510300.SS"]
csi300_data = None
for c in csi300_candidates:
    try:
        df = yf.download(c, start=start_1y, end=today.strftime("%Y-%m-%d"), progress=False)
        if df is not None and len(df) > 0:
            csi300_data = df
            print(f"CSI 300 found via: {c}")
            break
    except:
        continue

if csi300_data is None:
    print("CSI 300 not found, will use Shanghai Composite as proxy")

# Download main indices
tickers = ["^SSEC", "^HSI", "^GSPC", "^IXIC", "^DJI"]
eq_data = yf.download(tickers, start=start_1y, end=today.strftime("%Y-%m-%d"), progress=False)

for t in tickers:
    try:
        if len(eq_data.index) > 0:
            last = eq_data['Close'][t].dropna().iloc[-1] if isinstance(eq_data['Close'], pd.DataFrame) else eq_data['Close'].iloc[-1]
            # Handle multi-level columns
            if isinstance(eq_data['Close'], pd.DataFrame):
                if t in eq_data['Close'].columns:
                    last = eq_data['Close'][t].dropna().iloc[-1]
                else:
                    last = eq_data['Close'].dropna().iloc[-1]
            else:
                last = eq_data['Close'].dropna().iloc[-1]
            
            # Get 1-month and 3-month returns
            close_series = eq_data['Close'][t] if t in eq_data['Close'].columns else eq_data['Close']
            close_series = close_series.dropna()
            
            m1_ret = (close_series.iloc[-1] / close_series.iloc[-22] - 1) * 100 if len(close_series) > 22 else 0
            m3_ret = (close_series.iloc[-1] / close_series.iloc[-66] - 1) * 100 if len(close_series) > 66 else 0
            ytd_start = f"2026-01-01"
            ytd_data = yf.download(t, start=ytd_start, end=today.strftime("%Y-%m-%d"), progress=False)
            if len(ytd_data) > 0:
                ytd_ret = (ytd_data['Close'].iloc[-1] / ytd_data['Close'].iloc[0] - 1) * 100
            else:
                ytd_ret = 0
            
            print(f"  {t}: Last={last:.2f}, 1M={m1_ret:+.2f}%, 3M={m3_ret:+.2f}%, YTD={ytd_ret:+.2f}%")
    except Exception as e:
        print(f"  {t}: Error - {e}")

# -----------------------------------------------------------
# 2. BOND YIELDS & RATES
# -----------------------------------------------------------
print("\n--- 2. BOND YIELDS & RATES ---")
bond_tickers = {
    "^TNX": "US 10Y Yield",
    "^FVX": "US 5Y Yield",
    "^TYX": "US 10Y Yield (alt)",
    "GB10Y=X": "UK 10Y Yield",
    "DE10Y=X": "Germany 10Y Yield",
    "JP10Y=X": "Japan 10Y Yield",
}

for t, name in bond_tickers.items():
    try:
        df = yf.download(t, start=start_3m, end=today.strftime("%Y-%m-%d"), progress=False)
        if len(df) > 0:
            last = df['Close'].iloc[-1]
            first_3m = df['Close'].iloc[0]
            chg = (last - first_3m) * 100  # in basis points
            print(f"  {name} ({t}): {last:.3f}%, 3M change: {chg:+.1f}bp")
    except Exception as e:
        print(f"  {name} ({t}): Error - {e}")

# China 10Y yield proxy - try CGB ETF or similar
print("\n  China 10Y Government Bond:")
cgb_candidates = ["511010.SS", "GB20Y=X", "CN10Y=X"]
for c in cgb_candidates:
    try:
        df = yf.download(c, start=start_3m, end=today.strftime("%Y-%m-%d"), progress=False)
        if len(df) > 0:
            print(f"    {c}: {df['Close'].iloc[-1]:.3f}")
    except:
        pass

# -----------------------------------------------------------
# 3. FX RATES
# -----------------------------------------------------------
print("\n--- 3. FX RATES ---")
fx_tickers = {
    "DX-Y.NYB": "DXY (Dollar Index)",
    "CNY=X": "USD/CNY",
    "HKD=X": "USD/HKD",
    "EURUSD=X": "EUR/USD",
    "JPY=X": "USD/JPY",
    "GBPUSD=X": "GBP/USD",
}

for t, name in fx_tickers.items():
    try:
        df = yf.download(t, start=start_3m, end=today.strftime("%Y-%m-%d"), progress=False)
        if len(df) > 0:
            last = df['Close'].iloc[-1]
            first_3m = df['Close'].iloc[0]
            chg_pct = (last / first_3m - 1) * 100
            print(f"  {name} ({t}): {last:.4f}, 3M: {chg_pct:+.2f}%")
    except Exception as e:
        print(f"  {name} ({t}): Error - {e}")

# -----------------------------------------------------------
# 4. COMMODITIES
# -----------------------------------------------------------
print("\n--- 4. COMMODITIES ---")
comm_tickers = {
    "GC=F": "Gold",
    "SI=F": "Silver",
    "CL=F": "Crude Oil WTI",
    "HG=F": "Copper",
    "PA=F": "Palladium",
    "PL=F": "Platinum",
}

for t, name in comm_tickers.items():
    try:
        df = yf.download(t, start=start_3m, end=today.strftime("%Y-%m-%d"), progress=False)
        if len(df) > 0:
            last = df['Close'].iloc[-1]
            first_3m = df['Close'].iloc[0]
            chg_pct = (last / first_3m - 1) * 100
            first_1m = df['Close'].iloc[-22] if len(df) > 22 else df['Close'].iloc[0]
            m1_chg = (last / first_1m - 1) * 100
            print(f"  {name} ({t}): {last:.2f}, 1M: {m1_chg:+.2f}%, 3M: {chg_pct:+.2f}%")
    except Exception as e:
        print(f"  {name} ({t}): Error - {e}")

# -----------------------------------------------------------
# 5. VOLATILITY & RISK INDICATORS
# -----------------------------------------------------------
print("\n--- 5. VOLATILITY & RISK INDICATORS ---")
vol_tickers = {
    "^VIX": "VIX (US Volatility)",
    "^VXHT1": "VIX-HST (Hang Seng Vol)",
    "^OVX": "OVX (Oil Volatility)",
}

for t, name in vol_tickers.items():
    try:
        df = yf.download(t, start=start_3m, end=today.strftime("%Y-%m-%d"), progress=False)
        if len(df) > 0:
            last = df['Close'].iloc[-1]
            print(f"  {name} ({t}): {last:.2f}")
    except Exception as e:
        print(f"  {name} ({t}): Error - {e}")

# -----------------------------------------------------------
# 6. CREDIT SPREADS
# -----------------------------------------------------------
print("\n--- 6. CREDIT SPREADS ---")
credit_tickers = {
    "LQD": "US IG Corporate Bond ETF",
    "HYG": "US High Yield Bond ETF",
    "JNK": "US High Yield Bond ETF (alt)",
    "TLT": "US 20Y+ Treasury Bond ETF",
    "IEI": "US 3-7Y Treasury Bond ETF",
    "SHY": "US 1-3Y Treasury Bond ETF",
}

for t, name in credit_tickers.items():
    try:
        df = yf.download(t, start=start_3m, end=today.strftime("%Y-%m-%d"), progress=False)
        if len(df) > 0:
            last = df['Close'].iloc[-1]
            first_3m = df['Close'].iloc[0]
            chg_pct = (last / first_3m - 1) * 100
            print(f"  {name} ({t}): {last:.2f}, 3M: {chg_pct:+.2f}%")
    except Exception as e:
        print(f"  {name} ({t}): Error - {e}")

# -----------------------------------------------------------
# 7. KEY A-SHARES ETFs & SECTORS
# -----------------------------------------------------------
print("\n--- 7. A-SHARES KEY ETFs ---")
ashares_etfs = {
    "510300.SS": "Huatai-PineBridge CSI 300 ETF",
    "510050.SS": "Huatai-PineBridge SSE 50 ETF",
    "159919.SZ": "ChinaAMC CSI 300 ETF",
    "512880.SS": "Huatai-PineBridge Financials ETF",
    "512480.SS": "Guofund Semiconductors ETF",
    "515790.SS": "E Fund New Energy ETF",
    "515170.SS": "Huatai-PineBridge Consumer ETF",
}

for t, name in ashares_etfs.items():
    try:
        df = yf.download(t, start=start_3m, end=today.strftime("%Y-%m-%d"), progress=False)
        if len(df) > 0:
            last = df['Close'].iloc[-1]
            first_3m = df['Close'].iloc[0]
            chg_pct = (last / first_3m - 1) * 100
            print(f"  {name} ({t}): {last:.3f}, 3M: {chg_pct:+.2f}%")
    except Exception as e:
        print(f"  {name} ({t}): Error - {e}")

# -----------------------------------------------------------
# 8. NORTHBOUND FLOW PROXY (via Hang Seng & FX)
# -----------------------------------------------------------
print("\n--- 8. CROSS-MARKET SIGNALS ---")
# FXI = China Large-Cap ETF (proxy for foreign flows into China)
try:
    fxi = yf.download("FXI", start=start_1m, end=today.strftime("%Y-%m-%d"), progress=False)
    if len(fxi) > 0:
        last = fxi['Close'].iloc[-1]
        first = fxi['Close'].iloc[0]
        chg = (last / first - 1) * 100
        vol = fxi['Volume'].iloc[-1]
        avg_vol = fxi['Volume'].rolling(5).mean().iloc[-1]
        print(f"  FXI (China Large-Cap ETF): {last:.2f}, 1M: {chg:+.2f}%, Volume ratio: {vol/avg_vol:.2f}x")
except Exception as e:
    print(f"  FXI: Error - {e}")

# MCHI = MSCI China ETF
try:
    mchi = yf.download("MCHI", start=start_1m, end=today.strftime("%Y-%m-%d"), progress=False)
    if len(mchi) > 0:
        last = mchi['Close'].iloc[-1]
        first = mchi['Close'].iloc[0]
        chg = (last / first - 1) * 100
        print(f"  MCHI (MSCI China ETF): {last:.2f}, 1M: {chg:+.2f}%")
except Exception as e:
    print(f"  MCHI: Error - {e}")

# KWEB = China Internet ETF
try:
    kweb = yf.download("KWEB", start=start_1m, end=today.strftime("%Y-%m-%d"), progress=False)
    if len(kweb) > 0:
        last = kweb['Close'].iloc[-1]
        first = kweb['Close'].iloc[0]
        chg = (last / first - 1) * 100
        print(f"  KWEB (China Internet ETF): {last:.2f}, 1M: {chg:+.2f}%")
except Exception as e:
    print(f"  KWEB: Error - {e}")

# -----------------------------------------------------------
# 9. FED RATE EXPECTATIONS (via Fed Funds Futures proxy)
# -----------------------------------------------------------
print("\n--- 9. RATE EXPECTATIONS ---")
# ED = Eurodollar futures proxy, or use TLT/SHY spread
try:
    tlt = yf.download("TLT", start=start_3m, end=today.strftime("%Y-%m-%d"), progress=False)
    shv = yf.download("SHV", start=start_3m, end=today.strftime("%Y-%m-%d"), progress=False)
    if len(tlt) > 0 and len(shv) > 0:
        tlt_chg = (tlt['Close'].iloc[-1] / tlt['Close'].iloc[0] - 1) * 100
        shv_chg = (shv['Close'].iloc[-1] / shv['Close'].iloc[0] - 1) * 100
        print(f"  TLT (20Y+ Treasury): {tlt['Close'].iloc[-1]:.2f}, 3M: {tlt_chg:+.2f}%")
        print(f"  SHV (Short Treasury): {shv['Close'].iloc[-1]:.2f}, 3M: {shv_chg:+.2f}%")
        print(f"  Spread signal: Long bonds {'outperforming' if tlt_chg > shv_chg else 'underperforming'} short bonds")
except Exception as e:
    print(f"  Rate spread: Error - {e}")

# -----------------------------------------------------------
# 10. KEY MACRO SUMMARY
# -----------------------------------------------------------
print("\n" + "=" * 60)
print("MACRO SUMMARY TABLE")
print("=" * 60)

# Collect key latest values
summary = {}

# Shanghai Composite
try:
    ssec = yf.download("^SSEC", start=start_1y, end=today.strftime("%Y-%m-%d"), progress=False)
    if len(ssec) > 0:
        summary['Shanghai Comp'] = ssec['Close'].iloc[-1]
except: pass

# S&P 500
try:
    spx = yf.download("^GSPC", start=start_1y, end=today.strftime("%Y-%m-%d"), progress=False)
    if len(spx) > 0:
        summary['S&P 500'] = spx['Close'].iloc[-1]
except: pass

# US 10Y
try:
    tnx = yf.download("^TNX", start=start_3m, end=today.strftime("%Y-%m-%d"), progress=False)
    if len(tnx) > 0:
        summary['US 10Y Yield'] = tnx['Close'].iloc[-1]
except: pass

# DXY
try:
    dxy = yf.download("DX-Y.NYB", start=start_3m, end=today.strftime("%Y-%m-%d"), progress=False)
    if len(dxy) > 0:
        summary['DXY'] = dxy['Close'].iloc[-1]
except: pass

# USD/CNY
try:
    cny = yf.download("CNY=X", start=start_3m, end=today.strftime("%Y-%m-%d"), progress=False)
    if len(cny) > 0:
        summary['USD/CNY'] = cny['Close'].iloc[-1]
except: pass

# Gold
try:
    gold = yf.download("GC=F", start=start_3m, end=today.strftime("%Y-%m-%d"), progress=False)
    if len(gold) > 0:
        summary['Gold'] = gold['Close'].iloc[-1]
except: pass

# VIX
try:
    vix = yf.download("^VIX", start=start_3m, end=today.strftime("%Y-%m-%d"), progress=False)
    if len(vix) > 0:
        summary['VIX'] = vix['Close'].iloc[-1]
except: pass

# Oil
try:
    oil = yf.download("CL=F", start=start_3m, end=today.strftime("%Y-%m-%d"), progress=False)
    if len(oil) > 0:
        summary['WTI Oil'] = oil['Close'].iloc[-1]
except: pass

for k, v in summary.items():
    print(f"  {k}: {v:.2f}")

print("\n" + "=" * 60)
print("DATA COLLECTION COMPLETE")
print("=" * 60)
