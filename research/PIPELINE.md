# Research Pipeline 說明

本文件說明 `research/pipeline/` 各階段的功能與執行方式。

## 各階段概覽

| 階段 | 檔案 | 功能 |
|------|------|------|
| Stage 0 | `stage0_discovery.py` | 因子探索：由 LLM swarm 提議候選因子，寫出 `candidates_<sym>.json` |
| Stage 1 | `stage1_factor_eval.py` | 因子評估：計算 IC、t-stat，篩選有效因子 |
| Stage 2 | `stage2_regime.py` | 市場機制分類：偵測多頭/空頭/盤整等 regime |
| Stage 3 | `stage3_combine.py` | 因子合成：將多因子加權合併成複合訊號 |
| Stage 4 | `stage4_backtest.py` | 回測：對合成訊號做歷史績效驗證 |
| Stage 5 | `stage5_report.py` | 報告輸出：產出 manifest JSON 與可視化報告 |

---

## Stage 0 — 因子探索（Factor Discovery）

### 用法

```bash
# 從 repo root 執行
python -m research.pipeline.stage0_discovery

# 強制重跑（忽略快取）
python -m research.pipeline.stage0_discovery --force
# 或
RESEARCH_FORCE_DISCOVERY=1 python -m research.pipeline.stage0_discovery
```

### 輸出

對每個 symbol 產出 `research/manifests/candidates_<sym>.json`，格式符合 `CandidatesManifest` schema（定義於 `dashboard/server/schemas.py`）。

### 快取

`research_config.yaml` 的 `discovery_cache_days`（預設 7）控制重跑間隔。若 `candidates_<sym>.json` 的 `generated_at` 在此期間內，stage 0 跳過 swarm 呼叫。設為 0 則停用快取。

### Legacy fallback

Stage 1 若找不到 `candidates_<sym>.json`，預設退化為硬編 3 因子模式（`funding_rate`、`oi_change_24h`、`fng`）。
- 設 `RESEARCH_LEGACY_FACTORS=1`：強制 legacy 模式。
- 設 `RESEARCH_LEGACY_FACTORS=0`：強制動態模式（找不到 candidates 則 raise）。

### 失敗行為

Stage 0 失敗時寫 `candidates_<sym>.failed.json` 並輸出大紅警告。Stage 1 偵測到 failed.json 時退化為 legacy 模式。
