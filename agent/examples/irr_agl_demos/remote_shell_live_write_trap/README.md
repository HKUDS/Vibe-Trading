# Remote Shell Live Write Trap Demo

This deterministic demo proves that high-risk shell and live-write attempts are stopped before tool execution on governed runtime surfaces.

The runner uses counted fake tools, routes them through GovernedToolRegistry, records policy decisions into trace, artifact, and evidence index sinks, calls the production Research Card evidence builder, and then runs the final EvidenceVerifier. It does not call an LLM, broker, real shell, or market-data service.

Run:

```bash
python agent/examples/irr_agl_demos/remote_shell_live_write_trap/runner.py --dry-run
```
