import yfinance as yf
import pandas as pd
import time
import numpy as np

print("=" * 60)
print("MACRO DATA FETCHING - May 2026 (with rate limiting)")
print("=" * 60)

end_date = "2026-05-05"
start_date = "2025-11-05"

def fetch_safe(ticker, name):
    """Fetch with retry and delay"""
    for attempt in range(3):
        try:
            time.sleep(2)  # 2 second delay between requests
            df = yf.download(ticker, start=start_date, end=end_date, progress=False)
            if not df.empty:
                return df
            else:
                print(f"  {name}: Empty result")
                return None
        except Exception as e:
            print(f"  {name}: Attempt {attempt+1} failed - {e}")
            if attempt < 2:
                time.sleep(5)
    return None

# ============================================================
# BATCH 1: GLOBAL MACRO
# ============================================================
print("\n--- 1. GLOBAL MACRO INDICATORS ---")

us10y = fetch_safe("^TNX", "US 10Y")
if us10y is not None and not us10y.empty:
    print(f"US 10Y Treasury Yield: {us10y['Close'].iloc[-1]:.3f}%")

us2y = fetch_safe("^IRX", "US 2Y")
if us2y is not None and not us2y.empty:
    print(f"US 2Y Treasury Yield: {us2y['Close'].iloc[-1]:.3f}%")
    if us10y is not None and not us10y.empty:
        spread = us10y['Close'].iloc[-1] - us2y['Close'].iloc[-1]
        print(f"US 10Y-2Y Spread: {spread:.3f}% ({'inverted' if spread < 0 else 'normal'})")

dxy = fetch_safe("DX-Y.NYB", "DXY")
if dxy is None or dxy.empty:
    dxy = fetch_safe("DX=F", "DXY (alt)")
if dxy is not None and not dxy.empty:
    print(f"DXY (Dollar Index): {dxy['Close'].iloc[-1]:.2f}")

usdcny = fetch_safe("CNY=X", "USD/CNY")
if usdcny is not None and not usdcny.empty:
    print(f"USD/CNY: {usdcny['Close'].iloc[-1]:.4f}")

vix = fetch_safe("^VIX", "VIX")
if vix is not None and not vix.empty:
    print(f"VIX: {vix['Close'].iloc[-1]:.2f}")

gold = fetch_safe("GC=F", "Gold")
if gold is not None and not gold.empty:
    print(f"Gold (USD/oz): ${gold['Close'].iloc[-1]:.2f}")

oil = fetch_safe("CL=F", "WTI Oil")
if oil is not None and not oil.empty:
    print(f"WTI Oil (USD/bbl): ${oil['Close'].iloc[-1]:.2f}")

copper = fetch_safe("HG=F", "Copper")
if copper is not None and not copper.empty:
    print(f"Copper (USD/lb): ${copper['Close'].iloc[-1]:.4f}")

# ============================================================
# BATCH 2: A-SHARES
# ============================================================
print("\n--- 2. A-SHARES MARKET DATA ---")

csi300 = fetch_safe("000300.SS", "CSI 300")
if csi300 is not None and not csi300.empty:
    c = csi300['Close']
    latest = c.iloc[-1]
    chg = (latest - c.iloc[-2]) / c.iloc[-2] * 100 if len(c) > 1 else 0
    ret6m = (latest - c.iloc[0]) / c.iloc[0] * 100
    print(f"CSI 300: {latest:.2f} (1D: {chg:+.2f}%, 6M: {ret6m:+.2f}%)")

sse = fetch_safe("000001.SS", "SSE Composite")
if sse is not None and not sse.empty:
    c = sse['Close']
    latest = c.iloc[-1]
    chg = (latest - c.iloc[-2]) / c.iloc[-2] * 100 if len(c) > 1 else 0
    ret6m = (latest - c.iloc[0]) / c.iloc[0] * 100
    print(f"SSE Composite: {latest:.2f} (1D: {chg:+.2f}%, 6M: {ret6m:+.2f}%)")

szse = fetch_safe("399001.SZ", "SZSE Component")
if szse is not None and not szse.empty:
    c = szse['Close']
    latest = c.iloc[-1]
    chg = (latest - c.iloc[-2]) / c.iloc[-2] * 100 if len(c) > 1 else 0
    ret6m = (latest - c.iloc[0]) / c.iloc[0] * 100
    print(f"SZSE Component: {latest:.2f} (1D: {chg:+.2f}%, 6M: {ret6m:+.2f}%)")

chinet = fetch_safe("399006.SZ", "ChiNext")
if chinet is not None and not chinet.empty:
    c = chinet['Close']
    latest = c.iloc[-1]
    chg = (latest - c.iloc[-2]) / c.iloc[-2] * 100 if len(c) > 1 else 0
    ret6m = (latest - c.iloc[0]) / c.iloc[0] * 100
    print(f"ChiNext: {latest:.2f} (1D: {chg:+.2f}%, 6M: {ret6m:+.2f}%)")

star50 = fetch_safe("000688.SS", "STAR 50")
if star50 is not None and not star50.empty:
    c = star50['Close']
    latest = c.iloc[-1]
    chg = (latest - c.iloc[-2]) / c.iloc[-2] * 100 if len(c) > 1 else 0
    ret6m = (latest - c.iloc[0]) / c.iloc[0] * 100
    print(f"STAR 50: {latest:.2f} (1D: {chg:+.2f}%, 6M: {ret6m:+.2f}%)")

# ============================================================
# BATCH 3: GLOBAL MARKETS
# ============================================================
print("\n--- 3. GLOBAL MARKET LINKAGES ---")

