# Research Pipeline 說明

本文件說明 `research/pipeline/` 各階段的功能與執行方式。

## 30 秒看懂整條 pipeline（白話）

目標：從一堆市場資料裡，自動找出「能預測未來漲跌的訊號」，組成策略，回測，挑出最好的。

一條龍流程，分三大塊：

1. **找因子（Stage 0a → 0 → 1）** — 先算一池指標、量出每個指標對「未來報酬」的相關性（叫 **IC**），再讓 AI 依證據挑因子，最後嚴格驗證哪些真的有效。
2. **做策略（Stage 2 → 2b → 2.5）** — 用有效因子寫成買賣規則（YAML），編譯成可執行程式碼，並標記市場處於多頭/空頭/盤整。
3. **回測挑選（Stage 3 → 3-diag → 4 → 5）** — 跑歷史績效、診斷該怎麼改、掃參數調優、最後挑出贏家。

### 幾個關鍵名詞（新手必看）

- **因子（factor）**：一個你覺得能預測漲跌的數字訊號，例如「資金費率」「RSI」。
- **IC（Information Coefficient）**：這個因子今天的值，和「未來 N 小時報酬」的相關係數。|IC| 越大代表預測力越強；正號=同向、負號=反向（contrarian）。一般加密貨幣 |IC|>0.05 就算有料。
- **horizon（時窗）**：往未來看多久。本專案看 8/24/72/168 小時（即 8h ~ 1 週）。
- **feature store**：算好的因子數值倉庫，存成 `features_<sym>.parquet`。下游階段直接讀它，不用每次重抓資料（省時、可重現）。
- **evidence 表**：`evidence_<sym>.json`，一張「整池因子的 IC 排名表」，是 AI 挑因子時看的證據。
- **verdict（裁決）**：Stage 1 給每個因子的評級——`single_use`（夠強可單用）、`ensemble_only`（弱，只能多因子組合）、淘汰。

## 各階段概覽

| 階段 | 檔案 | 功能 |
|------|------|------|
| **Stage 0a** | `stage0a_features.py` | **特徵與證據建置**：抓 OHLCV + 非價格資料 → 算一池技術指標（RSI/MACD/ATR…）+ 非價格因子（funding/OI/穩定幣供給）→ 存進 feature store；再算每個因子在各 horizon 的 IC，輸出排名表 `evidence_<sym>.json`。**無 LLM，純計算**。 |
| **Stage 0** | `stage0_discovery.py` | **因子探索**：2-agent LLM swarm（研究員提案 + 審查員把關過擬合）讀 evidence 表挑/組因子，寫出 `candidates_<sym>.json`（每個候選帶 `feature_key` 指向 feature store 欄位）。**執行前會 preflight 檢查 Stage 0a 產物存在**。 |
| **Stage 1** | `stage1_factors.py` | **因子評估**：依 candidates 的 `feature_key` 從 feature store 取序列，算 IC/IR/穩定性/verdict（呼叫 `factor_extended` + `factor_regime`）；dump `factor_values_<sym>.parquet` + `factor_<sym>.json`/`.md`。 |
| Stage 2 | `stage2_strategies.py` | 策略合成：LLM swarm 寫 `strategy_<id>.yaml`（受 `StrategySpec` DSL 限制） |
| Stage 2b | `stage2b_compile_signal.py` | YAML→signal_engine 編譯：Jinja 模板產 `signal_engine.py`，AST 雙驗證 + 自動 smoke test |
| Stage 2.5 | `stage2_5_regime.py` | 市場機制分類：偵測多頭/空頭/盤整等 regime |
| Stage 3 | `stage3_backtest.py` | 回測：用編譯後 signal_engine 跑歷史績效；讀 parquet 不 fetch OKX |
| Stage 3-diag | `stage3_diagnose.py` | 回測診斷：輸出 `recommended_action`（proceed / back_to_stage_2 / back_to_stage_4） |
| Stage 4 | `stage4_optimize.py` | 參數優化：對 stage3 通過的策略掃參 |
| Stage 5 | `stage5_select.py` | 策略挑選：輸出 manifest JSON |

執行順序：`0a → 0 → 1 → 2 → 2b → 2.5 → 3 → 3-diag → 4 → 3 (re-verify) → 5`。

> ⚠️ **Stage 0a 必須先跑**：Stage 0 與 Stage 1 都依賴它產出的 feature store 和 evidence 表，缺了會直接報錯。

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

## Stage 0a — 特徵與證據建置（Feature & Evidence Build）

### 這階段在做什麼（白話）

