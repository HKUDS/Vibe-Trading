import yfinance as yf
import time

print("Trying batch download approach...")

# Try downloading multiple tickers at once
tickers = [
    "^GSPC", "^IXIC", "^HSI", "^N225",
    "SMH", "ASML", "AMAT", "TER",
    "MCHI", "FXI", "KWEB",
    "GC=F", "CL=F", "HG=F", "^VIX"
]

try:
    time.sleep(5)
    data = yf.download(tickers, start="2025-11-05", end="2026-05-05", group_by='ticker', progress=False)
    print(f"Batch download: {len(data)} tickers")
    
    for t in tickers:
        if t in data:
            df = data[t]
            if not df.empty:
                c = df['Close']
                latest = c.iloc[-1]
                ret6m = (latest - c.iloc[0]) / c.iloc[0] * 100
                print(f"  {t}: {latest:.2f} (6M: {ret6m:+.2f}%)")
            else:
                print(f"  {t}: Empty")
        else:
            print(f"  {t}: Not found")
except Exception as e:
    print(f"Batch download failed: {e}")

# Try individual tickers with longer delay
print("\nTrying individual tickers with 10s delay...")
individual = ["^GSPC", "^HSI", "SMH", "MCHI", "GC=F"]
for t in individual:
    time.sleep(10)
    try:
        df = yf.download(t, start="2025-11-05", end="2026-05-05", progress=False)
        if not df.empty:
            c = df['Close']
            latest = c.iloc[-1]
            ret6m = (latest - c.iloc[0]) / c.iloc[0] * 100
            print(f"  {t}: {latest:.2f} (6M: {ret6m:+.2f}%)")
        else:
            print(f"  {t}: Empty")
    except Exception as e:
        print(f"  {t}: Error - {e}")

print("\nDone.")
