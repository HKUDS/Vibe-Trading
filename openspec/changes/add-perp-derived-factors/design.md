# Design — add-perp-derived-factors

## Context

stage0a 因子池缺永續特有的去相關因子家族。本設計新增 basis / funding 衍生 / OI 衍生共 8 個因子，純擴充篩選候選池，邊界僅止於 stage0a（feature store + evidence IC），不建策略。最佳 window 由下游 signal compiler DSL + stage4 sweep + OOS 決定，stage0a 只用合理預設先看「有沒有料」。

## Decisions (brainstorm 拍板)

1. **範圍**：funding + OI + basis 三家族全包。
2. **邊界**：只做 stage0a（算因子 + IC 證據），不自動建策略。新因子寫進 parquet 後 strategy 端 `load_factor_values` 本就讀得到，不擋未來使用。
3. **粒度**：平衡，每家族 2–3 個，共 8 個。
4. **結構**：抽純函式模組 `lib/derived_factors.py`（vs 塞進 `build_feature_dict` 致其肥大；vs registry 過度設計）。
5. **window**：篩選預設抽成 config 常數，透明標示「非優化值」。
6. **儲存**：primitive + z/mom 都存進 evidence 篩 IC（看轉換版有沒有料，較直覺）。

## 單位定義

candle grid = 1H。所有 window 換算成 bar 數：`N 天 = N×24 bars`、`H 小時 = H bars`。沿用既有慣例（`stablecoin_supply_z` 用 `rolling(720)`、`oi_change_24h` 用 `pct_change(24)`）。

```python
SCREEN_ZSCORE_DAYS = 30      # z-score rolling window（= 720h）；對齊現有 house 預設
SCREEN_MOM_HOURS   = 24      # 動量 lookback（= 1 自然日 / funding 完整一輪）
OI_MOM_HOURS       = 72      # OI 動量（≈ 持倉週期尺度，比 24h 慢一階）
```

## 因子公式（`research/lib/derived_factors.py`）

共用 helper：
```python
def _rolling_z(s, window_h):
    m = s.rolling(window_h, min_periods=window_h // 2).mean()
    sd = s.rolling(window_h, min_periods=window_h // 2).std()
    return (s - m) / (sd + 1e-9)
```
（`min_periods = window//2` 對齊 signal_compiler 的 zscore 渲染。）

**basis_factors(perp_close, spot_close)** — spot 先 `reindex(perp_close.index, method="ffill")`：
| key | 公式 |
|---|---|
| `basis_rel` | `(perp_close - spot) / spot` |
| `basis_z` | `_rolling_z(basis_rel, SCREEN_ZSCORE_DAYS*24)` |
| `basis_mom` | `basis_rel - basis_rel.shift(SCREEN_MOM_HOURS)` |

**funding_factors(funding_on_candle)** — caller 傳入已 ffill 對齊 candle 的 funding：
| key | 公式 |
|---|---|
| `funding_z` | `_rolling_z(funding_on_candle, SCREEN_ZSCORE_DAYS*24)` |
| `funding_mom` | `funding_on_candle - funding_on_candle.shift(SCREEN_MOM_HOURS)` |

**oi_factors(oi_on_candle, close)** — caller 傳入已 ffill 對齊的 OI：
| key | 公式 |
|---|---|
| `oi_z` | `_rolling_z(oi_on_candle, SCREEN_ZSCORE_DAYS*24)` |
| `oi_price_divergence` | `oi_on_candle.pct_change(24) * close.pct_change(24)`（同號=趨勢確認；負=背離）|
| `oi_mom` | `oi_on_candle.pct_change(OI_MOM_HOURS)` |

全部僅用當下與過去資料（rolling / shift / pct_change），無 look-ahead。

## IC 量測層（誠實 IC，沿用 `apply_ic_eval_transform`）

篩選 IC MUST 用因子原生頻率，否則 ffill 灌水假高（既有 memory 教訓）。

