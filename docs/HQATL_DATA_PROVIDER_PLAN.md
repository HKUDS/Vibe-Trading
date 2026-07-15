# HQATL Data Provider Plan

## Goal

HQATL will use provider-neutral contracts so research, analytical, and strategy logic remain portable and testable. This is a future design; no provider connection is authorized in Phase 0.

## Provider contracts

### HistoricalDataProvider

Retrieves normalized completed bars and approved historical datasets with instrument, timeframe, timezone, session, provenance, completeness, and adjustment metadata.

### RealtimeDataProvider

Supplies timestamped realtime quotes/bars, explicitly distinguishes provisional from completed bars, and reports freshness, gaps, and connection quality.

### MarketDepthProvider

Supplies entitlement-aware depth/order-book events with venue, sequence, timestamp, coverage, and known limitations.

### ExecutionProvider

Encapsulates future practice/demo or order operations. It remains disabled by default and unavailable to strategy logic without a separately approved, order-capable development phase.

### InstrumentMapper

Maps canonical HQATL instruments to provider identifiers, contract metadata, price precision, trading calendars, and rollover/expiry rules.

## Providers

- **Initial provider: OANDA.** Future work may implement historical and practice adapters after official API, account, instrument, rate-limit, and licensing review.
- **Future provider: Moomoo/OpenD.** Work is conditional on account access, API support, data entitlements, licensing, regional availability, Level 2 coverage, and demo-trading verification.

## Boundary rules

- Strategies and analytics depend only on canonical data and provider contracts.
- Provider adapters perform translation; they do not contain strategy decisions.
- Recorded fixtures or test doubles support deterministic tests.
- Data-quality warnings propagate to research and decision workspaces.
- Provider differences must be disclosed rather than silently normalized away.
