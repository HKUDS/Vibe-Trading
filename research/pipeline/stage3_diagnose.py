"""Stage-3 Diagnosis runner.

research/pipeline/stage3_diagnose.py
──────────────────────────────────────
Stage-3 runner: Backtest Diagnosis.

For each strategy in strategy_runs.json this runner:
  1. Loads config via pipeline.config.load_config().
  2. Reads strategy_runs.json to get all strategies + their run directory names.
  3. For each strategy with a non-null base_run:
     - Gates on runs/<base_run>/artifacts/metrics.csv existing.
     - Reads metrics from base_run (and first oos_run if available).
     - Builds a prompt injecting the metrics JSON as decision context.
     - Invokes ``vibe-trading run -p <prompt> --no-rich`` via subprocess.
     - Parses the LLM response for a recommended_action (proceed / back_to_stage_2 / back_to_stage_4).
     - Falls back to rule-based action if the LLM response is unparseable.
  4. Writes research/manifests/<strategy_id>/diagnosis.json (DiagnosisBlock schema).
  5. Prints per-strategy summary; exits 0 on success / non-zero on failure.

Usage
-----
    # From repo root:
    python -m research.pipeline.stage3_diagnose

    # From research/ directory (preferred):
    python -m pipeline.stage3_diagnose

    # Direct script invocation:
    python research/pipeline/stage3_diagnose.py

Design note
-----------
Follows the stage-runner pattern from stage2_strategies.py exactly:
    config_load → stage_work → pure testable verification → summary + exit code.

``_REPO_ROOT`` is imported from ``pipeline.config`` (not recomputed here) so
all stages agree on exactly one repo-root definition.

The stage runner owns the structure; the LLM provides prose and a recommended
action. ``recommended_action`` MUST always have a value — rule-based fallback
is used when the LLM fails to produce a parseable response.
"""

from __future__ import annotations

import csv
import dataclasses
import json
import re
import subprocess
import sys
from pathlib import Path

# ── Path bootstrap ─────────────────────────────────────────────────────────────
# This module lives at <repo-root>/research/pipeline/stage3_diagnose.py.
# Bootstrap research/ and repo-root onto sys.path so imports work regardless
# of CWD or how this script is invoked.
_THIS_FILE = Path(__file__).resolve()
_PIPELINE_DIR = _THIS_FILE.parent          # research/pipeline/
_RESEARCH_DIR = _PIPELINE_DIR.parent       # research/

for _p in (_RESEARCH_DIR,):
    _ps = str(_p)
    if _ps not in sys.path:
        sys.path.insert(0, _ps)

# ── Internal imports ───────────────────────────────────────────────────────────
from pipeline.config import _REPO_ROOT, ResearchConfig, load_config  # noqa: E402
from pipeline.strategy_runs import StrategyRunsEntry, StrategyRunsMap, load_strategy_runs  # noqa: E402

# ── Dashboard schemas path ─────────────────────────────────────────────────────
_DASHBOARD_SCHEMAS = _REPO_ROOT / "dashboard" / "server"
if str(_DASHBOARD_SCHEMAS) not in sys.path:
    sys.path.insert(0, str(_DASHBOARD_SCHEMAS))

from schemas import DiagnosisBlock, RecommendedAction  # noqa: E402

# ─── Constants ────────────────────────────────────────────────────────────────

#: Timeout in seconds for the LLM diagnosis subprocess (shorter than backtest).
DIAGNOSE_TIMEOUT_S = 300

#: CLI path relative to _REPO_ROOT.
_CLI_PATH = _REPO_ROOT / "agent" / "cli.py"


# ─── Data containers ──────────────────────────────────────────────────────────


@dataclasses.dataclass
class DiagnosisCheckResult:
    """Result of verifying one strategy's diagnosis output."""

    strategy_id: str
    ok: bool
    error: str | None = None  # description if ok=False


# ─── Pure-logic helpers (testable, no subprocess/filesystem) ─────────────────


