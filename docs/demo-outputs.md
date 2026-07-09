# Demo Outputs

Evidence date: 2026-07-09

## Demo Suite

The Alpha Genesis demo tests ran together with alpha_foundry tests:

```text
pytest agent/tests/alpha_genesis_demos agent/tests/alpha_foundry -q
54 passed
```

## Demonstrated Scenarios

- Future leak trap: rejects future-looking alpha.
- Cherry-picked noise trap: warns/caps multiple-testing proxy risk.
- Survivorship-bias trap: caps at research-only when PIT/survivorship evidence
  is insufficient.
- High-turnover cost trap: rejects cost-exceeding alpha.
- Duplicate public alpha trap: rejects duplicate factor evidence.
- Orthogonal liquidity reversal candidate: preserves only narrow research
  candidate semantics.
- Forward decay/kill: proves append-only frozen observation behavior.

Demo artifacts are deterministic fixtures and do not imply live trading
readiness.
