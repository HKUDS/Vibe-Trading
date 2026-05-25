## Why

現有 `research/` pipeline 的階段 1（`factor_extended.py`）把要驗證的因子寫死成三個：`funding_rate`、`oi_change_24h`、`fng`。每次想擴新訊號（例如基差、跨所 funding 價差、OI/funding divergence）都得改 Python 原始碼，無法讓 swarm（多 agent 團隊）動態提案因子；同時 stage 2 已用 swarm 生策略，但因子層仍是人工硬編，造成「下游 AI 化、上游石化」的不對稱。

本變更新增一個前置「因子探索」階段（stage 0），用 swarm 在限定範圍內（funding / basis / OI 三類）產生**結構化候選因子規格 JSON**，並把 stage 1 從寫死改為「讀 candidates → 動態驗證」。先在窄範圍跑通流程，後續變更（Change 2/3）才擴資料源與嚴謹度。

## What Changes

- 新增 `agent/src/swarm/presets/crypto_factor_lab.yaml`：crypto 原生的因子探索 preset，要求 swarm 以**結構化 JSON 格式**輸出候選因子規格（範圍限 funding / basis / OI 三類，避開現階段沒 fetcher 的資料源）。
- 新增 `research/pipeline/stage0_discovery.py`：呼叫上述 preset → 解析 stdout 中的 JSON 區塊 → 寫 `research/manifests/candidates_<symbol>.json`。失敗有快取與重試。
- 新增 `dashboard/server/schemas.py` 內的 `FactorCandidate` 與 `CandidatesManifest` Pydantic 模型，作為 stage 0 → stage 1 的契約。
- **BREAKING**（內部）：重構 `research/factor_extended.py` —— 不再硬編三個因子名，改為讀 `candidates_<symbol>.json`，對每個候選查 `research/lib/sources.py` registry 並決定能否取資料。資料不存在的候選 verdict 設為 `data_unavailable`（schema 需新增此 enum 值）。
- 新增 `research/lib/sources.py`：資料源 → fetcher 映射 registry，僅實作目前已有的三個來源（OKX funding、Bybit OI、OKX candles），其餘標記為 `unavailable`。
- 新增 `research_config.yaml` 欄位 `discovery_cache_days`（預設 7）：candidates JSON 在快取期內 stage 0 跳過 swarm。
- 不動 stage 2-5：stage 2 的 `select_usable_factors` 已依 verdict 過濾，`data_unavailable` 與 `reject` 同樣會被排除，無需改動。

## Capabilities

### New Capabilities
- `factor-discovery`: 用 swarm 在限定訊號範圍內動態提案候選因子、輸出結構化 JSON 規格、供 stage 1 動態驗證；含 candidates manifest schema、stage 0 runner、preset 結構契約、快取機制、資料源 registry。

### Modified Capabilities
<!-- 無。`research-pipeline` capability 由 quant-strategy-dashboard change 引入但尚未 archive 至 openspec/specs/；該 change 本身的 stage 1 行為定義為「寫死三因子」，本變更新增 stage 0 並重構 stage 1 的因子來源邏輯。待 quant-strategy-dashboard archive 後，下一個變更應補一份對 `research-pipeline` 的 delta 描述新的 stage 1 動態行為。目前以新 capability 收斂。 -->

## Impact

- 新增檔案：
  - `agent/src/swarm/presets/crypto_factor_lab.yaml`（新 preset）
  - `research/pipeline/stage0_discovery.py`（新 runner）
  - `research/lib/sources.py`（資料源 registry）
  - `openspec/changes/add-factor-discovery-stage0/specs/factor-discovery/spec.md`
- 修改檔案：
  - `research/factor_extended.py`：從硬編 3 因子改為讀 candidates 動態驗證
  - `research_config.yaml`：新增 `discovery_cache_days` 欄位
  - `dashboard/server/schemas.py`：新增 `FactorCandidate`、`CandidatesManifest`、`FactorVerdict.DATA_UNAVAILABLE`
- 修改既有測試：
  - `research/tests/test_factor_extended.py`：新增 candidates 讀取與 data_unavailable verdict 的測試
- Vibe-Trading 約束：本變更需新增 preset 於 `agent/src/swarm/presets/`，屬於該目錄的「資料設定檔」非邏輯改動，與 quant-strategy-dashboard 的「禁改 agent/ 邏輯」原則相容。若 review 認定 preset 也算修改 `agent/`，備案是把 preset 放 `research/presets/` 並在 stage 0 用 `--preset-path` 參數注入（vibe-trading CLI 已支援）。
- 成本：每次 stage 0 跑 swarm ~ $1-5 OpenRouter 額度；`discovery_cache_days=7` 把多數 pipeline run 收斂到快取讀取，零 LLM 成本。
- 不影響：stage 2-5、dashboard backend / web、testnet 模組。
