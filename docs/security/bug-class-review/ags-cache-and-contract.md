# Bug Class Review: AGS Cache And Return Contract

## Class

Research artifacts can include private evidence, secret-like keys, or labels that users may overinterpret as production/live readiness.

## Fix

Alpha Genesis API reads now set no-store headers and redact secret-like keys before returning artifact JSON. Decision enums and strict schema tests lock research-only labels and forbid live/production-ready labels.

## Regression Coverage

- `agent/tests/security/test_artifact_cache_thumbnail_ocr_isolation.py`
- `agent/tests/security/test_return_value_contract_security.py`
- `frontend/src/lib/__tests__/decision-badge-truthfulness.test.tsx`
- `frontend/src/lib/__tests__/service-worker-cache-sensitive-report.test.tsx`
