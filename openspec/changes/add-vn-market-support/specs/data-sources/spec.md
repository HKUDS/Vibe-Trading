# Delta for data-sources

## ADDED Requirements

### Requirement: Vietnam Stock Provider
The system MUST integrate a `VNStockProvider` exposing the common `DataProvider` contract for HOSE/HNX/UPCoM equities, ETFs, and indices, with a 4-source fallback chain: vnstock → TCBS public API → SSI iBoard → DNSE LightSpeed.

#### Scenario: Zero-key VN backtest
- GIVEN no broker credentials configured
- WHEN the user requests bars for `VNM`
- THEN vnstock is used as the free primary
- AND data is normalized to the common bar schema
- AND the provider used is recorded in the run trace

#### Scenario: Fallback on vnstock outage
- GIVEN vnstock returns a network error
- WHEN the loader requests bars
- THEN TCBS public API is attempted next
- AND the fallback decision is logged
- AND user-facing flow is uninterrupted

### Requirement: VN Symbol Normalization
The provider MUST accept symbol forms `VNM`, `VNM.HOSE`, and `HOSE:VNM`, normalizing internally to canonical `<TICKER>.<EXCHANGE>`.

#### Scenario: Bare ticker resolves to exchange
- WHEN the user requests bars for `VNM`
- THEN the provider resolves the exchange to `HOSE` via metadata lookup
- AND subsequent calls use canonical `VNM.HOSE`

### Requirement: Vietnam Fundamental Provider (VAS Point-in-Time)
The system MUST provide a `VNFundamentalProvider` exposing point-in-time financial statements based on Vietnamese Accounting Standards (VAS), with a documented mapping from VAS account codes to IFRS-equivalent labels.

#### Scenario: Fetch FPT quarterly statements
- WHEN the user requests Q4 2024 statements for `FPT`
- THEN the provider returns balance sheet, income statement, cash flow
- AND each line item carries both VAS code and IFRS-equivalent label
- AND the data is point-in-time as of the original disclosure date

### Requirement: VN Routing in data-routing Skill
The `data-routing` skill MUST detect VN ticker patterns (3-letter uppercase, optional `.HOSE/.HNX/.UPCOM` suffix) and route to `VNStockProvider` rather than the A-share or US providers.

#### Scenario: VNM not mistaken for A-share
- GIVEN ambiguous bare ticker `VNM`
- WHEN data-routing inspects the symbol
- THEN VN routing is selected over A-share routing
- AND no AKShare call is attempted
