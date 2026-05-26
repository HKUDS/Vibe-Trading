"""
research/pipeline/stage3_backtest.py
──────────────────────────────────────
Stage-3 runner: Backtest Execution.

For each strategy in strategy_runs.json this runner:
  1. Loads config via pipeline.config.load_config().
  2. Reads strategy_runs.json to get all strategies + their run directory names.
  3. For each non-null run (base_run, regime_runs values, oos_runs items):
     - Gates on stage1 factor manifest existing for the symbol.
     - Creates the run directory under <repo_root>/runs/<run_name>/.
     - Writes config.json inside the run dir.
     - Copies or generates code/signal_engine.py.
     - Calls python -m backtest.runner <run_dir> via subprocess.
  4. Verifies artifacts exist after each call.
  5. Prints per-run summary; exits 0 on success / non-zero on failure.

Usage
-----
    # From repo root:
    python -m research.pipeline.stage3_backtest

    # From research/ directory (preferred):
    python -m pipeline.stage3_backtest

    # Direct script invocation:
    python research/pipeline/stage3_backtest.py

Design note
-----------
Follows the stage-runner pattern from stage2_5_regime.py exactly:
    config_load → stage_work → pure testable verification → summary + exit code.

``_REPO_ROOT`` is imported from ``pipeline.config`` (not recomputed here) so
all stages agree on exactly one repo-root definition.
"""

from __future__ import annotations

import dataclasses
import json
import re
import shutil
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Iterator

# ── Path bootstrap ─────────────────────────────────────────────────────────────
# This module lives at <repo-root>/research/pipeline/stage3_backtest.py.
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
from pipeline.config import _REPO_ROOT, ResearchConfig, SymbolConfig, load_config  # noqa: E402
from pipeline.strategy_runs import StrategyRunsEntry, StrategyRunsMap, load_strategy_runs  # noqa: E402

# ── Agent / backtest path ──────────────────────────────────────────────────────
_REPO_ROOT_STR = str(_REPO_ROOT)
if _REPO_ROOT_STR not in sys.path:
    sys.path.insert(0, _REPO_ROOT_STR)


# ─── Data containers ──────────────────────────────────────────────────────────

@dataclasses.dataclass
class BacktestRunResult:
    """Result of one backtest run attempt."""

    run_name: str
    ok: bool
    error: str | None = None  # description if ok=False


# ─── Pure-logic helpers (testable, network-free) ──────────────────────────────


def symbol_to_short(symbol: str) -> str:
    """Derive a short lowercase symbol name from an exchange ticker.

    "BTC-USDT-SWAP" -> "btc"
    "ETH-USDT-SWAP" -> "eth"

    Args:
        symbol: Exchange ticker string, e.g. "BTC-USDT-SWAP".

    Returns:
        Short lowercase first component, e.g. "btc".
    """
    return symbol.split("-")[0].lower()


def build_run_config(symbol: str, cfg: ResearchConfig, today: date | None = None) -> dict:
    """Build the config.json dict for a backtest run.

    The schema matches agent/backtest/runner.py BacktestConfigSchema:
    {
        "codes": ["BTC-USDT-SWAP"],
        "start_date": "2022-01-01",
        "end_date": "2024-12-31",
        "source": "okx",
        "interval": "1H",
        "engine": "daily"
    }

    - codes: list with the strategy's symbol.
    - start_date / end_date: end=today, start=today minus period days.
    - source: always "okx" for crypto strategies.
    - interval: from research_config.yaml's interval field.
    - engine: always "daily".

    Args:
        symbol: Exchange ticker, e.g. "BTC-USDT-SWAP".
        cfg:    ResearchConfig loaded from research_config.yaml.
        today:  Reference date for end_date (defaults to date.today()).

    Returns:
        Dict conforming to BacktestConfigSchema (JSON-serialisable).
    """
    if today is None:
        today = date.today()
    start = today - timedelta(days=cfg.period)
    return {
        "codes": [symbol],
        "start_date": start.isoformat(),
        "end_date": today.isoformat(),
        "source": "okx",
        "interval": cfg.interval,
        "engine": "daily",
    }


def find_signal_engine(strategies_code_dir: Path, strategy_id: str) -> Path | None:
    """Look for an existing signal_engine.py for a strategy.

    Searches ``strategies_code_dir / strategy_id / signal_engine.py``.

    Args:
        strategies_code_dir: Path to research/strategies/code/.
        strategy_id:         Strategy identifier, e.g. "btc_s1_multifactor_contrarian".

    Returns:
        Path to signal_engine.py if found, else None.
    """
    candidate = strategies_code_dir / strategy_id / "signal_engine.py"
    return candidate if candidate.exists() else None


