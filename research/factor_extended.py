"""
Extended factor research — 2-year sample, 3 non-price factors, multi-horizon IC.

Factors:
- funding_rate: OKX 8h settlement (forward-filled to hourly)
- oi_change_24h: Bybit hourly OI %change over 24h (proxy for total perp leverage)
- fng: alternative.me daily Fear & Greed Index (forward-filled to hourly)

Horizons: 8h, 24h, 72h, 168h (1 week)
Output: research/factor_extended.md
"""

from datetime import datetime, timezone

import pandas as pd

from lib.ccxt_data import fetch_oi_history_bybit
from lib.factor_metrics import add_forward_returns, evaluate_factor
from lib.okx_data import fetch_candles, fetch_funding_history
from lib.report import build_factor_report
from lib.sentiment import fetch_fear_greed

SYMBOL_OKX = "BTC-USDT-SWAP"
SYMBOL_BYBIT = "BTC/USDT:USDT"  # ccxt unified
PERIOD_DAYS = 730  # 2 years
HORIZONS = [8, 24, 72, 168]
OUT_REPORT = r"C:/Users/cool6/Vibe-Trading/research/factor_extended.md"


def main() -> None:
    print(f"[1/4] funding history (last {PERIOD_DAYS}d)")
    funding = fetch_funding_history(SYMBOL_OKX, PERIOD_DAYS)
    print(f"     rows: {len(funding)}  range: {funding.index.min()} ~ {funding.index.max()}")

    print(f"[2/4] hourly candles (history endpoint, last {PERIOD_DAYS}d)")
    candles = fetch_candles(SYMBOL_OKX, PERIOD_DAYS, bar="1H", use_history_endpoint=True)
    print(f"     rows: {len(candles)}  range: {candles.index.min()} ~ {candles.index.max()}")

    print(f"[3/4] Bybit hourly OI history (last {PERIOD_DAYS}d)")
    try:
        oi_hist = fetch_oi_history_bybit(SYMBOL_BYBIT, days=PERIOD_DAYS, timeframe="1h")
        print(f"     rows: {len(oi_hist)}  range: {oi_hist.index.min()} ~ {oi_hist.index.max()}")
    except Exception as e:
        print(f"     WARN: OI fetch failed ({e}); continuing without OI")
        oi_hist = pd.DataFrame(columns=["oi", "oi_usd"])

    print(f"[4/4] Fear & Greed (last {PERIOD_DAYS}d)")
    fng = fetch_fear_greed(days=PERIOD_DAYS)
    print(f"     rows: {len(fng)}  range: {fng.index.min()} ~ {fng.index.max()}")

    # Align everything onto hourly candle index
    print("\n[align] joining factors to hourly candle index")
    df = pd.DataFrame(index=candles.index)
    df["close"] = candles["close"]

    fund_h = funding.reindex(candles.index, method="ffill").bfill()
    df["funding_rate"] = fund_h["funding_rate"]

    if not oi_hist.empty:
        oi_h = oi_hist.reindex(candles.index, method="ffill")
        df["oi"] = oi_h["oi"]
        df["oi_change_24h"] = df["oi"].pct_change(24)  # stationarize OI
    else:
        df["oi_change_24h"] = pd.NA

    fng_h = fng.reindex(candles.index, method="ffill").bfill()
    df["fng"] = fng_h["fng"]

    df = add_forward_returns(df, "close", HORIZONS)

    # Evaluate each factor
    print("\n[evaluate] computing IC/IR for each factor x horizon")
    all_results: list = []
    for factor in ["funding_rate", "oi_change_24h", "fng"]:
        if df[factor].isna().all():
            print(f"  {factor}: all NaN, skipping")
            continue
        res = evaluate_factor(df, factor, HORIZONS)
        for r in res:
            print(f"  {factor:>16} @ {r.horizon:>5}: IC={r.ic:+.4f} IR={r.ir:+.3f} n={r.n_samples}")
        all_results.extend(res)

    data_summary = {
        "Sample": f"{SYMBOL_OKX}, hourly, ~{PERIOD_DAYS} days",
        "Funding": f"{len(funding)} rows (OKX 8h)",
        "Candles": f"{len(candles)} rows (OKX hourly)",
        "OI": f"{len(oi_hist)} rows (Bybit hourly)" if not oi_hist.empty else "unavailable",
        "F&G": f"{len(fng)} rows (alternative.me daily)",
        "Horizons tested": ", ".join(f"{h}h" for h in HORIZONS),
    }
    caveats = [
        "OI 來源 Bybit、funding & candles 來源 OKX；不同交易所微小差異但模式高度相關。",
        "F&G 為日頻、forward-fill 到 hourly，可能高估該因子的有效樣本量。",
        "funding 為 8h 頻、forward-fill 到 hourly 同樣造成自相關膨脹，IR 偏樂觀。",
        "OI 用 24h pct change（差分化）使其平穩；原始 OI 為趨勢序列、與價格高度共線。",
        "Spearman IC 不考慮交易成本與滑點，**不代表策略獲利**。",
        "未做 multiple-testing 校正：3 因子 × 4 horizon = 12 檢定，部分 |IC| 可能為偽。",
    ]

    md = build_factor_report(
        title=f"Extended Factor Research — {SYMBOL_OKX}",
        period_days=PERIOD_DAYS,
        data_summary=data_summary,
        factor_results=all_results,
        caveats=caveats,
    )
    with open(OUT_REPORT, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"\n[done] report -> {OUT_REPORT}")


if __name__ == "__main__":
    main()
