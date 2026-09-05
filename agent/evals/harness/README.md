# Harness artifact verifier

This package checks a completed agent run from persisted files. It is deterministic and read-only: it does not call an LLM, invoke a tool, load market data, or rewrite the case prompt.

Run it from an installed or editable checkout:

```bash
python -m evals.harness.runner \
  --case agent/evals/harness/cases/identity/explicit_a_share.json \
  --run-dir /path/to/run \
  --trace-dir /path/to/session
```

`--trace-dir` is optional when `trace.jsonl` and `run_manifest.json` are stored in the run directory. The JSON report emits one `PASS`, `FAIL`, `NOT_EVALUABLE`, or `INVALID_ARTIFACT` verdict per assertion. Missing future instrumentation is never treated as success.

Session traces can contain several turns. The loader evaluates only the records from the final `start` event onward, which matches the latest run artifacts. A future immutable message ID can replace this bounded association without changing old reports.

Exit status is `0` when all evaluable assertions pass, `1` when an assertion fails, and `2` when the case or artifact bundle is invalid. `NOT_EVALUABLE` does not fail the command because the report preserves its coverage explicitly.

The first version reads these files only:

- `req.json`
- `state.json`
- `trace.jsonl` and safe prompt/content sidecars
- `artifacts/grounding_evidence.json`
- `llm_usage.json`
- `run_manifest.json`

Cases keep the natural-language prompt unchanged. Everything below `expect` is evaluator metadata and is never sent to the Agent.

`data_snapshot` is a relative pointer for the separate run producer. This verifier never loads or fetches that data; the included example points to a synthetic, credential-free snapshot packaged beside the case.