def build_stub_signal_engine() -> str:
    """Generate a minimal no-op SignalEngine stub.

    The stub is valid Python that passes the AST validator in
    agent/backtest/runner.py:_validate_signal_engine_source().

    Returns:
        String containing the stub Python source.
    """
    return (
        "import pandas as pd\n"
        "\n"
        "\n"
        "class SignalEngine:\n"
        "    def generate(self, data_map):\n"
        "        signals = {}\n"
        "        for code, df in data_map.items():\n"
        "            if isinstance(df, pd.DataFrame) and not df.empty:\n"
        "                signals[code] = pd.Series(0.0, index=df.index)\n"
        "        return signals\n"
    )


def verify_run_artifacts(run_dir: Path) -> BacktestRunResult:
    """Verify that a backtest run produced at least one .csv in artifacts/.

    Args:
        run_dir: Path to the run directory (e.g. <repo_root>/runs/btc_s1_base/).

    Returns:
        BacktestRunResult with ok=True if artifacts/ exists and contains a .csv.
    """
    run_name = run_dir.name
    artifacts_dir = run_dir / "artifacts"

    if not artifacts_dir.exists():
        return BacktestRunResult(
            run_name=run_name,
            ok=False,
            error=f"artifacts directory missing: {artifacts_dir}",
        )

    csv_files = list(artifacts_dir.glob("*.csv"))
    if not csv_files:
        return BacktestRunResult(
            run_name=run_name,
            ok=False,
            error=f"no .csv files found in {artifacts_dir}",
        )

    return BacktestRunResult(run_name=run_name, ok=True)


def compute_exit_code(results: list[BacktestRunResult]) -> int:
    """Return 0 if at least one result was produced and all are ok; 1 otherwise.

    An empty result list is a failure: the stage produced no run results.

    Args:
        results: List of BacktestRunResult from verify_run_artifacts() calls.

    Returns:
        0 on full success (>=1 run, all ok); 1 otherwise.
    """
    if not results:
        return 1
    return 0 if all(r.ok for r in results) else 1


def list_pending_runs(
    strategy_id: str,
    entry: StrategyRunsEntry,
) -> list[tuple[str, str, str, str]]:
    """List all backtest runs to process from a strategy entry.

    Processes base_run, regime_runs values, and oos_runs items.
    Does NOT include stress_runs or sweep_run (those belong to other tools).
    Skips null/None values.

    Args:
        strategy_id: Strategy identifier string.
        entry:       StrategyRunsEntry from strategy_runs.json.

    Returns:
        List of (run_name, strategy_id, symbol, role) tuples.
        Role is one of: "base", "<regime_label>" (e.g. "bull"), or the oos
        run_name itself (e.g. "eth_s1_oos_2023") — caller parses year from it.
    """
    runs: list[tuple[str, str, str, str]] = []

    if entry.base_run is not None:
        runs.append((entry.base_run, strategy_id, entry.symbol, "base"))

    for regime_label, run_name in entry.regime_runs.items():
        runs.append((run_name, strategy_id, entry.symbol, regime_label))

    for run_name in entry.oos_runs:
        runs.append((run_name, strategy_id, entry.symbol, run_name))

    return runs


# ── Per-run window overrides (regime / oos slicing) ───────────────────────────


_OOS_YEAR_RE = re.compile(r"oos_(\d{4})$")


def load_regime_windows(manifests_dir: Path, short: str) -> dict[str, tuple[str, str]]:
    """Read regime_<short>.json breakdown, return longest contiguous span per label.

    Args:
        manifests_dir: research/manifests/
        short:         Symbol short, e.g. "eth"

    Returns:
        {regime_label: (start_iso, end_iso)} for each label that has data.
        Empty dict if regime file missing.
    """
    path = manifests_dir / f"regime_{short}.json"
    if not path.exists():
        return {}

    data = json.loads(path.read_text(encoding="utf-8"))
    breakdown = data.get("breakdown", [])
    if not breakdown:
        return {}

    # For each label, find longest contiguous run of consecutive days.
    best: dict[str, tuple[str, str, int]] = {}  # label -> (start, end, length)
    current_label: str | None = None
    current_start: str | None = None
    current_len = 0
    prev_date: str | None = None

    for row in breakdown:
        label = row.get("regime")
        d = row.get("date")
        if label != current_label:
            if current_label is not None and current_start is not None:
                prior = best.get(current_label)
                if prior is None or current_len > prior[2]:
                    best[current_label] = (current_start, prev_date, current_len)
            current_label = label
            current_start = d
            current_len = 1
        else:
            current_len += 1
        prev_date = d

    if current_label is not None and current_start is not None:
        prior = best.get(current_label)
        if prior is None or current_len > prior[2]:
            best[current_label] = (current_start, prev_date, current_len)

    return {lbl: (s, e) for lbl, (s, e, _n) in best.items()}


