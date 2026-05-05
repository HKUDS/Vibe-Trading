import yfinance as yf
import time
from datetime import datetime

today = datetime(2026, 5, 5)
start_3m = "2026-02-01"
start_1m = "2026-04-01"
start_1y = "2025-05-01"

results = {}

def fetch_single(ticker, start, name):
    """Fetch single ticker with retry"""
    for attempt in range(3):
        try:
            df = yf.Ticker(ticker).history(period="max" if start == "1y" else "3mo")
            if start == "1mo":
                df = df[df.index >= "2026-04-01"]
            elif start == "3mo":
                df = df[df.index >= "2026-02-01"]
            elif start == "1y":
                df = df[df.index >= "2025-05-01"]
            
            if len(df) > 0:
                last = df['Close'].iloc[-1]
                first = df['Close'].iloc[0]
                m1_ret = (df['Close'].iloc[-1] / df['Close'].iloc[-22] - 1) * 100 if len(df) > 22 else 0
                m3_ret = (last / first - 1) * 100
                results[name] = {
                    'ticker': ticker,
                    'last': last,
                    'm1_ret': m1_ret,
                    'm3_ret': m3_ret,
                }
                print(f"  ✓ {name} ({ticker}): {last:.4f} | 1M: {m1_ret:+.2f}% | 3M: {m3_ret:+.2f}%")
                return True
            else:
                print(f"  ✗ {name} ({ticker}): No data")
                return False
        except Exception as e:
            if "rate" in str(e).lower() or "429" in str(e):
                wait = 5 * (attempt + 1)
                print(f"  ⏳ {name} ({ticker}): Rate limited, waiting {wait}s...")
                time.sleep(wait)
            else:
                print(f"  ✗ {name} ({ticker}): {e}")
                return False
    return False

print("=" * 60)
print("MACRO DATA COLLECTION - SINGLE TICKER MODE")
print("=" * 60)

# Equities
print("\n--- EQUITIES ---")
fetch_single("^SSEC", "1y", "Shanghai Composite")
time.sleep(3)
fetch_single("^HSI", "1y", "Hang Seng")
time.sleep(3)
fetch_single("^GSPC", "1y", "S&P 500")
time.sleep(3)
fetch_single("^IXIC", "1y", "NASDAQ")
time.sleep(3)

# Yields
print("\n--- BOND YIELDS ---")
fetch_single("^TNX", "3mo", "US 10Y Yield")
time.sleep(3)
fetch_single("^FVX", "3mo", "US 5Y Yield")
time.sleep(3)
fetch_single("DE10Y=X", "3mo", "Germany 10Y")
time.sleep(3)
fetch_single("JP10Y=X", "3mo", "Japan 10Y")
time.sleep(3)

# FX
print("\n--- FX ---")
fetch_single("DX-Y.NYB", "3mo", "DXY")
time.sleep(3)
fetch_single("CNY=X", "3mo", "USD/CNY")
time.sleep(3)
fetch_single("EURUSD=X", "3mo", "EUR/USD")
time.sleep(3)
fetch_single("JPY=X", "3mo", "USD/JPY")
time.sleep(3)

# Commodities
print("\n--- COMMODITIES ---")
fetch_single("GC=F", "3mo", "Gold")
time.sleep(3)
fetch_single("CL=F", "3mo", "WTI Oil")
time.sleep(3)
fetch_single("HG=F", "3mo", "Copper")
time.sleep(3)

# Risk
print("\n--- RISK INDICATORS ---")
fetch_single("^VIX", "3mo", "VIX")
time.sleep(3)
fetch_single("TLT", "3mo", "TLT (20Y+ Treasury)")
time.sleep(3)
fetch_single("LQD", "3mo", "LQD (IG Corp)")
time.sleep(3)
fetch_single("HYG", "3mo", "HYG (High Yield)")
time.sleep(3)

# China ETFs
print("\n--- CHINA ETFs ---")
fetch_single("FXI", "1mo", "FXI (China Large Cap)")
time.sleep(3)
fetch_single("MCHI", "1mo", "MCHI (MSCI China)")
time.sleep(3)
fetch_single("KWEB", "1mo", "KWEB (China Internet)")
time.sleep(3)

# A-Shares ETFs
print("\n--- A-SHARES ETFs ---")
fetch_single("510300.SS", "3mo", "CSI 300 ETF")
time.sleep(3)
fetch_single("510050.SS", "3mo", "SSE 50 ETF")
time.sleep(3)
fetch_single("512880.SS", "3mo", "Financials ETF")
time.sleep(3)
fetch_single("512480.SS", "3mo", "Semiconductors ETF")
time.sleep(3)

print("\n" + "=" * 60)
print("RESULTS SUMMARY")
print("=" * 60)
for name, data in results.items():
    print(f"  {name}: {data['last']:.4f} | 1M: {data['m1_ret']:+.2f}% | 3M: {data['m3_ret']:+.2f}%")

print(f"\nTotal fetched: {len(results)} indicators")
