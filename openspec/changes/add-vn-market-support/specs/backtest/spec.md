# Delta for backtest

## ADDED Requirements

### Requirement: Vietnam Equity Engine
The system MUST provide a `VNEquityEngine` implementing the common `Engine` interface with VN-specific rules: T+2 settlement, dynamic price band per exchange (HOSE ±7%, HNX ±10%, UPCoM ±15%), 100-share lot rounding, sell-side tax of 0.1%, and configurable broker commission.

#### Scenario: T+2 cash availability
- GIVEN a backtest sells `VNM` on day T0
- WHEN the engine processes day T1
- THEN the proceeds are NOT yet available as buying power
- AND on day T+2 the cash becomes available
- AND the cash ledger records the pending balance

#### Scenario: Price band enforcement
- GIVEN a strategy submits a buy order at +10% above prior close on a HOSE stock
- WHEN the engine evaluates the order
- THEN the order price is truncated to +7% (HOSE band)
- AND the truncation is recorded in the trade log

#### Scenario: Sell-side tax applied
- GIVEN a sell order of 1000 VNM at 100,000 VND
- WHEN the engine fills the order
- THEN proceeds are reduced by 0.1% × 100,000,000 = 100,000 VND tax
- AND broker commission is deducted separately according to config

### Requirement: VN30 Futures Engine
The system MUST provide a `VNFuturesEngine` supporting VN30F1M, VN30F2M, VN30F1Q, and VN30F2Q contracts with daily mark-to-market, 17% initial margin (configurable per broker), margin call simulation, and cash settlement at expiry against the VN30 close.

#### Scenario: Daily mark-to-market
- GIVEN a long VN30F1M position opened at 1200
- WHEN the close on the next day is 1180
- THEN the daily P&L is debited from margin account
- AND margin maintenance is checked
- AND a margin call is triggered if equity falls below maintenance threshold

#### Scenario: Cash settlement at expiry
- GIVEN a VN30F1M position held to the third Thursday
- WHEN the expiry settlement runs
- THEN P&L is computed against the VN30 index close
- AND the position is closed in cash, no underlying delivery

### Requirement: VN Engines in CompositeEngine
The `CompositeEngine` MUST register `VNEquityEngine` and `VNFuturesEngine` so cross-market portfolios spanning VN equities, VN30F, A-shares, and Crypto run on a shared capital pool with per-market execution rules.

#### Scenario: VN equity + VN30F hedge
- GIVEN a strategy holds 70% VN equities and shorts VN30F as hedge
- WHEN CompositeEngine runs
- THEN one shared cash pool is used
- AND VN equity legs obey T+2 + biên độ
- AND VN30F legs obey daily mark-to-market
- AND combined equity curve and Sharpe are reported

### Requirement: VN-Aware Performance Reports
Backtest reports for VN runs MUST display tax and broker commission breakdown separately and use the `vi-VN` locale when configured.

#### Scenario: Cost transparency in report
- WHEN a VN equity backtest completes
- THEN the report shows: gross return, total tax paid, total commission, net return
- AND when locale is `vi-VN`, numbers render as `1.000.000,50` and labels are Vietnamese