def apply_run_window_overrides(
    config_dict: dict,
    role: str,
    regime_windows: dict[str, tuple[str, str]],
) -> dict:
    """Mutate-and-return config_dict with per-role start_date/end_date overrides.

    Role mapping:
      - "base"                  → unchanged (full window)
      - "bull"/"bear"/"neutral" → longest contiguous regime span from regime_windows
      - "*_oos_YYYY"            → YYYY-01-01 to YYYY-12-31

    Unknown roles → unchanged.
    """
    if role == "base":
        return config_dict

    if role in regime_windows:
        start, end = regime_windows[role]
        config_dict["start_date"] = start
        config_dict["end_date"] = end
        return config_dict

    m = _OOS_YEAR_RE.search(role)
    if m:
        year = m.group(1)
        config_dict["start_date"] = f"{year}-01-01"
        config_dict["end_date"] = f"{year}-12-31"
        return config_dict

    return config_dict


def print_summary(results: list[BacktestRunResult]) -> None:
    """Print a human-readable per-run summary to stdout.

    Args:
        results: List of BacktestRunResult from run execution.
    """
    print("\n" + "=" * 60)
    print("Stage-3 output verification summary")
    print("=" * 60)
    if not results:
        print("  (no backtest runs were attempted)")

    for r in results:
        status = "OK" if r.ok else "FAIL"
        if r.ok:
            msg = "artifacts present"
        else:
            msg = f"FAILED — {r.error}"
        print(f"  [{status}] {r.run_name}: {msg}")

    total = len(results)
    passed = sum(1 for r in results if r.ok)
    print(f"\n{passed}/{total} runs passed.")
    if total == 0 or passed < total:
        print("Stage 3 FAILED: no runs were attempted or one or more backtest runs failed.")
    else:
        print("Stage 3 PASSED: all backtest runs produced artifacts.")
    print("=" * 60)


# ─── Per-run orchestration (thin shell, subprocess calls) ─────────────────────


def _setup_run_dir(
    run_dir: Path,
    config_dict: dict,
    strategies_code_dir: Path,
    strategy_id: str,
) -> None:
    """Create run directory, write config.json, install signal_engine.py.

    This function IS intentionally NOT unit-tested in isolation because it
    performs filesystem I/O (mkdir, write, copy). The pure helpers it calls
    (build_run_config, find_signal_engine, build_stub_signal_engine) are
    individually tested.

    Args:
        run_dir:              Absolute path to the run directory to create.
        config_dict:          Dict to write as config.json.
        strategies_code_dir:  research/strategies/code/ — checked for existing signal_engine.py.
        strategy_id:          Strategy identifier used to look up signal_engine.py.
    """
    # Create run directory and code subdirectory
    run_dir.mkdir(parents=True, exist_ok=True)
    code_dir = run_dir / "code"
    code_dir.mkdir(parents=True, exist_ok=True)

    # Write config.json
    config_path = run_dir / "config.json"
    config_path.write_text(json.dumps(config_dict, indent=2, ensure_ascii=False), encoding="utf-8")

    # Install signal_engine.py: copy if found, else write stub
    se_source = find_signal_engine(strategies_code_dir, strategy_id)
    se_dest = code_dir / "signal_engine.py"
    if se_source is not None:
        shutil.copy2(se_source, se_dest)
        print(f"      [signal_engine] copied from {se_source.relative_to(_REPO_ROOT)}")
    else:
        stub = build_stub_signal_engine()
        se_dest.write_text(stub, encoding="utf-8")
        print(f"      [signal_engine] generated stub at {se_dest.relative_to(_REPO_ROOT)}")


def _run_backtest(run_dir: Path) -> subprocess.CompletedProcess:
    """Invoke python -m backtest.runner <run_dir> as a subprocess.

    Args:
        run_dir: Absolute path to the run directory.

    Returns:
        CompletedProcess with stdout, stderr, returncode.
    """
    return subprocess.run(
        [sys.executable, "-m", "backtest.runner", str(run_dir)],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=600,
    )


