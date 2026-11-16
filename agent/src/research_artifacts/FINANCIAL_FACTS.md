# Structured financial facts (opt-in)

Vibe can save machine-readable issuer financial facts as immutable research
artifacts using `save_financial_research_artifact`. Existing narrative
`save_research_artifact` and the research-artifact API remain unchanged.
There is no database migration, new provider, scheduler, or trading integration.

## Contract

The `financial-facts/v1` document has `schema_version`, `subject`, a
`sources` catalog (`id`, HTTPS `url`) and a nonempty `facts` list.
Each fact includes:

- `metric`, `scope`, `definition`, `value`, `currency`, `unit`;
- `period_kind`: `duration` with `period_start` and `period_end`,
  or `instant` with `as_of_date` (ISO dates);
- `source_id`, `source_section`, optional `source_page`;
- `verification_status`: `verified`, `partial`, or `unavailable`.

`unavailable` requires `value=null`. A `verified` fact requires a
numeric value, source reference, section and unit. Currency is required
for monetary or ambiguous units (for example `millions`), but may be
`null` for clearly non-monetary units (for example `shares`, `%`, `ratio`,
`bps`, `days`). This is a conservative unit-based convention, not a
currency/issuer-specific rule: use explicit units such as `million shares`
rather than an ambiguous scale-only `millions`. Unknown units without a
currency are rejected for `verified` facts; use `partial` until clarified.
Duplicate metric/period/scope/currency/unit identities are rejected. Unknown requested
values should be represented explicitly as unavailable when reporting dates
are known, rather than fabricated.

## Usage

The agent passes a JSON object as `document` plus `data_as_of` to
`save_financial_research_artifact`; optionally `artifact_id` appends a
revision. The tool validates before writing, links the document's sources
to revision evidence, and saves through the existing `ResearchArtifactStore`.

Python callers can use `encode_financial_facts(document)` and
`decode_financial_facts(content)` from
`src.research_artifacts.financial_facts`. Narrative content remains valid
in the same store. The revision's verification status is independent of
individual facts.

## Trust boundary

**Fact-level `verified` is an agent assertion, not an independent audit.**
Structural validation does not authenticate documents, reconcile accounting
figures, prove period correctness, or establish source accuracy. Evidence
references are links, not cryptographic proof. Consumers must independently
verify figures before treating them as authoritative. The JSON Schema offered
to model providers is guidance; Python validation enforces the contract.

## Validation and rollback

Run `pytest agent/tests/test_research_financial_facts.py
agent/tests/test_financial_research_artifact_tool.py -q` plus the existing
research-artifact regression tests. The change is opt-in; rollback is a
single-commit revert with no migration or persistent-data cleanup.
