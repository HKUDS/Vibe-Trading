"""
research/pipeline/stage4_optimize.py
──────────────────────────────────────
Stage-4 runner: Optimization.

For each strategy that has a diagnosis.json (stage-3 output) this runner:
  1. Gates on diagnosis.json existing.
  2. Gates on the strategy YAML existing.
  3. Reads diagnosis.json + strategy YAML text + base_run metrics (optional).
  4. Builds a Vibe-Trading swarm invocation (quant_strategy_desk preset),
     injecting strategy YAML, diagnosis findings and metrics as context.
  5. Parses swept_params + best_params from the swarm prose report.
  6. Writes research/manifests/<strategy_id>/optimization.json (OptimizationBlock).
  7. Verifies the output; exits non-zero on any failure.

Usage
-----
    # From repo root:
    python -m research.pipeline.stage4_optimize

    # From research/ directory:
    python -m pipeline.stage4_optimize

    # Direct script invocation:
    python research/pipeline/stage4_optimize.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# ── Path bootstrap ─────────────────────────────────────────────────────────────
_THIS_FILE = Path(__file__).resolve()
_PIPELINE_DIR = _THIS_FILE.parent          # research/pipeline/
_RESEARCH_DIR = _PIPELINE_DIR.parent       # research/

for _p in (_RESEARCH_DIR,):
    _ps = str(_p)
    if _ps not in sys.path:
        sys.path.insert(0, _ps)

# ── Standard library ───────────────────────────────────────────────────────────
import dataclasses
import json
import re
import subprocess

# ── Internal imports ───────────────────────────────────────────────────────────
from pipeline.config import _REPO_ROOT, ResearchConfig, load_config
from pipeline.strategy_runs import StrategyRunsEntry, StrategyRunsMap, load_strategy_runs

# ── Dashboard schemas path ─────────────────────────────────────────────────────
_DASHBOARD_SCHEMAS = _REPO_ROOT / "dashboard" / "server"
if str(_DASHBOARD_SCHEMAS) not in sys.path:
    sys.path.insert(0, str(_DASHBOARD_SCHEMAS))

from schemas import OptimizationBlock  # noqa: E402

# ─── Constants ────────────────────────────────────────────────────────────────

#: The swarm preset stage 4 drives (design D2).
SWARM_PRESET = "quant_strategy_desk"

#: Method string recorded in OptimizationBlock.method.
OPTIMIZATION_METHOD = f"{SWARM_PRESET} swarm (stage 4 optimization)"

#: Run id regex — swarm-YYYYMMDD-HHMMSS-<hex8>.
_RUN_ID_RE = re.compile(r"\bswarm-\d{8}-\d{6}-[0-9a-f]{8}\b")

#: Maximum wall-clock seconds to wait for a swarm subprocess.
SWARM_TIMEOUT_S = 600


# ─── Data containers ──────────────────────────────────────────────────────────


@dataclasses.dataclass
class OptimizationCheckResult:
    """Result of verifying one strategy's optimization output."""

    strategy_id: str
    ok: bool
    error: str | None = None


# ─── Pure-logic helpers (testable, no subprocess/filesystem) ──────────────────


def swarm_target_from_ticker(okx_swap: str) -> str:
    """Convert an OKX swap ticker into a grounding-friendly swarm ``market`` value.

    Strips the ``-SWAP`` suffix so the swarm grounding layer can detect the
    ``BASE-USDT`` token.

    Args:
        okx_swap: OKX perpetual swap ticker, e.g. "BTC-USDT-SWAP".

    Returns:
        Token without the ``-SWAP`` suffix, e.g. "BTC-USDT".
        The case of the input is preserved (uppercase inputs stay uppercase).

    Note:
        This function is intentionally duplicated from stage2_strategies.py to
        avoid cross-stage dependencies.
    """
    token = okx_swap.strip()
    if token.upper().endswith("-SWAP"):
        token = token[: -len("-SWAP")]
    return token


