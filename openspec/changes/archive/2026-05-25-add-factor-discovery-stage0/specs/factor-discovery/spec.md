## ADDED Requirements

### Requirement: 候選因子 schema 契約

系統 SHALL 以 Pydantic 模型 `FactorCandidate` 與 `CandidatesManifest` 作為 stage 0 → stage 1 的結構化資料契約，並 SHALL 將兩個模型定義於 `dashboard/server/schemas.py`，與既有 `FactorManifest` 同檔案以保持 schema 來源單一。

`FactorCandidate` MUST 包含以下欄位：`name`（字串，因子識別名）、`formula`（字串，自然語＋虛擬公式）、`data_source`（字串，對應 `research/lib/sources.py` registry 的 key）、`transform`（字串，對應 `transform_registry` 的 key）、`expected_ic_sign`（`"+"` / `"-"` / `"?"`）、`economic_logic`（字串）、`horizons_h`（int 陣列）、`category`（`"funding"` / `"basis"` / `"oi"`）。

`CandidatesManifest` MUST 包含：`schema_version`（int，預設 1）、`symbol`（字串）、`generated_at`（datetime）、`source_swarm_run`（字串或 null）、`candidates`（`FactorCandidate` 陣列）。

#### Scenario: candidates JSON 通過 schema 驗證
- **WHEN** stage 0 寫入 `research/manifests/candidates_<sym>.json` 後
- **THEN** 該檔 MUST 能以 `CandidatesManifest.model_validate_json(text)` 驗證通過
- **AND** 每個 `FactorCandidate.category` MUST 屬於 `{"funding", "basis", "oi"}`
- **AND** 每個 `FactorCandidate.data_source` MUST 為 `SOURCE_REGISTRY` 中 `status == "available"` 的 key

#### Scenario: schema 缺欄位被拒
- **WHEN** swarm 輸出之 JSON 缺 `economic_logic` 或 `category` 等必要欄位
- **THEN** Pydantic 驗證 MUST raise，stage 0 MUST 進入 retry 流程

### Requirement: 新增 data_unavailable verdict

`FactorVerdict` enum SHALL 新增 `DATA_UNAVAILABLE = "data_unavailable"`，用於標記候選因子之資料源未實作的情境。本變更之 stage 1 路徑 MUST 不產生此 verdict（因 stage 0 已過濾），但 schema 與 dashboard 顯示層 MUST 支援該 enum 值以供 Change 2 後續使用。

#### Scenario: enum 列舉完整
- **WHEN** 任何讀 `FactorManifest` 的程式列舉 `FactorVerdict`
- **THEN** `DATA_UNAVAILABLE` MUST 為合法成員
- **AND** dashboard backend `factors.py` MUST 不因新 enum 值 raise

### Requirement: Stage 0 swarm 探索流程

系統 SHALL 提供 `research/pipeline/stage0_discovery.py` 作為新 pipeline 階段 runner，其 main 函式 MUST 對 `research_config.yaml` 中每個 symbol 執行一次因子探索流程，且 MUST 遵循下列順序：(1) 檢查快取；(2) 呼叫 swarm；(3) 解析 JSON；(4) 驗證 schema；(5) 寫 manifest；(6) verify outputs + 適當 exit code（0 全成功、1 任一失敗）。

stage 0 runner MUST 採與既有 stage1_factors.py 相同的設計模式：thin orchestration shell + 抽離 pure-logic helpers（如 `parse_candidates_json`、`verify_outputs`、`compute_exit_code`、`print_summary`）以供單元測試。

#### Scenario: 全部 symbols 成功
- **WHEN** 對所有 symbols stage 0 都成功產生有效 `candidates_<sym>.json`
- **THEN** runner exit code MUST 為 0
- **AND** stdout MUST 包含每個 symbol 的「candidates: N」與「source_swarm_run: <id>」摘要

#### Scenario: 部分 symbol 失敗
- **WHEN** 任一 symbol 之 swarm 解析失敗且 retry 後仍失敗
- **THEN** runner exit code MUST 為 1
- **AND** 失敗 symbol MUST 同時產生 `candidates_<sym>.failed.json` 紀錄錯誤 stdout 摘要

### Requirement: Swarm preset crypto_factor_lab

系統 SHALL 提供新 swarm preset `crypto_factor_lab`（預設路徑 `agent/src/swarm/presets/crypto_factor_lab.yaml`，備案 `research/presets/crypto_factor_lab.yaml`），其中 MUST 定義至少三個 agent：(1) `factor_proposer` 提案候選因子；(2) `factor_critic` 檢查公式可實作性與經濟邏輯；(3) `output_formatter` 將前述輸出整理為嚴格 JSON。

