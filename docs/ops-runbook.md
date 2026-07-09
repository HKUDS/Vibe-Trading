# Operations Runbook

## Normal Validation

Use workspace-local pytest temp directories on Windows:

```powershell
New-Item -ItemType Directory -Force .tmp\pytest | Out-Null
$env:TEMP=(Resolve-Path .tmp).Path
$env:TMP=$env:TEMP
.\.venv\Scripts\python.exe -m pytest <tests> -q -p no:cacheprovider --basetemp .tmp\pytest
```

Recommended release checks:

```powershell
git diff --check
.\.venv\Scripts\python.exe -m compileall -q agent/src agent/cli
.\.venv\Scripts\python.exe -m pytest agent/tests/acceptance agent/tests/alpha_quality agent/tests/alpha_foundry agent/tests/research_ledger -q -p no:cacheprovider --basetemp .tmp\pytest
.\.venv\Scripts\python.exe -m pytest agent/tests/factors/test_alpha_purity.py agent/tests/factors/test_lookahead.py -q -p no:cacheprovider --basetemp .tmp\pytest-factors
cd frontend
npm.cmd run test:run
npm.cmd run build
```

## Incident Response

- Corrupt AGS report artifact: CLI/API should return sanitized invalid-artifact
  messages. Do not expose local paths or tracebacks.
- Ledger tamper signal: reject promotion above `research_only`, preserve the
  tampered artifact for investigation, and start a fresh ledger only after
  operator approval.
- Forward observation out of order: reject the append; do not edit prior
  observations.
- Data snapshot PIT missing or survivorship biased: cap decision at
  `research_only`.
- Report/UI shows hard failures with a green decision: treat as a release
  blocker and rerun quality-decision response-schema tests.

## PR Checklist

- Scope and non-goals stated.
- Live/order/broker impact stated as none.
- Tests run and tests not run documented.
- Rollback path linked.
- Known limitations linked.
- Draft PR preferred unless the maintainer asks for ready review.
