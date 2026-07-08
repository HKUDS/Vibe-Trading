# AGS Current-Main Baseline

Date: 2026-07-08

Repository baseline commit: `b8a7c5e`

Branch used for Phase 0: `phase/ags-00-baseline-scope-lock`, created from
local primary branch `codex/ags-v31-main`.

Root execution specs are local-only files:

- `AGENTS.MD`
- `execplan.md`

They are intentionally ignored through `.git/info/exclude` and must not be
committed.

## Phase 0 Scope Lock

Phase 0 is a characterization and regression-harness phase only. It does not
add Alpha Genesis System runtime modules, feature flags, APIs, live-trading
surfaces, or scorecard behavior. Later phases must remain additive and
feature-flagged.

Files touched in this phase:

- `docs/ags-current-main-baseline.md`
- `agent/tests/alpha_genesis/test_phase0_current_bench_contract.py`

Core runtime files intentionally not touched:

- `agent/src/agent/context.py`
- `agent/src/agent/tools.py`
- `agent/src/factors/bench_runner.py`
- `agent/src/factors/registry.py`
- `agent/src/tools/alpha_bench_tool.py`
- `agent/src/api/live_routes.py`
- `agent/src/tools/trading_connector_tool.py`

## Current Bench Function Signatures

Current additive target:

```python
src.factors.bench_runner.run_bench(
    zoo: str,
    universe: str,
    period: str,
    top: int = 20,
    on_progress: ProgressCb | None = None,
    registry: Registry | None = None,
    only: Iterable[str] | None = None,
) -> dict[str, Any]
```

Current strict opt-in runner:

```python
src.factors.bench_runner_strict.run_bench_strict(
    zoo: str,
    universe: str,
    period: str,
    *,
    random_control: bool,
    top: int = 20,
    on_progress: ProgressCb | None = None,
    registry: Registry | None = None,
    only: Iterable[str] | None = None,
    n_random_seeds: int = 5,
    random_seed: int = 42,
    oos_split: str | None = None,
    thresholds: StrictThresholds | None = None,
) -> dict[str, Any]
```

Tool interfaces that AGS must not wrap or break:

```python
src.agent.tools.BaseTool.execute(self, **kwargs: Any) -> str
src.agent.tools.ToolRegistry.execute(self, name: str, params: Dict[str, Any]) -> str
```

Data loader interface that AGS must not break:

```python
agent.backtest.loaders.base.DataLoaderProtocol.fetch(
    self,
    codes: list[str],
    start_date: str,
    end_date: str,
    *,
    interval: str = "1D",
    fields: list[str] | None = None,
) -> dict[str, pd.DataFrame]
```

`run_bench` currently returns an API-shaped dictionary with keys including:

- `status`
- `zoo`
- `universe`
- `period`
- `n_alphas_tested`
- `n_skipped`
- `alive`
- `reversed`
- `dead`
- `by_theme`
- `top5_by_ir`
- `dead_examples`
- `rows`
- `skipped`
- `meta`
- `wall_seconds`

The Phase 0 test locks this output shape through a hermetic injected registry
and monkeypatched fixture panel.

## Current Forward Return Behavior

The current Alpha Zoo bench forward return helper is
`src.tools.alpha_bench_tool._compute_forward_returns`.

Current behavior:

```python
fwd = close.pct_change().shift(-1)
```

This is a one-bar close-to-close forward simple return aligned to the factor
timestamp. It is not a multi-horizon execution return. It does not model
A-share T+1, limit-up buy infeasibility, limit-down sell infeasibility,
suspension, ST state, lot size, fees, slippage, or capacity.

Phase 1 must add explicit multi-horizon and execution-aware scorecard behavior
through new additive `alpha_quality` modules and a new `run_bench_with_scorecard`
entrypoint. The existing `run_bench` behavior must remain unchanged.

## Current Categorise Thresholds

`src.factors.bench_runner.categorise` currently buckets rows as:

- `alive`: `ic_mean > 0.02`, `ic_positive_ratio >= 0.55`, and `abs(t) > 2`
- `reversed`: `ic_mean < -0.02` and `abs(t) > 2`
- `dead`: everything else

The t-stat is:

```python
ic_mean / (ic_std / sqrt(n))
```

with zero returned when `n <= 0`, `ic_std <= 0`, or `ic_std` is not finite.

`src.factors.bench_runner_strict` is already an opt-in stricter path with
same-universe random controls, an optional OOS split, and `StrictThresholds`
defaulting to:

```python
StrictThresholds(alpha_t_threshold=2.0, min_ic_count=30)
```

The AGS phases must not mutate these existing thresholds in place. New scoring
or decision behavior belongs in additive modules.

## Existing Metadata Fields

`run_bench` copies any non-DataFrame panel metadata from `panel["_meta"]` into
the top-level result key `meta`. Current `alpha_bench_tool` uses this for the
S&P 500 loader:

```python
panel["_meta"] = {
    "universe": "sp500",
    "survivorship_bias": True,
    ...
}
```

Phase 0 fixture metadata used in the contract test:

```python
{
    "survivorship_bias": False,
    "pit_contract_present": False,
    "source": "phase0_fixture",
}
```

AGS must treat `survivorship_bias=True` and missing PIT contracts as quality
caps in later phases, not as runtime crashes in the legacy bench path.

## Live Safety Boundary To Avoid Touching

Current live-trading privileged surfaces are separate from Alpha Zoo benching:

- `agent/src/api/live_routes.py`
  - `POST /mandate/commit`
  - `POST /live/halt`
  - `POST /live/resume`
  - `GET /live/status`
  - `POST /live/authorize`
  - `POST /live/runner/start`
  - `POST /live/runner/stop`
- `agent/src/tools/propose_mandate_tool.py`
  - read-only mandate proposal tool
  - writes proposals only, never a committed mandate
- `agent/src/tools/trading_connector_tool.py`
  - `trading_place_order` and `trading_cancel_order` are non-read-only broker
    write tools
  - live profiles are documented as gated by mandate and kill switch

AGS must not wrap, monkeypatch, replace, or widen:

- `AgentLoop`
- `AgentContext`
- `ToolRegistry`
- live mandate commit paths
- kill-switch paths
- broker connector write tools
- MCP schemas
- scheduler executor

AGS API/report surfaces, if added in later phases, must be research-only. API
surfaces in AGS v1 must be GET-only and must not start mining jobs or route
orders.

## Current Factor And Registry Observations

`src.factors.registry.Registry` is the current Alpha Zoo source of truth. It
AST-extracts `__alpha_meta__`, lazy-loads compute modules, validates output
shape, and exposes:

- `list(zoo=None, theme=None, universe=None) -> list[str]`
- `get(alpha_id) -> Alpha`
- `get_source(alpha_id) -> str`
- `health() -> dict[str, Any]`
- `compute(alpha_id, panel) -> pd.DataFrame`
- `export_manifest() -> dict[str, Any]`

`src.factors.factor_analysis_core.compute_ic_series` computes daily Spearman
rank IC as Pearson correlation over per-row ranks after aligning common dates
and symbols. A date is dropped when fewer than five instruments have paired
factor and return values.

## Feature-Flag Baseline

AGS feature flags do not exist yet on current main. Phase 0 therefore does not
add `maybe_enable_ags` or any AGS feature-flag module. Feature-off identity
must be added when the first AGS feature-flag constants are introduced.

The Phase 0 characterization test ensures `run_bench` remains injectable and
returns the current API-shaped contract before later additive functions are
introduced.

## Tests Run

Red step:

```bash
pytest agent/tests/alpha_genesis/test_phase0_current_bench_contract.py -q
```

Observed result before this document existed:

```text
1 failed, 1 passed
```

Expected failure:

```text
FileNotFoundError: docs/ags-current-main-baseline.md
```

Green step:

```bash
pytest agent/tests/alpha_genesis/test_phase0_current_bench_contract.py -q
```

Observed result after adding this document:

```text
2 passed in 1.38s
```

Final Phase 0 validation should include:

```bash
pytest agent/tests/alpha_genesis/test_phase0_current_bench_contract.py -q
pytest agent/tests/factors -q
git diff --check
```

Observed Phase 0 validation:

```text
pytest agent/tests/alpha_genesis/test_phase0_current_bench_contract.py -q
2 passed in 1.38s

pytest agent/tests/factors -q
1030 passed, 5 skipped, 12 warnings in 201.54s

git diff --check
passed with no output
```

The warnings are pre-existing `DataFrame.pct_change` FutureWarnings from
Alpha101 lookahead tests and are not introduced by Phase 0.

## Rollback

Rollback Phase 0 by removing only:

- `docs/ags-current-main-baseline.md`
- `agent/tests/alpha_genesis/test_phase0_current_bench_contract.py`

No runtime module should need rollback for Phase 0.
