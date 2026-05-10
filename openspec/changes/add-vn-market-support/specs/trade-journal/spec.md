# Delta for trade-journal

## ADDED Requirements

### Requirement: Vietnam Broker Journal Imports
The trade journal analyzer MUST accept exports from at least 5 Vietnamese brokers: SSI, HSC, VNDirect, TCBS, and DNSE. Both CSV and Excel (XLSX) formats MUST be supported where the broker provides them.

#### Scenario: SSI CSV import
- GIVEN an SSI iBoard export `journal_ssi.csv`
- WHEN the user runs `analyze_trade_journal`
- THEN the reader normalizes records to the common journal schema
- AND the trading profile (avg holding days, win rate, P&L ratio, max DD, total trades) is produced
- AND the 4 bias diagnostics run against the normalized records

#### Scenario: TCBS XLSX import
- GIVEN a TCBS XLSX export with Vietnamese column headers
- WHEN the analyzer runs
- THEN Vietnamese headers are mapped to canonical fields
- AND no manual user mapping is required

### Requirement: VN Tax and Fee Reconciliation
For VN broker journals, the analyzer MUST reconcile reported gross P&L against tax (0.1% sell) and broker commission, and report the net P&L matching the broker statement within 1 VND tolerance.

#### Scenario: Net P&L reconciliation
- GIVEN a journal with 200 trades and broker-reported net P&L
- WHEN the analyzer runs
- THEN computed net P&L = gross − tax − commission
- AND the difference vs broker-reported net is ≤ 1 VND for each trade

### Requirement: Per-Reader Regression
Each of the 5 VN journal readers MUST be pinned by a regression test using an anonymized fixture file shipped under `tests/fixtures/vn_journals/`.
