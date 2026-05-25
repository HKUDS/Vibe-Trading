## 1. Schema 與 DSL 規範化（dashboard/server/schemas.py）

- [ ] 1.1 新增 `IndicatorSpec` Pydantic 模型，欄位 `source`（regex 驗證 `^stage1:[a-z][a-z0-9_]*$`）、`smoothing`（regex 驗證 `^(none|sma_\d+|ema_\d+)$`）
- [ ] 1.2 新增 `EntryBlock` Pydantic 模型，欄位 `description`、`conditions`（字串陣列）；每條 condition 須通過 DSL pattern validator（percentile / zscore / raw 比較 + 可選 `persist m/n` 後綴）
- [ ] 1.3 新增 `ExitRule` Pydantic discriminated union：`time_based` / `take_profit_pct` / `stop_loss_pct` / `signal_invalidation` 四種
- [ ] 1.4 新增 `StrategySpec` Pydantic 模型，欄位 `name / archetype / symbol / timeframe_signal / indicators / entry_long / entry_short / exit_rules`
- [ ] 1.5 在 `_parse_condition()` 純函式中實作 DSL pattern parser，回傳 `(indicator, op, value, persist_m, persist_n)` tuple；非法 raise `ValueError`
- [ ] 1.6 新增單元測試 `dashboard/server/tests/test_schemas_strategy_spec.py`：(a) 合法 YAML 解析成功、(b) 未知 source 被拒、(c) 未知 condition 詞彙被拒、(d) `persist 2/3` 正確 parse、(e) 各 ExitRule discriminator 正確 dispatch
- [ ] 1.7 跑現有 `pytest dashboard/server/tests` 套件，確認新模型不破壞既有 API 序列化

## 2. 因子時間序列 I/O（research/lib/factor_io.py + factor_extended.py）

- [ ] 2.1 加 `pyarrow` 到 `agent/requirements.txt`（若有 `research/requirements.txt` 也加）
- [ ] 2.2 新建 `research/lib/factor_io.py`，公開 `dump_factor_values(symbol, factor_series_dict, manifests_dir) -> Path`：寫 parquet + sidecar meta.json
- [ ] 2.3 新建 `load_factor_values(symbol) -> pd.DataFrame` + `load_factor_meta(symbol) -> dict`；缺檔 raise 明確錯誤（含 `"run stage1_factors first"`）
- [ ] 2.4 在 `research/factor_extended.py:_run_symbol_dynamic` 末段（manifest 寫出之後）呼叫 `dump_factor_values`，傳入已累積的 factor_series_dict
- [ ] 2.5 在 `_run_symbol_legacy` 同樣呼叫 `dump_factor_values`（factor_series 從 legacy compute 階段累積）
- [ ] 2.6 dump 失敗以 try/except 包裹，log warning 不 raise，確保 stage1 退場碼仍為 0
- [ ] 2.7 加 stdout print `[stage1] {sym}: wrote factor_values parquet ({n_factors} factors, {n_rows} rows)`
- [ ] 2.8 新增 `research/tests/test_factor_io.py`：(a) dump → load round-trip 一致、(b) meta.json 欄位完整、(c) load 缺檔 raise、(d) schema_version 不符 raise
- [ ] 2.9 新增整合測試片段在 `research/tests/test_factor_extended_dynamic.py`：跑完 dynamic 流程後 assert parquet 與 meta 存在

## 3. YAML → Python 編譯器（research/lib/signal_compiler.py + Jinja 樣板）

- [ ] 3.1 新建 `research/strategies/code/_templates/signal_engine.py.j2`，含 `class SignalEngine` 骨架、generate() 方法樁，並用 Jinja control flow 渲染 indicator load / entry / exit 區塊
- [ ] 3.2 新建 `research/lib/signal_compiler.py`，公開 `compile_strategy(spec: StrategySpec) -> str`
- [ ] 3.3 實作 `_render_indicator_load(name, spec)` 翻 `stage1:<factor>` 為 `lib.factor_io.load_factor_values(symbol)[<factor>]`，並套 smoothing（`sma_n` / `ema_n` / `none`）
- [ ] 3.4 實作 `_render_condition(cond_str)` 翻 DSL 為 pandas boolean expression；支援 percentile（須 rolling rank pct=True）、zscore（rolling z）、raw 比較；`persist m/n` 後綴翻為 `.rolling(n).sum() >= m`
- [ ] 3.5 實作 `_render_entry_block(side, block)` 用 `&` 串接多個 condition，產出 long/short event Series
- [ ] 3.6 實作 `_render_exit_state_machine(exit_rules)` 為 stateful loop（time_based 計入持倉小時數；TP/SL 對 entry price 算 unrealized P&L；signal_invalidation 用 percentile band 觸發歸 0）
- [ ] 3.7 編譯器主流程：渲染樣板後 `ast.parse()` syntax check → `_validate_signal_engine_source()` AST scrubber check → 兩步都通過才回字串
- [ ] 3.8 新增單元測試 `research/tests/test_signal_compiler.py`：(a) 合法 spec 渲染後 `ast.parse` 不 raise、(b) AST scrubber 通過、(c) 渲染結果含 `class SignalEngine` + `def generate`、(d) `persist 2/3` 翻譯正確、(e) 雙因子 AND 條件用 `&` 串接、(f) 各 ExitRule 翻譯正確

