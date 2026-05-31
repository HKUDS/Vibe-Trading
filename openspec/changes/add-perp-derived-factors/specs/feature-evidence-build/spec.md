## ADDED Requirements

### Requirement: 永續衍生因子族（basis / funding / OI 衍生）

系統 SHALL 提供 `research/lib/derived_factors.py`，公開三個純函式（無網路、無檔案 I/O、可單元測試）計算永續合約衍生因子並各回 `dict[str, pd.Series]`：

- `basis_factors(perp_close, spot_close)` → `basis_rel = (perp−spot)/spot`、`basis_z`（basis_rel 之 rolling z-score）、`basis_mom`（basis_rel 之 N 小時差分）。
- `funding_factors(funding_on_candle)` → `funding_z`（rolling z-score）、`funding_mom`（N 小時差分）。
- `oi_factors(oi_on_candle, close)` → `oi_z`（rolling z-score）、`oi_price_divergence`（OI 變化 × 價格報酬）、`oi_mom`（較長窗 OI 動量）。

所有 rolling / 動量 window MUST 由模組層級 config 常數定義（`SCREEN_ZSCORE_DAYS`、`SCREEN_MOM_HOURS`、`OI_MOM_HOURS`），並 MUST 以 `N 天 = N×24` bar 換算對齊 1H candle grid。所有計算 MUST 為因果（僅用當下與過去資料），MUST NOT 引入 look-ahead，且每條輸出 series MUST 與輸入 index 對齊。

Stage 0a SHALL 取得 basis 所需之**現貨 close**：以 perp instId 去除 `-SWAP` 後綴經既有 OHLCV fetcher 取得（同 endpoint、同 bar），並於取得失敗時 graceful 跳過 basis 家族而不阻斷其餘因子。這 8 個衍生因子 MUST 與既有價格/非價格因子一併寫入 `features_<sym>.parquet`（1H 對齊）並納入 `evidence_<sym>.json` IC 證據表。

funding 衍生因子（`funding_z`、`funding_mom`）之**篩選 IC** MUST 以 funding 原生 8h 結算頻率量測（measurement-layer subsample，比照 `funding_rate_raw`），以避免 8h→1H ffill 造成的樣本灌水與自相關高估；其所**儲存**之 series 仍為 1H 對齊版，不受量測層影響。

#### Scenario: 衍生因子寫入 feature store 與 evidence

- **WHEN** Stage 0a 對某 symbol 成功取得 perp、spot、funding、OI 資料並完成執行
- **THEN** `features_<sym>.parquet` MUST 含 `basis_rel`、`basis_z`、`basis_mom`、`funding_z`、`funding_mom`、`oi_z`、`oi_price_divergence`、`oi_mom` 八個欄
- **AND** `evidence_<sym>.json` MUST 對此八個 feature_key 各有一條 IC 條目，且其 `category` 分屬 `basis` / `funding` / `oi`

#### Scenario: funding 衍生以原生頻率量測 IC

- **WHEN** 對 `funding_z` 或 `funding_mom` 計算篩選 IC
- **THEN** 量測層 MUST 將序列 subsample 至 8h 原生頻率（非 1H ffill 全格）
- **AND** evidence 條目之 `ic_eval_transform` MUST 標示其原生頻率轉換（如 `native_8H`）

#### Scenario: basis 資料缺失不阻斷其餘因子

- **WHEN** 現貨 close 取得失敗
- **THEN** Stage 0a MUST 記錄 warning 並跳過 `basis_*` 三因子
- **AND** funding/OI 衍生因子與既有所有因子 MUST 仍正常寫出

#### Scenario: 衍生因子為因果且對齊

- **WHEN** 以一段 hourly 序列呼叫任一家族函式
- **THEN** 回傳之每條 series MUST 與輸入 index 同 index、同長度
- **AND** 任一時點之值 MUST NOT 依賴該時點之後的資料（無 look-ahead）
