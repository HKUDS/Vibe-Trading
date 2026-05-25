## ADDED Requirements

### Requirement: 因子時間序列 parquet 持久化契約

系統 SHALL 在 Stage 1 完成因子 IC 計算後，將每個因子之 hourly 時間序列以 parquet 檔案持久化於 `research/manifests/factor_values_<sym>.parquet`，其中 `<sym>` 為小寫短 symbol 名稱（如 `eth`、`btc`）。

parquet 檔 schema MUST：
- 索引欄：`time`（DatetimeIndex，UTC tz-aware，hourly 頻率）
- 因子欄：每個 stage1 評估通過（含 reject）的 factor 為一個 `float64` 欄，欄名 MUST 等於 `FactorEntry.name`
- 允許 NaN（warm-up window / 缺失資料）
- 採 `pyarrow` engine、`snappy` 壓縮

並 SHALL 同檔目錄產出 sidecar `research/manifests/factor_values_<sym>.meta.json` 含：
- `schema_version`（int，初版 1）
- `symbol`
- `generated_at`（ISO-8601 UTC datetime）
- `factor_names`（字串陣列，與 parquet 欄名一致）
- `index_start`、`index_end`（ISO-8601）
- `n_rows`

#### Scenario: stage1 寫出 parquet 與 meta
- **WHEN** `python -m research.pipeline.stage1_factors` 對 `eth` 完成執行
- **THEN** `research/manifests/factor_values_eth.parquet` MUST 存在
- **AND** `research/manifests/factor_values_eth.meta.json` MUST 存在
- **AND** 兩檔的 `factor_names` MUST 一致
- **AND** parquet 之 row 數 MUST > 0 且等於 `meta.n_rows`

#### Scenario: parquet 欄名與 manifest factor 名一致
- **WHEN** stage1 評估 N 個因子並寫出 `factor_<sym>.json`
- **THEN** `factor_values_<sym>.parquet` MUST 含相同 N 個欄
- **AND** 每欄名 MUST 等於對應 `FactorEntry.name`

### Requirement: 因子時間序列讀取 helper

系統 SHALL 提供 `research/lib/factor_io.py`，公開函式：

- `load_factor_values(symbol: str) -> pd.DataFrame`：讀 `research/manifests/factor_values_<symbol_short>.parquet`，回傳 DataFrame；檔不存在 SHALL raise `FileNotFoundError`，訊息 MUST 指引使用者先跑 `stage1_factors`
- `load_factor_meta(symbol: str) -> dict`：讀 sidecar meta.json，schema_version 不符當前版本 SHALL raise `ValueError`

下游 Stage 2b 編譯出的 `signal_engine.py` MUST 透過此 helper 讀取因子資料，不可直接呼叫 OKX fetcher。

#### Scenario: helper 讀回 stage1 寫出的 parquet
- **WHEN** stage1 已產出 `factor_values_eth.parquet`
- **AND** 呼叫 `load_factor_values("eth")`
- **THEN** 回傳 MUST 為 `pd.DataFrame`，columns MUST 等於 meta 中 `factor_names`
- **AND** index MUST 為 `pd.DatetimeIndex` 且 tz 為 UTC

#### Scenario: parquet 缺失時 raise 明確錯誤
- **WHEN** `factor_values_btc.parquet` 不存在
- **AND** 呼叫 `load_factor_values("btc")`
- **THEN** MUST raise `FileNotFoundError`
- **AND** 錯誤訊息 MUST 包含 `"run stage1_factors first"` 字樣
