# Extended Factor Research — BTC-USDT-SWAP

- Period: last 730 days (UTC, as of 2026-05-13T12:44:56.773660+00:00)
- Sample: BTC-USDT-SWAP, hourly, ~730 days
- Funding: 271 rows (OKX 8h)
- Candles: 17520 rows (OKX hourly)
- OI: 200 rows (Bybit hourly)
- F&G: 730 rows (alternative.me daily)
- Horizons tested: 8h, 24h, 72h, 168h

## Factor IC / IR vs Forward Return

| factor | horizon | IC (Spearman) | IR (rolling 30d) | n_samples | interpretation |
|---|---:|---:|---:|---:|---|
| funding_rate | 8h | -0.0181 | -0.587 | 17512 | weak / none |
| funding_rate | 24h | -0.0335 | -1.217 | 17496 | weak / none |
| funding_rate | 72h | -0.0770 | -1.160 | 17448 | predictive (|IC|>0.05) |
| funding_rate | 168h | -0.0889 | -0.710 | 17352 | predictive (|IC|>0.05) |
| oi_change_24h | 8h | NA | NA | 168 | weak / none |
| oi_change_24h | 24h | NA | NA | 152 | weak / none |
| oi_change_24h | 72h | NA | NA | 104 | weak / none |
| oi_change_24h | 168h | NA | NA | 8 | weak / none |
| fng | 8h | -0.0025 | -1.273 | 17512 | weak / none |
| fng | 24h | -0.0115 | -1.437 | 17496 | weak / none |
| fng | 72h | -0.0287 | -1.409 | 17448 | weak / none |
| fng | 168h | -0.0303 | -1.444 | 17352 | weak / none |

## Summary (plain language)

- **funding_rate @ 72h**: IC = -0.0770（負向相關）。funding_rate 高 -> 未來 72h 報酬低。
- **funding_rate @ 168h**: IC = -0.0889（負向相關）。funding_rate 高 -> 未來 168h 報酬低。

## Caveats

- OI 來源 Bybit、funding & candles 來源 OKX；不同交易所微小差異但模式高度相關。
- F&G 為日頻、forward-fill 到 hourly，可能高估該因子的有效樣本量。
- funding 為 8h 頻、forward-fill 到 hourly 同樣造成自相關膨脹，IR 偏樂觀。
- OI 用 24h pct change（差分化）使其平穩；原始 OI 為趨勢序列、與價格高度共線。
- Spearman IC 不考慮交易成本與滑點，**不代表策略獲利**。
- 未做 multiple-testing 校正：3 因子 × 4 horizon = 12 檢定，部分 |IC| 可能為偽。