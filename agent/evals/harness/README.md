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
- `artifacts/identity_evidence.json` (current instrument resolution)
- `artifacts/grounding_evidence.json` (legacy/offline numeric diagnostics)
- `llm_usage.json`
- `run_manifest.json`

Cases keep the natural-language prompt unchanged. Everything below `expect` is evaluator metadata and is never sent to the Agent.

`data_snapshot` is a relative pointer for the separate run producer. This verifier never loads or fetches that data; the included example points to a synthetic, credential-free snapshot packaged beside the case.

## Financial tasks and measurement checks

The Research Lab adds 20 synthetic-input financial tasks and a shared saved-run
replay interface. `vibe-trading research-lab cases --json` lists exact original
prompts. `research-lab replay RUN --case ID --json` evaluates that saved run;
`--bindings FILE.json` maps each task to its own run and optional trace directory.
Web exposes the same case selector, report and coverage through `/research-lab`.

`expect.measurements` holds at most 100 objects with a relative JSON/CSV
`artifact`, dotted `field`, operator (`approx`, `equals`, `finite`, `gte`, `lte`),
and `expected` (except `finite`). Optional `absolute_tolerance` defaults to
1e-8; optional CSV `row` is zero-based and below 100000. Paths cannot escape
the run, including through symlinks. Read size is bounded by the artifact
loader limit. Missing values remain NOT_EVALUABLE; malformed values or files
are INVALID_ARTIFACT. `expect.timing.max_seconds` compares finite start/end
trace timestamps; missing timing remains NOT_EVALUABLE. Financial accuracy,
latency and budgets have separate aggregate coverage metrics.

Synthetic test fixtures validate both success and rejection; they do not
measure live Agent quality. Run production prompts unchanged through the
normal Agent, then bind the actual persisted artifacts for a real evaluation.
The stricter Research Lab command exits 2 for incomplete coverage, while the
original standalone harness CLI retains its existing exit behavior.

## Research delivery and offline diagnostics

The research runtime imports only `src.agent.instrument_identity` for instrument
resolution and tool authorization. Numeric diagnostics live in `evals.grounding`;
no runtime path imports them. They emit findings only: no correction prompts,
redaction, fallback answers, declaration stripping or streaming limits. Legacy
figures declarations remain readable solely for historical evaluation. Missing
numeric diagnostics do not constitute a numeric correctness pass.

`agent/tests/fixtures/research_output/collar_sign.json` preserves a human-reviewed
real PM transcription error: the reported cap was −18.5%, while the tool computed
+18.532041639%. Its report hash and producing run identify the unchanged original.
`test_research_cleanup.py` uses the existing measurement evaluator to fail the
negative claim and pass the positive rounding control, without altering either.
No heuristic is added to infer a claim's meaning from arbitrary report prose.

The same offline regression set also retains two errors observed in the cleanup
validation: confusing GPD scale with mean excess loss, and misstating collar
returns at scenario endpoints. Human-reviewed claims and source/report hashes
are stored alongside the sign case; the existing measurement evaluator checks
them against independent calculations. Correctly rounded controls pass. No
production parser, report gate, or rewriting rule is added for these cases.