| 因子 | 原生頻率 | 校正 |
|---|---|---|
| `basis_*` | perp/spot 皆 1H → 真 1H，且為有界小比值（mean-reverting，非 cumulative）| 無（raw）|
| `oi_*` | Bybit OI 1h → 真 1H | 無（raw）|
| `funding_z` / `funding_mom` | funding 8h ffill 至 1H | `_IC_NATIVE_FREQ` 加 `"8H"` resample（比照 `funding_rate_raw` 的 on_change 精神）|

→ stored 因子（1H 對齊版）**不動**；只在算篩選 IC 時對 funding 衍生 subsample 至 8H。

## 接線（`stage0a_features.py`）

- `_process_symbol`：抓完 perp candles 後，`spot_instid = sym_cfg.okx_swap.replace("-SWAP","")`，`fetch_candles(spot_instid, cfg.period, bar=cfg.interval)`，取 `spot_close`；try/except 失敗 → `spot_close=None` + log warning（比照 funding/OI graceful）。傳入 `build_feature_dict`。
- `build_feature_dict`：加 `spot_close: pd.Series | None = None` 參數。將既有 funding/OI 的 ffill 對齊序列抽成本地 `funding_on_candle` / `oi_on_candle`（供 raw 與衍生共用），其後：
  ```python
  if spot_close is not None:
      features.update(basis_factors(candles["close"], spot_close))
  if funding_on_candle is not None:
      features.update(funding_factors(funding_on_candle))
  if oi_on_candle is not None:
      features.update(oi_factors(oi_on_candle, candles["close"]))
  ```
- `_INDICATOR_CATEGORY` 加：`basis_rel`/`basis_z`/`basis_mom`→`basis`；`funding_z`/`funding_mom`→`funding`；`oi_z`/`oi_price_divergence`/`oi_mom`→`oi`。
- `_IC_NATIVE_FREQ` 加：`funding_z`→`"8H"`、`funding_mom`→`"8H"`。

## Error handling

- spot 抓取失敗 → basis 三因子跳過，其餘照常（單 symbol graceful，不阻斷）。
- spot 與 perp bar 不齊 → spot `reindex(ffill)`；缺口處 basis 為 NaN，`evaluate_factor` 既有 dropna 處理。
- funding/OI 缺 → 對應家族跳過（沿用既有 `if ... is not None` 守衛）。

## 待驗證假設（實作第一步）

OKX 現貨 instId（如 `"BTC-USDT"`）走 `/market/history-candles` — 高信心但未實跑。Task 4.1 先 smoke 抓一次確認；失敗 fallback 用既有 `fetch_ohlcv_ccxt("binance","BTC/USDT")`（跨所 basis，次佳，須處理時區/對齊）。

## Testing

- **新 `research/tests/test_derived_factors.py`**：每家族餵合成序列，斷言
  - `basis_rel` 精確 `=(p−s)/s`；`basis_mom` = 24-bar diff；known z-score。
  - `funding_z`/`funding_mom` 數值與形狀。
  - `oi_price_divergence` 同號為正、異號為負、單邊為 0/負的行為；`oi_mom` = 72-bar pct_change。
  - 全部輸出與輸入 index 對齊、無未來函數（末端值不依賴未來點）。
- **擴 `research/tests/test_stage0a_features.py`**：
  - `build_feature_dict(..., spot_close=, funding_df=, oi_df=)` 吐 8 個新 key。
  - `apply_ic_eval_transform` 對 `funding_z`/`funding_mom` 回 `("...","native_8H")`、對 `basis_*`/`oi_*` 回 `(series, None)`。
  - 8 個新 key 都有 `_INDICATOR_CATEGORY` 分類。
- 現有測試保持綠（`cd research && pytest -q`）。

## 不做（YAGNI / 範圍外）

- 不建 basis 策略 spec、不碰 stage1–5、不改 signal compiler、不做 cross-sectional / regime 接線（另案）。
- 不重構既有 stablecoin/funding_raw/oi_change_24h 計算。
- 不加 multiple-testing 校正（evidence caveat 已標示，下游把關）。