sp500 = fetch_safe("^GSPC", "S&P 500")
if sp500 is not None and not sp500.empty:
    c = sp500['Close']
    latest = c.iloc[-1]
    ret6m = (latest - c.iloc[0]) / c.iloc[0] * 100
    print(f"S&P 500: {latest:.2f} (6M: {ret6m:+.2f}%)")

nasdaq = fetch_safe("^IXIC", "NASDAQ")
if nasdaq is not None and not nasdaq.empty:
    c = nasdaq['Close']
    latest = c.iloc[-1]
    ret6m = (latest - c.iloc[0]) / c.iloc[0] * 100
    print(f"NASDAQ: {latest:.2f} (6M: {ret6m:+.2f}%)")

hsi = fetch_safe("^HSI", "Hang Seng")
if hsi is not None and not hsi.empty:
    c = hsi['Close']
    latest = c.iloc[-1]
    ret6m = (latest - c.iloc[0]) / c.iloc[0] * 100
    print(f"Hang Seng: {latest:.2f} (6M: {ret6m:+.2f}%)")

nikkei = fetch_safe("^N225", "Nikkei 225")
if nikkei is not None and not nikkei.empty:
    c = nikkei['Close']
    latest = c.iloc[-1]
    ret6m = (latest - c.iloc[0]) / c.iloc[0] * 100
    print(f"Nikkei 225: {latest:.2f} (6M: {ret6m:+.2f}%)")

# ============================================================
# BATCH 4: SEMICONDUCTOR / TESTING
# ============================================================
print("\n--- 4. SEMICONDUCTOR / TESTING SECTOR ---")

smh = fetch_safe("SMH", "SMH")
if smh is not None and not smh.empty:
    c = smh['Close']
    latest = c.iloc[-1]
    ret6m = (latest - c.iloc[0]) / c.iloc[0] * 100
    print(f"SMH (Semiconductor ETF): ${latest:.2f} (6M: {ret6m:+.2f}%)")

asml = fetch_safe("ASML", "ASML")
if asml is not None and not asml.empty:
    c = asml['Close']
    latest = c.iloc[-1]
    ret6m = (latest - c.iloc[0]) / c.iloc[0] * 100
    print(f"ASML: ${latest:.2f} (6M: {ret6m:+.2f}%)")

amat = fetch_safe("AMAT", "AMAT")
if amat is not None and not amat.empty:
    c = amat['Close']
    latest = c.iloc[-1]
    ret6m = (latest - c.iloc[0]) / c.iloc[0] * 100
    print(f"Applied Materials (AMAT): ${latest:.2f} (6M: {ret6m:+.2f}%)")

ter = fetch_safe("TER", "Teradyne")
if ter is not None and not ter.empty:
    c = ter['Close']
    latest = c.iloc[-1]
    ret6m = (latest - c.iloc[0]) / c.iloc[0] * 100
    print(f"Teradyne (TER - ATE): ${latest:.2f} (6M: {ret6m:+.2f}%)")

advnt = fetch_safe("6857.T", "Advantest")
if advnt is not None and not advnt.empty:
    c = advnt['Close']
    latest = c.iloc[-1]
    ret6m = (latest - c.iloc[0]) / c.iloc[0] * 100
    print(f"Advantest (6857.T - ATE): ¥{latest:.0f} (6M: {ret6m:+.2f}%)")

# ============================================================
# BATCH 5: CHINA ETFs
# ============================================================
print("\n--- 5. CHINA-RELATED ETFs ---")

mchi = fetch_safe("MCHI", "MCHI")
if mchi is not None and not mchi.empty:
    c = mchi['Close']
    latest = c.iloc[-1]
    ret6m = (latest - c.iloc[0]) / c.iloc[0] * 100
    print(f"MCHI (MSCI China): ${latest:.2f} (6M: {ret6m:+.2f}%)")

fxi = fetch_safe("FXI", "FXI")
if fxi is not None and not fxi.empty:
    c = fxi['Close']
    latest = c.iloc[-1]
    ret6m = (latest - c.iloc[0]) / c.iloc[0] * 100
    print(f"FXI (China Large-Cap): ${latest:.2f} (6M: {ret6m:+.2f}%)")

kweb = fetch_safe("KWEB", "KWEB")
if kweb is not None and not kweb.empty:
    c = kweb['Close']
    latest = c.iloc[-1]
    ret6m = (latest - c.iloc[0]) / c.iloc[0] * 100
    print(f"KWEB (China Internet): ${latest:.2f} (6M: {ret6m:+.2f}%)")

# ============================================================
# BATCH 6: TREND ANALYSIS
# ============================================================
print("\n--- 6. TREND ANALYSIS ---")

if csi300 is not None and not csi300.empty:
    c = csi300['Close']
    ma30 = c.rolling(30).mean().iloc[-1]
    ma90 = c.rolling(90).mean().iloc[-1] if len(c) >= 90 else None
    print(f"CSI 300: Price={c.iloc[-1]:.2f}, MA30={ma30:.2f}, MA90={ma90:.2f if ma90 else 'N/A'}")
    if ma90:
        if c.iloc[-1] > ma30 > ma90:
            print("  -> Bullish trend (price > MA30 > MA90)")
        elif c.iloc[-1] < ma30 < ma90:
            print("  -> Bearish trend (price < MA30 < MA90)")
        else:
            print("  -> Mixed/consolidation")

if dxy is not None and not dxy.empty:
    c = dxy['Close']
    ma30 = c.rolling(30).mean().iloc[-1]
    print(f"DXY: Price={c.iloc[-1]:.2f}, MA30={ma30:.2f}")
    if c.iloc[-1] > ma30:
        print("  -> Strong dollar trend")
    else:
        print("  -> Weak dollar trend")

print("\n" + "=" * 60)
print("DATA FETCHING COMPLETE")
print("=" * 60)
