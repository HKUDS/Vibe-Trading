## 1. derived_factors 純函式模組

- [ ] 1.1 新增 `research/lib/derived_factors.py`：config 常數 `SCREEN_ZSCORE_DAYS=30`/`SCREEN_MOM_HOURS=24`/`OI_MOM_HOURS=72` + `_rolling_z(s, window_h)` helper（`min_periods=window//2`）
- [ ] 1.2 實作 `basis_factors(perp_close, spot_close)` → `{basis_rel, basis_z, basis_mom}`（spot 先 reindex ffill）
- [ ] 1.3 實作 `funding_factors(funding_on_candle)` → `{funding_z, funding_mom}`
- [ ] 1.4 實作 `oi_factors(oi_on_candle, close)` → `{oi_z, oi_price_divergence, oi_mom}`
- [ ] 1.5 全部因果、無 look-ahead；每條輸出對齊輸入 index

## 2. derived_factors 單元測試

- [ ] 2.1 新增 `research/tests/test_derived_factors.py`：合成序列驗 `basis_rel=(p−s)/s` 精確值、`basis_mom`=24-bar diff、known z-score
- [ ] 2.2 驗 `oi_price_divergence` 同號正/異號負、`oi_mom`=72-bar pct_change、`funding_z`/`funding_mom` 數值與形狀
- [ ] 2.3 驗無未來函數（末端值不依賴未來點）+ index 對齊

## 3. stage0a 接線

- [ ] 3.1 `build_feature_dict` 加 `spot_close` 參數；將既有 funding/OI ffill 對齊序列抽成本地 `funding_on_candle`/`oi_on_candle`（raw 與衍生共用，不改 raw 行為）
- [ ] 3.2 呼叫三家族函式 `features.update(...)`（各以 `is not None` 守衛）
- [ ] 3.3 `_INDICATOR_CATEGORY` 加 8 筆分類（basis/funding/oi）
- [ ] 3.4 `_IC_NATIVE_FREQ` 加 `funding_z`→`"8H"`、`funding_mom`→`"8H"`
- [ ] 3.5 `_process_symbol` 加 spot 抓取（`okx_swap.replace("-SWAP","")` 走 `fetch_candles`）+ try/except graceful → 傳 `spot_close` 進 `build_feature_dict`

## 4. 驗證

- [ ] 4.1 **spike**：smoke 抓 OKX 現貨 `BTC-USDT` 一次確認 `/market/history-candles` 回得了 K；失敗則改 `fetch_ohlcv_ccxt("binance","BTC/USDT")` 並回頭調整 3.5
- [ ] 4.2 擴 `research/tests/test_stage0a_features.py`：`build_feature_dict` 吐 8 新 key、`apply_ic_eval_transform` 對 funding 衍生回 `native_8H` / 對 basis/oi 回 None、8 key 都有分類
- [ ] 4.3 `cd research && pytest -q` 全綠（含新 + 既有）
- [ ] 4.4 實跑 `python -m research.pipeline.stage0a_features`（至少 BTC）→ `features_btc.parquet` 含 8 新欄、`evidence_btc.json` 含 8 新條目且 funding 衍生標 `native_8H`；人工看一眼 basis/OI 衍生因子的 IC 是否有訊號
- [ ] 4.5 回歸：既有 13 指標 + 3 非價格因子之 key/值不變（diff parquet 欄集合）
