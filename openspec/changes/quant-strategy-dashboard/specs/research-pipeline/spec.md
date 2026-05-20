## ADDED Requirements

### Requirement: 種子設定檔
管線 MUST 從單一 `research/research_config.yaml` 讀取種子輸入（`symbols` 清單、`period`、`interval`、`data_source`、`engine`、`fees`、`horizons_h`），不得在腳本內寫死。

#### Scenario: 換研究幣種
- **WHEN** 使用者修改 `research_config.yaml` 的 `symbols`
- **THEN** 後續所有 stage runner 使用新幣種，不需改任何 `.py` 原始碼

#### Scenario: 多幣種逐一跑
- **WHEN** `symbols` 含多個幣種
- **THEN** 管線對每個幣種各跑一輪，產出檔名與 run 目錄帶幣種前綴（如 `btc_`、`eth_`）互不覆蓋

### Requirement: 階段結構化 I/O 契約
階段 1~5 每個 stage runner MUST 讀上游結構化 JSON 作為輸入、寫下游結構化 JSON 作為輸出。階段間 MUST NOT 僅靠 prose markdown 傳遞決策資料。

#### Scenario: 階段 2 讀階段 1 輸出
- **WHEN** 階段 2 策略產生 runner 啟動
- **THEN** 它讀取 `manifests/factor_<symbol>.json`，只採用 `verdict` 不為 `reject` 的因子

#### Scenario: LLM 階段注入上游資料
- **WHEN** 階段 2、3-診斷、4 呼叫 LLM
- **THEN** 上游 JSON 內容注入 prompt 當決策 context，而非要求 LLM 自行讀檔

### Requirement: 階段 1 因子分析輸出
階段 1 MUST 以純 local Python 計算各因子 IC/IR，輸出 `manifests/factor_<symbol>.json`，含 `ic_by_horizon`、`ir`、`sample_size`、`cross_regime_ic`、`stability`、`verdict`。

#### Scenario: 因子裁定
- **WHEN** 某因子 |IC| ≥ 0.10
- **THEN** 其 `verdict` 為 `single_use`；0.05 ≤ |IC| < 0.10 為 `ensemble_only`；|IC| < 0.05 為 `reject`

#### Scenario: 未做 cross-regime 驗證
- **WHEN** cross-regime IC 尚未計算
- **THEN** `cross_regime_ic` 與 `stability` 填 `null`，不阻擋管線

### Requirement: 診斷反饋行動
階段 3 診斷 MUST 輸出 `diagnosis.json`，含 `recommended_action`，值為 `proceed`、`back_to_stage_2` 或 `back_to_stage_4`。

#### Scenario: 診斷建議重設計
- **WHEN** 診斷判定策略需重新設計
- **THEN** `recommended_action` 為 `back_to_stage_2`

### Requirement: 策略 manifest 組合
`emit_manifest.py` MUST 依 `strategy_runs.json` 對應表，聚合一個策略的多個 run 目錄 metrics 與各階段 handoff JSON，組合 `manifests/<strategy_id>/manifest.json` 並計算 `gate`。

#### Scenario: 聚合多 run
- **WHEN** 一個策略對應 base / regime / stress / oos 多個 run 目錄
- **THEN** manifest 的 `backtest` 區塊正確聚合各 run，並於每區塊標註 `source_run`

#### Scenario: 門檻與紅旗計算
- **WHEN** 組合 manifest
- **THEN** 依 alpha-workflow 門檻計算 `gate.thresholds` 的 pass/fail、`overall_pass`、`fatal_fail`，並推導 `red_flags`

### Requirement: 不修改 Vibe-Trading 本體
管線可呼叫 Vibe-Trading CLI / swarm / 回測引擎，但 MUST NOT 修改 `agent/`、`frontend/` 任何檔案。

#### Scenario: 呼叫而非修改
- **WHEN** 階段 2、3、4 需要 Vibe-Trading 功能
- **THEN** 透過 `vibe-trading` CLI 或 `python -m backtest.runner` 呼叫，新增碼僅落在 `research/`
