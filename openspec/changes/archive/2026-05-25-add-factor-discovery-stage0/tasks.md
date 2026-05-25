## 1. Schema 擴充（dashboard/server/schemas.py）

- [x] 1.1 新增 `FactorVerdict.DATA_UNAVAILABLE = "data_unavailable"` enum 值
- [x] 1.2 新增 `FactorCandidate` Pydantic 模型，欄位 `name / formula / data_source / transform / expected_ic_sign / economic_logic / horizons_h / category`
- [x] 1.3 新增 `CandidatesManifest` Pydantic 模型，欄位 `schema_version / symbol / generated_at / source_swarm_run / candidates`
- [x] 1.4 新增 schema 單元測試 `dashboard/server/tests/test_schemas_candidates.py`：(a) 必要欄位缺少 raise、(b) `category` 屬白名單、(c) `expected_ic_sign` 屬 `{+,-,?}`
- [x] 1.5 跑現有 dashboard backend 測試套件，確認 `DATA_UNAVAILABLE` 新值不破壞既有 enum 列舉與 API 序列化

## 2. 資料源 / Transform registry（research/lib/sources.py）

- [x] 2.1 新建 `research/lib/sources.py`，定義 `SourceSpec` dataclass（`fetcher / status / description / category`）
- [x] 2.2 實作 `SOURCE_REGISTRY` 含 `okx_funding`、`okx_candles`、`bybit_oi` 三個 `available` 項
- [x] 2.3 預先新增 `coinglass_liq`、`glassnode_pub`、`deribit_skew`、`alt_fng`、`okx_orderbook` 等 5 個 `unavailable` 條目（為 Change 2 鋪路；不必含 fetcher）
- [x] 2.4 實作 `TRANSFORM_REGISTRY` 含 `raw / z_30d / z_90d / pct_change_24h / ma_diff_7d_30d`
- [x] 2.5 新增單元測試 `research/tests/test_sources_registry.py`：(a) registry 全可被 lookup、(b) `available` 條目之 fetcher 為 callable、(c) `unavailable` 條目之 fetcher 為 None、(d) 每個 transform 對 100-row 隨機序列輸出長度等於輸入

## 3. Swarm preset（crypto_factor_lab.yaml）

