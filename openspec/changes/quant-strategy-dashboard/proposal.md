## Why

使用者依 `alpha-workflow.md` 用 CLI 跑加密永續合約 alpha 策略發掘流程（階段 1~5），產出散落在 `research/`、`runs/` 的 markdown、yaml、csv，缺一個地方收斂成決策畫面。同時現況的階段串接很鬆散 —— handoff 靠把 prose markdown 貼進 LLM prompt。需要：(1) 把階段 1~5 改成結構化資料管線，(2) 一個 dashboard 撐住 GO/NO-GO 決策並主動指出回測在哪裡可能騙人。

完整設計見 `docs/superpowers/specs/2026-05-20-quant-trading-dashboard-design.md`（該檔在 gitignore 的 `docs/` 下，故設計內容納入本 change 的 `design.md` 使其被追蹤）。

## What Changes

- 新增 `research/` 階段 I/O 管線：`research_config.yaml`（種子輸入）、`research/pipeline/` 六個 stage runner、`emit_manifest.py`、`strategy_runs.json`。每階段讀上游結構化 JSON、寫下游結構化 JSON。
- 新增 `dashboard/server/`：薄 FastAPI，讀 `research/manifests/`、`runs/`、`runs/testnet/`，吐 REST JSON。
- 新增 `dashboard/web/`：React viewer —— 策略比較表、單策略證據鏈、因子分析、面板分 Tier、GO/NO-GO 紅綠燈。
- 新增 testnet 監控：讀 testnet 產出做 live vs backtest 對照；策略 promotion 軟擋流程。
- 新增 `dashboard/trader/`（v1.5）：直接串 Bybit testnet 依策略訊號下單，含 kill switch。
- 新增 `dashboard/docker-compose.yml`：dashboard 獨立部署，與 Vibe-Trading 解耦。
- **約束**：嚴禁修改 `agent/`、`frontend/` 等 Vibe-Trading 本體；只新增 `dashboard/`、`research/`。呼叫 Vibe-Trading CLI / swarm 為「使用」非「修改」，允許。

## Capabilities

### New Capabilities
- `research-pipeline`: 階段 1~5 結構化 I/O 契約 —— 各 stage runner 讀上游 JSON、呼叫 Vibe-Trading（或 local Python）、寫下游 handoff JSON，並組合策略 manifest。
- `dashboard-backend`: 薄 FastAPI server，掃描解析 research/runs 產出，提供 REST API 給前端。
- `dashboard-viewer`: React 純 viewer —— 多幣種策略比較、單策略證據鏈、面板分 Tier、紅旗、可重現戳記。
- `testnet-monitoring`: 策略 promotion 軟擋決策流程，與 testnet live vs backtest 監控對照（v1）。
- `testnet-execution`: dashboard 直接串 Bybit testnet 自動下單的 trader，含啟停控制與 kill switch（v1.5）。

### Modified Capabilities
<!-- 無。openspec/specs/ 目前無既有 spec，全為新增。 -->

## Impact

- 新增目錄：`dashboard/`（server / web / trader / data / docker 設定）、`research/pipeline/`、`research/manifests/`。
- 新增 `research/` 檔：`research_config.yaml`、`emit_manifest.py`、`strategy_runs.json`。
- 修改 `research/` 既有腳本：`factor_extended.py`（讀 config、輸出 JSON、修 Windows 寫死路徑）、`setup_*.py`（讀 config）。
- 採納 `my-research` 分支的 `research/lib/`。
- 呼叫（不修改）Vibe-Trading：`vibe-trading --swarm-run`、`vibe-trading backtest-diagnose`、`python -m backtest.runner`。
- 零修改 `agent/`、`frontend/`。
- 外部依賴：v1.5 trader 需 Bybit testnet API key（後端 env / docker secret，不入版控）。
