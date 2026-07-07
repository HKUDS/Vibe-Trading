# Overfit Best Trial Trap Demo

This deterministic demo proves that a selected best trial remains visible alongside the full eight-trial ledger.

The runner persists each trial event, calls the production Research Card evidence builder, and then runs the final EvidenceVerifier. It does not call an LLM, broker, shell, or market-data service.

Run:

```bash
python agent/examples/irr_agl_demos/overfit_best_trial_trap/runner.py --dry-run
```
