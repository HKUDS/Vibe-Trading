## Context

Vibe-Trading 的 research pipeline 階段（stage0 → stage1 → stage2 → stage2.5 → stage3 → stage4 → stage5）裡，Stage 2 用 swarm preset `crypto_trading_desk` 由 LLM 產出 markdown rationale + `strategy_<id>.yaml`（規格描述），但 **沒有產出 `signal_engine.py`**。Stage 3 (`research/pipeline/stage3_backtest.py`) 在 `_setup_run_dir` 找 `research/strategies/code/<id>/signal_engine.py`，找不到時 fallback 到 `build_stub_signal_engine()`（回傳全 0 series 的 stub）。結果：每個策略 backtest `trade_count=0`，Stage 3 diagnose LLM 一定判 `back_to_stage_2`，下游 stage4 / stage5 全部跳過。

2026-05-24 ETH 端到端跑通的唯一辦法是「手寫 `research/strategies/code/eth_s1_multi_factor_consensus/signal_engine.py`」：120 行 pandas code，把 yaml 的 percentile / persistence / smoothing / signal invalidation 規格翻成可執行邏輯。要 scale 到多策略（BTC、SOL、未來幣種）× 多 archetype，手寫不可行。

並列限制：
- Stage 1 寫 `factor_<sym>.json`（IC summary）但**不寫因子時間序列**。手寫 signal_engine 每次回測都得重新 fetch OKX → 慢且依賴外部。
- `agent/backtest/runner.py:_validate_signal_engine_source` 用 AST 拒絕 top-level executable statement，所以 LLM 直接寫 .py 風險高（易違規 + 邏輯 bug 難除）。
- 既有 `research/strategies/strategy_S1.yaml` ~ `strategy_S4.yaml`（legacy stub strategies）使用詞彙不一致，未來自動編譯前需要先規範。

利害人：研究人員（要 pipeline 跑通才能驗 alpha）；維運（要 reproducible build）；未來新增策略的人（不該每加一個策略就手寫一份 .py）。

## Goals / Non-Goals

**Goals:**

- 定義受限 YAML DSL（indicator / entry / exit / sizing 欄位語意），具備 Pydantic schema 驗證能力。
- 純 Python templater（不靠 LLM）把符合 DSL 的 YAML 翻成 AST-safe `signal_engine.py`。
- Stage 1 之後持久化因子 hourly 時間序列到 parquet，signal_engine 直接讀檔。
- 為手寫 escape hatch 留口子：若 `signal_engine.py` 開頭有 `# manual: do-not-overwrite`，Stage 2b 不覆寫。
- 每個 stage 都可單測，且 stage2b 生成的 .py 必須通過 `_validate_signal_engine_source` AST scrubber 與 `pytest research/strategies/code/<id>/test_signal_engine.py`（同步生成一支煙霧測試）。

**Non-Goals:**

- 不引入 LLM 寫 Python（templater 唯一路徑）。
- 不改 `agent/backtest/runner.py` 或 backtest engine 內部行為（讓 engine 把 YAML 當一等公民是另一個更大 change 的事）。
- 不處理多 symbol 同 yaml 的批次回測（一個 yaml 仍對應一個 symbol）。
- 不重寫 stage3 流程；stage3 仍從 `research/strategies/code/<id>/` 拷貝 signal_engine.py。
- 不改現有 `strategy_S1.yaml` ~ `S4.yaml` 的邏輯，只加 manual escape hatch 標記保留 legacy 行為。

## Decisions

### D1：以 Jinja templater 而非 AST builder 生程式碼
**選 Jinja2 樣板**，把 YAML 欄位填入 `signal_engine.py.j2` 樣板。
**替代**：(a) `ast.unparse(ast.Module(...))` 程式化組 AST；(b) LLM 生程式。
**理由**：
- Jinja 模板對人類可讀，研究人員可手 review 樣板，比 AST builder 直觀。
- 已有 jinja2 在 dependency tree（fastapi → jinja2），不增依賴重量級。
- AST builder 雖然「保證合法」，但對 pandas chain expression 寫起來囉嗦，且生成的 source 對 debug 不友善。
- LLM 路徑被 Goals 明確排除（AST 失敗 + token 成本 + 不可重現）。
**緩解**：樣板渲染後 必須先過 `ast.parse()` syntax check，再過 `_validate_signal_engine_source()` AST scrubber，最後 dry-run import；任何一步失敗 stage2b raise。

