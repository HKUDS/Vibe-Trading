import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

print("=" * 60)
print("MACRO DATA FETCHING - May 2026")
print("=" * 60)

# Define date range - last 6 months for context
end_date = "2026-05-05"
start_date = "2025-11-05"

# ============================================================
# 1. GLOBAL MACRO INDICATORS
# ============================================================
print("\n--- 1. GLOBAL MACRO INDICATORS ---")

# US Treasury yields
try:
    us10y = yf.download("^TNX", start=start_date, end=end_date, progress=False)
    if not us10y.empty:
        latest_10y = us10y['Close'].iloc[-1]
        print(f"US 10Y Treasury Yield: {latest_10y:.3f}%")
    else:
        latest_10y = None
        print("US 10Y: No data")
except Exception as e:
    print(f"US 10Y error: {e}")
    latest_10y = None

# US 2Y yield
try:
    us2y = yf.download("^IRX", start=start_date, end=end_date, progress=False)
    if not us2y.empty:
        latest_2y = us2y['Close'].iloc[-1]
        print(f"US 2Y Treasury Yield: {latest_2y:.3f}%")
    else:
        latest_2y = None
except:
    latest_2y = None

# 10Y-2Y spread
if latest_10y and latest_2y:
    spread = latest_10y - latest_2y
    print(f"US 10Y-2Y Spread: {spread:.3f}% ({'inverted' if spread < 0 else 'normal'})")

# DXY (Dollar Index)
try:
    dxy = yf.download("DX-Y.NYB", start=start_date, end=end_date, progress=False)
    if dxy.empty:
        dxy = yf.download("DX=F", start=start_date, end=end_date, progress=False)
    if not dxy.empty:
        latest_dxy = dxy['Close'].iloc[-1]
        print(f"DXY (Dollar Index): {latest_dxy:.2f}")
    else:
        latest_dxy = None
except Exception as e:
    print(f"DXY error: {e}")
    latest_dxy = None

# USD/CNY
try:
    usdcny = yf.download("CNY=X", start=start_date, end=end_date, progress=False)
    if not usdcny.empty:
        latest_cny = usdcny['Close'].iloc[-1]
        print(f"USD/CNY: {latest_cny:.4f}")
    else:
        latest_cny = None
except Exception as e:
    print(f"USD/CNY error: {e}")
    latest_cny = None

# VIX
try:
    vix = yf.download("^VIX", start=start_date, end=end_date, progress=False)
    if not vix.empty:
        latest_vix = vix['Close'].iloc[-1]
        print(f"VIX: {latest_vix:.2f}")
    else:
        latest_vix = None
except Exception as e:
    print(f"VIX error: {e}")
    latest_vix = None

# Gold
try:
    gold = yf.download("GC=F", start=start_date, end=end_date, progress=False)
    if not gold.empty:
        latest_gold = gold['Close'].iloc[-1]
        print(f"Gold (USD/oz): ${latest_gold:.2f}")
    else:
        latest_gold = None
except Exception as e:
    print(f"Gold error: {e}")
    latest_gold = None

# Oil (WTI)
try:
    oil = yf.download("CL=F", start=start_date, end=end_date, progress=False)
    if not oil.empty:
        latest_oil = oil['Close'].iloc[-1]
        print(f"WTI Oil (USD/bbl): ${latest_oil:.2f}")
    else:
        latest_oil = None
except Exception as e:
    print(f"Oil error: {e}")
    latest_oil = None

# Copper
try:
    copper = yf.download("HG=F", start=start_date, end=end_date, progress=False)
    if not copper.empty:
        latest_copper = copper['Close'].iloc[-1]
        print(f"Copper (USD/lb): ${latest_copper:.4f}")
    else:
        latest_copper = None
except Exception as e:
    print(f"Copper error: {e}")
    latest_copper = None

# ============================================================
# 2. A-SHARES MARKET DATA
# ============================================================
print("\n--- 2. A-SHARES MARKET DATA ---")

