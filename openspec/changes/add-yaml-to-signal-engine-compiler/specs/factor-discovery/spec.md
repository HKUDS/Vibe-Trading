## ADDED Requirements

### Requirement: Stage 1 後置 dump 因子時間序列

Stage 1 (`research/factor_extended.py`) 在寫出 `factor_<sym>.json` IC 摘要之後 SHALL 額外呼叫因子時間序列 dump 流程，產出 `factor_values_<sym>.parquet` 與其 sidecar `factor_values_<sym>.meta.json`（schema 與內容由 `factor-values-io` capability 定義）。

dump 流程 MUST：
- 在 dynamic 路徑（`_run_symbol_dynamic`）與 legacy 路徑（`_run_symbol_legacy`）都執行
- 蒐集已在 `_compute_candidate_series` / legacy compute 過程算出的因子序列，避免重新呼叫 source fetcher
- 若 dump 失敗 SHALL log 警告但 MUST NOT 中斷 stage1（IC manifest 仍視為主要產出）
- 完成後 print `[stage1] {sym}: wrote factor_values parquet ({n_factors} factors, {n_rows} rows)`

#### Scenario: dynamic 路徑跑完後 parquet 與 IC manifest 同時存在
- **WHEN** `python -m research.pipeline.stage1_factors` 對 `eth` 在 dynamic 模式下完成
- **THEN** `research/manifests/factor_eth.json` MUST 存在
- **AND** `research/manifests/factor_values_eth.parquet` MUST 存在
- **AND** 兩檔的因子名集合 MUST 一致

#### Scenario: legacy 路徑跑完後 parquet 仍存在
- **WHEN** `RESEARCH_LEGACY_FACTORS=1 python -m research.pipeline.stage1_factors` 對 `eth` 完成
- **THEN** `research/manifests/factor_values_eth.parquet` MUST 存在
- **AND** 欄位 MUST 為 `["funding_rate", "oi_change_24h", "fng"]` 對應 legacy 因子集

#### Scenario: parquet dump 失敗不阻斷 stage1
- **WHEN** dump 過程拋出 `IOError`（例如磁碟滿）
- **THEN** stage1 MUST log warning `[stage1] {sym}: factor_values parquet dump failed — <error>`
- **AND** stage1 MUST 仍以 exit code 0 結束（前提 IC manifest 已寫出）
