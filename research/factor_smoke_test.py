"""
Smoke test orchestrator — uses research/lib utilities.

Verifies that:
1. lib.okx_data fetch works
2. lib.factor_metrics IC/IR computation works
3. lib.report markdown rendering works

Should reproduce identical IC numbers to the pre-refactor version.
"""

from lib.factor_metrics import add_forward_returns, evaluate_factor
from lib.okx_data import fetch_candles, fetch_current_oi, fetch_funding_history
from lib.report import build_factor_report

import pandas as pd

SYMBOL = "BTC-USDT-SWAP"
PERIOD_DAYS = 90
HORIZONS = [8, 24, 72]
OUT_REPORT = r"C:/Users/cool6/Vibe-Trading/research/factor_smoke_test.md"


def main() -> None:
    print(f"[1/3] funding history (last {PERIOD_DAYS}d)")
    # Smoke test uses /market/candles (~1440 bars) to match prior baseline.
    # Full Phase 1 will switch to use_history_endpoint=True for deep history.
    funding = fetch_funding_history(SYMBOL, PERIOD_DAYS)
    print(f"     rows: {len(funding)}  range: {funding.index.min()} ~ {funding.index.max()}")

    print(f"[2/3] hourly candles (last {PERIOD_DAYS}d)")
    candles = fetch_candles(SYMBOL, PERIOD_DAYS, bar="1H", use_history_endpoint=False)
    print(f"     rows: {len(candles)}  range: {candles.index.min()} ~ {candles.index.max()}")

    print("[3/3] current OI snapshot")
    oi_now = fetch_current_oi(SYMBOL)

    # Align funding (8h) to hourly via forward-fill
    fund_hourly = funding.reindex(candles.index, method="ffill").bfill()
    df = pd.DataFrame(index=candles.index)
    df["close"] = candles["close"]
    df["funding_rate"] = fund_hourly["funding_rate"]
    df = add_forward_returns(df, "close", HORIZONS)

    results = evaluate_factor(df, "funding_rate", HORIZONS)

    data_summary = {
        "Data source": "OKX V5 public REST (no auth)",
        "Funding rows": len(funding),
        "Hourly candles": len(candles),
        "Current OI (USD)": oi_now.get("oiUsd", "NA"),
        "Current OI (contracts)": oi_now.get("oi", "NA"),
    }
    caveats = [
        "樣本只有 ~60-90 天，不足以判斷長期 alpha。完整 Phase 1 應 use_history_endpoint=True 拉 2 年。",
        "funding rate 為 8h 頻率，hourly forward-fill 會產生樣本內自相關，IR 偏樂觀。",
        "未含 Open Interest 歷史（需 OKX 認證或 ccxt Bybit）與 Fear & Greed Index。",
        "結果僅證明資料管道 + IC 計算邏輯可跑通，**不代表策略品質**。",
    ]

    md = build_factor_report(
        title=f"Factor Smoke Test - {SYMBOL}",
        period_days=PERIOD_DAYS,
        data_summary=data_summary,
        factor_results=results,
        caveats=caveats,
    )
    with open(OUT_REPORT, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"\n[done] report -> {OUT_REPORT}")
    print("\n--- 3-line summary ---")
    for r in results:
        ic_s = f"{r.ic:+.4f}" if r.ic == r.ic else "NA"  # NaN check
        ir_s = f"{r.ir:+.3f}" if r.ir == r.ir else "NA"
        print(f"  {r.horizon:>4}: IC={ic_s}  IR={ir_s}  n={r.n_samples}")


if __name__ == "__main__":
    main()
