"""Stage-5 Selection runner.

research/pipeline/stage5_select.py
────────────────────────────────────
Stage-5 runner: Strategy Selection (pure Python, no LLM).

For each strategy in strategy_runs.json this runner:
  1. Checks eligibility (diagnosis.json + optimization.json + metrics.csv present,
     and recommended_action != "back_to_stage_2").
  2. Reads metrics.csv from the base_run artifacts directory.
  3. Computes a weighted composite score (pure Python, no LLM).
  4. Sorts all eligible strategies by score descending.
  5. Assigns rank (1 = best).
  6. Marks selected=True for strategies with recommended_action == "proceed",
     False for those with "back_to_stage_4".
  7. Writes research/manifests/selection.json (SelectionManifest schema).
  8. Verifies + prints summary.

Usage
-----
    # From repo root:
    python -m research.pipeline.stage5_select

    # From research/ directory (preferred):
    python -m pipeline.stage5_select

Design note
-----------
Stage 5 has NO LLM call — pure Python scoring only. This is by design (the
spec states "無（純 Python 算分）"). The scoring formula uses a weighted
composite:

    score = 0.4 * clamp(sharpe / 1.5, 0, 2)
          + 0.3 * clamp(1 - |drawdown| / 0.10, 0, 2)
          + 0.2 * clamp(profit_factor / 1.5, 0, 2)
          + 0.1 * clamp(trade_count / 100.0, 0, 2)

Missing metric values contribute 0.0 to their component.
"""

from __future__ import annotations

import dataclasses
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── Path bootstrap ─────────────────────────────────────────────────────────────
# This module lives at <repo-root>/research/pipeline/stage5_select.py.
# Bootstrap research/ onto sys.path so imports work regardless of CWD.
_THIS_FILE = Path(__file__).resolve()
_PIPELINE_DIR = _THIS_FILE.parent          # research/pipeline/
_RESEARCH_DIR = _PIPELINE_DIR.parent       # research/

for _p in (_RESEARCH_DIR,):
    _ps = str(_p)
    if _ps not in sys.path:
        sys.path.insert(0, _ps)

# ── Internal imports ───────────────────────────────────────────────────────────
from pipeline.config import _REPO_ROOT, ResearchConfig, load_config  # noqa: E402
from pipeline.strategy_runs import StrategyRunsMap, load_strategy_runs  # noqa: E402
from pipeline.stage3_diagnose import read_metrics_csv  # noqa: E402

# ── Dashboard schemas path ─────────────────────────────────────────────────────
_DASHBOARD_SCHEMAS = _REPO_ROOT / "dashboard" / "server"
if str(_DASHBOARD_SCHEMAS) not in sys.path:
    sys.path.insert(0, str(_DASHBOARD_SCHEMAS))

from schemas import SelectionManifest, SelectionEntry  # noqa: E402

# ─── Constants ────────────────────────────────────────────────────────────────

#: Scoring method identifier written into selection.json.
SELECTION_METHOD = "weighted_composite_score_v1"

#: Recommended actions that qualify a strategy for selection (not back_to_stage_2).
_ELIGIBLE_ACTIONS = {"proceed", "back_to_stage_4"}

#: Only strategies with this action are marked selected=True.
_SELECTED_ACTION = "proceed"


# ─── Data containers ──────────────────────────────────────────────────────────


@dataclasses.dataclass
class SelectionCheckResult:
    """Result of verifying the selection.json output."""

    ok: bool
    error: str | None = None


# ─── Pure-logic helpers (testable, no subprocess/filesystem side-effects) ─────


def clamp(value: float, lo: float, hi: float) -> float:
    """Clamp *value* to the interval [lo, hi].

    Args:
        value: The value to clamp.
        lo:    Lower bound (inclusive).
        hi:    Upper bound (inclusive).

    Returns:
        value clamped to [lo, hi].
    """
    return max(lo, min(hi, value))


def score_strategy(
    sharpe: float | None,
    drawdown: float | None,
    profit_factor: float | None,
    trade_count: float | None,
) -> float:
    """Compute the weighted composite score for a strategy.

    Scoring formula:
        score = 0.4 * clamp(sharpe / 1.5, 0.0, 2.0)
              + 0.3 * clamp(1.0 - |drawdown| / 0.10, 0.0, 2.0)
              + 0.2 * clamp(profit_factor / 1.5, 0.0, 2.0)
              + 0.1 * clamp(trade_count / 100.0, 0.0, 2.0)

    Missing (None) values contribute 0.0 for that component.

    Args:
        sharpe:        Sharpe ratio, or None if unavailable.
        drawdown:      Max drawdown (positive or negative fraction), or None.
        profit_factor: Profit factor, or None if unavailable.
        trade_count:   Number of trades, or None if unavailable.

    Returns:
        Composite score as a float in [0.0, 2.0] (theoretical max is 2.0 but
        practically ≤ 2.0 since each component is clamped to [0, 2]).
    """
    sharpe_contrib: float = 0.0
    if sharpe is not None:
        sharpe_contrib = 0.4 * clamp(sharpe / 1.5, 0.0, 2.0)

    drawdown_contrib: float = 0.0
    if drawdown is not None:
        drawdown_contrib = 0.3 * clamp(1.0 - abs(drawdown) / 0.10, 0.0, 2.0)

    pf_contrib: float = 0.0
    if profit_factor is not None:
        pf_contrib = 0.2 * clamp(profit_factor / 1.5, 0.0, 2.0)

    tc_contrib: float = 0.0
    if trade_count is not None:
        tc_contrib = 0.1 * clamp(trade_count / 100.0, 0.0, 2.0)

    return sharpe_contrib + drawdown_contrib + pf_contrib + tc_contrib


