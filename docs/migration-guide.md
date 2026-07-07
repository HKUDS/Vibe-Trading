# IRR-AGL Migration Guide

IRR-AGL is designed as an additive governance and reliability layer. Existing
run directories, trace JSONL files, run cards, tool schemas, MCP schemas, and
README quickstart flows remain readable.

## Feature Flags

| Variable | Values | Default | Effect |
| --- | --- | --- | --- |
| `VIBE_TRADING_RELIABILITY_MODE` | `off`, `observe`, `warn`, `enforce` | `observe` | Controls reliability artifacts such as scorecards and Research Cards. `off` skips new reliability writes. |
| `VIBE_TRADING_GOVERNANCE_MODE` | `off`, `observe`, `warn`, `enforce` | `observe` | Controls governed tool policy decisions. `off` delegates directly to the wrapped registry. |
| `VIBE_TRADING_ARTIFACT_ROOT` | path | `~/.vibe-trading/artifacts` | Local artifact object and index root. |
| `VIBE_TRADING_RESEARCH_LEDGER_PATH` | path | `~/.vibe-trading/research-ledger/ledger.sqlite` | TrialLedger SQLite WAL path. |

PowerShell example:

```powershell
$artifactRoot = [Environment]::GetFolderPath("UserProfile") + "\.vibe-trading\artifacts"
$ledgerPath = [Environment]::GetFolderPath("UserProfile") + "\.vibe-trading\research-ledger\ledger.sqlite"
$env:VIBE_TRADING_ARTIFACT_ROOT = $artifactRoot
$env:VIBE_TRADING_RESEARCH_LEDGER_PATH = $ledgerPath
$env:VIBE_TRADING_RELIABILITY_MODE = "observe"
$env:VIBE_TRADING_GOVERNANCE_MODE = "observe"
```

## Compatibility

- Old trace records stay readable because new policy and artifact fields are
  optional additions.
- Old `run_card.json` files stay readable because `scorecard_refs` and Research
  Card references are optional.
- No forced SQLite migration is performed for existing goal stores or trial
  ledgers. TrialLedger creates its own WAL-backed database when enabled.
- Deleting `artifact_index.sqlite` recreates an empty local index on the next
  write. Content-addressed object files remain under `objects/`, but callers
  should preserve run-card or research-card refs if they need lookup continuity.
- Schema compatibility is controlled by explicit `schema_version` fields. Phase
  8 pins v1.0 fixtures under `agent/tests/fixtures/schema_migration/`.

## Off Mode

Set `VIBE_TRADING_RELIABILITY_MODE=off` to skip scorecard and reliability
artifact writes. Existing backtest and alpha bench behavior remains intact, and
old metrics shapes are not changed by the reliability layer.

Set `VIBE_TRADING_GOVERNANCE_MODE=off` to disable the governance wrapper where
it is explicitly used. This does not disable existing live safety, path
containment, SSRF checks, API auth, or generated subprocess environment
allowlists.

## Ledger Verification

Use the TrialLedger verifier after moving or restoring a ledger:

```powershell
.\.venv\Scripts\python.exe -X utf8 -c "from pathlib import Path; from src.research_protocol.ledger import TrialLedger; print(TrialLedger(Path(r'$env:VIBE_TRADING_RESEARCH_LEDGER_PATH')).verify().model_dump())"
```

The verifier checks sequence continuity, previous hash links, event hashes,
protocol hashes, event types, and schema versions.

## Research Card Export

Research Cards are schema-versioned JSON artifacts that may also be rendered by
the UI/API read-only surfaces. They reference protocol, audit, policy, trace,
backtest, alpha bench, and scorecard artifacts. They do not replace run cards;
they are an optional reliability summary.

## Performance Baselines

Linux/macOS CI targets:

- DataAudit 10K-row metadata P95 <= 50 ms.
- `PolicyEngine.evaluate` P95 <= 10 ms.
- `protocol_hash` P95 <= 5 ms.
- `TrialLedger.append` P95 <= 50 ms.
- `ArtifactStore.write_bytes` for 1 MB P95 <= 500 ms.
- Governed registry overhead P99 <= 15 ms.

Windows local thresholds are relaxed in tests and documented because NTFS,
antivirus, and SQLite file locks add variance. Flaky exploratory performance
checks may be moved to nightly, but security regression tests are never
optional.

## Rollback

- Documentation and fixture-only changes can be reverted with `git revert`.
- To disable new reliability writes without reverting code, set
  `VIBE_TRADING_RELIABILITY_MODE=off`.
- To disable governed registry wrapping where configured, set
  `VIBE_TRADING_GOVERNANCE_MODE=off`. Live mandates, kill switch, and order
  guard semantics still apply.
