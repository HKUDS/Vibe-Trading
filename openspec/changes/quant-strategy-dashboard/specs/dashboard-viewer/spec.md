## ADDED Requirements

### Requirement: 策略比較表首頁
首頁MUST以一列一策略並排所有策略，欄位含 Tier 1 指標、GO/NO-GO 紅綠燈與 red flag 標籤，並提供幣種篩選器。

#### Scenario: 多幣種篩選
- **WHEN** 已研究 BTC 與 ETH 多個幣種且使用者選某幣種
- **THEN** 比較表只顯示該幣種的策略

#### Scenario: 紅綠燈總結
- **WHEN** 某策略 `gate.overall_pass` 為 false
- **THEN** 該列顯示紅燈並列出未過門檻

### Requirement: 單策略證據鏈
單策略頁MUST以證據鏈呈現該策略的階段 handoff：因子輸入 → 策略規格與生成理由 → 回測 → 診斷 → 優化 → 門檻。

#### Scenario: 點策略 drill-down
- **WHEN** 使用者點比較表某列
- **THEN** 進入該策略頁，顯示完整證據鏈

#### Scenario: 顯示診斷行動
- **WHEN** 策略診斷的 `recommended_action` 不是 `proceed`
- **THEN** 證據鏈標示需回到的階段

### Requirement: 面板分 Tier
面板MUST分三層：Tier 1 決策關鍵預設展開、Tier 2 audit 預設收合、Tier 3 雜訊置於深層。策略生成的 LLM 散文MUST屬 Tier 3，不得當頭版面板。

#### Scenario: Tier 1 預設展開
- **WHEN** 開啟單策略頁
- **THEN** OOS/IS 並排、淨值疊 HODL、成本壓力、regime 表、門檻 checklist 預設展開

#### Scenario: LLM 生成理由降級
- **WHEN** 呈現「策略生成原因」
- **THEN** 它置於 Tier 3 深層連結，不出現在頁面主區

### Requirement: 自動紅旗橫幅
單策略頁頂部MUST永遠顯示 red flag 橫幅，列出 manifest `gate.red_flags`。

#### Scenario: 輸給 HODL 的策略
- **WHEN** 策略 `benchmark.beat_hodl` 為 false
- **THEN** 紅旗橫幅顯示 `underperforms_hodl`

### Requirement: 因子分析頁
MUST有因子分析頁，呈現 factor manifest 的 IC/IR 表、cross-regime IC、stability 與 verdict，原始 markdown 報告當附件。

#### Scenario: 未做 cross-regime
- **WHEN** factor manifest 的 `cross_regime_ic` 為 null
- **THEN** 頁面顯示「未做 cross-regime 驗證」警示

### Requirement: 複用且不影響 Vibe-Trading 前端
前端MUST以複製方式重用 `frontend/` 的元件，不得修改 `frontend/` 任何檔案，亦不得在執行期依賴它。

#### Scenario: 複製而非引用
- **WHEN** dashboard 前端使用圖表元件
- **THEN** 元件複製到 `dashboard/web/`，`frontend/` 維持原狀
