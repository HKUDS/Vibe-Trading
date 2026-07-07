# Future Data Trap Demo

This deterministic demo proves that a point-in-time violation overrides impressive raw metrics.

The runner uses local fixture inputs, persists a data-audit artifact, then calls the production Research Card evidence builder and final EvidenceVerifier. It does not call an LLM, broker, shell, or market-data service.

Run:

```bash
python agent/examples/irr_agl_demos/future_data_trap/runner.py --dry-run
```
