# Contributing to Vibe-Trading

Vibe-Trading is a natural-language finance research AI agent (FastAPI + ReAct
agent backend, Vite+React frontend, vectorized daily and options backtesting).
This guide covers contribution governance: the Developer Certificate of Origin
(DCO) sign-off requirement, the reviewer checklist for Alpha Zoo factor
contributions, and the quickstart for adding a new alpha.

For general project setup (`pip install -e ".[dev]"`, dev servers,
`pytest --ignore=agent/tests/e2e_backtest`), see the README. For bug reports
and feature requests, use the GitHub issue templates.

For AI-assisted or automation-assisted contributions, also see
[`AGENT_CONTRIBUTOR_GUIDE.md`](AGENT_CONTRIBUTOR_GUIDE.md). It summarizes safe
local checks, higher-risk broker/MCP/credential surfaces, and the expected PR
risk notes for agent-authored changes.

## Developer Certificate of Origin (DCO)

Every commit in a community pull request MUST carry a `Signed-off-by:`
trailer. We do not require a CLA — the DCO is a lightweight per-commit
attestation that you wrote the code or have the right to submit it under
the project's MIT license. Maintainer-direct commits to `main` are not
subject to the trailer requirement (the maintainer's authorship is
already attested by the commit's author field), but community PRs are.

Sign your commits with `-s`:

```bash
git commit -s -m "feat(factors): add gtja191 alpha 042"
```

This appends a trailer like:

```
Signed-off-by: Your Name <you@example.com>
```

PRs without a `Signed-off-by:` on every commit will be asked to rebase and
resign. To fix an unsigned series, run
`git rebase --signoff <base-branch>` and force-push the branch.

### DCO 1.1 (full text)

```
Developer Certificate of Origin
Version 1.1

Copyright (C) 2004, 2006 The Linux Foundation and its contributors.
1 Letterman Drive
Suite D4700
San Francisco, CA, 94129

Everyone is permitted to copy and distribute verbatim copies of this
license document, but changing it is not allowed.


Developer's Certificate of Origin 1.1

By making a contribution to this project, I certify that:

(a) The contribution was created in whole or in part by me and I
    have the right to submit it under the open source license
    indicated in the file; or

(b) The contribution is based upon previous work that, to the best
    of my knowledge, is covered under an appropriate open source
    license and I have the right under that license to submit that
    work with modifications, whether created in whole or in part
    by me, under the same open source license (unless I am
    permitted to submit under a different license), as indicated
    in the file; or

(c) The contribution was provided directly to me by some other
    person who certified (a), (b) or (c) and I have not modified
    it.

(d) I understand and agree that this project and the contribution
    are public and that a record of the contribution (including all
    personal information I submit with it, including my sign-off) is
    maintained indefinitely and may be redistributed consistent with
    this project or the open source license(s) involved.
```

## Alpha PR Reviewer Checklist

This checklist applies to any PR adding or modifying files under
`agent/src/factors/zoo/**/*.py`. Reviewers MUST verify every box before
merging. Authors are strongly encouraged to self-check first.

- [ ] **Purity gate**: file passes `pytest agent/tests/factors/test_alpha_purity.py`.
  The AST scan rejects any imports outside the allowlist
  (`pandas`, `numpy`, `scipy.*`, `src.factors.base`, `__future__`, `typing`,
  `math`, `dataclasses`) and any reference to forbidden names: `os`,
  `subprocess`, `socket`, `urllib`, `requests`, `httpx`, `pathlib`, `Path`,
  `eval`, `exec`, `compile`, `__import__`, bare `open`, or `getattr` with a
  second argument beginning with `"__"`.
- [ ] **Lookahead gate**: file passes `pytest agent/tests/factors/test_lookahead.py`.
  No negative shifts, no forward leakage. `delta(df, d)` must have `d >= 1`.
- [ ] **`__alpha_meta__` present** with all required pydantic-validated fields:
  `id`, `theme`, `formula_latex`, `columns_required`, `universe`, `frequency`,
  `decay_horizon`, `min_warmup_bars`. Optional: `nickname`, `extras_required`,
  `requires_sector`, `notes`.
- [ ] **`compute(panel)` contract**: returns a DataFrame with the same shape
  as `panel["close"]`, NaN preserved at warmup / missing-data positions,
  no `+/-inf` values.
- [ ] **LaTeX matches code**: the `formula_latex` in `__alpha_meta__` and the
  formula in the module docstring describe what `compute()` actually does.
- [ ] **Per-zoo `LICENSE.md` updated** to cite the source paper / report and
  to state that formulas are mathematical facts, not subject to copyright,
  and that prose / tables / figures from papers and reports are not
  reproduced in this repo. Do NOT frame the bundled formulas using US
  affirmative-defense terminology — that is a litigation posture, not a
  license grant. State the mathematical-facts rationale instead.
- [ ] **Apache-2 attribution**: if the alpha is adapted from an Apache-2.0
  upstream (e.g. Microsoft Qlib), the file MUST carry a header of the form
  `# Adapted from <repo>@<commit-sha>:<path> (Apache-2.0). Copyright (c) <holder>.`
- [ ] **DCO**: every commit in the PR carries `Signed-off-by:`.

## Adding a New Alpha (Quickstart)

1. Pick the target zoo directory under `agent/src/factors/zoo/` (e.g.
   `gtja191/`, `alpha101/`, `qlib158/`, `academic/`).
2. Create `<alpha_id_short>.py` in that directory. Define `__alpha_meta__`
   (must satisfy the pydantic `AlphaMeta` schema in
   `agent/src/factors/registry.py`) and a pure `compute(panel)` function
   that imports only from `src.factors.base` plus the allowlisted stdlib /
   numpy / pandas / scipy.
3. Run the purity and lookahead gates locally:
   ```bash
   pytest agent/tests/factors/test_alpha_purity.py agent/tests/factors/test_lookahead.py -q
   ```
4. (Optional but recommended) Run a quick bench:
   ```bash
   vibe-trading alpha bench --zoo <zoo_id> --universe csi300 --period 2020-2025
   ```
5. Open a PR. Every commit must include `Signed-off-by:` (use
   `git commit -s`). Reviewers will walk the checklist above.

## Adding a Channel (Quickstart)

Channels ship through one authoring contract; the Web UI renders any channel's
configuration with no per-channel frontend code.

1. Create `agent/src/channels/<name>.py` with a `BaseChannel` subclass:
   implement `start`, `stop`, and `send` (abstract), and `default_config()`
   returning the stored config shape. The registry (`src/channels/registry.py`)
   auto-discovers the module; delivery receipts, retries and manager wiring come
   from the base class and manager.
2. Field metadata lives in `agent/src/channels/config_meta.py`. Hand-written
   `FIELD_HINTS[name]` entries supply labels and authoritative secret flags;
   anything you omit is derived from `default_config()` with type inference, and
   credential-shaped keys are masked by the unconditional `SECRET_KEY_RE`
   fail-safe either way. If the platform has a credential endpoint, build the
   connection probe on `token_probe.py` rather than writing a new client (see
   `dingtalk_probe.py` for the pattern) and override `test_connection()`.
3. Run the authoring contract locally:
   ```bash
   pytest agent/tests/test_channel_authoring_contract.py -q
   ```
   It walks every discovered channel and fails when one breaks the recipe
   (abstracts unset, scalar config keys with no field hint, or an uncovered
   credential-shaped key that would leak unmasked into the form).
4. Open a PR with `Signed-off-by:` on every commit. Dict-valued config (e.g.
   per-group maps) stays file-configured by design; the generic form edits
   text/password/bool/list widgets only.

## Code Style

- Format with `black`; lint with `ruff` (config in `pyproject.toml`).
- Install both tools with the development extra: `pip install -e ".[dev]"`.
- Run them on the Python files you changed, for example:
  ```bash
  black --check agent/src/example.py agent/tests/test_example.py
  ruff check agent/src/example.py agent/tests/test_example.py
  ```
  The repository does not yet enforce a whole-tree Black or Ruff check, so
  avoid mixing unrelated formatting cleanup into a focused pull request.
- Type-annotate all public function and method signatures.
- Google-style docstrings (`Args:` / `Returns:` / `Raises:`).
- Keep files under 400 lines where practical, 800 hard cap.
- No hardcoded paths, secrets, or URLs — config via `.env`, YAML, or
  module-level constants.
- Delete unused code rather than commenting it out.

## Attribution

Do NOT add `Co-Authored-By:` trailers or AI-assistant attribution lines to
commit messages or PR descriptions. The DCO sign-off is the only required
trailer; keep commit metadata clean.

By contributing, you agree that your contributions are licensed under the
project's MIT license (see `LICENSE`).

## Broker Bring-up Checklist

Apply this checklist to every new connector or capability change. A generated
matrix row records a declaration; attach separate evidence for runtime claims.

- [ ] Declare each paper/live and read-only/trading profile separately in the
  connector's `profiles.py`. Do not transfer a paper permission into a live
  profile. Document sandbox versus local simulation and the structural runtime
  discriminator; without one, live placement must remain disabled.
- [ ] Declare only mapped capabilities. Record the actual read/quote endpoints,
  response shapes, currency, pagination, and unsupported asset coverage, with
  sanitized fixtures and source references. A listed quote capability is not
  proof that every position can be priced.
- [ ] Record supported order kinds and instrument classes from observed schemas
  or broker documentation; they are not inferred by the matrix. Test unsupported
  requests and malformed or incomplete replies fail closed.
- [ ] Test live risk-increasing actions through the shared mandate gate,
  including account selection, limits, kill switch, and audit. Verify cancel,
  flatten, position management, and copy paths separately where implemented;
  placement coverage alone does not establish their coverage.
- [ ] Separate offline contract tests from authorized sandbox/live verification.
  State exactly which paths were exercised, when, and which remain unverified.
  Never commit credentials, account records, or unsanitized broker responses.
- [ ] Regenerate the README from the repository root and run the CI drift guard:
  ```bash
  PYTHONPATH=agent python -m src.trading.capability_matrix
  pytest agent/tests/test_capability_matrix.py -q
  ```
  Include the generated profile rows and verification evidence in the same PR.

### Public-source health lane

The **Public loader health** workflow runs weekly (Monday 04:17 UTC) and can
be dispatched manually. It is separate from offline PR tests. To reproduce:

```bash
python3.11 -m venv /tmp/vibe-loader-health-venv
/tmp/vibe-loader-health-venv/bin/python -m pip install -r tools/requirements-loader-health.txt
cd agent
/tmp/vibe-loader-health-venv/bin/python -m backtest.loader_health --output /tmp/loader-health.json
```

Use the isolated environment: mootdx's HTTP client requirement conflicts with
the application's dependency range. The canary imports the checkout's loader
code directly, without installing the full application dependency set.

Each unauthenticated network loader has a liquid canary symbol; the local-file
loader is explicitly excluded. Adding a public loader requires updating the
canary catalog, enforced by the offline test suite. Probes bypass the loader
cache and run with a temporary home and no inherited credentials. Each source
has a 120-second total subprocess deadline, including two attempts, and the
workflow has its own job deadline. Reports contain only source identifiers and
validation metadata, never returned bars, raw exceptions, or account settings.

Missing dependencies, unavailable endpoints, connection failures, malformed
OHLCV, and bars older than 14 days fail the health lane; none become passing
skips. A failed lane is an investigation signal, not proof the provider itself
is broken: runner geography, holidays and upstream changes need checking.
The 14-day window is a coarse freshness alarm, not a market-calendar guarantee.
Reports are retained for 30 days. No authenticated source or broker order path
is exercised.
