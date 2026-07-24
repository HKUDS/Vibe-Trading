# ADR 0001: Taiwan Quant Extension Boundary

- Status: Accepted
- Scope: Phase 01 only
- Baseline: `feature/tw-quant-phase-01` at `a5eb30fd00d6ee71cd5099d15f57de5ae47010ff`

## Decision

Taiwan quantitative research support is implemented as a thin extension under
`agent/src/tw_quant/`. It owns local schema, import, immutable snapshot,
verification, symbol parsing, and the snapshot-only loader. It does not create
a parallel backtest core or provider integration layer.

The existing `backtest.loaders.registry`, market detection, and runner receive
only the smallest compatibility patches needed to opt into the Taiwan
snapshot loader. Existing market fallback chains remain unchanged. Taiwan
symbols never silently fall through to a network source.

## Rationale

- The repository's install boundary is `agent/`, with `src*` and `backtest*`
  packages discovered by setuptools.
- Existing loaders use a registry decorator and a `fetch()` contract returning
  `{symbol: pandas.DataFrame}`. The extension adapts to that contract instead
  of duplicating it.
- Existing local storage supports DuckDB and Parquet, but there is no shared
  migration or immutable snapshot subsystem. Phase 01 therefore adds one in
  the extension and uses DuckDB's native Parquet reader/writer so it does not
  require a second Parquet engine.
- Formal backtests are snapshot-only. Provider SDK, HTTP, MCP, credentials,
  and source fallback belong to later ingestion work and are intentionally
  absent here.
- The current `BaseEngine` exposes generic execution hooks but no Taiwan rule
  profile. Phase 01 does not implement a Taiwan execution engine or change
  the base algorithm. A full Taiwan backtest path must fail closed until that
  engine is designed in a later phase.

## Consequences

- A snapshot ID is required by the Taiwan loader; registry discovery can use
  `TW_QUANT_SNAPSHOT_ID` and `TW_QUANT_SNAPSHOT_ROOT` for explicit offline
  operation.
- The loader verifies the manifest and file hashes before every load and reads
  only manifest-listed Parquet files.
- `tw-data` is a thin offline CLI over the extension APIs. It performs
  migration, validation/import, snapshot creation, and verification only.
- Phase 02 FinMind/FinLab MCP or SDK integration, provider ingestion, Taiwan
  execution/cost rules, and live trading remain out of scope.

