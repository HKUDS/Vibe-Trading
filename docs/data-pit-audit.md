# Data PIT Audit

Data reliability records source provenance, bounded quality checks, circuit
breaker state, and point-in-time (PIT) safety evidence without changing
`DataLoaderProtocol.fetch`.

## Contracts

`DataSetContract` describes the requested dataset:

- asset class, frequency, calendar, fields, timezone,
- corporate action policy,
- survivorship policy.

`DataAccessContract` records how data was fetched:

- requested source and selected source,
- request parameter hash,
- fallback chain,
- cache key,
- fetch timestamp and source timestamp,
- explicit local flag,
- source priority and circuit breaker state,
- loader latency.

`DataAuditReport` combines those contracts with row counts, symbol counts,
field coverage, PIT violations, quality warnings, market-rule warnings, circuit
breaker snapshots, and artifact refs.

## PIT Timestamps

Use the five timestamp fields consistently:

| Field | Meaning |
| --- | --- |
| `effective_at` | When the event economically took effect. |
| `published_at` | When the issuer/source published it. |
| `ingested_at` | When the system captured it. |
| `available_at` | When a researcher could have known it. |
| `as_of` | The simulated decision time. |

If `available_at > as_of`, the result is future data and must be a hard
failure. Financial statements must not use period end as a substitute for
announcement availability.

## Source Rules

- `local:` and explicit local sources never silently fall back to network.
- `auto` may fall back, but selected source, fallback path, cache hit, and
  fetch time must be recorded.
- If every source is circuit-open, the result must surface
  `DATA_ALL_SOURCES_OPEN`; empty success is not acceptable.
- Missing data and forward fill policies must be explicit.

## Circuit Breakers

Circuit breaker snapshots include source, state, consecutive failures, open
time, last error class, and next probe time. They are audit metadata, not a
permission grant.

## Market Rules

A-share tradability claims require coverage for T+1, limit up/down,
suspension, lot size, fees, and slippage. Missing critical market rules prevent
tradability claims.
