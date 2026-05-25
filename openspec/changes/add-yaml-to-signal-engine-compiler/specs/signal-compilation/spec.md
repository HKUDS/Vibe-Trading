## ADDED Requirements

### Requirement: 策略 YAML 受限 DSL schema

系統 SHALL 以 Pydantic 模型 `StrategySpec` 定義 `research/strategies/strategy_<id>.yaml` 的受限 DSL，並 SHALL 將模型定義於 `dashboard/server/schemas.py`，與既有 `FactorManifest` / `CandidatesManifest` 同檔案以保持 schema 來源單一。

`StrategySpec` MUST 包含以下頂層欄位：
- `name`（字串，snake_case）
- `archetype`（字串）
- `symbol`（字串，OKX swap ticker，如 `ETH-USDT-SWAP`）
- `timeframe_signal`（`"1H"` / `"4H"` / `"8h"` / `"1D"`）
- `indicators`（dict，key 為 indicator 變數名，value 為 `IndicatorSpec`）
- `entry_long`（`EntryBlock`，可為 null）
- `entry_short`（`EntryBlock`，可為 null）
- `exit_rules`（`ExitRule` 陣列）

`IndicatorSpec` MUST 包含：
- `source`（字串，必為 `stage1:<factor_name>` 格式，`<factor_name>` 須符合 `[a-z][a-z0-9_]*`）
- `smoothing`（`"none"` / `"sma_<n>"` / `"ema_<n>"`，`<n>` 為正整數）

`EntryBlock` MUST 包含：
- `description`（字串）
- `conditions`（字串陣列；每條 MUST 符合 D2 DSL pattern：percentile / zscore / raw 比較，可加 `persist <m>/<n>` 後綴）

`ExitRule` 為以下四種其一：
- `{condition: "time_based", max_hold_hours: int}`
- `{condition: "take_profit_pct", value: float}`
- `{condition: "stop_loss_pct", value: float}`
- `{condition: "signal_invalidation", expression: "<indicator>_percentile_<n>d between <lo>,<hi>"}`

#### Scenario: 合法 YAML 通過 schema 驗證
- **WHEN** Stage 2 產出之 `strategy_eth_s1_multi_factor_consensus.yaml` 採用受限 DSL 詞彙
- **THEN** `StrategySpec.model_validate_json(yaml_as_json)` MUST 通過
- **AND** Stage 2b 編譯時 MUST 取得有效 `StrategySpec` instance

#### Scenario: 未知 DSL 詞彙被拒
- **WHEN** YAML 的 `entry_long.conditions` 含 `funding_rate AND custom_indicator > 0`（非 DSL 規範詞彙）
- **THEN** Pydantic 驗證 MUST raise，錯誤訊息 MUST 指出第幾條 condition 與不合 pattern 之處
- **AND** Stage 2b 編譯 MUST 終止並回報非零 exit code

#### Scenario: 未知 indicator source 被拒
- **WHEN** `indicators.foo.source` 為 `binance:price` 而非 `stage1:<factor>`
- **THEN** Pydantic 驗證 MUST raise，訊息 MUST 指出 `source` 必須以 `stage1:` 開頭

### Requirement: YAML → signal_engine.py 編譯器

系統 SHALL 提供模組 `research/lib/signal_compiler.py`，公開函式 `compile_strategy(spec: StrategySpec) -> str`，回傳值為合法 Python 原始碼字串（即 `signal_engine.py` 內容）。

編譯器 SHALL：
- 使用 Jinja2 樣板 `research/strategies/code/_templates/signal_engine.py.j2` 渲染
- 為每個 `IndicatorSpec.source = "stage1:<factor>"` 產生 `lib.factor_io.load_factor_values(symbol)[<factor>]` 讀取碼
- 套用對應 smoothing（`sma_<n>` → `.rolling(n, min_periods=1).mean()` 等）
- 將 `entry_long.conditions` / `entry_short.conditions` 翻成 pandas boolean expression chain
- 套用 `persist m/n` wrapper 為 `.rolling(n).sum() >= m`
- 將 `exit_rules` 翻成 state machine：`time_based` → 計入 holding bar 計數；`take_profit_pct` / `stop_loss_pct` → 對 entry price 計算 unrealized P&L；`signal_invalidation` → percentile band 觸發歸 0
- 回傳的字串 MUST 通過 `ast.parse()` 與 `agent/backtest/runner.py:_validate_signal_engine_source`