# CSI 300
try:
    csi300 = yf.download("000300.SS", start=start_date, end=end_date, progress=False)
    if not csi300.empty:
        latest_csi = csi300['Close'].iloc[-1]
        prev_csi = csi300['Close'].iloc[-2] if len(csi300) > 1 else latest_csi
        chg_csi = (latest_csi - prev_csi) / prev_csi * 100
        ret_6m = (latest_csi - csi300['Close'].iloc[0]) / csi300['Close'].iloc[0] * 100
        print(f"CSI 300: {latest_csi:.2f} (1D: {chg_csi:+.2f}%, 6M: {ret_6m:+.2f}%)")
    else:
        print("CSI 300: No data")
except Exception as e:
    print(f"CSI 300 error: {e}")

# SSE Composite
try:
    sse = yf.download("000001.SS", start=start_date, end=end_date, progress=False)
    if not sse.empty:
        latest_sse = sse['Close'].iloc[-1]
        prev_sse = sse['Close'].iloc[-2] if len(sse) > 1 else latest_sse
        chg_sse = (latest_sse - prev_sse) / prev_sse * 100
        ret_6m_sse = (latest_sse - sse['Close'].iloc[0]) / sse['Close'].iloc[0] * 100
        print(f"SSE Composite: {latest_sse:.2f} (1D: {chg_sse:+.2f}%, 6M: {ret_6m_sse:+.2f}%)")
    else:
        print("SSE Composite: No data")
except Exception as e:
    print(f"SSE error: {e}")

# SZSE Component
try:
    szse = yf.download("399001.SZ", start=start_date, end=end_date, progress=False)
    if not szse.empty:
        latest_szse = szse['Close'].iloc[-1]
        prev_szse = szse['Close'].iloc[-2] if len(szse) > 1 else latest_szse
        chg_szse = (latest_szse - prev_szse) / prev_szse * 100
        ret_6m_szse = (latest_szse - szse['Close'].iloc[0]) / szse['Close'].iloc[0] * 100
        print(f"SZSE Component: {latest_szse:.2f} (1D: {chg_szse:+.2f}%, 6M: {ret_6m_szse:+.2f}%)")
    else:
        print("SZSE Component: No data")
except Exception as e:
    print(f"SZSE error: {e}")

# ChiNext
try:
    chinet = yf.download("399006.SZ", start=start_date, end=end_date, progress=False)
    if not chinet.empty:
        latest_chinet = chinet['Close'].iloc[-1]
        prev_chinet = chinet['Close'].iloc[-2] if len(chinet) > 1 else latest_chinet
        chg_chinet = (latest_chinet - prev_chinet) / prev_chinet * 100
        ret_6m_chinet = (latest_chinet - chinet['Close'].iloc[0]) / chinet['Close'].iloc[0] * 100
        print(f"ChiNext: {latest_chinet:.2f} (1D: {chg_chinet:+.2f}%, 6M: {ret_6m_chinet:+.2f}%)")
    else:
        print("ChiNext: No data")
except Exception as e:
    print(f"ChiNext error: {e}")

# STAR 50
try:
    star50 = yf.download("000688.SS", start=start_date, end=end_date, progress=False)
    if not star50.empty:
        latest_star = star50['Close'].iloc[-1]
        prev_star = star50['Close'].iloc[-2] if len(star50) > 1 else latest_star
        chg_star = (latest_star - prev_star) / prev_star * 100
        ret_6m_star = (latest_star - star50['Close'].iloc[0]) / star50['Close'].iloc[0] * 100
        print(f"STAR 50: {latest_star:.2f} (1D: {chg_star:+.2f}%, 6M: {ret_6m_star:+.2f}%)")
    else:
        print("STAR 50: No data")
except Exception as e:
    print(f"STAR 50 error: {e}")

# ============================================================
# 3. GLOBAL MARKET LINKAGES
# ============================================================
print("\n--- 3. GLOBAL MARKET LINKAGES ---")

# S&P 500
try:
    sp500 = yf.download("^GSPC", start=start_date, end=end_date, progress=False)
    if not sp500.empty:
        latest_sp = sp500['Close'].iloc[-1]
        ret_6m_sp = (latest_sp - sp500['Close'].iloc[0]) / sp500['Close'].iloc[0] * 100
        print(f"S&P 500: {latest_sp:.2f} (6M: {ret_6m_sp:+.2f}%)")
    else:
        print("S&P 500: No data")
