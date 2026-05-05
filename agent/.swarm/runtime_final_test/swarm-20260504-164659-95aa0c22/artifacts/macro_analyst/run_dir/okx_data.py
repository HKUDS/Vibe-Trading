import requests
import json
import time

print("=== OKX Crypto Market Data ===")

# OKX V5 API - no auth needed for public data
base_url = "https://www.okx.com/api/v5"

# 1. Get BTC/USDT ticker
try:
    resp = requests.get(f"{base_url}/market/ticker", params={"instId": "BTC-USDT"}, timeout=15)
    if resp.status_code == 200:
        data = resp.json()
        if data['code'] == '0':
            ticker = data['data'][0]
            print(f"\nBTC/USDT:")
            print(f"  Last: {ticker['last']}")
            print(f"  24h High: {ticker['high24h']}")
            print(f"  24h Low: {ticker['low24h']}")
            print(f"  24h Volume: {ticker['vol24h']}")
            print(f"  24h Change: {ticker['sodUtc8']}")
except Exception as e:
    print(f"BTC error: {e}")

time.sleep(1)

# 2. Get ETH/USDT ticker
try:
    resp = requests.get(f"{base_url}/market/ticker", params={"instId": "ETH-USDT"}, timeout=15)
    if resp.status_code == 200:
        data = resp.json()
        if data['code'] == '0':
            ticker = data['data'][0]
            print(f"\nETH/USDT:")
            print(f"  Last: {ticker['last']}")
            print(f"  24h Change: {ticker['sodUtc8']}")
except Exception as e:
    print(f"ETH error: {e}")

time.sleep(1)

# 3. Get market candlestick data for BTC (1D)
try:
    resp = requests.get(f"{base_url}/market/candles", params={"instId": "BTC-USDT", "bar": "1D", "limit": "30"}, timeout=15)
    if resp.status_code == 200:
        data = resp.json()
        if data['code'] == '0':
            candles = data['data'][:10]
            print(f"\nBTC 1D Candles (last 10):")
            for c in candles:
                ts, o, h, l, cl, vol, vol_c, conf = c
                print(f"  {ts}: O={o} H={h} L={l} C={cl} Vol={vol}")
except Exception as e:
    print(f"BTC candles error: {e}")

time.sleep(1)

# 4. Get funding rates for major crypto
try:
    resp = requests.get(f"{base_url}/public/funding-rate", params={"instId": "BTC-USDT-SWAP"}, timeout=15)
    if resp.status_code == 200:
        data = resp.json()
        if data['code'] == '0':
            fr = data['data']
            print(f"\nBTC Funding Rate: {fr['fundingRate']}")
            print(f"  Next Funding: {fr['fundingTime']}")
except Exception as e:
    print(f"Funding rate error: {e}")

time.sleep(1)

# 5. Get open interest
try:
    resp = requests.get(f"{base_url}/market/open-history", params={"instId": "BTC-USDT-SWAP", "type": "open_interest"}, timeout=15)
    if resp.status_code == 200:
        data = resp.json()
        if data['code'] == '0':
            oi = data['data'][:5]
            print(f"\nBTC Open Interest (recent):")
            for item in oi:
                print(f"  {item['ts']}: {item['oi']}")
except Exception as e:
    print(f"OI error: {e}")

# 6. Get major altcoin tickers
altcoins = ["ETH-USDT", "SOL-USDT", "BNB-USDT", "XRP-USDT", "ADA-USDT"]
print("\n=== Altcoin Tickers ===")
for coin in altcoins:
    try:
        resp = requests.get(f"{base_url}/market/ticker", params={"instId": coin}, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            if data['code'] == '0' and len(data['data']) > 0:
                t = data['data'][0]
                print(f"  {coin}: Last={t['last']} | 24h Chg={t.get('sodUtc8', 'N/A')}")
    except:
        pass
    time.sleep(0.5)

print("\n=== OKX DATA COLLECTION COMPLETE ===")