### D2：YAML DSL 受限詞彙
**indicator.source** 只接受 `stage1:<factor_name>`（從 stage1 因子序列讀）。**smoothing** 只接受 `none`、`sma_<n>`、`ema_<n>`。
**entry_long.conditions / entry_short.conditions** 每條須為以下三種 pattern 之一：
- `<indicator>_percentile_<n>d <op> <value>` （`<op>` ∈ `<=`、`>=`、`<`、`>`、`==`）
- `<indicator>_zscore_<n>d <op> <value>`
- `<indicator> <op> <value>` （raw 比較）

外加 persistence wrapper：`persist <m>/<n>` 表示「最近 n 個 bar 至少 m 個滿足前面條件」。
**exit_rules** 接 `time_based`、`take_profit_pct`、`stop_loss_pct`、`signal_invalidation`（後者用 `<indicator>_percentile_<n>d between <lo>,<hi>`）。
**替代**：完全自由 expr DSL（aka Python eval）或內嵌 Python snippet。
**理由**：限制詞彙才能 100% 編譯 + 100% AST 安全。自由 DSL 等於再做一遍 Python parser。
**緩解**：DSL 詞彙不夠用時走 manual escape hatch；本 change 文件列出已支援詞彙與 known limitations。

### D3：因子時間序列存為 parquet（不是 CSV / JSON）
**選 parquet**。檔名 `research/manifests/factor_values_<sym>.parquet`，schema：DatetimeIndex (UTC, hourly) × 一欄一因子（float64）。
**替代**：CSV、JSON、Feather。
**理由**：parquet 對 hourly 多年資料體積最小、欄式 query 最快；pandas + pyarrow 一行 read。CSV 慢且大；JSON 對時序資料浪費。
**依賴**：加 `pyarrow` 到 `agent/requirements.txt` + `research/requirements.txt`（若有）。
**緩解**：parquet 讀失敗時 signal_engine 必須 raise 清楚錯誤（不可 silent fallback 回 OKX fetch），由 stage2b 在生成時加 explicit guard。

### D4：Stage 2b 的位置與呼叫時機
Stage 2b 位於 Stage 2 與 Stage 2.5 之間（`0 → 1 → 2 → 2b → 2.5 → 3 → ...`）。Stage 2b runner 讀 `strategy_runs.json` 所有 entry，對每個 `spec_yaml` 編譯，寫 `research/strategies/code/<id>/signal_engine.py`。
**替代**：Stage 2b 跟 Stage 2 合併（stage2 yaml + compile 同一 runner）。
**理由**：分離讓 stage2 純 LLM、stage2b 純 deterministic，兩者各自可測 / 可 cache / 可獨立 rerun。
**Side note**：Stage 2.5（regime）不依賴 signal_engine 存在，所以 2b 可以排在 2.5 之前或之後皆可；排前者更接近「補完 stage2 缺口」直覺。

### D5：手寫 escape hatch
Stage 2b 在覆寫 `signal_engine.py` 之前 SHALL `head -1 <file>` 檢查是否存在 `# manual: do-not-overwrite`（任何位置在前 5 行）。若存在則跳過該 strategy_id 並 print warning。
**理由**：研究階段難免要手 patch；強制重寫會擋路。
**風險**：手寫版本可能跟 yaml 不同步 → stage2b 加 `# yaml-hash: <sha256>` 註解，下游 diagnose / audit 可比對。

### D6：Stage 2b 生成的 signal_engine 自帶煙霧測試
每次寫 `signal_engine.py` 同時寫 `research/strategies/code/<id>/test_signal_engine.py`：以 fixture parquet 跑 `SignalEngine().generate({code: df})`，assert 回傳 dict 含 code key、series index 與 df 一致、值在 `{-1, 0, 1}`。
**理由**：擋住 templater bug 在 stage3 才被發現。
**緩解**：stage2b runner 在生成後立即 subprocess 跑 `pytest <test>`，失敗 raise（exit code 非 0）。