- [x] 3.1 新建 `agent/src/swarm/presets/crypto_factor_lab.yaml`，定義三個 agent：`factor_proposer / factor_critic / output_formatter`
- [x] 3.2 為每個 agent 撰寫繁中描述的 system_prompt；`factor_proposer` 強調經濟邏輯 + 已驗證 funding 反向訊號之 prior（見 smoke_test_findings 記憶）；`factor_critic` 檢查公式可實作性與資料源是否在 available 清單
- [x] 3.3 `output_formatter` system_prompt 末段附 `FactorCandidate` JSON Schema 範例，並強制 final report 以 ` ```json ` 區塊輸出陣列
- [x] 3.4 宣告變數：`target_universe / signal_categories / horizons_h / available_sources / available_transforms`
- [x] 3.5 在 `agent/src/swarm/presets/` 開 PR 前先用 `vibe-trading --swarm-list` 與 `--swarm-show crypto_factor_lab` 驗證 preset 載入成功
- [x] 3.6 若 review 否決動 `agent/`，把 preset 搬到 `research/presets/crypto_factor_lab.yaml`，並改 stage 0 呼叫為 `vibe-trading --swarm-run-from-file <path>`（驗證 CLI 已支援；若無，回 design.md 加備案實作）

## 4. Stage 0 runner（research/pipeline/stage0_discovery.py）

- [x] 4.1 新建檔案，採與 `stage1_factors.py` 相同的 path bootstrap 與 thin shell 模式
- [x] 4.2 實作 pure-logic helpers：`parse_candidates_json(stdout) -> list[FactorCandidate]`、`filter_invalid_candidates(cands, available_sources, available_transforms) -> list`、`verify_outputs(symbols, manifests_dir) -> list[CheckResult]`、`compute_exit_code(results) -> int`
- [x] 4.3 實作快取邏輯 `cache_hit(manifests_dir, sym, cache_days) -> bool`，根據 `generated_at` 比較
- [x] 4.4 實作 `run_swarm(vars_dict) -> str`（仿 stage 2 的 subprocess 寫法；timeout=1200s）
- [x] 4.5 實作 retry 流程：解析失敗時對 swarm 重 prompt 一次（附「請嚴格輸出 JSON」追加指示）
- [x] 4.6 失敗時寫 `candidates_<sym>.failed.json` 並 print 大紅警告
- [x] 4.7 main() 採 stage 1 verify+exit 模式；新增 CLI flag `--force` 與 env `RESEARCH_FORCE_DISCOVERY`
- [x] 4.8 在 `research_config.yaml` 新增 `discovery_cache_days: 7` 欄位，於 `pipeline/config.py` ResearchConfig 模型加同名欄位（預設 7）

## 5. Stage 1 改造（research/factor_extended.py）

- [x] 5.1 抽出 legacy 路徑為獨立函式 `_run_symbol_legacy(sym, cfg, manifests_dir)`，保留現行硬編 3 因子邏輯
- [x] 5.2 實作 `_load_candidates(manifests_dir, sym) -> CandidatesManifest | None`，找不到 candidates JSON 回 None
- [x] 5.3 實作 `_compute_candidate_series(cand, candles, funding, oi_hist) -> pd.Series`，依 `data_source` dispatch、再套 `TRANSFORM_REGISTRY[cand.transform]`
- [x] 5.4 實作 `_run_symbol_dynamic(sym, cfg, manifests_dir, candidates)`：對每個 candidate 算 series、`add_forward_returns`、`evaluate_factor`、組 `FactorEntry` 寫 manifest
- [x] 5.5 改造 `run_symbol`：(a) 讀 env `RESEARCH_LEGACY_FACTORS`、(b) load candidates、(c) 依 design.md D5 的決策表 dispatch legacy 或 dynamic 路徑
- [x] 5.6 dynamic 模式仍呼 `factor_regime.main()` 做 cross-regime 補強（factor name 改動，regime 模組已用 manifest 之 factor 列表，應自動 follow，但需測試）
- [x] 5.7 print 路徑訊息：`[stage1] btc: DYNAMIC mode (N candidates)` 或 `[stage1] btc: LEGACY mode (reason)`

## 6. 測試擴充

- [x] 6.1 新增 `research/tests/test_stage0_discovery.py`：(a) `parse_candidates_json` 對良好 / 缺欄位 / 多餘空白等 stdout 之容錯、(b) `filter_invalid_candidates` 過濾 unavailable source / 未知 transform、(c) `cache_hit` 邊界（剛好 7 天、7 天 +1 秒）、(d) `compute_exit_code` 結果集對應
- [x] 6.2 新增 `research/tests/test_factor_extended_dynamic.py`：(a) 缺 candidates 走 legacy、(b) candidates 含 5 個因子產出 5 個 FactorEntry、(c) `RESEARCH_LEGACY_FACTORS=1` 強制 legacy、(d) `RESEARCH_LEGACY_FACTORS=0` 且 candidates 缺則 raise
- [x] 6.3 更新既有 `research/tests/test_factor_extended.py`：把測試樁裡的 `for factor in HARDCODED_LIST` 改為「明確走 legacy 路徑」
- [x] 6.4 新增整合測試 `research/tests/test_stage0_to_stage1_integration.py`（mocked swarm subprocess）：stage 0 寫 candidates → stage 1 讀且產出 valid manifest
- [x] 6.5 跑全套 `pytest research/tests` 與 `pytest dashboard/server/tests`，全綠

## 7. 文件 / 流程記錄

- [x] 7.1 在 `research/README.md`（若存在）或新建 `research/PIPELINE.md` 補一節「Stage 0 因子探索」說明用法、快取、legacy fallback
- [x] 7.2 更新 `pipeline/run_all.py`（若存在；若無則在本變更不建）讓全 pipeline 順序為 `stage0 → stage1 → ... → stage5`
- [x] 7.3 在 `memory/MEMORY.md` 加一行指向本變更的 ADR 訊息（用 update-config skill 或手工）

## 8. 收尾驗證

- [x] 8.1 本機跑 `python -m research.pipeline.stage0_discovery`，確認 ETH symbol 產出 `candidates_eth.json` 且 schema 合法
- [x] 8.2 本機跑 `python -m research.pipeline.stage1_factors`，確認 `factor_eth.json` 之 `factors` 數量等於 candidates 數量
- [x] 8.3 設 `RESEARCH_LEGACY_FACTORS=1` 跑 stage 1，確認回到硬編 3 因子模式
- [x] 8.4 跑既有 stage 2（不動），確認下游 `select_usable_factors` 仍能 work；若全 reject，stage 2 raise 是預期行為（屬下變更處理）
- [x] 8.5 用 superpowers:verification-before-completion skill 走完成清單再宣告完成
- [x] 8.6 用 `openspec validate add-factor-discovery-stage0 --strict` 驗證 change 結構合法
