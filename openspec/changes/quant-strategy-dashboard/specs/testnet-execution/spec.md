## ADDED Requirements

### Requirement: testnet 自動下單
trader MUST能串接 Bybit testnet，依策略訊號自動下單與平倉，並把成交、淨值寫入 `runs/testnet/<id>/`。

#### Scenario: 訊號觸發下單
- **WHEN** live 迴圈算出進場訊號
- **THEN** trader 透過 ccxt 在 Bybit testnet 下單，並記錄到 `runs/testnet/<id>/trades.csv`

#### Scenario: 訊號邏輯一致
- **WHEN** trader 計算策略訊號
- **THEN** 使用與回測 signal engine 相同的邏輯，避免 live/backtest 分叉

### Requirement: Kill switch
trader MUST內建 kill switch：回撤達設定門檻自動暫停或終止。

#### Scenario: 回撤達終止線
- **WHEN** 累計回撤達 7%
- **THEN** kill switch 自動終止 trader process，並於 `testnet_status.json` 記錄觸發

#### Scenario: 回撤達暫停線
- **WHEN** 累計回撤達 5%
- **THEN** trader 暫停下單並發出 alert

### Requirement: UI 啟停控制
dashboard MUST能透過後端啟動與停止 trader process，一個 promoted 策略對應一個 trader process。

#### Scenario: 啟動 trader
- **WHEN** 使用者在 UI 對某 promoted 策略按「啟動」
- **THEN** 後端 supervisor 啟動對應 trader process，Bybit testnet 開始接單

#### Scenario: 手動停止
- **WHEN** 使用者在 UI 按「停止」
- **THEN** 對應 trader process 結束

### Requirement: API key 安全
Bybit testnet API key MUST只存於後端環境（env / docker secret），不得進入前端、不得進入版本控制。

#### Scenario: key 不外洩
- **WHEN** 設定 trader 的 Bybit 憑證
- **THEN** key 存於後端 `.env` 或 docker secret，`.gitignore` 排除，前端程式碼不含 key
