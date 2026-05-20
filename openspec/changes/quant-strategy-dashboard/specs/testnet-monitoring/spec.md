## ADDED Requirements

### Requirement: 策略 promotion 軟擋
送策略進 testnet 時，門檻未全過MUST軟擋：標紅列出未過項，使用者勾選「我知道風險」並填 override 理由後方可確認。

#### Scenario: 非致命門檻未過
- **WHEN** 策略某非致命門檻未過且使用者按「送 testnet」
- **THEN** 對話框標紅該項，需勾確認 + 填理由才能完成 promotion

#### Scenario: 全門檻通過
- **WHEN** 策略所有門檻通過
- **THEN** 可直接確認 promotion，不需 override

### Requirement: 致命門檻硬擋
致命門檻（OOS Sharpe < 0、alpha 被費吃）未過時MUST硬擋，「確認」按鈕鎖死，不可 override。

#### Scenario: OOS Sharpe 為負
- **WHEN** 策略 `gate.fatal_fail` 為 true
- **THEN** promotion 對話框的確認鈕停用，無法送入 testnet

### Requirement: promotion 狀態與匯出
確認 promotion MUST寫入 dashboard 自有 `data/state.json`，並把策略 config/yaml 匯出至 `dashboard/data/exports/`，不得回寫 `research/`。

#### Scenario: 確認 promotion
- **WHEN** 使用者完成 promotion 確認
- **THEN** `state.json` 記錄 promoted 狀態與 override 紀錄，config 匯出到 exports 目錄

### Requirement: testnet live vs backtest 對照
testnet 監控頁MUST讀 `runs/testnet/<id>/` 產出，呈現 live 與 backtest 的對照：淨值疊圖、live/backtest Sharpe 比、滑點實際 vs 假設、未成交數。

#### Scenario: 有 testnet 資料
- **WHEN** 某 promoted 策略的 `runs/testnet/<id>/` 有產出
- **THEN** 監控頁顯示 live vs backtest 對照與 alert

#### Scenario: 尚無 testnet 資料
- **WHEN** promoted 策略尚未有 testnet 產出
- **THEN** 監控頁顯示「等待 testnet 資料」狀態，不報錯
