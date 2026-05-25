## Context

現有 `research/` pipeline 五階段：

```
stage 1 factor_extended.py     → 寫死 3 個因子 → factor_<sym>.json
stage 2 stage2_strategies.py   → 已用 swarm (crypto_trading_desk) → strategy YAML
stage 3 stage3_backtest.py     → backtest
stage 4 stage4_optimize.py     → 參數掃描
stage 5 stage5_select.py       → 入選與晉升
```

stage 2 已透過呼叫 `vibe-trading --swarm-run` 與 swarm 整合，並把 stage 1 manifest JSON 作為決策上下文塞進 `timeframe` 變數（既有設計受限於 preset 變數只支援字串）。本變更要建立一個更前置的「因子探索」階段，但同樣以 swarm 為動力源，並避開既有 stage 2 的 prose-only 限制 —— 因為下游 stage 1 IC 驗證需要可計算的因子規格，而非散文。

既有可用資源：
- `agent/src/swarm/presets/` 已有 `factor_research_committee`（A 股導向）、`crypto_research_lab`（方向分析非因子探索）、`crypto_trading_desk`（執行導向）。
- `agent/src/skills/` 已有 19+ crypto 相關 skills（perp-funding-basis、onchain-analysis、liquidation-heatmap、stablecoin-flow 等）。
- `research/lib/` 有 OKX funding/candles fetcher、Bybit OI fetcher、alternative.me Fear&Greed。
- `dashboard/server/schemas.py` 已有 `FactorEntry`、`FactorManifest`、`FactorVerdict` enum（含 SINGLE_USE / ENSEMBLE_ONLY / REJECT）。

關鍵限制：
- quant-strategy-dashboard change 確立「禁改 agent/、frontend/ 邏輯」原則。新 preset 屬於 `agent/src/swarm/presets/` 之下的資料設定檔（YAML），歸類為設定非邏輯。
- 使用者為量化新手，繁中環境；新模組需含可讀的中文 docstring 與報表。
- Vibe-Trading 平台不支援 Anthropic 直連，swarm LLM 必須走 OpenRouter；preset 不需設定，由 CLI 環境變數注入。

## Goals / Non-Goals

**Goals:**
- 把 stage 1 從「寫死 3 因子」改為「讀 candidates JSON 動態驗證」，且整個改動可獨立 ship、可 rollback。
- 新 stage 0 用 swarm 在 funding / basis / OI 三類訊號內提案候選因子，輸出可被 stage 1 直接消化的結構化 JSON。
- 提供資料源 registry 機制：候選因子的 `data_source` 欄位查 registry 決定能否取資料；不可取者標 `data_unavailable` verdict（不報錯、不阻塞 pipeline）。
- 加快取：`discovery_cache_days` 內重跑 pipeline 不重新呼叫 swarm。
- 維持向後相容：若 stage 0 失敗或快取缺失，stage 1 退化為硬編 3 因子模式（保命用，環境變數 `RESEARCH_LEGACY_FACTORS=1`）。

**Non-Goals:**
- 不在本變更擴資料源（穩定幣、清算、ETF、unlock、options skew、macro 等屬 Change 2 `expand-factor-data-sources` 範圍）。
- 不在本變更做 multiple testing 校正（屬 Change 3 `add-multiple-testing-and-risk-gates` 範圍）。
- 不在本變更動 stage 2-5。
- 不讓 LLM 寫量化門檻數字（驗證門檻仍由 `factor_extended.py` 既有規則 `|IC| >= 0.10 / 0.05 / <0.05` 決定）。
- 不支援 stage 0 → stage 1 之外的 fan-out 工作流（如多 preset 並跑融合）。

## Decisions

### D1：新建 crypto_factor_lab preset，不重用既有 preset

**選**：新建 `agent/src/swarm/presets/crypto_factor_lab.yaml`。

**為何不用 factor_research_committee**：該 preset 變數為 `market` + `factor_type=value/momentum/quality/growth/alternative`，屬 A 股傳統因子分類，無 funding / OI / 鏈上 / 清算等 crypto 原生概念；agent system_prompt 中的 IC 門檻（0.03/0.05）也是月頻股票標準，不是 8h 永續標準。直接套用會產出毫不相關的「市值因子」、「PB 因子」候選，於我們的場景毫無價值。

