# Research Pipeline 說明

本文件說明 `research/pipeline/` 各階段的功能與執行方式。

## 各階段概覽

| 階段 | 檔案 | 功能 |
|------|------|------|
| Stage 0 | `stage0_discovery.py` | 因子探索：由 LLM swarm 提議候選因子，寫出 `candidates_<sym>.json` |
| Stage 1 | `stage1_factor_eval.py` | 因子評估：計算 IC、t-stat，篩選有效因子 |
| Stage 2 | `stage2_regime.py` | 市場機制分類：偵測多頭/空頭/盤整等 regime |
| Stage 2b | `stage2b_compile_signal.py` | YAML→signal_engine 編譯：將策略 spec YAML 透過 Jinja 模板產生 signal_engine.py |
| Stage 3 | `stage3_combine.py` | 因子合成：將多因子加權合併成複合訊號 |
| Stage 4 | `stage4_backtest.py` | 回測：對合成訊號做歷史績效驗證 |
| Stage 5 | `stage5_report.py` | 報告輸出：產出 manifest JSON 與可視化報告 |

---

## Stage 2b — YAML→signal_engine 編譯

### 用途

將策略 YAML spec（`StrategySpec` schema）透過 Jinja 模板編譯成 `signal_engine.py`，並在寫入前對產出碼做 AST 語法驗證與 backtest scrubber 檢查。位於 Stage 2（市場機制分類）與 Stage 2.5 之間。

### 用法

```bash
# 編譯特定策略（從 repo root 執行）
python -m research.pipeline.stage2b_compile_signal --strategy <strategy_id>

# 試跑（只顯示產出碼，不寫入檔案）
python -m research.pipeline.stage2b_compile_signal --strategy <strategy_id> --dry-run
```

### Escape hatch — 保護手寫 signal_engine

若 `signal_engine.py` 前 5 行內含 `# manual: do-not-overwrite`，stage 2b 跳過該檔案，不覆寫。

```python
# manual: do-not-overwrite
# 手寫實作，暫不透過 DSL 編譯
```

### DSL 詞彙速查

#### 指標來源格式（`indicators[*].source`）

```
stage1:<factor_key>
# 例：stage1:funding_rate, stage1:oi_change_24h
```

#### 平滑選項（`indicators[*].smoothing`）

| 值 | 說明 |
|---|---|
| `none` | 不平滑 |
| `sma_<n>` | n 期簡單移動平均，例 `sma_3` |
| `ema_<n>` | n 期指數移動平均，例 `ema_5` |

#### 進場條件格式（`entry_long.conditions` / `entry_short.conditions`）

```
<indicator>_percentile_<n>d <op> <value> [persist <m>/<k>]
<indicator>_zscore_<n>d    <op> <value> [persist <m>/<k>]
<indicator>                <op> <value> [persist <m>/<k>]
```

- `<op>`：`<=`、`>=`、`<`、`>`、`==`
- `persist <m>/<k>`：過去 k 根 K 線中至少 m 根滿足條件才觸發
- 例：`funding_rate_percentile_90d <= 20 persist 2/3`

#### 出場規則類型（`exit_rules[*].condition`）

| `condition` | 必填欄位 | 說明 |
|---|---|---|
| `time_based` | `max_hold_hours: int` | 最多持有 N 小時後強制平倉 |
| `take_profit_pct` | `value: float` | 獲利達 value% 平倉 |
| `stop_loss_pct` | `value: float` | 虧損達 value% 平倉 |
| `signal_invalidation` | `expression: str` | 當指標落入中性區間時平倉，格式：`<indicator>_percentile_<n>d between <lo>,<hi>` |

### 失敗模式

- YAML schema 驗證失敗 → 顯示 Pydantic validation error，中止
- AST 語法錯誤（jinja 渲染後）→ 顯示 SyntaxError，中止
- pytest 測試失敗（若 `--skip-test` 未設定）→ 顯示測試輸出，中止
- 遇 `# manual: do-not-overwrite` → 印出跳過訊息，正常結束

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