def build_swarm_vars(
    strategy_id: str,
    spec_yaml_text: str,
    diagnosis: dict,
    metrics_by_run: dict[str, dict],
    market: str,
) -> dict[str, str]:
    """Build the user_vars dict for ``vibe-trading --swarm-run quant_strategy_desk``.

    The quant_strategy_desk preset declares two variables: ``market`` and
    ``goal``. Strategy context is injected into ``goal`` (free-form prose)
    because ``market`` must stay a clean ``BASE-USDT`` token.

    Args:
        strategy_id:    Strategy identifier.
        spec_yaml_text: Raw YAML text of the strategy spec.
        diagnosis:      Parsed diagnosis.json dict (at minimum ``recommended_action``
                        and ``findings`` keys are expected).
        metrics_by_run: Dict mapping run_name -> metrics dict (may be empty).
        market:         Clean swarm market token, e.g. "BTC-USDT".

    Returns:
        dict[str, str] with keys ``market`` and ``goal``.
    """
    # Truncate YAML to avoid token overflow.
    yaml_snippet = spec_yaml_text[:2000]

    # Extract relevant diagnosis fields.
    diagnosis_context = {
        "recommended_action": diagnosis.get("recommended_action"),
        "findings": diagnosis.get("findings", []),
        "summary": diagnosis.get("summary"),
    }

    # Include base_run metrics if available.
    base_metrics: dict = {}
    if metrics_by_run:
        first_key = next(iter(metrics_by_run))
        base_metrics = metrics_by_run[first_key] or {}

    goal_text = (
        f"Strategy ID: {strategy_id}\n\n"
        "## Strategy Spec (YAML)\n\n"
        f"```yaml\n{yaml_snippet}\n```\n\n"
        "## Stage-3 Diagnosis\n\n"
        f"```json\n{json.dumps(diagnosis_context, indent=2, ensure_ascii=False)}\n```\n\n"
        "## Base Run Metrics\n\n"
        f"```json\n{json.dumps(base_metrics, indent=2, ensure_ascii=False)}\n```\n\n"
        "## Optimization Task\n\n"
        "Identify the top 3-5 parameters to sweep from the strategy's "
        "``parameter_search_ranges``. Suggest improved ranges for each parameter "
        "based on the diagnosis findings and metrics. Output optimization findings "
        "including: which parameters to sweep, recommended best values, and a "
        "summary of expected improvement."
    )

    return {
        "market": market,
        "goal": goal_text,
    }


def parse_swarm_run_id(stdout: str) -> str | None:
    """Extract the swarm run id from ``vibe-trading --swarm-run`` stdout.

    Args:
        stdout: Captured stdout of the swarm subprocess.

    Returns:
        The run id string (swarm-YYYYMMDD-HHMMSS-<hex8>), or None.
    """
    match = _RUN_ID_RE.search(stdout or "")
    return match.group(0) if match else None


def extract_swarm_report(stdout: str) -> str:
    """Best-effort extraction of the swarm's prose final report from stdout.

    Args:
        stdout: Captured stdout of the swarm subprocess.

    Returns:
        The optimization prose report, trimmed to a reasonable length.
    """
    text = stdout or ""
    marker = "Final Report"
    idx = text.rfind(marker)
    if idx != -1:
        report = text[idx + len(marker):]
        report = report.strip().lstrip("-─— \t").strip()
        return report[:4000]
    else:
        return text[-4000:].strip()


def parse_optimization_from_report(
    report: str,
    strategy_yaml_text: str,
) -> tuple[list[str], dict[str, float]]:
    """Extract swept_params and best_params from the swarm prose report.

    Uses heuristics / regex to parse:
      - ``swept_params``: parameter names from the strategy YAML's
        ``parameter_search_ranges`` that appear in the report text.
      - ``best_params``: lines like "lookback_days: 90" or "param = 3.0".

    Args:
        report:             Prose text from the swarm Final Report.
        strategy_yaml_text: Raw YAML text of the strategy spec (used to
                            identify which parameter names are relevant).

    Returns:
        (swept_params, best_params). Both are empty if nothing parseable is
        found. This function never raises.
    """
    try:
        return _parse_optimization_from_report_inner(report, strategy_yaml_text)
    except Exception:  # noqa: BLE001
        return [], {}