#### Scenario: 編譯成功且通過 AST scrubber
- **WHEN** `compile_strategy(valid_spec)` 被呼叫且 `valid_spec` 屬合法 `StrategySpec`
- **THEN** 回傳字串 MUST 為非空 Python 程式碼
- **AND** `ast.parse(回傳字串)` MUST 不 raise
- **AND** `_validate_signal_engine_source(回傳字串)` MUST 不 raise
- **AND** 字串內 MUST 含 `class SignalEngine` 與 `def generate(self, data_map)` 兩段

#### Scenario: persist DSL 正確翻譯
- **WHEN** condition 字串為 `funding_zscore_30d <= -1.5 persist 2/3`
- **THEN** 編譯後程式碼 MUST 包含等效於 `(funding_zscore_30d <= -1.5).rolling(3).sum() >= 2` 的 pandas expression

#### Scenario: 雙因子 AND 條件
- **WHEN** `entry_long.conditions` 為 `["funding_percentile_90d <= 20", "basis_percentile_90d <= 20"]`
- **THEN** 編譯後 MUST 用 `&` 把兩條件 boolean Series 合併

### Requirement: Stage 2b runner

系統 SHALL 提供 `research/pipeline/stage2b_compile_signal.py`，可由 `python -m research.pipeline.stage2b_compile_signal` 執行，並 SHALL：
- 讀取 `research/strategy_runs.json` 全部 entry
- 對每個 entry，讀 `spec_yaml` 指向的 YAML、`StrategySpec.model_validate` 通過後呼叫 `compile_strategy`
- 寫 `research/strategies/code/<strategy_id>/signal_engine.py`
- 同檔內第一行附 `# yaml-hash: <sha256-of-yaml-content>` 註解供下游 audit
- 同時寫 `research/strategies/code/<strategy_id>/test_signal_engine.py`（煙霧測試），並 subprocess 跑 `pytest <test_path>`，失敗則整個 stage2b raise
- 寫出前檢查既有檔案前 5 行是否含 `# manual: do-not-overwrite`，若有則 SHALL 跳過該 strategy_id 並 print warning（黃色字）
- 結束時印每個 strategy 狀態（OK / SKIP / FAIL），任一 FAIL exit code 非 0

#### Scenario: stage2b 對 ETH 策略產出 AST-safe signal_engine
- **WHEN** `strategy_runs.json` 含 `eth_s1_multi_factor_consensus` 指向合法 YAML
- **AND** 對應 `research/strategies/code/eth_s1_multi_factor_consensus/signal_engine.py` 不存在或不含 manual 標記
- **THEN** stage2b 執行後該檔 MUST 被寫出
- **AND** 第一行 MUST 為 `# yaml-hash: <hash>` 註解
- **AND** 對應 `test_signal_engine.py` MUST 被寫出
- **AND** 該 test pytest 執行 MUST exit 0

#### Scenario: 手寫 escape hatch 跳過編譯
- **WHEN** `research/strategies/code/<id>/signal_engine.py` 前 5 行含 `# manual: do-not-overwrite`
- **THEN** stage2b MUST 不覆寫該檔
- **AND** stdout MUST 印警告 `[stage2b] <id>: SKIP — manual escape hatch present`
- **AND** stage2b exit code MUST 仍為 0（前提其他 strategy 都成功）

#### Scenario: 編譯失敗時 stage2b 終止
- **WHEN** 某 strategy YAML 含未知 DSL 詞彙
- **THEN** `StrategySpec.model_validate` raise
- **AND** stage2b MUST print 紅字 `[stage2b] <id>: FAIL — <error>`
- **AND** stage2b 收集所有錯誤後以 non-zero exit code 結束（不於第一個錯誤即止，讓使用者一次看到全部）

### Requirement: 配套煙霧測試

Stage 2b 為每支生成的 `signal_engine.py` SHALL 同時生成 `test_signal_engine.py`，內容 MUST：
- 用 `pytest` fixture mock `lib.factor_io.load_factor_values` 回傳長 200 hourly bars 的 DataFrame，欄為 YAML 所列因子
- 呼叫 `SignalEngine().generate({symbol: ohlcv_df})`
- assert 回傳 dict 含對應 `symbol` key
- assert 回傳 Series index 與輸入 OHLCV 一致、長度相同
- assert 回傳值 ⊂ `{-1.0, 0.0, 1.0}`（容許 NaN 在 warm-up window）

#### Scenario: stage2b 自動跑生成的 pytest
- **WHEN** stage2b 完成 `signal_engine.py` 寫出
- **THEN** stage2b MUST subprocess 呼叫 `python -m pytest research/strategies/code/<id>/test_signal_engine.py -q`
- **AND** 該 pytest exit code 非 0 MUST 讓 stage2b raise，並把 pytest stdout 包進錯誤訊息
