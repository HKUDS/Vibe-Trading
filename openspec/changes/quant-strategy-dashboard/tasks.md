# Tasks — quant-strategy-dashboard

Workstream：WS0 前置／契約 · WS1 research pipeline · WS2 後端 · WS3 前端 · 部署 · WS4 v1.5 trader。
v1 = 群組 1~5；v1.5 = 群組 6。契約（1.3）一鎖定，WS1／WS2／WS3 可拿 sample manifest 並行。

## 1. 前置與契約（WS0）

- [ ] 1.1 採納 `my-research` 分支的 `research/lib/`（ccxt_data、factor_metrics、okx_data、regime、report、sentiment）到本分支
- [ ] 1.2 建立目錄骨架：`dashboard/{server,web,trader,data,data/exports}`、`research/{pipeline,manifests}`
- [ ] 1.3 鎖定 manifest schema：`dashboard/server/schemas.py`（factor / 策略 / testnet pydantic models），附 sample manifest 檔供 WS2/WS3 並行開發
- [ ] 1.4 `.gitignore` 補 `dashboard/data/`、`dashboard/server/.env`、exports；確認 `agent/`、`frontend/` 不被本 change 觸碰

## 2. Research pipeline（WS1）

- [ ] 2.1 建 `research/research_config.yaml`（symbols 清單、period、interval、fees、engine、horizons_h）
- [ ] 2.2 重構 `factor_extended.py`：改讀 `research_config.yaml`、修掉寫死的 Windows 路徑、輸出 `manifests/factor_<symbol>.json`
- [ ] 2.3 新增 `factor_regime.py`：分 regime 算 IC → 填 `cross_regime_ic`、`stability`、`verdict`
- [ ] 2.4 建 `research/strategy_runs.json` 對應表（策略 ↔ base/regime/stress/oos/sweep run）
- [ ] 2.5 `pipeline/stage1_factors.py`：包裝階段 1 因子分析 runner
- [ ] 2.6 `pipeline/stage2_strategies.py`：讀 factor manifest、呼叫 `crypto_trading_desk` swarm（注入 JSON）、輸出 strategy yaml + `generation.json`
- [ ] 2.7 `pipeline/stage2_5_regime.py`：regime detector + 輸出 `regime_<symbol>.json`
- [ ] 2.8 `pipeline/stage3_backtest.py`：建 run dir/config、呼叫 `python -m backtest.runner`
- [ ] 2.9 階段 3 診斷：呼叫 `vibe-trading backtest-diagnose`、輸出 `diagnosis.json`（含 `recommended_action`）
- [ ] 2.10 `pipeline/stage4_optimize.py`：呼叫 `quant_strategy_desk`、輸出 `optimization.json`
- [ ] 2.11 `pipeline/stage5_select.py`：對 manifest 算分、輸出 `selection.json`
- [ ] 2.12 `emit_manifest.py`：依 `strategy_runs.json` 聚合多 run metrics + handoff JSON → 策略 manifest，算 `gate` 與 `red_flags`
- [ ] 2.13 `setup_*.py` 改讀 `research_config.yaml`；補 emitter 需要而目前只 print 的指標 dump

## 3. Dashboard 後端（WS2）

- [ ] 3.1 FastAPI app 骨架 + repo 根路徑 env 設定 + CORS
- [ ] 3.2 `artifacts.py`：掃描 `research/manifests`、`runs`、`runs/testnet`
- [ ] 3.3 `parsers.py`：csv / yaml / markdown 解析
- [ ] 3.4 `GET /api/strategies`、`GET /api/strategies/{id}`（含 404）
- [ ] 3.5 `GET /api/strategies/{id}/equity`、`/trades`（csv → JSON）
- [ ] 3.6 `GET /api/factor-analysis`、`/api/regime`、`/api/selection`
- [ ] 3.7 `GET /api/reports`：markdown 附件白名單（非白名單回 403）
- [ ] 3.8 `GET /api/pipeline`：各策略 pipeline_stage
- [ ] 3.9 `state.py` + `POST/DELETE /api/strategies/{id}/promote`（寫 state.json + 匯出 config）
- [ ] 3.10 `GET /api/testnet`、`GET /api/testnet/{id}`

## 4. Dashboard 前端（WS3）

- [ ] 4.1 Vite + React 專案骨架；從 `frontend/` 複製圖表/卡片/lib/設定檔
- [ ] 4.2 api client + manifest TypeScript 型別
- [ ] 4.3 `Compare.tsx` 首頁：策略比較表 + 幣種篩選器 + `PipelineStrip`
- [ ] 4.4 `StrategyDetail.tsx`：`EvidenceChain` + Tier 1 面板群（OOSvsIS、EquityChart+Benchmark、CostStress、RegimeTable、成交明細）
- [ ] 4.5 `GateChecklist` + `RedFlagBanner`
- [ ] 4.6 Tier 2 收合面板（策略 YAML、因子 IC/IR、診斷報告、可重現戳記）；Tier 3 深層連結
- [ ] 4.7 `FactorReport.tsx`：因子 IC/IR + cross-regime + verdict
- [ ] 4.8 `PromoteDialog`：軟擋（override + 理由）/ 致命項硬擋
- [ ] 4.9 `Testnet.tsx`：live vs backtest 對照（無資料顯示等待態）
- [ ] 4.10 整合：對 sample manifest 與真實 manifest 跑通

## 5. 部署與 v1 驗證

- [ ] 5.1 `Dockerfile.server`、`Dockerfile.web`、`nginx.conf`
- [ ] 5.2 `dashboard/docker-compose.yml`（server + web，掛 host `research/`+`runs/` read-only）
- [ ] 5.3 `dashboard/README.md` 啟動說明（本機 + Docker）
- [ ] 5.4 v1 端到端驗證：對照 design §15 v1 判準 1~8（含「未修改 agent/、frontend/」）

## 6. testnet 執行 trader（WS4，v1.5）

- [ ] 6.1 `trader/signal.py`：與回測 signal engine 同一套訊號邏輯
- [ ] 6.2 `trader/broker.py`：ccxt Bybit testnet 下單／平倉／查部位
- [ ] 6.3 `trader/loop.py`：live 迴圈（抓資料→算訊號→下單→寫 `testnet_status.json`）
- [ ] 6.4 `trader/killswitch.py`：DD 5% 暫停、7% 終止
- [ ] 6.5 `server/supervisor.py` + `POST /api/testnet/{id}/start`、`/stop`
- [ ] 6.6 前端 `Testnet.tsx` 加啟停按鈕 + kill switch 狀態
- [ ] 6.7 `dashboard-trader` 加入 docker-compose（API key 走 env / docker secret）
- [ ] 6.8 v1.5 端到端驗證：對照 design §15 v1.5 判準 9~10