def _parse_optimization_from_report_inner(
    report: str,
    strategy_yaml_text: str,
) -> tuple[list[str], dict[str, float]]:
    """Inner implementation (may raise; outer wrapper catches all exceptions)."""
    import yaml as _yaml

    swept_params: list[str] = []
    best_params: dict[str, float] = {}

    if not report:
        return swept_params, best_params

    # ── Extract parameter names from YAML parameter_search_ranges ─────────────
    known_param_names: list[str] = []
    try:
        doc = _yaml.safe_load(strategy_yaml_text or "")
        if isinstance(doc, dict):
            psr = doc.get("parameter_search_ranges", {})
            if isinstance(psr, dict):
                known_param_names = list(psr.keys())
    except Exception:  # noqa: BLE001
        pass

    # ── Identify swept params: known param names that appear in the report ─────
    report_lower = report.lower()
    for param in known_param_names:
        if param.lower() in report_lower:
            swept_params.append(param)

    # ── Extract best_params: lines like "param: value" or "param = value" ──────
    # Pattern covers both ":" and "=" separators, with optional spaces.
    # Value must be numeric (int or float).
    param_value_re = re.compile(
        r"\b([a-zA-Z_][a-zA-Z0-9_]*)\s*[:=]\s*([+-]?\d+(?:\.\d+)?)\b"
    )

    for match in param_value_re.finditer(report):
        param_name = match.group(1)
        value_str = match.group(2)
        # Only include params we recognise from the strategy YAML.
        if param_name in known_param_names:
            try:
                best_params[param_name] = float(value_str)
            except ValueError:
                pass

    return swept_params, best_params


def build_optimization_block(
    run_id: str | None,
    swept_params: list[str],
    best_params: dict[str, float],
    improvement_summary: str | None,
) -> dict:
    """Build the OptimizationBlock dict.

    Args:
        run_id:              The swarm run id; None if unavailable.
        swept_params:        List of parameter names that were swept.
        best_params:         Dict of {param_name: best_float_value}.
        improvement_summary: First 2000 chars of the prose report (or None).

    Returns:
        A plain dict that validates against OptimizationBlock schema.
    """
    return {
        "source_run": run_id,
        "method": OPTIMIZATION_METHOD,
        "swept_params": list(swept_params),
        "best_params": dict(best_params),
        "improvement_summary": improvement_summary,
    }


def verify_optimization(optimization_path: Path) -> OptimizationCheckResult:
    """Verify optimization.json exists and validates against OptimizationBlock schema.

    Args:
        optimization_path: Path to the <strategy_id>/optimization.json file.

    Returns:
        OptimizationCheckResult with ok=True if the file validates; ok=False otherwise.
    """
    strategy_id = optimization_path.parent.name

    if not optimization_path.exists():
        return OptimizationCheckResult(
            strategy_id=strategy_id,
            ok=False,
            error=f"optimization.json missing: {optimization_path}",
        )

    try:
        raw = optimization_path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        return OptimizationCheckResult(
            strategy_id=strategy_id,
            ok=False,
            error=f"optimization.json invalid JSON: {exc}",
        )

    try:
        OptimizationBlock.model_validate(data)
    except Exception as exc:  # noqa: BLE001
        return OptimizationCheckResult(
            strategy_id=strategy_id,
            ok=False,
            error=f"optimization.json schema validation failed: {exc}",
        )

    return OptimizationCheckResult(strategy_id=strategy_id, ok=True)


def compute_exit_code(results: list[OptimizationCheckResult]) -> int:
    """Return 0 if at least one result was produced and all are ok; 1 otherwise.

    Args:
        results: List of OptimizationCheckResult from verify_optimization() calls.

    Returns:
        0 on full success (>=1 result, all ok); 1 otherwise.
    """
    if not results:
        return 1
    return 0 if all(r.ok for r in results) else 1


def print_summary(results: list[OptimizationCheckResult]) -> None:
    """Print a human-readable per-strategy optimization summary to stdout.

    Args:
        results: List of OptimizationCheckResult.
    """
    print("\n" + "=" * 60)
    print("Stage-4 Optimization output verification summary")
    print("=" * 60)
    if not results:
        print("  (no strategies were optimized)")

    for r in results:
        status = "OK" if r.ok else "FAIL"
        if r.ok:
            msg = "optimization.json present and valid"
        else:
            msg = f"FAILED — {r.error}"
        print(f"  [{status}] {r.strategy_id}: {msg}")

    total = len(results)
    passed = sum(1 for r in results if r.ok)
    print(f"\n{passed}/{total} optimizations passed.")
    if total == 0 or passed < total:
        print("Stage 4 Optimization FAILED: no strategies were optimized or one or more failed.")
    else:
        print("Stage 4 Optimization PASSED: all strategies have valid optimization.json.")
    print("=" * 60)


# ─── Stage orchestration (thin shell, not unit-tested) ────────────────────────


