# Research Pipeline 說明

本文件說明 `research/pipeline/` 各階段的功能與執行方式。

## 30 秒看懂整條 pipeline（白話）

目標：從一堆市場資料裡，自動找出「能預測未來漲跌的訊號」，組成策略，回測，挑出最好的。

一條龍流程，分三大塊：

1. **找因子（Stage 0a → 0 → 1）** — 先算一池指標、量出每個指標對「未來報酬」的相關性（叫 **IC**），再讓 AI 依證據挑因子，最後嚴格驗證哪些真的有效。
2. **做策略（Stage 2 → 2b → 2.5）** — 用有效因子寫成買賣規則（YAML），編譯成可執行程式碼，並標記市場處於多頭/空頭/盤整。
3. **回測挑選（Stage 3 → 3-diag → 4 → 5）** — 跑歷史績效、診斷該怎麼改、掃參數調優、最後挑出贏家。

> 💡 **train/OOS 切分（重要）**：設 `oos_start` 後，回測與調參**只用 train 窗**，stage4 調完**自動**用最佳參數在 held-out OOS 跑一次（walk-forward），結果寫進 `manifest.walk_forward`。這才是可信的「換到沒看過的資料還賺不賺」。詳見檔尾「Walk-Forward train/OOS」。

### 幾個關鍵名詞（新手必看）

- **因子（factor）**：一個你覺得能預測漲跌的數字訊號，例如「資金費率」「RSI」。
- **IC（Information Coefficient）**：這個因子今天的值，和「未來 N 小時報酬」的相關係數。|IC| 越大代表預測力越強；正號=同向、負號=反向（contrarian）。一般加密貨幣 |IC|>0.05 就算有料。
- **horizon（時窗）**：往未來看多久（量報酬）。本專案看 8/24/72/168 小時（即 8h ~ 1 週）。
- **interval（K 棒週期）≠ horizon**：`interval` 是 K 棒大小（`research_config.yaml` 預設 `"1H"` = 1 小時 K），horizon 是「往未來看多久量報酬」。兩者獨立。⚠️ 目前 IC / forward-return 計算**寫死「1 根 K = 1 小時」**（`add_forward_returns` 用 `shift(-h)` 把 h 當列數），所以**只有 `interval="1H"` 正確**；要做 15m/30m 級別需改 horizon→bar 換算（見檔尾「多時間級別」）。
- **feature store**：算好的因子數值倉庫，存成 `features_<sym>.parquet`。下游階段直接讀它，不用每次重抓資料（省時、可重現）。
- **evidence 表**：`evidence_<sym>.json`，一張「整池因子的 IC 排名表」，是 AI 挑因子時看的證據。
- **verdict（裁決）**：Stage 1 給每個因子的評級——`single_use`（夠強可單用）、`ensemble_only`（弱，只能多因子組合）、淘汰。
- **train / OOS（樣本內/樣本外）**：把資料切兩段——**train（in-sample）**用來選參數，**OOS（out-of-sample, 樣本外）**是 train 之後、選參時**完全沒看過**的期間，用來驗證策略換到新資料還賺不賺。設 `research_config.yaml` 的 `oos_start` 啟用切分。
- **walk-forward（前測）**：在 train 窗調好參數，再丟 held-out OOS 看績效能否維持。`manifest.walk_forward` 存的就是這個——**唯一可信的真·樣本外結果**。

## 各階段概覽

| 階段 | 檔案 | 功能 |
|------|------|------|
| **Stage 0a** | `stage0a_features.py` | **特徵與證據建置**：抓 OHLCV（OKX）+ 非價格資料（funding/OI + **穩定幣供給走 DefiLlama**，多年全史）→ 算一池技術指標 + 非價格因子 → 存進 feature store；再算每個因子在各 horizon 的 IC，輸出排名表 `evidence_<sym>.json`。**無 LLM，純計算**。 |
| **Stage 0** | `stage0_discovery.py` | **因子探索**：2-agent LLM swarm（研究員提案 + 審查員把關過擬合）讀 evidence 表挑/組因子，寫出 `candidates_<sym>.json`（每個候選帶 `feature_key` 指向 feature store 欄位）。**執行前會 preflight 檢查 Stage 0a 產物存在**。 |
| **Stage 1** | `stage1_factors.py` | **因子評估**：依 candidates 的 `feature_key` 從 feature store 取序列，算 IC/IR/穩定性/verdict（呼叫 `factor_extended` + `factor_regime`）；dump `factor_values_<sym>.parquet` + `factor_<sym>.json`/`.md`。 |
| Stage 2 | `stage2_strategies.py` | 策略合成：deterministic scaffold 依 stage1 verdict 產 `strategy_<id>.yaml`（LLM swarm 只給理由）；**進場方向依因子實測 IC 符號**（正 IC→trend 做高、負 IC→contrarian 做低）；≥3 因子用 `logic: any` |
| Stage 2b | `stage2b_compile_signal.py` | YAML→signal_engine 編譯：Jinja 模板產 `signal_engine.py`，AST 雙驗證 + 自動 smoke test |
| Stage 2.5 | `stage2_5_regime.py` | 市場機制分類：偵測多頭/空頭/盤整等 regime（**價格** regime，供報告用） |
| Stage 3 | `stage3_backtest.py` | 回測：用編譯後 signal_engine 跑歷史績效；讀 parquet 不 fetch OKX。**設 `oos_start` 時 base = train 窗** |
| Stage 3-diag | `stage3_diagnose.py` | 回測診斷：讀 base + stage4 best，輸出 `recommended_action`（proceed / back_to_stage_2 / back_to_stage_4） |
| Stage 4 | `stage4_optimize.py` | 參數優化：deterministic grid sweep。**設 `oos_start` 時只在 train 掃參、掃完自動跑 held-out OOS holdout** 寫入 walk_forward |
| Stage 5 | `stage5_select.py` | 策略挑選：純 Python 加權算分，挑 `recommended_action != back_to_stage_2`，`proceed` 標 selected=True，寫 `selection.json` |

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

