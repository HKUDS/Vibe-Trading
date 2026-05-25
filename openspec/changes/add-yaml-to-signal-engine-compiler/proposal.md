## Why

Stage 2 swarm 目前只產 `strategy_<id>.yaml`（描述性規格）與一段 markdown rationale；**沒有產出 `signal_engine.py`**（可執行交易碼）。Stage 3 backtest 找不到 `research/strategies/code/<id>/signal_engine.py` 時，會用 `build_stub_signal_engine()` 落到全 0 訊號的 stub，導致每個策略 `trade_count=0`、`recommended_action="back_to_stage_2"`，後面 Stage 4 / 5 全部被閘掉，pipeline 走死路。實測 2026-05-24 跑 ETH 端到端時，唯一能跑出真實回測的辦法是手寫 `research/strategies/code/eth_s1_multi_factor_consensus/signal_engine.py`，無法 scale 到多策略 / 多 symbol。

此 change 加 Stage 2b（YAML → signal_engine.py 編譯器）把 YAML 的 entry/exit/indicator/smoothing/persistence 規格機械式翻成 pandas-based Python class，產出 AST-safe code，自動填入 `research/strategies/code/<id>/`。同步加 Stage 1 dump 因子時間序列到 parquet，讓 signal_engine 直接讀檔不重新 fetch OKX。

## What Changes

- **新增 Stage 2b runner** `research/pipeline/stage2b_compile_signal.py`：純 Python，讀 `strategy_<id>.yaml` → 寫 `research/strategies/code/<id>/signal_engine.py`。
- **新增 YAML → code 編譯器模組** `research/lib/signal_compiler.py`：定義受限 DSL（indicator / entry / exit / sizing），用 Jinja 樣板生成 pandas 程式碼。
- **新增因子時間序列持久化**：Stage 1 (`research/factor_extended.py`) 新增 dump `research/manifests/factor_values_<sym>.parquet`（hourly index × 因子欄位），讓 signal_engine 透過 helper `lib.factor_io.load_factor_values(sym)` 直接讀檔。
- **限制 YAML schema**：新增 `dashboard/server/schemas.py` 的 `StrategySpec` Pydantic 模型，明訂可用 `indicator.source` / `entry_*.conditions` DSL 詞彙；Stage 2 寫 YAML 後 SHALL 通過 `StrategySpec` 驗證，否則 raise。
- **更新 pipeline 串接**：`research/PIPELINE.md` 加 Stage 2b 步驟；run-all 順序為 `0 → 1 → 2 → 2b → 2.5 → 3 → 3-diagnose → 4 → 3 (re-verify) → 5`。
- **保留手寫 escape hatch**：若 `research/strategies/code/<id>/signal_engine.py` 已存在且檔內含 `# manual: do-not-overwrite` 標記，stage2b SHALL 跳過該策略，沿用手寫版本。
- 不引入 LLM 寫程式碼（保持純 templater，避免 AST 驗證失敗 + token 開銷）。
- **BREAKING**：Stage 2 寫出的 YAML 若用了 `StrategySpec` 詞彙以外的 source/condition 關鍵字，Stage 2b 會 raise，現有 `strategy_S1-S4.yaml`（legacy）必須先升級或加入 escape hatch。

## Capabilities

### New Capabilities
- `signal-compilation`: YAML 策略規格的受限 DSL 與翻譯到 pandas-based `SignalEngine` Python class 的契約。涵蓋 indicator 來源、entry/exit conditions、smoothing、persistence、time-stop、TP/SL、signal invalidation。
- `factor-values-io`: Stage 1 之後將因子 hourly 時間序列以 parquet 持久化的契約（schema、檔名、讀寫 helper），讓下游回測 / signal_engine 直接讀檔不重新 fetch 原始資料。

### Modified Capabilities
- `factor-discovery`: 新增 stage1 dump factor parquet 的後置步驟，候選因子 schema 不變。

## Impact

- **新增檔案**：`research/pipeline/stage2b_compile_signal.py`、`research/lib/signal_compiler.py`、`research/lib/factor_io.py`、`research/strategies/code/_templates/signal_engine.py.j2`、相關 tests。
- **修改檔案**：`research/factor_extended.py`（dump parquet）、`research/PIPELINE.md`、`dashboard/server/schemas.py`（加 `StrategySpec`）、`research/strategies/strategy_S1-S4.yaml`（升級或加 manual 標記）。
- **影響流程**：Stage 2 → 2b → 3 順序新增 stage2b；現有 stage3 不需改（仍從 `code/<id>/` 拷貝 signal_engine）。
- **效能**：parquet 讀取替代 OKX HTTP fetch，single backtest 從 ~10s 降至 <1s（factor 階段）。
- **依賴**：新增 `pyarrow`（parquet 後端）、`jinja2`（已在 fastapi 鏈中）。
- **資安**：生成的 `signal_engine.py` 必須通過 `agent/backtest/runner.py:_validate_signal_engine_source` AST 驗證，templater 須杜絕 import-time executable statement。
- **退場路徑**：手寫 escape hatch（`# manual: do-not-overwrite`）讓研究人員可繞過編譯器；本 change 不刪 `build_stub_signal_engine`，stage3 仍可在無 yaml 情境 fallback。