**為何不用 crypto_research_lab**：該 preset 設計目標是「對單一標的給出方向性建議」（onchain/defi/sentiment → alpha_synthesizer 給多空判斷），非「列出可量化的候選因子規格」。其 agent 輸出格式偏散文分析報告，不適合機器化解析。

**為何不用 crypto_trading_desk**：與 crypto_research_lab 同類問題；已被 stage 2 占用。

**新 preset 設計要點**：
- 變數：`target_universe`（如 `BTC-USDT,ETH-USDT`）、`signal_categories`（如 `funding,basis,oi`）、`horizons_h`（如 `[8,24,72,168]`）。
- Agents：`factor_proposer`（提案）+ `factor_critic`（檢查公式可實作性與經濟邏輯）+ `output_formatter`（強制輸出 JSON）。
- 強制 output schema：每個 agent system_prompt 最後段附 JSON Schema 樣板，要求 final report 以 ``` ```json 區塊包覆候選因子陣列。
- `output_formatter` 的職責是「把前兩個 agent 的散文整理成嚴格 JSON」，等於把結構化 contract 從 user-facing prompt 外移到 swarm 內部分工。

**備案**：若 review 認定新增 preset 也算動 `agent/`，把 preset 改放 `research/presets/crypto_factor_lab.yaml`，stage0 用 `vibe-trading --swarm-run-from-file research/presets/crypto_factor_lab.yaml VARS_JSON` 注入（vibe-trading CLI 已支援檔案路徑，見 `agent/cli.py`）。

### D2：候選因子 schema 設計

**選**：以 Pydantic 模型定義 `FactorCandidate` 與 `CandidatesManifest`，放 `dashboard/server/schemas.py`（與既有 `FactorManifest` 同檔案）。

```
class FactorCandidate(BaseModel):
    name: str                      # 例 "funding_z_30d"
    formula: str                   # 自然語 + pseudo-formula，stage 1 不直接 eval
    data_source: str               # 對應 sources.py registry key，例 "okx_funding"
    expected_ic_sign: Literal["+", "-", "?"]
    economic_logic: str            # 為何此因子有 alpha
    horizons_h: list[int]          # 適用週期
    category: Literal["funding", "basis", "oi"]  # 本變更限三類

class CandidatesManifest(BaseModel):
    schema_version: int = 1
    symbol: str
    generated_at: datetime
    source_swarm_run: str | None   # swarm run id
    candidates: list[FactorCandidate]
```

**為何 formula 是字串、非 AST**：本變更不做 LLM 因子自動執行；stage 1 仍由人寫好的 fetcher 提供候選因子值（fetcher 名 = candidate.name 或 candidate.data_source 衍生）。formula 純粹是給人讀與 audit 用。

**為何不用 dataclass**：與既有 `dashboard/server/schemas.py` 風格一致（全部 Pydantic），且要在 stage 0 寫檔、stage 1 讀檔，Pydantic 的 JSON validate 比手寫穩。

### D3：新 stage 0 而非擴 stage 1

**選**：新增 `research/pipeline/stage0_discovery.py`，與 stage1-5 平行的 runner。

**為何不擴 stage 1**：stage 1 是 IC 計算階段，職責單一；混入 swarm 呼叫會讓 stage 1 變慢且難測（既有的 pure-logic 抽離模式會破）。stage 0 與 stage 1 切開後可獨立執行：`python -m research.pipeline.stage0_discovery` 與 `python -m research.pipeline.stage1_factors`，符合既有 pipeline 設計慣例。

**為何不放 `factor_extended.py` 同檔**：同上，且 stage 0 失敗時應退化為 legacy 模式（環境變數 `RESEARCH_LEGACY_FACTORS=1`），切開檔案讓 fallback 邏輯清楚。

**stage 0 流程**：
1. 讀 `research_config.yaml` 取 symbols、horizons。
2. 對每個 symbol：
   - 檢查 `candidates_<sym>.json` 是否存在且 `generated_at` 在 `discovery_cache_days` 內 → 有則跳過 swarm。
   - 否則 build vars dict → 呼叫 `vibe-trading --swarm-run crypto_factor_lab VARS_JSON` → 捕 stdout。
   - 解析 stdout 中 ```json ``` 區塊 → Pydantic validate → 寫 `candidates_<sym>.json`。
   - 解析失敗：retry 一次（重 prompt 要求嚴格 JSON），仍失敗則寫一個 `candidates_<sym>.failed.json` 記錯，stage 1 行為退化為 legacy。