該 preset MUST 宣告下列變數：`target_universe`（字串，例 `BTC-USDT,ETH-USDT`）、`signal_categories`（字串，預設 `funding,basis,oi`）、`horizons_h`（字串，預設 `[8,24,72,168]`）、`available_sources`（字串，列出 stage 0 注入的合法 `data_source` 清單）、`available_transforms`（字串，列出合法 `transform` 清單）。

`output_formatter` 之 system_prompt MUST 包含 `FactorCandidate` JSON Schema 範例並 MUST 要求 final report 以 ` ```json ` 區塊包覆候選因子陣列。

#### Scenario: preset 載入無誤
- **WHEN** 執行 `vibe-trading --swarm-run crypto_factor_lab '{"target_universe":"BTC-USDT","signal_categories":"funding,basis,oi","horizons_h":"[8,24,72,168]","available_sources":"okx_funding,okx_candles,bybit_oi","available_transforms":"raw,z_30d,z_90d,pct_change_24h,ma_diff_7d_30d"}'`
- **THEN** swarm 運作時 MUST 不因變數缺失 raise
- **AND** swarm 完成後 stdout MUST 至少包含一個合法 ```json fenced code block

#### Scenario: 提案違反 available_sources
- **WHEN** swarm 輸出的某 candidate.data_source 不在 `available_sources` 清單內
- **THEN** stage 0 解析後 MUST 丟棄該 candidate（不寫入 manifest），並於 stdout print 警告

### Requirement: 資料源 registry

系統 SHALL 提供 `research/lib/sources.py`，其中 MUST 定義一個 `SOURCE_REGISTRY: dict[str, SourceSpec]`。`SourceSpec` MUST 為 dataclass，欄位含 `fetcher: Callable | None`、`status: Literal["available", "unavailable"]`、`description: str`、`category: str`（對應 FactorCandidate.category）。

本變更範圍內，registry MUST 至少包含三個 `status="available"` 條目：`okx_funding`（fetcher=`fetch_funding_history`）、`okx_candles`（fetcher=`fetch_candles`）、`bybit_oi`（fetcher=`fetch_oi_history_bybit`）。其他規劃中的來源（如 `coinglass_liq`、`glassnode_pub`、`deribit_skew` 等）MAY 預先以 `status="unavailable"` 形式列入，方便 Change 2 接手。

#### Scenario: 查詢已實作來源
- **WHEN** 呼叫 `SOURCE_REGISTRY["okx_funding"]`
- **THEN** 回傳之 `SourceSpec.status` MUST 等於 `"available"`
- **AND** `SourceSpec.fetcher` MUST 為可呼叫物件且 callable signature 包含 `symbol` 與 `days` 參數

#### Scenario: 查詢未實作來源
- **WHEN** 呼叫 `SOURCE_REGISTRY["coinglass_liq"]`（若已預先列入）
- **THEN** 回傳之 `SourceSpec.status` MUST 等於 `"unavailable"`
- **AND** `SourceSpec.fetcher` MUST 為 None

### Requirement: Transform registry

系統 SHALL 提供 `research/lib/sources.py` 內之 `TRANSFORM_REGISTRY: dict[str, Callable[[pd.Series], pd.Series]]`，本變更範圍內 MUST 至少實作下列五個 transform：`raw`、`z_30d`、`z_90d`、`pct_change_24h`、`ma_diff_7d_30d`。

stage 1 在計算 candidate 因子值時 MUST 透過 `TRANSFORM_REGISTRY[candidate.transform]` 取得轉換函式，不得使用 `eval` / `exec` 或任何字串轉程式碼機制。

#### Scenario: 已知 transform 套用
- **WHEN** stage 1 對 funding rate 序列套用 `TRANSFORM_REGISTRY["z_30d"]`
- **THEN** 回傳序列 MUST 與輸入同 index、同長度
- **AND** 計算邏輯 MUST 為 `(s - rolling_mean(90)) / rolling_std(90)`（30 個 8h funding settlement ≈ 10 天；採 funding 設定的 8h 顆粒度時實作者 SHALL 對齊註解。）

#### Scenario: 未知 transform 拒絕
- **WHEN** candidate.transform 不在 `TRANSFORM_REGISTRY` keys 中
- **THEN** stage 1 MUST raise `ValueError` 而非執行未驗證的 transform

### Requirement: 探索快取機制