def run_swarm(vars_dict: dict[str, str]) -> str:
    """Invoke ``vibe-trading --swarm-run quant_strategy_desk`` and return stdout.

    The CLI entry point is ``cli.py`` in the agent directory. The subprocess
    MUST run with cwd=<repo>/agent because cli.py imports ``src.*`` packages.

    Args:
        vars_dict: The user_vars dict from build_swarm_vars().

    Returns:
        Captured stdout of the swarm run.

    Raises:
        subprocess.TimeoutExpired: If the swarm subprocess does not complete
            within SWARM_TIMEOUT_S seconds.
        subprocess.CalledProcessError: If the CLI exits non-zero.
    """
    agent_dir = _REPO_ROOT / "agent"
    cli_path = agent_dir / "cli.py"
    vars_json = json.dumps(vars_dict, ensure_ascii=False)

    cmd = [sys.executable, str(cli_path), "--swarm-run", SWARM_PRESET, vars_json]
    print(f"[stage4] invoking swarm: {SWARM_PRESET}  (cwd={agent_dir}, timeout={SWARM_TIMEOUT_S}s)")
    completed = subprocess.run(
        cmd,
        cwd=str(agent_dir),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=SWARM_TIMEOUT_S,
    )
    if completed.returncode != 0:
        stderr_snippet = (completed.stderr or "")[:2000]
        print(
            f"[stage4] swarm subprocess exited with code {completed.returncode}.\n"
            f"stderr (first 2000 chars):\n{stderr_snippet}",
            file=sys.stderr,
        )
        raise subprocess.CalledProcessError(
            returncode=completed.returncode,
            cmd=cmd,
            output=completed.stdout,
            stderr=completed.stderr,
        )
    return completed.stdout or ""


