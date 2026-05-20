## ADDED Requirements

### Requirement: 策略資料 API
後端MUST提供 REST 端點，回傳策略清單與單策略完整 manifest 的 JSON。

#### Scenario: 取策略清單
- **WHEN** 前端請求 `GET /api/strategies`
- **THEN** 回傳所有策略的比較表欄位（Tier 1 指標、gate、幣種）

#### Scenario: 取單策略 manifest
- **WHEN** 前端請求 `GET /api/strategies/{id}`
- **THEN** 回傳該策略完整 manifest JSON

#### Scenario: 策略不存在
- **WHEN** 請求的 `{id}` 無對應 manifest
- **THEN** 回傳 HTTP 404

### Requirement: 時序資料 API
後端MUST能把 run 目錄的 `equity.csv`、`trades.csv` 解析成 JSON 回傳。

#### Scenario: 取淨值曲線
- **WHEN** 前端請求 `GET /api/strategies/{id}/equity?run=<run>`
- **THEN** 回傳指定 run 的 equity 時序 JSON

### Requirement: 階段產出 API
後端MUST提供因子分析、regime、selection 的端點，並能原樣回傳白名單內的 markdown 附件。

#### Scenario: 取因子分析
- **WHEN** 前端請求 `GET /api/factor-analysis?symbol=<symbol>`
- **THEN** 回傳該幣種的 factor manifest

#### Scenario: markdown 附件白名單
- **WHEN** 請求 `GET /api/reports?path=<path>` 且 path 不在 `research/` 白名單內
- **THEN** 回傳 HTTP 403，不讀取該檔

### Requirement: 後端只讀不算
後端MUST只做讀檔、解析、回傳；不得跑回測、不得呼叫 LLM。重運算在 CLI 階段完成。

#### Scenario: 無重運算
- **WHEN** 後端處理任何請求
- **THEN** 不啟動回測引擎、不呼叫任何 LLM API

### Requirement: 可設定的 repo 根路徑
後端掃描 `research/`、`runs/` 的根路徑MUST可由環境變數設定，以支援 Linux 部署。

#### Scenario: 容器內路徑
- **WHEN** 後端在 Docker 容器執行且設定根路徑環境變數
- **THEN** 後端依該路徑掃描掛載進來的 `research/`、`runs/`