except Exception as e:
    print(f"S&P 500 error: {e}")

# NASDAQ
try:
    nasdaq = yf.download("^IXIC", start=start_date, end=end_date, progress=False)
    if not nasdaq.empty:
        latest_nas = nasdaq['Close'].iloc[-1]
        ret_6m_nas = (latest_nas - nasdaq['Close'].iloc[0]) / nasdaq['Close'].iloc[0] * 100
        print(f"NASDAQ: {latest_nas:.2f} (6M: {ret_6m_nas:+.2f}%)")
    else:
        print("NASDAQ: No data")
except Exception as e:
    print(f"NASDAQ error: {e}")

# Hang Seng
try:
    hsi = yf.download("^HSI", start=start_date, end=end_date, progress=False)
    if not hsi.empty:
        latest_hsi = hsi['Close'].iloc[-1]
        ret_6m_hsi = (latest_hsi - hsi['Close'].iloc[0]) / hsi['Close'].iloc[0] * 100
        print(f"Hang Seng: {latest_hsi:.2f} (6M: {ret_6m_hsi:+.2f}%)")
    else:
        print("Hang Seng: No data")
except Exception as e:
    print(f"Hang Seng error: {e}")

# Nikkei 225
try:
    nikkei = yf.download("^N225", start=start_date, end=end_date, progress=False)
    if not nikkei.empty:
        latest_nik = nikkei['Close'].iloc[-1]
        ret_6m_nik = (latest_nik - nikkei['Close'].iloc[0]) / nikkei['Close'].iloc[0] * 100
        print(f"Nikkei 225: {latest_nik:.2f} (6M: {ret_6m_nik:+.2f}%)")
    else:
        print("Nikkei 225: No data")
except Exception as e:
    print(f"Nikkei error: {e}")

# ============================================================
# 4. SEMICONDUCTOR / TESTING SECTOR
# ============================================================
print("\n--- 4. SEMICONDUCTOR / TESTING SECTOR ---")

# SMH (Semiconductor ETF)
try:
    smh = yf.download("SMH", start=start_date, end=end_date, progress=False)
    if not smh.empty:
        latest_smh = smh['Close'].iloc[-1]
        ret_6m_smh = (latest_smh - smh['Close'].iloc[0]) / smh['Close'].iloc[0] * 100
        print(f"SMH (Semiconductor ETF): ${latest_smh:.2f} (6M: {ret_6m_smh:+.2f}%)")
    else:
        print("SMH: No data")
except Exception as e:
    print(f"SMH error: {e}")

# ASML (key semiconductor equipment/testing)
try:
    asml = yf.download("ASML", start=start_date, end=end_date, progress=False)
    if not asml.empty:
        latest_asml = asml['Close'].iloc[-1]
        ret_6m_asml = (latest_asml - asml['Close'].iloc[0]) / asml['Close'].iloc[0] * 100
        print(f"ASML: ${latest_asml:.2f} (6M: {ret_6m_asml:+.2f}%)")
    else:
        print("ASML: No data")
except Exception as e:
    print(f"ASML error: {e}")

# Applied Materials (testing/semiconductor equipment)
try:
    amat = yf.download("AMAT", start=start_date, end=end_date, progress=False)
    if not amat.empty:
        latest_amat = amat['Close'].iloc[-1]
        ret_6m_amat = (latest_amat - amat['Close'].iloc[0]) / amat['Close'].iloc[0] * 100
        print(f"Applied Materials (AMAT): ${latest_amat:.2f} (6M: {ret_6m_amat:+.2f}%)")
    else:
        print("AMAT: No data")
except Exception as e:
    print(f"AMAT error: {e}")

# Teradyne (ATE testing equipment)
try:
    ter = yf.download("TER", start=start_date, end=end_date, progress=False)
    if not ter.empty:
        latest_ter = ter['Close'].iloc[-1]
        ret_6m_ter = (latest_ter - ter['Close'].iloc[0]) / ter['Close'].iloc[0] * 100
        print(f"Teradyne (TER - ATE): ${latest_ter:.2f} (6M: {ret_6m_ter:+.2f}%)")
    else:
        print("TER: No data")
