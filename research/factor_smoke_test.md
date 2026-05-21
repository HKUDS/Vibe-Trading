# Factor Smoke Test - BTC-USDT-SWAP

- Period: last 90 days (UTC, as of 2026-05-13T12:27:30.666429+00:00)
- Data source: OKX V5 public REST (no auth)
- Funding rows: 270
- Hourly candles: 1440
- Current OI (USD): 2669535340.37659712599356
- Current OI (contracts): 3323281.26000002132

## Factor IC / IR vs Forward Return

| factor | horizon | IC (Spearman) | IR (rolling 30d) | n_samples | interpretation |
|---|---:|---:|---:|---:|---|
| funding_rate | 8h | +0.0628 | +0.738 | 1432 | predictive (|IC|>0.05) |
| funding_rate | 24h | -0.0910 | -0.211 | 1416 | predictive (|IC|>0.05) |
| funding_rate | 72h | -0.1222 | -0.067 | 1368 | predictive (|IC|>0.05) |

## Summary (plain language)

- **funding_rate @ 8h**: IC = +0.0628（正向相關）。funding_rate 高 -> 未來 8h 報酬高。
- **funding_rate @ 24h**: IC = -0.0910（負向相關）。funding_rate 高 -> 未來 24h 報酬低。
- **funding_rate @ 72h**: IC = -0.1222（負向相關）。funding_rate 高 -> 未來 72h 報酬低。

## Caveats

- 樣本只有 ~60-90 天，不足以判斷長期 alpha。完整 Phase 1 應 use_history_endpoint=True 拉 2 年。
- funding rate 為 8h 頻率，hourly forward-fill 會產生樣本內自相關，IR 偏樂觀。
- 未含 Open Interest 歷史（需 OKX 認證或 ccxt Bybit）與 Fear & Greed Index。
- 結果僅證明資料管道 + IC 計算邏輯可跑通，**不代表策略品質**。