def is_eligible(
    diagnosis_path: Path,
    optimization_path: Path,
    metrics_csv_path: Path,
) -> tuple[bool, str]:
    """Check whether a strategy is eligible for stage-5 selection.

    A strategy is eligible if:
    1. diagnosis.json exists.
    2. optimization.json exists (stage 4 complete).
    3. metrics.csv exists (stage 3 complete).
    4. diagnosis recommended_action != "back_to_stage_2".

    Args:
        diagnosis_path:    Path to manifests/<strategy_id>/diagnosis.json.
        optimization_path: Path to manifests/<strategy_id>/optimization.json.
        metrics_csv_path:  Path to runs/<base_run>/artifacts/metrics.csv.

    Returns:
        Tuple of (eligible: bool, reason: str).
    """
    if not diagnosis_path.exists():
        return False, f"diagnosis.json missing: {diagnosis_path}"

    if not optimization_path.exists():
        return False, f"optimization.json missing: {optimization_path}"

    if not metrics_csv_path.exists():
        return False, f"metrics.csv missing: {metrics_csv_path}"

    # Read recommended_action from diagnosis.json.
    try:
        raw = diagnosis_path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        return False, f"diagnosis.json unreadable: {exc}"

    action = data.get("recommended_action", "")
    if action not in _ELIGIBLE_ACTIONS:
        return False, f"recommended_action={action!r} (must be in {sorted(_ELIGIBLE_ACTIONS)})"

    return True, "eligible"


def build_selection_entry(
    strategy_id: str,
    symbol: str,
    rank: int,
    score: float,
    selected: bool,
) -> dict:
    """Build a SelectionEntry dict.

    Args:
        strategy_id: Strategy identifier.
        symbol:      Trading symbol (short, e.g. 'BTC').
        rank:        Rank integer (1-based, 1 = best).
        score:       Composite score.
        selected:    True if selected for testnet promotion.

    Returns:
        Plain dict conforming to SelectionEntry schema.
    """
    return {
        "strategy_id": strategy_id,
        "symbol": symbol,
        "rank": rank,
        "score": score,
        "selected": selected,
    }


def build_selection_manifest(entries: list[dict], method: str) -> dict:
    """Build a SelectionManifest dict with the current UTC timestamp.

    Args:
        entries: List of SelectionEntry dicts (from build_selection_entry).
        method:  Scoring method string, e.g. SELECTION_METHOD.

    Returns:
        Plain dict conforming to SelectionManifest schema.
    """
    return {
        "schema_version": 1,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "method": method,
        "ranking": entries,
    }


def verify_selection(selection_path: Path) -> SelectionCheckResult:
    """Verify selection.json exists and validates against SelectionManifest schema.

    Args:
        selection_path: Path to research/manifests/selection.json.

    Returns:
        SelectionCheckResult with ok=True if valid; ok=False with error message otherwise.
    """
    if not selection_path.exists():
        return SelectionCheckResult(ok=False, error=f"selection.json missing: {selection_path}")

    try:
        raw = selection_path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        return SelectionCheckResult(ok=False, error=f"selection.json invalid JSON: {exc}")

    try:
        SelectionManifest.model_validate(data)
    except Exception as exc:  # noqa: BLE001
        return SelectionCheckResult(ok=False, error=f"selection.json schema validation failed: {exc}")

    return SelectionCheckResult(ok=True)


def compute_exit_code(results_ok: bool) -> int:
    """Return exit code 0 if results_ok is True; 1 otherwise.

    Args:
        results_ok: True if stage completed successfully.

    Returns:
        0 on success, 1 on failure.
    """
    return 0 if results_ok else 1


def print_summary(entries: list[dict], total_strategies: int) -> None:
    """Print a human-readable stage-5 selection summary to stdout.

    Args:
        entries:           List of SelectionEntry dicts that were ranked.
        total_strategies:  Total number of strategies evaluated (including ineligible).
    """
    eligible = len(entries)
    selected = sum(1 for e in entries if e.get("selected", False))

    print("\n" + "=" * 60)
    print("Stage-5 Selection output summary")
    print("=" * 60)
    print(f"  Total strategies evaluated : {total_strategies}")
    print(f"  Eligible for ranking       : {eligible}")
    print(f"  Selected (proceed)         : {selected}")
    print()

    if not entries:
        print("  (no strategies were ranked — selection.json has empty ranking)")
    else:
        print(f"  {'Rank':<6} {'Strategy':<40} {'Score':>8}  {'Selected'}")
        print(f"  {'-'*6} {'-'*40} {'-'*8}  {'-'*8}")
        for e in entries:
            rank = e.get("rank", "?")
            sid = e.get("strategy_id", "?")
            score = e.get("score", 0.0)
            sel = "YES" if e.get("selected", False) else "no"
            print(f"  {rank:<6} {sid:<40} {score:>8.4f}  {sel}")

    print()
    if eligible > 0:
        print("Stage 5 Selection PASSED: selection.json written and valid.")
    else:
        print("Stage 5 Selection: no eligible strategies — empty selection.json written.")
    print("=" * 60)


