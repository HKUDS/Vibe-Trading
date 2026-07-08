# Alpha Genesis Demo Index

## Demos

- `future_leak_trap`: rejects future-return leakage with `LOOKAHEAD_DETECTED`.
- `cherry_picked_noise_trap`: reports `HIGH_PBO_PROXY` for selected noise.
- `survivorship_bias_trap`: caps biased universe results with `PIT_CONTRACT_MISSING`.
- `high_turnover_cost_trap`: rejects execution-cost blowups with `COST_EXCEEDS_ALPHA`.
- `duplicate_public_alpha_trap`: rejects public alpha duplication with `DUPLICATE_ALPHA`.
- `orthogonal_liquidity_reversal_candidate`: preserves a narrow candidate with positive marginal IR.
- `forward_decay_kill`: kills a frozen forward plan after append-only negative observations.

## How To Run

```bash
pytest agent/tests/alpha_genesis_demos -q
```

Each demo runner supports `run_demo(dry_run=True)` and compares its stable output
with `expected_output.json`.
