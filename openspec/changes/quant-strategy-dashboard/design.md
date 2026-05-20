## Context

使用者依 `alpha-workflow.md`（加密永續合約 Alpha 策略發掘 9 階段流程）用 CLI 跑階段 1~5，產出散落在 `research/`、`runs/` 的 markdown、yaml、csv。兩個問題：(1) 沒有地方把產出收斂成決策畫面；(2) 階段串接鬆散 —— handoff 靠把 prose markdown 貼進 LLM prompt。

本設計來自 brainstorming 全程（完整版 `docs/superpowers/specs/2026-05-20-quant-trading-dashboard-design.md`，因 `docs/` 在 gitignore，內容納入本檔以受版控）。

**現況關鍵事實（已讀碼確認）：**
- `runs/` 在 repo 根目錄（`setup_stress.py` 用 `ROOT/"runs"`）。
- 一個「策略」對應**多個 run 目錄**（base / 各 regime / `_stress` / oos / sweep），各有 `config.json` + `artifacts/`。
- 因子腳本內部有結構化 `FactorResult` dataclass，markdown 是 render 出來的 → 多吐 JSON 成本低。
- `factor_extended.py` 寫死 `SYMBOL_OKX` 等常數與 Windows 路徑 `C:/Users/cool6/...`。
- Vibe-Trading 已有 `frontend/`（React 19 + Vite）與 `agent/api_server.py`。

**約束（硬性）：** 嚴禁修改 `agent/`、`frontend/` 等 Vibe-Trading 本體；只新增 `dashboard/`、`research/`。呼叫 Vibe-Trading CLI / swarm 為「使用」非「修改」，允許。單機單人、繁體中文介面。

## Goals / Non-Goals

**Goals（v1）：** 階段 1~5 結構化 I/O 管線；多幣種策略比較 viewer；GO/NO-GO 紅綠燈 + 軟擋；策略 promotion + 匯出；testnet 監控（live vs backtest）。
**Goals（v1.5）：** dashboard 直接串 Bybit testnet 自動下單的 trader，含啟停 + kill switch。

**Non-Goals：** 在 dashboard UI 觸發 workflow 階段（driver 模式 → v2）；階段 6 Pine 匯出；階段 8/9 真錢實盤；ML 策略。

dashboard 職責是撐住 GO/NO-GO 決策 + 讓使用者騙自己變難，不是秀過程。每個面板要能斃掉一個策略，否則砍。

## Decisions

### D1：架構 —— 薄後端 + React 前端（方案 A）
瀏覽器不能讀檔案系統，viewer 需後端讀 `research/`、`runs/`。選 `dashboard/server`（FastAPI）+ `dashboard/web`（React）。
- 否決「純靜態網站」：testnet 監控需 live 資料，靜態做不到。
- 否決「擴充 api_server」：違反不改 Vibe-Trading。
- 後端 Python，與 `research/lib/` 同環境；不跑回測、不呼叫 LLM。

### D2：階段 I/O 契約 —— 結構化 JSON handoff
階段 1~5 每階段輸出結構化 JSON，下一階段直接讀。取代「prose md 貼進 prompt」。執行由 `research/pipeline/` 的 CLI runner 推進，dashboard 純觀察。

| 階段 | Vibe-Trading 呼叫 | 讀（上游） | 寫（下游） |
|---|---|---|---|
| 1 因子分析 | 無（`research/lib` local Python） | `research_config` | `manifests/factor_<symbol>.json` |
| 2 策略產生 | `vibe-trading --swarm-run crypto_trading_desk`（gpt-5） | `factor_<symbol>.json` | `strategy_Sn.yaml` + `<id>/generation.json` |
| 2.5 regime | 無（`research/lib/regime.py`） | `factor_<symbol>.json`、價格 | `manifests/regime_<symbol>.json` |
| 3 回測 | `python -m backtest.runner`（Vibe-Trading 引擎） | strategy yaml、regime、config | run `artifacts/*.csv` |
| 3 診斷 | `vibe-trading backtest-diagnose`（gpt-5） | run metrics | `<id>/diagnosis.json` |
| 4 優化 | `vibe-trading --swarm-run quant_strategy_desk`（gpt-5） | strategy yaml、metrics、diagnosis | `<id>/optimization.json` |
| 5 選擇 | 無（純 Python 算分） | 全通過策略 manifest | `manifests/selection.json` |

每 stage runner = 薄包裝：讀上游 JSON → 組命令/prompt（注入 JSON）→ 呼叫 Vibe-Trading 或 local Python → 寫下游 JSON。LLM 階段把上游 JSON 注入 prompt 當決策 context。`diagnosis.json` 帶 `recommended_action`（`proceed`/`back_to_stage_2`/`back_to_stage_4`）使 feedback loop 顯式化。

### D3：manifest 漸進式 + 三種 schema
manifest 為階段交接契約，隨階段完成漸進寫入；非結尾一次 aggregate。`emit_manifest.py` 組合 `<id>/manifest.json` 並算 gate。