#### 多條件組合（`entry_long.logic` / `entry_short.logic`）

| 值 | 說明 |
|---|---|
| `all`（預設）| AND — 所有條件同時成立才進場（多因子共識；3+ 因子常過稀疏、近 0 交易）|
| `any` | OR — 任一條件成立即進場（每因子各有 edge、但交集太稀疏時用）|

> Stage 2 scaffold ≥3 因子自動用 `any`；進場方向（做高 `>=` 或做低 `<=`）依各因子**實測 IC 符號**決定，不寫死 contrarian。

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
1. 抓資料：OHLCV K 線（OKX）+ 非價格資料（資金費率 OKX、OI Bybit、**穩定幣供給 DefiLlama**）。
2. 算因子：一池技術指標（RSI、MACD、ATR、布林帶寬…）+ 非價格因子，全部存進 feature store（`features_<sym>.parquet`）。
3. 量證據：算每個因子對未來 8/24/72/168h 報酬的 **IC**，依 |IC| 由大到小排序，寫出 `evidence_<sym>.json`。

> **穩定幣資料源 = DefiLlama**（`research/lib/defillama_data.py`，endpoint `stablecoins.llama.fi/stablecoincharts/all`，免費無 key、2017 至今全史、聚合所有 USD 穩定幣）。早期用 CoinGecko 免費版卡 365 天 → 因子只 1 年覆蓋、IC 被牛市灌水；換 DefiLlama 後 BTC stablecoin_supply_z 覆蓋率 25%→99.9%，真 4yr IC 從假象 +0.104 降到誠實 +0.068。

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

---

## Stage 2 — 策略合成（Strategy Synthesis）

### 這階段在做什麼（白話）

把 Stage 1 存活的因子組成可回測的買賣規則（`strategy_<id>.yaml`）。

**關鍵：策略骨架是程式確定性產生的，不是 LLM 寫的。** LLM swarm（`crypto_trading_desk`）只負責產出「交易理由」散文（存進 `generation.rationale`）；門檻、進出場條件是 `stage2_strategies.py` 依因子 verdict + IC 確定性 scaffold 出來的（design decision B）。swarm 掛了也不影響 YAML 生成。

### 進場方向（重要）

每個因子的進場方向**依其實測 IC 符號**決定（不寫死 contrarian）：
- **正 IC → trend**：因子值高時做多（`>= 80`）、低時做空（`<= 20`）
- **負 IC → contrarian**：因子值低時做多（`<= 20`）、高時做空（`>= 80`）

用實測 IC（`ic_by_horizon` 在 max-|IC| horizon 的符號）而非 LLM 的 `expected_ic_sign`（後者會標錯）。**早期 bug：scaffold 對所有因子寫死 contrarian，把正 IC 的 stablecoin 因子做反 → 回測 -99%；修正後同因子 trend 方向轉正。**

### 多/單因子組合
≥3 因子自動 `logic: any`（AND 太稀疏會 0 交易）；2 因子用 `all`。

### 用法
```bash
python -m research.pipeline.stage2_strategies
```

---

## Stage 3 — 回測（Backtest）

### 用法
```bash
python -m research.pipeline.stage3_backtest
```

### 跑哪些 run
讀 `research/strategy_runs.json`，每策略跑：`base_run`（主回測）、`regime_runs`（bull/bear/neutral 切片）、`oos_runs`（年度切片）。透過 subprocess 呼叫 `python -m backtest.runner <run_dir>`，產物寫 `runs/<run>/artifacts/`（metrics.csv / equity.csv / trades.csv …）。

### train/OOS 行為
- **未設 `oos_start`**：base = 全期（legacy）。
- **設 `oos_start`**：base = **train 窗** `[start, oos_start)`，regime 切片也夾在 train 內 → in-sample 不偷看 OOS。真 OOS 由 Stage 4 的 holdout 負責。