def read_metrics_csv(metrics_csv: Path) -> dict | None:
    """Read a 1-row metrics CSV and return a dict, or None if missing/empty.

    Uses only the stdlib csv module (no pandas dependency).

    Args:
        metrics_csv: Path to the metrics.csv artifact file.

    Returns:
        Dict mapping column name to float/string value, or None if the file
        does not exist or cannot be read (empty, malformed, no data rows).
    """
    if not metrics_csv.exists():
        return None
    try:
        with metrics_csv.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            rows = list(reader)
        if not rows:
            return None
        row = rows[0]
        # Convert numeric-looking values to float; leave others as string.
        result: dict = {}
        for k, v in row.items():
            if v is None or v == "":
                result[k] = None
                continue
            try:
                result[k] = float(v)
            except (ValueError, TypeError):
                result[k] = v
        return result
    except Exception:  # noqa: BLE001
        return None


def build_diagnosis_prompt(
    strategy_id: str,
    metrics_by_run: dict[str, dict],
    optimization_metrics: dict | None = None,
) -> str:
    """Build the LLM prompt for diagnosis, injecting metrics JSON.

    The prompt asks the LLM to output a JSON object with:
      - recommended_action: one of proceed / back_to_stage_2 / back_to_stage_4
      - summary: 1-2 sentence prose
      - findings: list of strings, one per key observation

    Args:
        strategy_id:          The strategy identifier, e.g. "btc_s1_multifactor_contrarian".
        metrics_by_run:       Dict mapping run_name -> metrics dict from read_metrics_csv().
        optimization_metrics: Optional stage-4 best combo metrics. When present, the
                              prompt instructs the LLM that the base_run reflects
                              UNTUNED default params and the stage-4 best is the
                              authoritative concept-level evidence.

    Returns:
        The prompt text string.
    """
    metrics_json = json.dumps(metrics_by_run, indent=2, ensure_ascii=False)
    opt_section = ""
    if optimization_metrics is not None:
        opt_json = json.dumps(optimization_metrics, indent=2, ensure_ascii=False)
        opt_section = (
            f"## Stage-4 Best Combo (post-optimisation)\n\n"
            f"The base_run above uses the strategy YAML's DEFAULT parameters. "
            f"Stage 4 has already run a parameter sweep; the best combo's metrics "
            f"are below. **Treat these as the concept-level evidence, not the "
            f"untuned base_run.** A profitable best-combo means the concept is "
            f"sound under tuned params — do NOT recommend back_to_stage_2 in that "
            f"case.\n\n"
            f"```json\n{opt_json}\n```\n\n"
        )
    return (
        f"You are a quantitative trading analyst reviewing backtest results for "
        f"strategy '{strategy_id}'.\n\n"
        f"## Backtest Metrics\n\n"
        f"```json\n{metrics_json}\n```\n\n"
        f"{opt_section}"
        f"## Task\n\n"
        f"Based on the metrics above, diagnose this strategy and decide the next "
        f"recommended action. Consider:\n"
        f"  - Sharpe ratio (target >= 1.5, minimum acceptable >= 1.0)\n"
        f"  - Max drawdown (target <= 10%, critical threshold > 15%)\n"
        f"  - Trade count (minimum 100 for statistical validity; < 50 is critical)\n"
        f"  - Profit factor (target >= 1.5)\n"
        f"  - Any signs of overfitting or data snooping\n\n"
        f"## Required Output\n\n"
        f"Respond with ONLY a JSON object (no prose outside the JSON block):\n\n"
        f"```json\n"
        f"{{\n"
        f'  "recommended_action": "<proceed|back_to_stage_2|back_to_stage_4>",\n'
        f'  "summary": "<1-2 sentence summary of the diagnosis>",\n'
        f'  "findings": ["<finding 1>", "<finding 2>", ...]\n'
        f"}}\n"
        f"```\n\n"
        f"Use:\n"
        f"  - 'proceed' if metrics are acceptable and the strategy can advance\n"
        f"  - 'back_to_stage_4' if the strategy concept is sound but parameters "
        f"need optimization (e.g. sharpe between 1.0 and 1.5, drawdown between "
        f"10% and 15%, OR trade_count below 50 — low trade count usually means "
        f"entry thresholds are too strict, which is a parameter problem)\n"
        f"  - 'back_to_stage_2' ONLY if the strategy concept itself is flawed and "
        f"needs redesign (e.g. sharpe < 0, fundamentally negative edge, or "
        f"logic issues that cannot be tuned away)\n"
    )


