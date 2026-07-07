# Reliability Artifacts

IRR-AGL artifacts provide a stable graph of evidence for research conclusions.
They are additive and are skipped when `VIBE_TRADING_RELIABILITY_MODE=off`.

## Artifact Record

`src.reliability.artifacts.model.ArtifactRecord` is the v1.0 metadata record:

- `artifact_id`
- `artifact_type`
- `schema_version`
- `sha256`
- `uri`
- optional `path` or `inline_ref`
- `parent_artifacts`
- `created_at`
- `generated_by`
- redacted `metadata`

Artifact types are declared in `src.reliability.schema.ARTIFACT_TYPES` and
include `data_audit`, `tool_trace`, `policy_decision`, `research_protocol`,
`trial_event`, `backtest_result`, `alpha_bench_result`, `scorecard`, and
`research_card`.

## Hashing

- JSON hashes use canonical sorted-key serialization with `allow_nan=False`.
- Pydantic models must be converted with `model_dump(mode="json")` before
  hashing.
- Raw `datetime`, `date`, `time`, `UUID`, pandas `DataFrame`, pandas `Series`,
  `NaN`, and `Inf` are rejected by canonical hashing.
- Large files use streaming SHA-256.

## Storage

`ArtifactStore` writes content-addressed payloads under:

```text
~/.vibe-trading/artifacts/objects/<prefix>/<sha256>.bin
```

The local SQLite index is:

```text
~/.vibe-trading/artifacts/artifact_index.sqlite
```

The index is a convenience lookup surface. The object path and artifact refs are
the durable references used by run cards and research cards.

## Redaction

Artifact metadata is redacted before validation. Do not store raw credentials,
OAuth tokens, broker secrets, raw env vars, private local exports, or token
caches in artifact metadata.

## Parent Graph

Use `parent_artifacts` to preserve lineage:

```text
research_protocol
trial_event
data_audit
policy_decision
tool_trace
backtest_result / alpha_bench_result
scorecard
research_card
```

The graph is append-only for auditability. New derived artifacts should point
back to the evidence they consumed.