3. verify_outputs + exit code（同 stage 1 設計模式）。

### D4：資料源 registry

**選**：`research/lib/sources.py` 內定義一個 `SOURCE_REGISTRY: dict[str, SourceSpec]`，其中 `SourceSpec` 包含 `fetcher: Callable | None`、`status: Literal["available", "unavailable"]`、`description: str`。

```
SOURCE_REGISTRY = {
    "okx_funding": SourceSpec(fetcher=fetch_funding_history, status="available", ...),
    "okx_candles": SourceSpec(fetcher=fetch_candles, status="available", ...),
    "bybit_oi":    SourceSpec(fetcher=fetch_oi_history_bybit, status="available", ...),
    "coinglass_liq": SourceSpec(fetcher=None, status="unavailable", description="需付費 API，留待 Change 2"),
    # ...
}
```

**為何 registry 而非 if/elif**：Change 2 會擴 5+ 個新 fetcher，dict lookup 比 if-elif 容易增刪、容易單元測；同時 stage 1 對 `data_unavailable` 候選的處理可寫得 generic。

**為何不直接 import fetcher**：stage 0 不需要呼叫 fetcher，只需要把 registry key 給 swarm 看；fetcher 在 stage 1 才被 dispatch。把 registry 與 fetcher 解耦讓 stage 0 不依賴實作。

### D5：factor_extended.py 改造

**核心改變**：
- 刪除 `for factor in ["funding_rate", "oi_change_24h", "fng"]:` 硬編迴圈。
- 新增 `_load_candidates(symbol) -> list[FactorCandidate]` 讀 candidates JSON；缺檔則檢查 `RESEARCH_LEGACY_FACTORS` env，true 則回傳 hardcoded 3 個，false 則 raise。
- 新增 `_compute_factor_from_candidate(candidate, df, candles, funding, oi_hist) -> tuple[pd.Series, bool]`：依 candidate.data_source 查 registry，若 unavailable 回傳 `(None, False)`；否則計算 factor series 並回傳 `(series, True)`。
- 對 unavailable 候選：直接 build `FactorEntry(name=cand.name, ..., verdict=FactorVerdict.DATA_UNAVAILABLE)` 寫入 manifest，stage 2 既有的 `select_usable_factors` 邏輯（過濾 verdict != REJECT）要修為 `verdict in {SINGLE_USE, ENSEMBLE_ONLY}` —— **但此修改延到 Change 2**，本變更暫時讓 `data_unavailable` 候選不出現在 candidates JSON（swarm prompt 限定只能用 registry available 的 source；違反者 stage 0 丟棄該候選）。

**為何讓 swarm 只能用 available 的 source 而非全清單**：本變更範圍只到 funding/basis/OI 三類，且這三類的 source 都是 available（okx_funding、bybit_oi、okx_candles）。stage 0 prompt 中明確列出可用 source，違反者 stage 0 過濾掉（不傳給 stage 1），降低 `data_unavailable` 路徑被觸發的機率。`data_unavailable` enum 仍加入 schema，但本變更不會產生此 verdict 的 factor —— 留給 Change 2 接手。

**factor name → fetcher mapping**：本變更引入「衍生因子」概念，例如 candidate name = `funding_z_30d`，data_source = `okx_funding`，計算邏輯為 `(funding - funding.rolling(90*8).mean()) / funding.rolling(90*8).std()`。stage 1 不能讓 LLM 寫 Python eval；改用一個小型 `transform_registry`：
```
TRANSFORM_REGISTRY = {
    "raw":          lambda s: s,
    "z_30d":        lambda s: (s - s.rolling(90).mean()) / s.rolling(90).std(),
    "pct_change_24h": lambda s: s.pct_change(24),
    "ma_diff_7d_30d": lambda s: s.rolling(21).mean() - s.rolling(90).mean(),
    # ...
}
```
candidate 額外帶一個 `transform` 欄位（值為 registry key）。swarm prompt 列出可用 transform；無對應者 stage 0 過濾。

### D6：快取與重跑語意