> ⚠️ base 失敗時舊 artifacts 還在會被誤判 PASS（同 stage0）；要重跑先刪 `runs/<run>/`。

---

## Stage 3-diag — 回測診斷

讀 base run 指標 + Stage 4 best（`optimization.json`）做概念層路由，吐 `recommended_action`：
- `proceed`：概念成立，可進 Stage 5。
- `back_to_stage_4`：有潛力但要調參。
- `back_to_stage_2`：概念有缺陷（如負 sharpe），回去重做策略。

用 LLM（`vibe-trading run`）。⚠️ 會讀 `optimization.json`，若是舊的會誤導；重跑前確認 stage4 已更新。

```bash
python -m research.pipeline.stage3_diagnose
```

---

## Stage 4 — 參數優化（Deterministic Grid Sweep）

### 這階段在做什麼
把 YAML 的 `parameter_search_ranges` 展開成參數網格，每組跑一次回測，依 sharpe（過 trade_count 門檻）排名，挑最佳，寫 `optimization.json`（`best_params` + top-5 摘要）。**純確定性、無 LLM**（早期 LLM 版回空 dict 燒 445k token，已廢）。

### train/OOS（walk-forward）
- **未設 `oos_start` 且無 `--train-start`**：在全期掃參（legacy；此時「OOS」是假的）。
- **設 `oos_start`**：自動只在 **train 窗**掃參 → 挑 best → **自動用 best 在 held-out OOS 窗跑一次** holdout run → 寫進 `manifest.walk_forward`。這就是真·樣本外驗證。
- 手動覆寫：`--train-start / --train-end`。

### 前置
需先有 `diagnosis.json`（Stage 3-diag 產），否則 SKIP/FAIL。順序：stage3 → stage3-diag → stage4。

```bash
python -m research.pipeline.stage4_optimize --strategy <id> --max 200
# 手動 walk-forward 窗：
python -m research.pipeline.stage4_optimize --strategy <id> --train-start 2022-06-01 --train-end 2025-01-01
```

---

## Stage 5 — 策略挑選（Selection）

純 Python 加權算分（無 LLM），挑出可進 testnet 的策略，寫 `selection.json`。

- **資格**：要有 diagnosis + optimization + metrics，且 `recommended_action != back_to_stage_2`。
- **selected**：`recommended_action == proceed` → `selected=True`；`back_to_stage_4` → 入榜但 `selected=False`。
- **評分**：`0.4×(sharpe/1.5) + 0.3×(1−|dd|/0.10) + 0.2×(pf/1.5) + 0.1×(trades/100)`（各項 clamp 0~2）。

```bash
python -m research.pipeline.stage5_select
```

> 之後 → dashboard promote → testnet（`POST /api/strategies/<id>/promote` → `/api/testnet/<id>/start`）。

---

## Walk-Forward train/OOS（核心：可信回測）

### 為什麼
若在全部資料上選參，再拿同一段資料的子集當「OOS」= 循環驗證、會高估。正確做法是切 train / 真 held-out OOS。

### 怎麼設
`research_config.yaml`：
```yaml
oos_start: "2025-01-01"   # 之前 = train（選參）、之後 = held-out OOS（驗證）；留空 = 不切分
```

### 時間軸
```
period_start ─────────────── oos_start ─────────────── today
            [   in-sample TRAIN   ]   [   held-out OOS   ]
             ↑ Stage3 base 回測         ↑ Stage4 自動 holdout
             ↑ Stage4 掃參               （manifest.walk_forward）
             ↑ Stage3-diag 判讀
```

### 規則
- **in-sample（train）**：base 回測 + regime 切片 + 掃參 + diagnosis，全部止於 `oos_start`，**不碰 OOS**。
- **真 OOS**：只有 `manifest.backtest.walk_forward` 是真樣本外。`backtest.oos`（年度切片）在切分模式下應視為描述用、非真 OOS（建議乾脆清空 `oos_runs`，讓 walk_forward 當唯一 OOS）。
- **解讀**：train 調得好、held-out 也撐住 = 真 edge；train 好但 held-out 崩 = overfit。例 BTC s2：train sharpe ~1.5 → held-out 2025 僅 0.27 = edge 在 2025 退潮（真相，非藏起來）。

### 自動流程
設好 `oos_start` 後，照常跑 `stage3 → stage3-diag → stage4`，walk-forward 全自動，無需手動切窗。

---

## 多時間級別（15m / 30m）

目前 IC / forward-return / rolling 窗**寫死「1 根 K = 1 小時」**（`add_forward_returns` 的 `shift(-h)`、stage0a 的 `pct_change(periods=24)` / `rolling(720)` 都假設 1 列 = 1h）。所以：
- **1H**：現成，直接用。
- **15m / 30m**：要改 code——`interval` 改 `"15m"`/`"30m"`，並把所有 horizon/window 改成「先算每小時幾根，再乘 bar 數」；非價格因子（funding 8h、OI、穩定幣日頻）在日內幾乎沒資訊，日內 alpha 只能靠純價量技術指標。