把「原始資料」變成「算好的因子數值 + 一張 IC 排名表」，給後面的 AI 當證據。整段**不用 LLM**，純 Python 計算，所以快、便宜、可重現。

做三件事：
1. 抓資料：OHLCV K 線（OKX）+ 非價格資料（資金費率、OI、穩定幣供給…）。
2. 算因子：一池技術指標（RSI、MACD、ATR、布林帶寬…）+ 非價格因子，全部存進 feature store（`features_<sym>.parquet`）。
3. 量證據：算每個因子對未來 8/24/72/168h 報酬的 **IC**，依 |IC| 由大到小排序，寫出 `evidence_<sym>.json`。

### 用法

```bash
# 從 repo root 執行（先跑這個，再跑 Stage 0）
python -m research.pipeline.stage0a_features
```

### 輸出（都在 `research/manifests/`）

| 檔案 | 內容 |
|------|------|
| `features_<sym>.parquet` | feature store：所有因子的時間序列數值 |
| `features_<sym>.meta.json` | 中繼資料：schema 版本、欄名、時間範圍、列數 |
| `evidence_<sym>.json` | IC 排名表：每個 `feature_key` 的 `ic_by_horizon` / `ir` / 樣本數，附 multiple-testing 警語 |

### 注意

- evidence 表只是「篩選參考」，**不是最終裁決**。真正的把關靠 Stage 0 的審查員 + Stage 1 的 verdict gate。
- 大指標池容易出現 IC 膨脹的偽訊號（multiple-testing），evidence 檔內含 caveat 提醒。

---

## Stage 0 — 因子探索（Factor Discovery，證據驅動）

### 這階段在做什麼（白話）

讓兩個 AI agent 接力，依 Stage 0a 的證據挑出值得進一步驗證的因子：

- **研究員（researcher）**：讀 evidence 表，依 IC 排名挑 3–6 個因子（也可用 `append_feature_column` 自組複合因子）。每個提案要附經濟邏輯，不能只說「IC 高」。
- **審查員（skeptic）**：逐一審查過擬合風險、正交性、因果有效性（無 look-ahead）、經濟邏輯，給 PASS / REVISE / REJECT，最後吐出一個 `json` 候選清單給程式解析。

> 為何要兩個 agent 對抗：過擬合是頭號殺手。研究員會樂觀，審查員專門找碴，一攻一守降低撿到偽訊號的機率。

### 用法

```bash
# 從 repo root 執行（務必先跑完 Stage 0a）
python -m research.pipeline.stage0_discovery

# 強制重跑（忽略快取）
python -m research.pipeline.stage0_discovery --force
# 或
RESEARCH_FORCE_DISCOVERY=1 python -m research.pipeline.stage0_discovery
```

### Preflight 檢查

Stage 0 開跑前會檢查 `features_<sym>.parquet` 和 `evidence_<sym>.json` 是否存在，缺了直接報錯並要你先跑 Stage 0a。

### 輸出

對每個 symbol 產出 `research/manifests/candidates_<sym>.json`，格式符合 `CandidatesManifest` schema（定義於 `dashboard/server/schemas.py`）。每個候選含：
`feature_key`（指向 feature store 欄名）、`name`、`formula`、`expected_ic_sign`（+/−/?）、`economic_logic`、`horizons_h`、`category`。

> `feature_key` 必須是 feature store 裡確實存在的欄名。AI 若亂編不存在的 key，會被 `validate_feature_keys` 直接丟棄。

### 快取

`research_config.yaml` 的 `discovery_cache_days`（預設 7）控制重跑間隔。若 `candidates_<sym>.json` 的 `generated_at` 在此期間內，stage 0 跳過 swarm 呼叫。設為 0 或加 `--force` 則停用快取。

### Legacy fallback

Stage 1 若找不到 `candidates_<sym>.json`，預設退化為硬編 3 因子模式（`funding_rate`、`oi_change_24h`、`fng`）。
- 設 `RESEARCH_LEGACY_FACTORS=1`：強制 legacy 模式。
- 設 `RESEARCH_LEGACY_FACTORS=0`：強制動態模式（找不到 candidates 則 raise）。

### 失敗行為

Stage 0 失敗時寫 `candidates_<sym>.failed.json` 並輸出大紅警告。Stage 1 偵測到 failed.json 時退化為 legacy 模式。

> ⚠️ **除錯提醒**：swarm 失敗時，若舊的 `candidates_<sym>.json` 還在，verify 步驟會讀到舊檔誤報 PASS。debug 時先刪/備份舊 manifest，才看得出 swarm 是否真的成功。