except Exception as e:
    print(f"TER error: {e}")

# Advantest (Japanese ATE testing)
try:
    advnt = yf.download("6857.T", start=start_date, end=end_date, progress=False)
    if not advnt.empty:
        latest_advnt = advnt['Close'].iloc[-1]
        ret_6m_advnt = (latest_advnt - advnt['Close'].iloc[0]) / advnt['Close'].iloc[0] * 100
        print(f"Advantest (6857.T - ATE): ¥{latest_advnt:.0f} (6M: {ret_6m_advnt:+.2f}%)")
    else:
        print("Advantest: No data")
except Exception as e:
    print(f"Advantest error: {e}")

# ============================================================
# 5. KEY ETFs FOR A-SHARES
# ============================================================
print("\n--- 5. CHINA-RELATED ETFs ---")

# MSCI China ETF (MCHI)
try:
    mchi = yf.download("MCHI", start=start_date, end=end_date, progress=False)
    if not mchi.empty:
        latest_mchi = mchi['Close'].iloc[-1]
        ret_6m_mchi = (latest_mchi - mchi['Close'].iloc[0]) / mchi['Close'].iloc[0] * 100
        print(f"MCHI (MSCI China): ${latest_mchi:.2f} (6M: {ret_6m_mchi:+.2f}%)")
    else:
        print("MCHI: No data")
except Exception as e:
    print(f"MCHI error: {e}")

# China Large-Cap ETF (FXI)
try:
    fxi = yf.download("FXI", start=start_date, end=end_date, progress=False)
    if not fxi.empty:
        latest_fxi = fxi['Close'].iloc[-1]
        ret_6m_fxi = (latest_fxi - fxi['Close'].iloc[0]) / fxi['Close'].iloc[0] * 100
        print(f"FXI (China Large-Cap): ${latest_fxi:.2f} (6M: {ret_6m_fxi:+.2f}%)")
    else:
        print("FXI: No data")
except Exception as e:
    print(f"FXI error: {e}")

# KWEB (China Internet)
try:
    kweb = yf.download("KWEB", start=start_date, end=end_date, progress=False)
    if not kweb.empty:
        latest_kweb = kweb['Close'].iloc[-1]
        ret_6m_kweb = (latest_kweb - kweb['Close'].iloc[0]) / kweb['Close'].iloc[0] * 100
        print(f"KWEB (China Internet): ${latest_kweb:.2f} (6M: {ret_6m_kweb:+.2f}%)")
    else:
        print("KWEB: No data")
except Exception as e:
    print(f"KWEB error: {e}")

# ============================================================
# 6. TREND ANALYSIS (30-day and 90-day moving averages)
# ============================================================
print("\n--- 6. TREND ANALYSIS ---")

# CSI 300 trend
try:
    if not csi300.empty:
        csi_close = csi300['Close']
        ma30 = csi_close.rolling(30).mean().iloc[-1]
        ma90 = csi_close.rolling(90).mean().iloc[-1] if len(csi_close) >= 90 else None
        print(f"CSI 300: Price={csi_close.iloc[-1]:.2f}, MA30={ma30:.2f}, MA90={ma90:.2f if ma90 else 'N/A'}")
        if ma90:
            if csi_close.iloc[-1] > ma30 > ma90:
                print("  -> Bullish trend (price > MA30 > MA90)")
            elif csi_close.iloc[-1] < ma30 < ma90:
                print("  -> Bearish trend (price < MA30 < MA90)")
            else:
                print("  -> Mixed/consolidation")
except Exception as e:
    print(f"Trend analysis error: {e}")

# DXY trend
try:
    if not dxy.empty and latest_dxy:
        dxy_close = dxy['Close']
        dxy_ma30 = dxy_close.rolling(30).mean().iloc[-1]
        print(f"DXY: Price={latest_dxy:.2f}, MA30={dxy_ma30:.2f}")
        if latest_dxy > dxy_ma30:
            print("  -> Strong dollar trend")
        else:
            print("  -> Weak dollar trend")
except Exception as e:
    print(f"DXY trend error: {e}")

print("\n" + "=" * 60)
print("DATA FETCHING COMPLETE")
print("=" * 60)