# ─── Stage orchestration ──────────────────────────────────────────────────────


def main() -> None:
    """Stage-5 Selection entry point: score, rank, write, verify, report, exit."""
    cfg: ResearchConfig = load_config()
    runs_map: StrategyRunsMap = load_strategy_runs()

    runs_root = _REPO_ROOT / "runs"
    manifests_dir = _REPO_ROOT / "research" / "manifests"
    selection_path = manifests_dir / "selection.json"

    print("=" * 60)
    print("Stage 5 — Strategy Selection (pure Python scoring)")
    print("=" * 60)
    print(f"Strategies   : {list(runs_map.entries.keys())}")
    print(f"Runs root    : {runs_root}")
    print(f"Manifests    : {manifests_dir}")
    print(f"Output       : {selection_path}")

    # ── Collect eligible strategies ───────────────────────────────────────────

    @dataclasses.dataclass
    class _Candidate:
        strategy_id: str
        symbol: str
        score: float
        selected: bool  # True if recommended_action == "proceed"

    total_strategies = len(runs_map.entries)
    candidates: list[_Candidate] = []

    for strategy_id, entry in runs_map.entries.items():
        print(f"\n  [{strategy_id}]")

        # Resolve paths.
        diagnosis_path = manifests_dir / strategy_id / "diagnosis.json"
        optimization_path = manifests_dir / strategy_id / "optimization.json"

        if entry.base_run is None:
            print(f"    [SKIP] base_run is null — skipping")
            total_strategies = total_strategies  # already counted
            continue

        metrics_csv_path = runs_root / entry.base_run / "artifacts" / "metrics.csv"

        # Check eligibility.
        eligible, reason = is_eligible(diagnosis_path, optimization_path, metrics_csv_path)
        if not eligible:
            print(f"    [SKIP] {reason}")
            continue

        # Read metrics.
        metrics = read_metrics_csv(metrics_csv_path)
        if metrics is None:
            print(f"    [SKIP] metrics.csv empty or unreadable")
            continue

        sharpe = metrics.get("sharpe")
        drawdown = metrics.get("max_drawdown")
        profit_factor = metrics.get("profit_factor")
        trade_count = metrics.get("trade_count")

        # Convert to float where possible.
        def _to_float(v: object) -> float | None:
            if v is None:
                return None
            try:
                return float(v)
            except (TypeError, ValueError):
                return None

        sharpe_f = _to_float(sharpe)
        drawdown_f = _to_float(drawdown)
        pf_f = _to_float(profit_factor)
        tc_f = _to_float(trade_count)

        score = score_strategy(sharpe_f, drawdown_f, pf_f, tc_f)

        # Determine selected flag from recommended_action.
        diagnosis_data = json.loads(diagnosis_path.read_text(encoding="utf-8"))
        action = diagnosis_data.get("recommended_action", "")
        selected_flag = action == _SELECTED_ACTION

        # Derive short symbol name from entry.symbol (may be "BTC-USDT-SWAP" etc.)
        # Use the first hyphen-delimited token or the whole string if no hyphen.
        symbol_short = entry.symbol.split("-")[0] if "-" in entry.symbol else entry.symbol

        candidates.append(_Candidate(
            strategy_id=strategy_id,
            symbol=symbol_short,
            score=score,
            selected=selected_flag,
        ))
        print(f"    [OK] score={score:.4f}, selected={selected_flag}, action={action}")

    # ── Sort by score descending and assign ranks ────────────────────────────
    candidates.sort(key=lambda c: c.score, reverse=True)

    entries: list[dict] = []
    for rank, candidate in enumerate(candidates, start=1):
        entry_dict = build_selection_entry(
            strategy_id=candidate.strategy_id,
            symbol=candidate.symbol,
            rank=rank,
            score=candidate.score,
            selected=candidate.selected,
        )
        entries.append(entry_dict)

    # ── Build and write selection.json ───────────────────────────────────────
    manifest_dict = build_selection_manifest(entries=entries, method=SELECTION_METHOD)

    manifests_dir.mkdir(parents=True, exist_ok=True)
    selection_path.write_text(
        json.dumps(manifest_dict, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\n  [OK] wrote {selection_path}")

    # ── Verify ───────────────────────────────────────────────────────────────
    check = verify_selection(selection_path)
    if not check.ok:
        print(f"  [ERROR] verification failed: {check.error}", file=sys.stderr)

    # ── Print summary and exit ────────────────────────────────────────────────
    print_summary(entries, total_strategies)
    sys.exit(compute_exit_code(check.ok))


if __name__ == "__main__":
    main()