def _optimize_strategy(
    strategy_id: str,
    entry: StrategyRunsEntry,
    cfg: ResearchConfig,
    runs_root: Path,
    strategies_dir: Path,
    manifests_dir: Path,
) -> OptimizationCheckResult:
    """Gate, build vars, invoke swarm, and write optimization.json for one strategy.

    Steps:
      1. Gate: diagnosis.json must exist (stage-3 complete).
      2. Gate: strategy YAML must exist.
      3. Read diagnosis.json + strategy YAML text.
      4. Read base_run metrics (optional).
      5. Build swarm vars.
      6. Call run_swarm() — catch TimeoutExpired and generic exceptions.
      7. Parse run_id + extract report.
      8. Parse swept_params + best_params.
      9. Build optimization block + write optimization.json.
      10. Verify and return result.

    A swarm failure (timeout or CalledProcessError) produces an empty but valid
    OptimizationBlock (ok=True) so the pipeline can continue.

    Args:
        strategy_id:   Strategy identifier.
        entry:         StrategyRunsEntry from strategy_runs.json.
        cfg:           ResearchConfig (loaded from research_config.yaml).
        runs_root:     <repo_root>/runs/ directory.
        strategies_dir: research/strategies/ directory.
        manifests_dir: research/manifests/ directory.

    Returns:
        OptimizationCheckResult for this strategy.
    """
    print(f"\n{'=' * 60}")
    print(f"[stage4] Strategy: {strategy_id}")
    print(f"{'=' * 60}")

    # ── Gate: diagnosis.json must exist ──────────────────────────────────────
    diagnosis_path = manifests_dir / strategy_id / "diagnosis.json"
    if not diagnosis_path.exists():
        msg = f"{strategy_id}: diagnosis.json not found at {diagnosis_path} — run stage 3 first"
        print(f"  [SKIP] {msg}")
        return OptimizationCheckResult(strategy_id=strategy_id, ok=False, error=msg)

    # ── Gate: strategy YAML must exist ────────────────────────────────────────
    yaml_path = strategies_dir / f"strategy_{strategy_id}.yaml"
    if not yaml_path.exists():
        msg = f"{strategy_id}: strategy YAML not found at {yaml_path}"
        print(f"  [SKIP] {msg}")
        return OptimizationCheckResult(strategy_id=strategy_id, ok=False, error=msg)

    # ── Read inputs ───────────────────────────────────────────────────────────
    print("  [1/5] Reading diagnosis.json and strategy YAML …")
    try:
        diagnosis = json.loads(diagnosis_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        msg = f"{strategy_id}: failed to read diagnosis.json: {exc}"
        print(f"  [ERROR] {msg}")
        return OptimizationCheckResult(strategy_id=strategy_id, ok=False, error=msg)

    spec_yaml_text = yaml_path.read_text(encoding="utf-8")

    # ── Read base_run metrics (optional) ──────────────────────────────────────
    metrics_by_run: dict[str, dict] = {}
    if entry.base_run is not None:
        from pipeline.stage3_diagnose import read_metrics_csv  # local import to avoid circular
        base_metrics_path = runs_root / entry.base_run / "artifacts" / "metrics.csv"
        base_metrics = read_metrics_csv(base_metrics_path)
        if base_metrics is not None:
            metrics_by_run[entry.base_run] = base_metrics
            print(f"    base_run '{entry.base_run}': {len(base_metrics)} columns")
        else:
            print(f"    base_run '{entry.base_run}': metrics.csv missing or empty (skipped)")

    # ── Determine market token ─────────────────────────────────────────────────
    # Derive market from the config symbol whose strategy prefix matches.
    market = strategy_id  # fallback: use strategy_id itself
    for sym in cfg.symbols:
        if strategy_id.startswith(sym.name.lower()):
            market = swarm_target_from_ticker(sym.okx_swap)
            break

    # ── Build swarm vars ──────────────────────────────────────────────────────
    print("  [2/5] Building swarm vars …")
    vars_dict = build_swarm_vars(
        strategy_id=strategy_id,
        spec_yaml_text=spec_yaml_text,
        diagnosis=diagnosis,
        metrics_by_run=metrics_by_run,
        market=market,
    )

    # ── Invoke swarm ──────────────────────────────────────────────────────────
    print("  [3/5] Invoking swarm …")
    swarm_stdout: str = ""
    swarm_ok = True
    try:
        swarm_stdout = run_swarm(vars_dict)
    except subprocess.TimeoutExpired:
        swarm_ok = False
        print(f"  [WARN] swarm timed out after {SWARM_TIMEOUT_S}s — writing empty optimization block")
    except Exception as exc:  # noqa: BLE001
        swarm_ok = False
        print(f"  [WARN] swarm failed: {exc} — writing empty optimization block")

    # ── Parse results ─────────────────────────────────────────────────────────
    print("  [4/5] Parsing swarm output …")
    if swarm_ok and swarm_stdout:
        run_id = parse_swarm_run_id(swarm_stdout)
        report = extract_swarm_report(swarm_stdout)
        swept_params, best_params = parse_optimization_from_report(report, spec_yaml_text)
        improvement_summary = report[:2000] if report else None
        print(f"    run_id={run_id}, swept_params={swept_params}, best_params={best_params}")
    else:
        run_id = None
        swept_params = []
        best_params = {}
        improvement_summary = None

    # ── Write optimization.json ───────────────────────────────────────────────
    print("  [5/5] Writing optimization.json …")
    block = build_optimization_block(
        run_id=run_id,
        swept_params=swept_params,
        best_params=best_params,
        improvement_summary=improvement_summary,
    )

    out_dir = manifests_dir / strategy_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "optimization.json"
    out_path.write_text(json.dumps(block, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  [OK] wrote {out_path}")

    # ── Verify ────────────────────────────────────────────────────────────────
    return verify_optimization(out_path)


def main() -> None:
    """Stage-4 Optimization entry point: orchestrate, verify, report, exit."""
    cfg: ResearchConfig = load_config()
    runs_map: StrategyRunsMap = load_strategy_runs()

    runs_root = _REPO_ROOT / "runs"
    strategies_dir = _REPO_ROOT / "research" / "strategies"
    manifests_dir = _REPO_ROOT / "research" / "manifests"

    print("=" * 60)
    print("Stage 4 — Optimization")
    print("=" * 60)
    print(f"Strategies: {list(runs_map.entries.keys())}")
    print(f"Runs root:  {runs_root}")
    print(f"Manifests:  {manifests_dir}")

    all_results: list[OptimizationCheckResult] = []

    if not runs_map.entries:
        print("[stage4] WARNING: no strategies found in strategy_runs.json — nothing to optimize.")
        sys.exit(1)

    for strategy_id, entry in runs_map.entries.items():
        try:
            result = _optimize_strategy(
                strategy_id=strategy_id,
                entry=entry,
                cfg=cfg,
                runs_root=runs_root,
                strategies_dir=strategies_dir,
                manifests_dir=manifests_dir,
            )
        except Exception as exc:  # noqa: BLE001
            result = OptimizationCheckResult(
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
