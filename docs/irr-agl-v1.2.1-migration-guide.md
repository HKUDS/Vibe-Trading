# IRR-AGL v1.2.1 Migration Guide

v1.2.1 reads old artifacts tolerantly and writes new artifacts canonically.

## Legacy Policy Decisions

Old policy decision payloads may lack `evidence_identity`. They remain readable as artifact/API snapshots. Missing trace IDs are represented as `null`; they are not confused with artifact IDs.

## Legacy Research Cards

Old Research Cards may lack `claim_set_ref`, `methodology_fact_ref`, `scorecard_ref`, `triggered_rules`, and `evidence_closure_summary`. The v1.2.1 `ResearchCard` model defaults these fields without hiding existing `hard_failures`.

## Legacy Scorecards

Old scorecards may lack `triggered_rules`, policy refs, or diagnostics fields. The v1.2.1 scorecard model keeps those fields optional and leaves `conclusion_level` unchanged during read.

## Legacy Protocols

Old protocol provenance may lack confirmation status. `ProtocolFieldProvenance` supplies tolerant defaults, while new registered protocols still require confirmation for inferred core fields.

## Missing Index Runs

If old runs contain artifacts but no `RunEvidenceIndex`, `EvidenceVerifier` returns a degraded report with `index_missing_rebuilt_from_artifacts` rather than crashing.

## Rollback

Revert the Phase 10 commit to remove packaging docs and migration fixtures. Earlier phase behavior remains isolated in earlier stacked phase commits.