## 4. Stage 2b runner（research/pipeline/stage2b_compile_signal.py）

- [ ] 4.1 新建 `research/pipeline/stage2b_compile_signal.py`，採與 `stage2_strategies.py` 同 path bootstrap 模式
- [ ] 4.2 實作 `_load_strategy_runs()` 讀 `research/strategy_runs.json`（用既有 `pipeline.strategy_runs.load_strategy_runs`）
- [ ] 4.3 實作 `_check_manual_escape_hatch(path) -> bool`：讀目標 .py 前 5 行，含 `# manual: do-not-overwrite` 回 True
- [ ] 4.4 實作 `_compile_one(strategy_id, entry) -> CompileResult`：讀 yaml → StrategySpec 驗證 → compile_strategy → 寫 .py（首行 yaml-hash 註解）→ 寫 test_signal_engine.py → 跑 pytest subprocess
- [ ] 4.5 實作 `_render_smoke_test(spec) -> str` 產生 `test_signal_engine.py` 內容（fixture mock `load_factor_values`、assert generate 回傳 schema）
- [ ] 4.6 main() 對每個 strategy 呼叫 `_compile_one`，蒐集所有結果；任一 FAIL 最後 exit 非 0；skipped 用黃字、failed 用紅字、ok 用綠字
- [ ] 4.7 新增 CLI flag `--strategy <id>` 只編譯指定策略；`--dry-run` 渲染但不寫檔
- [ ] 4.8 新增單元測試 `research/tests/test_stage2b_compile_signal.py`：(a) 合法 yaml 寫出檔且 hash 註解正確、(b) manual 標記跳過、(c) 不合法 yaml 收集錯誤、(d) `--dry-run` 不留檔
- [ ] 4.9 新增整合測試 `research/tests/test_stage2_to_stage2b_integration.py`：mocked stage2 寫 yaml → 呼叫 stage2b → assert signal_engine.py + test_signal_engine.py 都存在且 import 成功

## 5. Pipeline 串接 + legacy 兼容

- [ ] 5.1 在 `research/PIPELINE.md` 補一節「Stage 2b — YAML→signal_engine 編譯」，含用法 / escape hatch / DSL 詞彙清單 / failure mode
- [ ] 5.2 若 `research/pipeline/run_all.py` 存在，把 stage2b 插入 stage2 與 stage2.5 之間；若無暫不建
- [ ] 5.3 在 `research/strategies/strategy_S1.yaml` ~ `S4.yaml` 對應的 `research/strategies/code/<id>/signal_engine.py` 開頭加 `# manual: do-not-overwrite` 註解（若這些 .py 不存在則先建 stub 含註解，保留 legacy 行為）
- [ ] 5.4 對 `eth_s1_multi_factor_consensus` 之手寫 signal_engine（2026-05-24 ETH 端到端時手寫的 scaffold），先加 manual 標記（避免 stage2b 上線後立即被覆寫），日後驗證編譯器產出與手寫等效後再移除標記
- [ ] 5.5 在 `agent/src/swarm/presets/crypto_trading_desk.yaml`（或對應 Stage 2 preset）的 output_formatter prompt 加一段「請只使用以下 DSL 詞彙」清單，引導 LLM 寫合規 yaml

## 6. 端到端驗證

- [ ] 6.1 `rm -rf runs/eth_s1_*`，從乾淨狀態跑 `stage1_factors` 驗 parquet 與 meta 都寫出
- [ ] 6.2 跑 `python -m research.pipeline.stage2_strategies`（產 yaml）→ `stage2b_compile_signal`，驗 `research/strategies/code/eth_s1_multi_factor_consensus/signal_engine.py` 由編譯器產出（移除原 manual 標記）且 hash 註解正確
- [ ] 6.3 跑 `python -m research.pipeline.stage3_backtest`，驗 `trade_count > 0` 且 metrics 非全 0
- [ ] 6.4 跑 `python -m research.pipeline.stage3_diagnose`，驗 `recommended_action` 非 `back_to_stage_2`（理想為 `back_to_stage_4` 或 `proceed`）
- [ ] 6.5 用 superpowers:verification-before-completion skill 走完成清單，確保所有 spec scenario 都有對應驗證

## 7. 文件 / 流程記錄

- [ ] 7.1 在 `memory/MEMORY.md` 加 ADR 條目指向本 change
- [ ] 7.2 在 `research/strategies/README.md` 補 DSL 詞彙速查表（indicator source / smoothing / condition pattern / exit rule）
- [ ] 7.3 用 `openspec validate add-yaml-to-signal-engine-compiler --strict` 驗證 change 結構合法