def _run_backtest_for_run(
    run_name: str,
    strategy_id: str,
    symbol: str,
    role: str,
    cfg: ResearchConfig,
    runs_root: Path,
    strategies_code_dir: Path,
    manifests_dir: Path,
) -> BacktestRunResult:
    """Gate, scaffold, invoke, and verify one backtest run.

    Args:
        run_name:             The run directory name (e.g. "btc_s1_base").
        strategy_id:          Strategy identifier.
        symbol:               Exchange ticker, e.g. "BTC-USDT-SWAP".
        cfg:                  ResearchConfig.
        runs_root:            <repo_root>/runs/.
        strategies_code_dir:  research/strategies/code/.
        manifests_dir:        research/manifests/.

    Returns:
        BacktestRunResult for this run.
    """
    short = symbol_to_short(symbol)

    print(f"\n{'='*60}")
    print(f"[stage3] Run: {run_name}  (strategy: {strategy_id}  symbol: {symbol})")
    print(f"{'='*60}")

    # ── Gate: stage1 factor manifest must exist and be valid ──────────────────
    # Local import to avoid circular imports at module level.
    from pipeline.stage2_5_regime import check_factor_manifest_gate  # noqa: PLC0415
    try:
        check_factor_manifest_gate(manifests_dir, short)
    except (FileNotFoundError, ValueError) as exc:
        msg = str(exc)
        print(f"  [SKIP] {msg}")
        return BacktestRunResult(run_name=run_name, ok=False, error=msg)

    # ── Setup run directory ────────────────────────────────────────────────────
    run_dir = runs_root / run_name
    config_dict = build_run_config(symbol=symbol, cfg=cfg)
    regime_windows = load_regime_windows(manifests_dir, short)
    config_dict = apply_run_window_overrides(config_dict, role, regime_windows)
    print(f"  [1/3] Creating run dir: {run_dir}  (role={role}, window={config_dict['start_date']}..{config_dict['end_date']})")
    _setup_run_dir(run_dir, config_dict, strategies_code_dir, strategy_id)

    # ── Invoke backtest runner ─────────────────────────────────────────────────
    print(f"  [2/3] Invoking backtest runner …")
    try:
        proc = _run_backtest(run_dir)
    except subprocess.TimeoutExpired:
        msg = "backtest runner timed out after 600s"
        print(f"  [FAIL] {msg}")
        return BacktestRunResult(run_name=run_name, ok=False, error=msg)
    except Exception as exc:  # noqa: BLE001
        msg = f"subprocess error: {exc}"
        print(f"  [FAIL] {msg}")
        return BacktestRunResult(run_name=run_name, ok=False, error=msg)

    if proc.stdout:
        print(proc.stdout.rstrip())
    if proc.returncode != 0:
        msg = f"backtest runner exited with code {proc.returncode}"
        if proc.stderr:
            msg += f": {proc.stderr.strip()[:300]}"
        print(f"  [FAIL] {msg}")
        return BacktestRunResult(run_name=run_name, ok=False, error=msg)

    # ── Verify artifacts ───────────────────────────────────────────────────────
    print(f"  [3/3] Verifying artifacts …")
    result = verify_run_artifacts(run_dir)
    if result.ok:
        print(f"  [OK] artifacts present in {run_dir / 'artifacts'}")
    else:
        print(f"  [FAIL] {result.error}")
    return result


def main() -> None:
    """Stage-3 entry point: orchestrate, verify, report, exit."""
    cfg: ResearchConfig = load_config()
    runs_map: StrategyRunsMap = load_strategy_runs()

    runs_root = _REPO_ROOT / "runs"
    manifests_dir = _REPO_ROOT / "research" / "manifests"
    strategies_code_dir = _REPO_ROOT / "research" / "strategies" / "code"

    print("=" * 60)
    print("Stage 3 — Backtest Execution")
    print("=" * 60)
    print(f"Config: period={cfg.period}d  interval={cfg.interval}  engine={cfg.engine}")
    print(f"Strategies: {list(runs_map.entries.keys())}")
    print(f"Runs root:  {runs_root}")

    all_results: list[BacktestRunResult] = []

    # Check that at least one run exists across all strategies
    all_pending: list[tuple[str, str, str, str]] = []
    for strategy_id, entry in runs_map.entries.items():
        all_pending.extend(list_pending_runs(strategy_id, entry))
    if not all_pending:
        print("[stage3] WARNING: no pending runs found in strategy_runs.json — nothing to run.")
        sys.exit(1)

    for strategy_id, entry in runs_map.entries.items():
        pending = list_pending_runs(strategy_id, entry)
        if not pending:
            print(f"\n[skip] {strategy_id}: no pending runs")
            continue

        for run_name, sid, symbol, role in pending:
            try:
                result = _run_backtest_for_run(
                    run_name=run_name,
                    strategy_id=sid,
                    symbol=symbol,
                    role=role,
                    cfg=cfg,
                    runs_root=runs_root,
                    strategies_code_dir=strategies_code_dir,
                    manifests_dir=manifests_dir,
                )
            except Exception as exc:  # noqa: BLE001
                result = BacktestRunResult(
                    run_name=run_name,
                    ok=False,
                    error=f"unexpected error: {exc}",
                )
                print(f"  [ERROR] {run_name}: {exc}")
            all_results.append(result)

    print_summary(all_results)
    sys.exit(compute_exit_code(all_results))


if __name__ == "__main__":
    main()
