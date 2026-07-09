# Trial Ledger Verification Output

Evidence date: 2026-07-09

## Tests

The AGS matrix included:

- `agent/tests/research_ledger/test_trial_ledger_append_only.py`
- `agent/tests/research_ledger/test_trial_ledger_concurrency.py`
- `agent/tests/research_ledger/test_trial_ledger_redaction.py`
- `agent/tests/research_ledger/test_ledger_integrity_and_tamper.py`

These tests ran as part of the 104-test AGS security/contract matrix and
passed.

## Verified Behaviors

- Ledger append-only mutation methods are rejected.
- Concurrent appends do not corrupt records.
- Failed, skipped, rejected, and successful trial statuses are represented in
  tests.
- Hash-chain verification detects tamper.
- Secret-like values are redacted from stored/queryable ledger output.

No production or persistent private ledger was mutated during validation.
