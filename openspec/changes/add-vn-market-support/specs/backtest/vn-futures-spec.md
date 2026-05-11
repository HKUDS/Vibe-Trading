# Delta for backtest — VN30 Futures (Sprint 2.1)

> Companion delta to `specs/backtest/spec.md`. Adds VN30F-specific requirements.

## ADDED Requirements

### Requirement: VN30 Futures Engine
The system MUST provide a `VNFuturesEngine` extending `FuturesBaseEngine` for VN30 index futures (HNX), supporting the 4 active contracts `VN30F1M`, `VN30F2M`, `VN30F1Q`, `VN30F2Q` with contract multiplier 100,000 VND × index points.

#### Scenario: Multiplier-aware PnL
- GIVEN a long position of 1 contract opened at VN30 = 1200
- WHEN the position is closed at VN30 = 1210
- THEN the realized P&L = 1 × 100,000 × (1210 − 1200) = 1,000,000 VND
- AND broker commission and 0.1% sell-side tax are deducted

#### Scenario: VN30F symbol routing precedence
- WHEN the composite engine detects `VN30F1M.HNX`
- THEN the symbol is routed to `vn_futures`, NOT `vn_equity`
- AND the VN30F detection rule is evaluated BEFORE the generic `.HNX` equity rule

### Requirement: Configurable Margin & Maintenance
The engine MUST accept configurable `margin_rate` (default 0.17), `maintenance_ratio` (default 0.80), `commission_per_contract` (default 2700 VND), and `tax_rate` (default 0.001), with broker-specific values overriding the exchange minimum (13%).

### Requirement: Daily Mark-to-Market
At each bar close, the engine MUST realize unrealized P&L against the close price for every open VN30F position, update the cash balance, and re-mark each position's reference price for the next bar.

#### Scenario: Loss settles to cash
- GIVEN a long 1 VN30F1M opened at 1200, with prior settle 1200
- WHEN the bar closes at 1180
- THEN cash is debited by 1 × 100,000 × (1180 − 1200) = −2,000,000 VND
- AND the position's prior_settle is updated to 1180

### Requirement: Margin Call Simulator
After each daily settle, the engine MUST verify that available margin ≥ position notional × `margin_rate` × `maintenance_ratio`. On breach, the engine MUST flag the position for forced liquidation at the next bar's open and record a `margin_call` event in the run trace.

#### Scenario: Forced liquidation on breach
- GIVEN cumulative settled losses bring cash below the maintenance threshold for an open position
- WHEN the next bar starts
- THEN the engine forces a close at the bar open price
- AND the trade record is tagged `forced_liquidation`
- AND a `margin_call` event with date, balance, threshold appears in the run log

### Requirement: Cash Settlement at Expiry
On the 3rd Thursday of each contract's expiry month, the engine MUST cash-settle any open position in that contract using the bar's close price (with documented future enhancement to use the avg of last 30-min minute bars when available), then mark the position as expired and reject any further executions for that contract.

#### Scenario: VN30F1M expires at scheduled date
- GIVEN an open long VN30F1M position on 2024-05-15 (Wednesday)
- WHEN the bar of 2024-05-16 (3rd Thursday of May 2024) closes
- THEN the position is cash-settled against the 2024-05-16 close
- AND any subsequent bars for VN30F1M reject orders via `can_execute` returning False
- AND the engine logs an `expiry_settlement` event

### Requirement: Position Limit
The engine MUST reject opens that would push the absolute open contract count for a single user above `position_limit` (default 5000).

### Requirement: Symmetric Long/Short
Unlike `VNEquityEngine`, the futures engine MUST allow short selling (direction = -1) without the T+2 lock — futures positions are inherently long/short symmetric and have no settlement period for the underlying shares.

### Requirement: BaseEngine `_after_bar_close` hook
`BaseEngine` MUST expose an `_after_bar_close(bar)` hook (default no-op) called after standard bar-by-bar processing. The hook MUST be a pure-Python override point with no behavioral effect on existing engines (ChinaAEngine, GlobalEquityEngine, CryptoEngine, ForexEngine, ChinaFuturesEngine, GlobalFuturesEngine) — verified by the existing regression suite remaining green.

#### Scenario: Hook is no-op for existing engines
- WHEN the full regression suite runs after the hook is introduced
- THEN every existing engine test passes with identical results
- AND no engine other than `VNFuturesEngine` overrides `_after_bar_close`