- **factor manifest** `manifests/factor_<symbol>.json`：每因子 `ic_by_horizon`、`ir`、`sample_size`、`cross_regime_ic`、`stability`（regime_stable/conditional）、`verdict`（single_use ≥0.10 / ensemble_only / reject）。`cross_regime_ic`/`stability` 現碼未算，需新增分 regime IC；未做時填 null + dashboard 顯示警示。
- **策略 manifest** `manifests/<strategy_id>/manifest.json`：`spec` / `generation` / `reproducibility` / `backtest`（in_sample / oos / walk_forward / monte_carlo / benchmark / by_regime / cost_stress）/ `optimization` / `diagnosis` / `gate`。各區塊標 `source_run` 來源。
- **testnet 產出** `runs/testnet/<id>/testnet_status.json`：`live` / `vs_backtest` / `killswitch` / `alerts`。
- **gate**：門檻來自 alpha-workflow §3（Sharpe≥1.5、MaxDD≤10%、Trades≥100、PF≥1.5、WF 各窗≥1.0、MC 95% CI 不跨 0）。`fatal:true` 兩項硬擋：`oos_sharpe_positive`、`alpha_not_fee_illusion`。`red_flags` 自動推導：`oos_sharpe_far_below_is`、`underperforms_hodl`、`too_few_trades`、`alpha_is_fee_illusion`、`overfit_suspect`、`regime_conditional`。

### D4：策略 ↔ run 對應表 `research/strategy_runs.json`
因一策略對應多 run 且現有 run 名（`ensemble_bull`）無策略前綴，需明確對應表，由使用者維護：`{strategy_id: {symbol, spec_yaml, base_run, regime_runs{}, stress_runs{}, oos_runs[], sweep_run}}`。多幣種時 run 目錄與 `strategy_id` 帶幣種前綴（`btc_`/`eth_`）防撞。

### D5：`research/research_config.yaml` 種子設定
只放管線種子輸入（`symbols` 清單、`period`、`interval`、`fees`、`engine`、`horizons_h`），不放階段間決策資料（走 handoff）。`symbols` 為清單，管線對每幣跑一輪。順帶終結 alpha-workflow 抱怨的 config mismatch 雷。

### D6：面板分 Tier
- Tier 1（決策關鍵，預設展開）：OOS/WF vs IS 並排、淨值+回撤疊 HODL、超額 vs HODL、成本壓力 3×、分 regime 表、GO/NO-GO checklist、成交明細、紅旗橫幅。
- Tier 2（audit，收合）：策略 YAML、因子 IC/IR 表、診斷報告、可重現戳記。
- Tier 3（雜訊，深層）：策略生成原因（LLM 散文 —— 不是證據，是事後合理化）、swarm 對話流水。
- IA：首頁策略比較表（多幣種篩選）+ 側邊 pipeline 進度條；單策略 EvidenceChain 對應 D2 handoff 鏈。

### D7：promotion 軟擋
門檻沒過 → 標紅列 fail 項，勾「我知道風險」+ 填 override 理由可 override；致命項（OOS Sharpe<0、alpha 被費吃）硬擋。promotion 決策寫 dashboard 自有 `data/state.json`，不回寫 research/。

### D8：testnet 監控（v1）/ 執行（v1.5）拆分
v1 只監控（讀 `runs/testnet/`）；v1.5 加 `dashboard/trader/`（signal/broker/loop/killswitch），一 promoted 策略一 process，server `supervisor.py` 啟停。

### D9：Docker 獨立部署
`dashboard/docker-compose.yml` 自包含（dashboard-server / dashboard-web / dashboard-trader），掛 host `research/`+`runs/` read-only，與 Vibe-Trading 的 compose 完全解耦，可單獨上 Linux。

### D10：複用 `frontend/` 元件（複製）
從 `frontend/src/` 複製圖表/卡片/lib/設定檔到 `dashboard/web/`，複製非引用，確保不依賴、不影響原檔。

## Risks / Trade-offs

- [現有 `research/` 腳本只 print 不落檔，emitter 缺欄位] → 實作前逐一檢查 `setup_*.py`，缺的補 dump csv/json。
- [`factor_extended.py` 寫死 Windows 路徑，Linux 部署會壞] → 修為相對路徑、改讀 `research_config.yaml`。
- [LLM 階段把上游 JSON 注入 prompt 可能 token 過量] → 視量決定注入完整 JSON 或摘要 digest。
- [v1.5 trader 持有 Bybit API key，上公開伺服器有外洩風險] → key 走後端 env / docker secret，不入 image、不入版控；對外 port 加認證；kill switch 必備。
- [一策略對應多 run，`strategy_runs.json` 需人工維護易錯] → emitter 對缺漏 run 給明確錯誤；schema 驗證。
- [WS 之間有依賴鏈拖慢進度] → manifest schema 為契約，先鎖 schema，WS2/WS3 用 sample manifest 並行開發。

## Migration Plan

無資料遷移（全新增）。交付分兩棒：v1（WS1 research pipeline + WS2 後端 + WS3 前端）→ v1.5（WS4 trader）。回滾 = 刪 `dashboard/` 與新增的 `research/` 檔；既有 `research/` 腳本的修改以 git 還原。部署為 `dashboard/docker-compose.yml`，獨立於 Vibe-Trading 容器。

## Open Questions

- 既有 `factor_extended.py` / `setup_*.py` / `regime_validate.py` 收進 `pipeline/` stage runner 的具體包裝方式 —— 盡量包裝不重寫，實作時逐一確認。
- `agent/backtest` runner 的 `metrics.csv` 欄名 —— 實作前讀 `agent/backtest/metrics.py` 對齊 manifest 欄位。
- LLM 階段 prompt 注入上游 JSON 的格式（完整 vs digest）—— 依 token 量定。
- Bybit testnet ccxt 介面細節（下單參數、rate limit）—— v1.5 實作時驗證。