def parse_diagnosis_response(stdout: str) -> dict | None:
    """Extract and parse the first ```json ... ``` block from LLM stdout.

    The block must contain a valid ``recommended_action`` key with one of the
    three canonical values.

    Args:
        stdout: Captured stdout from the vibe-trading run subprocess.

    Returns:
        Parsed dict if a valid block is found; else None.
    """
    if not stdout:
        return None
    # Find first ```json ... ``` block.
    match = re.search(r"```json\s*(\{.*?\})\s*```", stdout, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(1))
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    action = data.get("recommended_action")
    if not action:
        return None
    # Validate the action value.
    valid_actions = {e.value for e in RecommendedAction}
    if action not in valid_actions:
        return None
    return data


def read_optimization_best(
    optimization_path: Path,
    runs_root: Path,
) -> dict | None:
    """Return the stage-4 best combo's metrics dict, or None if unavailable.

    Reads ``optimization.json``, extracts the ``source_run`` field (the best
    sweep run id), then reads that run's ``artifacts/metrics.csv`` and returns
    the parsed metrics dict.

    Returns ``None`` if:
      - optimization.json does not exist,
      - optimization.json is unparseable or missing ``source_run``,
      - the referenced sweep run's metrics.csv does not exist or cannot be read.

    Args:
        optimization_path: Path to ``manifests/<strategy_id>/optimization.json``.
        runs_root:         ``<repo_root>/runs/`` directory.

    Returns:
        Metrics dict (same shape as ``read_metrics_csv`` output) or None.
    """
    if not optimization_path.exists():
        return None
    try:
        opt = json.loads(optimization_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    source_run = opt.get("source_run")
    if not source_run or not isinstance(source_run, str):
        return None
    metrics_csv = runs_root / source_run / "artifacts" / "metrics.csv"
    return read_metrics_csv(metrics_csv)


def rule_based_action(
    metrics_by_run: dict[str, dict],
    optimization_metrics: dict | None = None,
) -> RecommendedAction:
    """Fallback rule-based diagnosis when the LLM response is unparseable.

    When ``optimization_metrics`` is provided AND it has a positive sharpe,
    stage-4 has already proven the strategy concept can produce edge under
    tuned parameters. In that case the base_run is treated as a pre-tune
    snapshot (default yaml params) and routing is decided on the stage-4 best
    metrics, never on the untuned base. This prevents the common false
    positive where a negative-sharpe base_run gets routed to ``back_to_stage_2``
    even though stage 4 already found a profitable combo.

    Decision tree:
      1. If optimization_metrics has sharpe > 0:
            - apply standard thresholds to the stage-4 best metrics
            - never returns back_to_stage_2 (concept proven)
      2. Else (or optimization_metrics missing):
            - sharpe < 0                                  -> back_to_stage_2
            - sharpe < 1.0 OR |drawdown| > 0.15 OR trades < 50 -> back_to_stage_4
            - else                                        -> proceed

    Low trade count alone is NOT a stage_2 signal — it usually reflects entry
    thresholds being too strict, which is a parameter-tuning problem solvable
    in stage_4, not a concept failure.

    Drawdown convention: metrics.csv stores it as a negative fraction (e.g.
    -0.07 for 7%); abs() handles both signs.

    Args:
        metrics_by_run:        Dict mapping run_name -> metrics dict.
        optimization_metrics:  Optional stage-4 best combo metrics from
                               read_optimization_best().

    Returns:
        RecommendedAction enum value.
    """

    def _f(d: dict | None, k: str) -> float | None:
        if d is None:
            return None
        v = d.get(k)
        if v is None:
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    # Stage-4 override: if stage 4 has already produced a positive-sharpe combo,
    # the strategy concept is proven and routing must not regress to stage_2.
    opt_sharpe = _f(optimization_metrics, "sharpe")
    if opt_sharpe is not None and opt_sharpe > 0:
        opt_drawdown = _f(optimization_metrics, "max_drawdown")
        opt_trades = _f(optimization_metrics, "trade_count")
        if (
            opt_sharpe < 1.0
            or (opt_drawdown is not None and abs(opt_drawdown) > 0.15)
            or (opt_trades is not None and opt_trades < 50)
        ):
            return RecommendedAction.BACK_TO_STAGE_4
        return RecommendedAction.PROCEED

    # No stage-4 evidence → fall back to base_run inspection.
    if not metrics_by_run:
        return RecommendedAction.BACK_TO_STAGE_4

    first_metrics = next(iter(metrics_by_run.values()))
    if not first_metrics:
        return RecommendedAction.BACK_TO_STAGE_4

    sharpe_f = _f(first_metrics, "sharpe")
    drawdown_f = _f(first_metrics, "max_drawdown")
    trade_count_f = _f(first_metrics, "trade_count")

    # back_to_stage_2: concept-level failure (negative edge only).
    if sharpe_f is not None and sharpe_f < 0:
        return RecommendedAction.BACK_TO_STAGE_2

    # back_to_stage_4: moderate failures — needs optimization.
    if (
        (sharpe_f is not None and sharpe_f < 1.0)
        or (drawdown_f is not None and abs(drawdown_f) > 0.15)
        or (trade_count_f is not None and trade_count_f < 50)
    ):
        return RecommendedAction.BACK_TO_STAGE_4

    return RecommendedAction.PROCEED


def build_diagnosis_block(
    strategy_id: str,
    base_run: str | None,
    recommended_action: RecommendedAction,
    summary: str | None,
    findings: list[str],
) -> dict:
    """Build the DiagnosisBlock dict (plain dict, no Pydantic validation here).

    The returned dict conforms to the DiagnosisBlock schema in
    dashboard/server/schemas.py.

    Args:
        strategy_id:        Strategy identifier (not stored in the block itself
                            but used to build the filename externally).
        base_run:           The base run name, stored as source_run.
        recommended_action: One of the RecommendedAction enum values.
        summary:            1-2 sentence prose summary; may be None.
        findings:           List of finding strings; may be empty.

    Returns:
        Plain dict ready for JSON serialization.
    """
    return {
        "source_run": base_run,
        "recommended_action": recommended_action.value,
        "summary": summary,
        "findings": list(findings),
    }


def verify_diagnosis(diagnosis_path: Path) -> DiagnosisCheckResult:
    """Verify diagnosis.json exists and validates against DiagnosisBlock schema.

    Args:
        diagnosis_path: Path to the <strategy_id>/diagnosis.json file.

    Returns:
        DiagnosisCheckResult with ok=True if the file validates; ok=False otherwise.
    """
    strategy_id = diagnosis_path.parent.name

    if not diagnosis_path.exists():
        return DiagnosisCheckResult(
            strategy_id=strategy_id,
            ok=False,
            error=f"diagnosis.json missing: {diagnosis_path}",
        )

    try:
        raw = diagnosis_path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        return DiagnosisCheckResult(
            strategy_id=strategy_id,
            ok=False,
            error=f"diagnosis.json invalid JSON: {exc}",
        )

    try:
        DiagnosisBlock.model_validate(data)
    except Exception as exc:  # noqa: BLE001
        return DiagnosisCheckResult(
            strategy_id=strategy_id,
            ok=False,
            error=f"diagnosis.json schema validation failed: {exc}",
        )

    return DiagnosisCheckResult(strategy_id=strategy_id, ok=True)


def compute_exit_code(results: list[DiagnosisCheckResult]) -> int:
    """Return 0 if at least one result was produced and all are ok; 1 otherwise.

    An empty result list is a failure: the stage produced no diagnosis results.

    Args:
        results: List of DiagnosisCheckResult from verify_diagnosis() calls.

    Returns:
        0 on full success (>=1 result, all ok); 1 otherwise.
    """
    if not results:
        return 1
    return 0 if all(r.ok for r in results) else 1


def print_summary(results: list[DiagnosisCheckResult]) -> None:
    """Print a human-readable per-strategy diagnosis summary to stdout.

    Args:
        results: List of DiagnosisCheckResult from diagnosis runs.
    """
    print("\n" + "=" * 60)
    print("Stage-3 Diagnosis output verification summary")
    print("=" * 60)
    if not results:
        print("  (no strategies were diagnosed)")

    for r in results:
        status = "OK" if r.ok else "FAIL"
        if r.ok:
            msg = "diagnosis.json present and valid"
        else:
            msg = f"FAILED — {r.error}"
        print(f"  [{status}] {r.strategy_id}: {msg}")

    total = len(results)
    passed = sum(1 for r in results if r.ok)
    print(f"\n{passed}/{total} diagnoses passed.")
    if total == 0 or passed < total:
        print("Stage 3 Diagnosis FAILED: no strategies were diagnosed or one or more failed.")
    else:
        print("Stage 3 Diagnosis PASSED: all strategies have valid diagnosis.json.")
    print("=" * 60)


# ─── Stage orchestration (thin shell, not unit-tested) ────────────────────────


def run_vibe_trading_diagnose(prompt: str) -> str:
    """Invoke ``vibe-trading run -p <prompt> --no-rich`` and return stdout.

    The CLI entry point is ``cli.py`` in the agent directory.  The subprocess
    MUST run with cwd=<repo>/agent because cli.py imports ``src.*`` packages.

    Args:
        prompt: The diagnosis prompt text to pass to the LLM.

    Returns:
        Captured stdout of the run subprocess.

    Raises:
        subprocess.TimeoutExpired: If the subprocess does not complete within
            DIAGNOSE_TIMEOUT_S seconds.
    """
    cli_path = _REPO_ROOT / "agent" / "cli.py"
    agent_dir = _REPO_ROOT / "agent"

    cmd = [sys.executable, str(cli_path), "run", "-p", prompt, "--no-rich"]
    print(f"[stage3d] invoking vibe-trading run (timeout={DIAGNOSE_TIMEOUT_S}s) …")
    completed = subprocess.run(
        cmd,
        cwd=str(agent_dir),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=DIAGNOSE_TIMEOUT_S,
    )
    if completed.returncode != 0:
        stderr_snippet = (completed.stderr or "")[:500]
        print(
            f"[stage3d] vibe-trading run exited with code {completed.returncode}.\n"
            f"stderr: {stderr_snippet}",
            file=sys.stderr,
        )
    return completed.stdout or ""


def _diagnose_strategy(
    strategy_id: str,
    entry: StrategyRunsEntry,
    cfg: ResearchConfig,
    runs_root: Path,
    manifests_dir: Path,
) -> DiagnosisCheckResult:
    """Gate, build prompt, invoke LLM, and write diagnosis.json for one strategy.

    Args:
        strategy_id:  Strategy identifier, e.g. "btc_s1_multifactor_contrarian".
        entry:        StrategyRunsEntry from strategy_runs.json.
        cfg:          ResearchConfig (loaded from research_config.yaml).
        runs_root:    <repo_root>/runs/ directory.
        manifests_dir: research/manifests/ directory.

    Returns:
        DiagnosisCheckResult for this strategy.
    """
    print(f"\n{'=' * 60}")
    print(f"[stage3d] Strategy: {strategy_id}")
    print(f"{'=' * 60}")

    # ── Gate: base_run must be set ────────────────────────────────────────────
    if entry.base_run is None:
        msg = f"{strategy_id}: base_run is null — skipping diagnosis"
        print(f"  [SKIP] {msg}")
        return DiagnosisCheckResult(strategy_id=strategy_id, ok=False, error=msg)

    # ── Gate: base_run metrics.csv must exist ─────────────────────────────────
    base_metrics_path = runs_root / entry.base_run / "artifacts" / "metrics.csv"
    if not base_metrics_path.exists():
        msg = f"metrics.csv missing for base_run '{entry.base_run}': {base_metrics_path}"
        print(f"  [SKIP] {msg}")
        return DiagnosisCheckResult(strategy_id=strategy_id, ok=False, error=msg)

    # ── Collect metrics ───────────────────────────────────────────────────────
    print("  [1/4] Reading metrics …")
    metrics_by_run: dict[str, dict] = {}

    base_metrics = read_metrics_csv(base_metrics_path)
    if base_metrics is not None:
        metrics_by_run[entry.base_run] = base_metrics
        print(f"    base_run '{entry.base_run}': {len(base_metrics)} columns")
    else:
        print(f"    base_run '{entry.base_run}': metrics.csv empty or unreadable")

    # Collect first oos_run metrics if available.
    if entry.oos_runs:
        oos_run = entry.oos_runs[0]
        oos_metrics_path = runs_root / oos_run / "artifacts" / "metrics.csv"
        oos_metrics = read_metrics_csv(oos_metrics_path)
        if oos_metrics is not None:
            metrics_by_run[oos_run] = oos_metrics
            print(f"    oos_run '{oos_run}': {len(oos_metrics)} columns")
        else:
            print(f"    oos_run '{oos_run}': metrics.csv missing or empty (skipped)")

    # Read stage-4 optimisation best if available — used both in prompt and as
    # rule-based fallback override.
    optimization_path = manifests_dir / strategy_id / "optimization.json"
    optimization_metrics = read_optimization_best(optimization_path, runs_root)
    if optimization_metrics is not None:
        opt_sharpe = optimization_metrics.get("sharpe")
        opt_trades = optimization_metrics.get("trade_count")
        try:
            opt_sharpe_str = f"{float(opt_sharpe):+.3f}" if opt_sharpe is not None else "?"
            opt_trades_str = str(int(float(opt_trades))) if opt_trades is not None else "?"
        except (TypeError, ValueError):
            opt_sharpe_str, opt_trades_str = "?", "?"
        print(
            f"    stage-4 best: sharpe={opt_sharpe_str}  trades={opt_trades_str}  "
            f"(used to authoritatively decide concept-level routing)"
        )

    # ── Build LLM prompt ──────────────────────────────────────────────────────
    print("  [2/4] Building diagnosis prompt …")
    prompt = build_diagnosis_prompt(strategy_id, metrics_by_run, optimization_metrics)

    # ── Invoke LLM ────────────────────────────────────────────────────────────
    print("  [3/4] Invoking LLM diagnosis …")
    recommended_action: RecommendedAction
    summary: str | None = None
    findings: list[str] = []

    try:
        stdout = run_vibe_trading_diagnose(prompt)
        parsed = parse_diagnosis_response(stdout)
    except subprocess.TimeoutExpired:
        parsed = None
        print(f"  [WARN] LLM timed out after {DIAGNOSE_TIMEOUT_S}s — using rule-based fallback")
    except Exception as exc:  # noqa: BLE001
        parsed = None
        print(f"  [WARN] LLM subprocess error: {exc} — using rule-based fallback")

    if parsed is not None:
        action_str = parsed.get("recommended_action", "")
        try:
            recommended_action = RecommendedAction(action_str)
            print(f"  [LLM] recommended_action = {recommended_action.value}")
        except ValueError:
            recommended_action = rule_based_action(metrics_by_run, optimization_metrics)
            print(f"  [FALLBACK] invalid action '{action_str}' — rule-based: {recommended_action.value}")
        summary = parsed.get("summary")
        raw_findings = parsed.get("findings", [])
        findings = list(raw_findings) if isinstance(raw_findings, list) else []
    else:
        recommended_action = rule_based_action(metrics_by_run, optimization_metrics)
        print(f"  [FALLBACK] rule-based recommended_action = {recommended_action.value}")

    # ── Write diagnosis.json ──────────────────────────────────────────────────
    print("  [4/4] Writing diagnosis.json …")
    block = build_diagnosis_block(
        strategy_id=strategy_id,
        base_run=entry.base_run,
        recommended_action=recommended_action,
        summary=summary,
        findings=findings,
    )

    out_dir = manifests_dir / strategy_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "diagnosis.json"
    out_path.write_text(json.dumps(block, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  [OK] wrote {out_path}")

    # ── Verify ────────────────────────────────────────────────────────────────
    return verify_diagnosis(out_path)


def main() -> None:
    """Stage-3 Diagnosis entry point: orchestrate, verify, report, exit."""
    cfg: ResearchConfig = load_config()
    runs_map: StrategyRunsMap = load_strategy_runs()

    runs_root = _REPO_ROOT / "runs"
    manifests_dir = _REPO_ROOT / "research" / "manifests"

    print("=" * 60)
    print("Stage 3 — Backtest Diagnosis")
    print("=" * 60)
    print(f"Strategies: {list(runs_map.entries.keys())}")
    print(f"Runs root:  {runs_root}")
    print(f"Manifests:  {manifests_dir}")

    all_results: list[DiagnosisCheckResult] = []

    if not runs_map.entries:
        print("[stage3d] WARNING: no strategies found in strategy_runs.json — nothing to diagnose.")
        sys.exit(1)

    for strategy_id, entry in runs_map.entries.items():
        try:
            result = _diagnose_strategy(
                strategy_id=strategy_id,
                entry=entry,
                cfg=cfg,
                runs_root=runs_root,
                manifests_dir=manifests_dir,
            )
        except Exception as exc:  # noqa: BLE001
            result = DiagnosisCheckResult(
                strategy_id=strategy_id,
                ok=False,
                error=f"unexpected error: {exc}",
            )
            print(f"  [ERROR] {strategy_id}: {exc}")
        all_results.append(result)

    print_summary(all_results)
    sys.exit(compute_exit_code(all_results))


if __name__ == "__main__":
    main()