系統 SHALL 在 `research_config.yaml` 新增 `discovery_cache_days` 欄位（int，預設 7），stage 0 MUST 遵循下列快取規則：若 `candidates_<sym>.json` 存在且 `(now - generated_at) < discovery_cache_days` 天，則 stage 0 MUST 跳過 swarm 呼叫並直接視該 symbol 為成功；否則 MUST 呼叫 swarm 重新生成。

stage 0 MUST 提供 `--force` flag 或環境變數 `RESEARCH_FORCE_DISCOVERY=1` 強制忽略快取。

#### Scenario: 快取命中跳過 swarm
- **WHEN** `candidates_btc.json` 存在且其 `generated_at` 在 7 天內
- **AND** 不帶 `--force` flag
- **THEN** stage 0 MUST 不呼叫 `vibe-trading --swarm-run`
- **AND** stdout MUST print `[stage0] btc: cache hit, skipping swarm`

#### Scenario: 快取過期重跑
- **WHEN** `candidates_btc.json` 之 `generated_at` 超過 7 天
- **THEN** stage 0 MUST 呼叫 swarm 並覆寫 candidates JSON

#### Scenario: force 旗標強制重跑
- **WHEN** 執行 `python -m research.pipeline.stage0_discovery --force`
- **THEN** 即使快取在期內 stage 0 MUST 呼叫 swarm

### Requirement: Stage 1 改為動態讀取 candidates

系統 SHALL 修改 `research/factor_extended.py` 使其 `run_symbol` 函式不再硬編 `["funding_rate", "oi_change_24h", "fng"]` 三個因子名，改為先讀 `research/manifests/candidates_<sym>.json` 並依候選清單動態計算 IC/IR。每個候選 MUST 經 `SOURCE_REGISTRY[candidate.data_source].fetcher` 取原始序列、再經 `TRANSFORM_REGISTRY[candidate.transform]` 變換、再餵 `evaluate_factor`。

stage 1 MUST 支援 legacy fallback：若環境變數 `RESEARCH_LEGACY_FACTORS=1` 或 candidates JSON 缺失（且 `RESEARCH_LEGACY_FACTORS` 未設為 `0`）→ 退化為原硬編 3 因子模式；其餘情境（candidates 存在且 legacy 未設定）→ 採新模式。

#### Scenario: 新模式正常路徑
- **WHEN** `candidates_btc.json` 存在含 5 個候選因子
- **AND** stage 1 對該 symbol 執行
- **THEN** 產出之 `factor_btc.json` 之 `factors` 陣列長度 MUST 等於 5
- **AND** 每個 factor 之 `name` MUST 與 candidate.name 對齊

#### Scenario: candidates 缺失走 legacy fallback
- **WHEN** `candidates_btc.json` 不存在
- **AND** 環境變數 `RESEARCH_LEGACY_FACTORS` 未設或設為 `1`
- **THEN** stage 1 MUST 以原硬編 3 因子模式執行
- **AND** stdout MUST print 警告 `[stage1] LEGACY MODE: candidates missing for btc, using hardcoded factors`

#### Scenario: 明確要求 legacy
- **WHEN** 環境變數 `RESEARCH_LEGACY_FACTORS=1`
- **THEN** 即使 candidates JSON 存在 stage 1 MUST 走 legacy 模式
- **AND** stdout MUST print `[stage1] LEGACY MODE (forced via env)`

#### Scenario: 明確禁止 legacy 且 candidates 缺
- **WHEN** 環境變數 `RESEARCH_LEGACY_FACTORS=0`
- **AND** candidates JSON 不存在
- **THEN** stage 1 MUST raise `FileNotFoundError` 並終止該 symbol（不影響其他 symbol）

### Requirement: Stage 0 失敗的 fallback 行為

若 stage 0 對某 symbol 完全失敗（swarm 呼叫失敗 / JSON 解析失敗且 retry 失敗 / schema 驗證失敗），系統 MUST 寫入 `research/manifests/candidates_<sym>.failed.json` 紀錄錯誤摘要，stdout MUST print 大紅警告，且 runner exit code MUST 為 1。

下游 stage 1 在偵測到 `.failed.json` 存在且 `.json` 不存在時 MUST 退化為 legacy 模式（不阻塞整條 pipeline）。

#### Scenario: 完全失敗仍允許下游降級
- **WHEN** stage 0 對 btc 失敗，產出 `candidates_btc.failed.json`，未產出 `candidates_btc.json`
- **AND** stage 1 接著執行
- **THEN** stage 1 MUST 對 btc 走 legacy 路徑並完成
- **AND** stage 1 stdout MUST print `[stage1] btc: stage0 failed, using LEGACY factors`
