## Why

Stage 0a 目前的因子池只有 13 個價格 TA 指標 + 3 個慢頻非價格因子（`funding_rate_raw` 8h、`oi_change_24h`、`stablecoin_supply_z` 日級）。實證歷史（見 memory）反覆指出真正瓶頸是**因子數量不足 / 因子集脆弱**：ETH 整組死路、BTC 僅 `stablecoin_supply_z` 一個正 IC 因子，`funding_rate_raw` 為負 IC。

永續合約還有一整片未開發、且與現有擁擠 TA **天然去相關**的因子家族沒挖：

- **basis（perp−spot 溢價，即使用者用過的 premium index）** — 反映槓桿需求/情緒，永續核心，經濟意義最強。
- **funding 衍生**（z-score、動量）— raw 為負 IC，但極端度/趨勢版可能不同。
- **OI 衍生**（z-score、價量背離、動量）— 目前只有單一 24h 變化，組合用法未做。

本變更把 3 個家族、共 8 個衍生因子接進 stage0a 因子池與 evidence IC 證據表，擴大候選池供下游 stage0/1 篩選，且不破壞既有任何因子。

## What Changes

- **新模組** `research/lib/derived_factors.py`：純函式（無網路無 I/O、可單測），每家族一函式，於 config 常數 window 計算因子並回 `dict[name→Series]`，全部因果、無 look-ahead。
- **basis 資料源**：stage0a 額外抓 OKX **現貨** close（perp instId 去掉 `-SWAP`，走既有 `fetch_candles`，同 endpoint/同 1H 格，**零新 fetcher**），失敗則 graceful 跳過 basis。
- **接線** `research/pipeline/stage0a_features.py`：`build_feature_dict` 加 `spot_close` 參數並呼叫三家族函式；`_INDICATOR_CATEGORY` 加 8 筆分類（`basis`/`funding`/`oi`）；`_IC_NATIVE_FREQ` 加 `funding_z`/`funding_mom` → `"8H"`（誠實 IC：funding 衍生於 8h 原生頻率篩選，避免 ffill 灌水）。
- **8 個新因子**：`basis_rel`、`basis_z`、`basis_mom`、`funding_z`、`funding_mom`、`oi_z`、`oi_price_divergence`、`oi_mom`。全部寫進 `features_<sym>.parquet`（1H 對齊，strategy 之後 `load_factor_values` 讀得到）並進 `evidence_<sym>.json` IC 排名。
- **不動**：現有 13 指標 + `funding_rate_raw`/`oi_change_24h`/`stablecoin_supply_z` 計算、signal compiler、stage1–5、dashboard 全部行為不變。不做無關重構。

## Capabilities

### Modified Capabilities
- `feature-evidence-build`：feature store + evidence 證據表新增「永續衍生因子族（basis/funding/OI derived）」契約 — 新 `derived_factors` 純函式模組、OKX 現貨 close 來源、8 個具名因子、funding 衍生以原生 8h 頻率做篩選 IC。

## Impact

- 程式：新增 `research/lib/derived_factors.py`；修改 `research/pipeline/stage0a_features.py`（`build_feature_dict`、`_INDICATOR_CATEGORY`、`_IC_NATIVE_FREQ`、`_process_symbol` spot 抓取）。
- 測試：新增 `research/tests/test_derived_factors.py`（每家族純函式單測）；擴充 `research/tests/test_stage0a_features.py`（新 key、IC 轉換、分類）。
- 待驗證假設：OKX 現貨 instId `"BTC-USDT"` 是否走得了 `/market/history-candles`（高信心未實跑）。實作第一步先 smoke 驗證；失敗則 fallback 用 `fetch_ohlcv_ccxt("binance","BTC/USDT")`（跨所 basis，次佳）。
- 不影響：signal_engine、stage1–5、testnet、dashboard 既有行為；evidence IC 僅篩選用途，未做交易成本與 multiple-testing 校正（既有 caveat 不變）。
- 風險：候選池從 ~16 增至 ~24，多重比較面擴大；緩解 = stage0a 僅篩選不下注，真正把關仍在下游 IC gate / skeptic / OOS。
