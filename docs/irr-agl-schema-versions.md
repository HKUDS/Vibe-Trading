# IRR-AGL Schema Versions

Every new IRR-AGL schema includes `schema_version`. Fields should be added as
optional or backward-compatible additions unless a migration plan and fixture
are provided.

## Current Versions

| Artifact or model | Version | Module |
| --- | --- | --- |
| ArtifactRecord | `1.0.0` | `src.reliability.artifacts.model` |
| DataAuditReport | `1.0.0` | `src.reliability.data.contracts` |
| ResearchProtocol | `1.0.0` | `src.research_protocol.model` |
| TrialEvent | `1.0.0` | `src.research_protocol.trial` |
| BacktestReliabilityScorecard | `1.0.0` | `src.reliability.quant.scorecard` |
| ResearchCard | `1.0.0` | `src.research_card.model` |
| PolicyDecision | implicit v1 fields | `src.governance.decisions` |

## Migration Fixtures

Phase 8 pins v1.0 fixtures in:

```text
agent/tests/fixtures/schema_migration/
```

Fixtures:

- `protocol_v1_0.json`
- `data_audit_v1_0.json`
- `scorecard_v1_0.json`
- `research_card_v1_0.json`

The tests in `agent/tests/reliability/test_schema_migration.py` validate that
fixtures still parse, remain canonical-hashable, preserve protocol hashes, keep
scorecard dimension whitelist behavior, and keep DSR/PBO experimental-only.

## Compatibility Rules

- Keep old traces and run cards readable.
- Do not require a forced SQLite migration for existing users.
- Do not remove existing public fields from API responses.
- Do not change legacy metric meanings.
- Add new refs as optional fields.
- Reject non-canonical JSON inputs before hashing.
- Redact secrets before writing artifacts, traces, or cards.

## Version Bump Guidance

Patch version:

- New optional fields.
- New warning or hard-failure codes.
- New optional artifact refs.

Minor version:

- New artifact type.
- New required enum value with compatibility shim.
- New migration fixture set.

Major version:

- Incompatible field rename or removal.
- Changed hash payload semantics.
- Changed conclusion-gate semantics.

Major version bumps require a migration guide update and old-fixture parse
tests.