### D7：Stage 1 對 dump parquet 的最小侵入
在 `research/factor_extended.py` 的 `_run_symbol_dynamic` 末段（manifest 寫出之後）多加一個 `_dump_factor_values_parquet(sym, factor_series_dict, manifests_dir)` 呼叫；legacy 路徑同步加。`factor_series_dict` 已在 `_compute_candidate_series` 算出，只需在 caller 累積。
**替代**：另開 stage1.5。
**理由**：因子序列本就在 stage1 算好，多寫一個 dump 即可；獨立 stage1.5 是 over-engineering。

## Risks / Trade-offs

- **[Risk]** DSL 詞彙不夠用，研究人員轉去 manual escape hatch → templater 變沒人用。**Mitigation**：proposal 列首批支援詞彙；新增需求時開後續 change 擴 DSL，並把 manual 數量當 KPI 監控。
- **[Risk]** parquet schema 變動（factor 名 / horizon）破壞已存檔。**Mitigation**：parquet 寫出時欄位順序固定；signal_engine 讀檔用欄名 lookup 不用 positional index；引入 `schema_version` 於 sidecar `.meta.json`。
- **[Risk]** 樣板生成的 code 過 `_validate_signal_engine_source` AST scrubber 但 runtime 邏輯錯，stage3 才爆。**Mitigation**：D6 強制 stage2b 跑 smoke test pytest，error 才放行。
- **[Risk]** legacy `strategy_S1-S4.yaml` 詞彙不符 DSL，stage2b 全部 raise。**Mitigation**：本 change tasks 包含「加 manual 標記到所有 legacy yaml」一步；改寫成新 DSL 留給後續 change。
- **[Trade-off]** Jinja 樣板代碼是 string concat，比 AST builder 容易出 escaping bug（factor 名含奇怪字元）。**Mitigation**：DSL 把 factor name 限制為 `[a-z][a-z0-9_]*`；validator 在 stage2b 早期 raise。
- **[Trade-off]** stage2b 加在 pipeline 中間，舊 strategy_runs.json 依賴 stage3 直接拷貝既存 signal_engine.py 的工作流會微改。**Mitigation**：escape hatch 讓既存手寫版繼續可用；文件清楚示範.

## Migration Plan

1. **Phase 0 — schema 與 DSL 規範化**：實作 `StrategySpec` pydantic schema、`signal_compiler` templater、tests。完成後不上線 stage2b。
2. **Phase 1 — legacy yaml 標記**：在 `strategy_S1.yaml` ~ `S4.yaml` 加 `# manual: do-not-overwrite` 註解＋對應 `signal_engine.py` 若不存在則手寫一份（或留 stub 保留現況）。
3. **Phase 2 — stage1 dump parquet**：改 `factor_extended.py` 寫 `factor_values_<sym>.parquet`，新增 `lib/factor_io.py`。回填一次 ETH，驗 parquet 正確.
4. **Phase 3 — stage2b runner**：新增 `stage2b_compile_signal.py`，串到 `pipeline/run_all.py` 順序中。
5. **Phase 4 — 端到端驗收**：清 `runs/eth_s1_*`，重跑 stage2 → stage2b → stage3，驗證 `signal_engine.py` 由 templater 產出且 trade_count > 0。
6. **Phase 5 — 文件**：更新 `research/PIPELINE.md` 加 Stage 2b 一節；memory 加 ADR 紀錄。

**Rollback**：stage2b runner 是新增檔，移除即可；parquet dump 是 best-effort（讀失敗 signal_engine 自己 raise，沒有破壞性副作用）。

## Open Questions

- DSL 是否要支援「兩因子組合運算」（如 `factor_a + factor_b`）？v1 暫不支援，需要再開後續 change。
- 手寫 escape hatch 標記要不要寫進 `strategy_<id>.yaml`（metadata）而非 .py 註解？v1 用 .py 註解（最接近作用點），未來可加 yaml 欄位。
- Stage 2 LLM 是否需要被告知 DSL 詞彙？v1 在 swarm preset 加一段「請只用以下 entry condition 詞彙」prompt 約束，但編譯時仍以 validator 為準。
- 若 stage1 還沒跑（factor_values_*.parquet 缺），stage2b 是 raise 還是 lazy 等到 stage3？v1 在 stage2b 編譯期不檢查 parquet（templater 不讀資料），檢查推到 signal_engine 執行期。