**選**：stage 0 預設讀快取；強制重跑用 `--force` flag 或刪 candidates JSON。

`research_config.yaml`：
```yaml
discovery_cache_days: 7
```

stage 0 行為：若 `candidates_<sym>.json` 存在且 `(now - generated_at).days < discovery_cache_days` → skip swarm，print `cache hit`。否則跑 swarm。

**為何 7 天**：swarm 跑一次 ~$1-5；研究階段每週 sync 一次因子合理；trader 在 live 階段不會頻繁重跑因子分析。

## Risks / Trade-offs

- **LLM 輸出格式不穩** → 加 `output_formatter` agent 專責整 JSON；stage 0 retry 一次；仍失敗就 fallback 到 legacy 並標 `candidates_<sym>.failed.json` 紀錄。代價：兩階段 LLM 多花 ~20% 成本。
- **Preset 放 agent/ 可能違反 dashboard change 約束** → 備案放 `research/presets/`，CLI 已支援檔案路徑。
- **swarm 提案的因子可能全不通過 IC** → stage 1 verdict 仍照 |IC| 門檻判，全 reject 是合理輸出；stage 2 既有的「全 reject 則 raise」邏輯需放寬為「全 reject 則 log 後跳過該 symbol」（屬 stage 2 微調，本變更範圍內）。
- **legacy fallback 路徑被悄悄踩到** → stage 0 失敗時除了寫 failed.json 還必須 print 大紅警告 `[WARN] stage0 failed, stage1 will use LEGACY_FACTORS`，並在 stage 1 開頭再 print 一次當前是 candidates 模式或 legacy 模式。
- **新 schema 與既有 dashboard backend 衝突** → `CandidatesManifest` 是 stage 0 → stage 1 內部契約，dashboard backend 目前不讀；新增不破壞既有 API。`FactorVerdict.DATA_UNAVAILABLE` 為新 enum 值，dashboard backend `factors.py` 已用 enum string 對應，新值會自動帶出（review 時驗證 frontend 沒寫死 enum 列舉）。
- **swarm cost 失控** → 加 `discovery_cache_days` + manual `--force` flag；若 review 要求更嚴，可改為「只有 `--force` 才呼叫 swarm，預設 fail-on-missing-cache」。
- **stage 1 改動破壞既有測試** → `research/tests/test_factor_extended.py` 需更新；本變更 tasks.md 明確列出測試改動清單。
- **空 candidates list** → 若 swarm 提案 0 個因子（極不可能但需防），stage 0 視為失敗，走 fallback。

## Migration Plan

部署順序（單一 PR 可完成，無需分批）：

1. 在 dev 分支實作所有檔案：preset、stage0、sources.py、factor_extended 改造、schema 擴充。
2. 本機跑 `python -m research.pipeline.stage0_discovery` 確認 candidates JSON 產生。
3. 跑 `python -m research.pipeline.stage1_factors` 確認新模式下 manifest 仍有效（與舊版同 schema）。
4. 跑既有 stage 2-5 pipeline，確認下游不變。
5. 跑既有 dashboard backend tests，確認 schema 改動向後相容。
6. Merge。

**Rollback**：
- 設環境變數 `RESEARCH_LEGACY_FACTORS=1` 即可立即回到硬編模式，無需 revert code。
- 完整 revert：刪 stage0_discovery.py、sources.py、preset、回退 factor_extended.py 與 schemas.py。

## Open Questions

- Q1：swarm preset 放 `agent/src/swarm/presets/` 還是 `research/presets/`？傾向放 agent/ 與既有慣例一致；若 reviewer 否決則改 research/。
- Q2：`crypto_factor_lab` agent timeout 設多少？暫定 1200s（比 crypto_trading_desk 的 1800s 短，因 task 較聚焦）；首次跑後依實測調整。
- Q3：`transform_registry` 要在本變更實作多少 transform？暫定 5 個（`raw`、`z_30d`、`z_90d`、`pct_change_24h`、`ma_diff_7d_30d`）；可在 Change 2 擴展。
- Q4：若 swarm 在「提案階段」就跑 `factor_analysis` 工具預估 IC 是否要納入 prompt？傾向**不要**，避免 stage 0 跑 IC 又 stage 1 跑一次浪費；只要求文字提案。
