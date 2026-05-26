"""
research/pipeline/stage2b_compile_signal.py
────────────────────────────────────────────
Stage-2b runner: Signal Engine Compilation.

For each strategy in strategy_runs.json this runner:
  1. Reads the strategy's spec_yaml path.
  2. Validates the YAML against StrategySpec.
  3. Compiles the spec to a signal_engine.py via compile_strategy().
  4. Writes signal_engine.py + a smoke-test (test_signal_engine.py) into
     research/strategies/code/<strategy_id>/.
  5. Runs pytest on the smoke test to verify the generated engine imports
     and produces valid signal output.

Manual escape hatch: if signal_engine.py already contains the comment
``# manual: do-not-overwrite`` in its first 5 lines, the file is skipped
(so hand-tuned engines survive pipeline re-runs).

Usage
-----
    # From repo root:
    python -m research.pipeline.stage2b_compile_signal

    # With filters:
    python -m research.pipeline.stage2b_compile_signal --strategy eth_s1_multi_factor_consensus
    python -m research.pipeline.stage2b_compile_signal --dry-run
"""

from __future__ import annotations

import dataclasses
import hashlib
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

# ── Path bootstrap ─────────────────────────────────────────────────────────────
# Mirror stage2_strategies.py exactly.
_THIS_FILE = Path(__file__).resolve()
_PIPELINE_DIR = _THIS_FILE.parent          # research/pipeline/
_RESEARCH_DIR = _PIPELINE_DIR.parent       # research/

for _p in (_RESEARCH_DIR,):
    _ps = str(_p)
    if _ps not in sys.path:
        sys.path.insert(0, _ps)

# ── Extend sys.path for dashboard/server/ and agent/ ──────────────────────────
from pipeline.config import _REPO_ROOT  # noqa: E402  (bootstrap must be first)

_DASHBOARD_SCHEMAS = _REPO_ROOT / "dashboard" / "server"
if str(_DASHBOARD_SCHEMAS) not in sys.path:
    sys.path.insert(0, str(_DASHBOARD_SCHEMAS))

_AGENT_DIR = _REPO_ROOT / "agent"
if str(_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENT_DIR))

# ── Third-party ────────────────────────────────────────────────────────────────
import yaml  # noqa: E402

# ── Internal imports ───────────────────────────────────────────────────────────
from pipeline.strategy_runs import load_strategy_runs  # noqa: E402
from schemas import StrategySpec  # noqa: E402  (dashboard/server/schemas.py)
from lib.signal_compiler import compile_strategy  # noqa: E402


# ─── Data containers ──────────────────────────────────────────────────────────


@dataclasses.dataclass
class CompileResult:
    """Result of compiling one strategy's signal engine."""

    strategy_id: str
    status: str  # "ok" | "skip" | "fail"
    message: str = ""


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _check_manual_escape_hatch(path: Path) -> bool:
    """Return True if signal_engine.py contains the do-not-overwrite marker.

    Only the first 5 lines are examined, so the marker must appear near the top.

    Args:
        path: Path to signal_engine.py (may not exist yet).

    Returns:
        True if the marker ``# manual: do-not-overwrite`` appears in the first
        5 lines; False if the file does not exist or the marker is absent.
    """
    if not path.exists():
        return False
    try:
        with path.open("r", encoding="utf-8") as fh:
            for _ in range(5):
                line = fh.readline()
                if not line:
                    break
                if "# manual: do-not-overwrite" in line:
                    return True
    except OSError:
        return False
    return False


def _extract_factor_names(spec: StrategySpec) -> list[str]:
    """Return the list of factor keys referenced by stage1: indicators.

    For an indicator with source ``"stage1:funding_rate"``, the factor name is
    ``"funding_rate"``.

    Args:
        spec: Validated StrategySpec.

    Returns:
        Sorted list of factor name strings.
    """
    names: list[str] = []
    for ind_spec in spec.indicators.values():
        src = ind_spec.source  # e.g. "stage1:funding_rate"
        if ":" in src:
            names.append(src.split(":", 1)[1])
        else:
            names.append(src)
    return names


def _render_smoke_test(spec: StrategySpec, strategy_id: str) -> str:  # noqa: ARG001
    """Generate test_signal_engine.py content for a compiled signal engine.

    The test is designed to run with ``pytest`` from the strategy's code
    directory (``research/strategies/code/<strategy_id>/``), where
    ``signal_engine.py`` lives alongside it and can be imported directly.

    Args:
        spec: Validated StrategySpec — used to extract indicator/factor names
              and the trading symbol.
        strategy_id: Strategy identifier (currently unused in the template but
                     kept for future reference / parametrisation).

    Returns:
        Python source string for test_signal_engine.py.
    """
    factor_names = _extract_factor_names(spec)
    symbol = spec.symbol

    # Build the factor_names list literal for embedding in the test source.
    factor_names_repr = repr(factor_names)

    return dedent(f"""\
        \"\"\"Smoke test for the compiled signal_engine.py.

        Run from the strategy code directory:
            pytest test_signal_engine.py -q
        \"\"\"
        from __future__ import annotations

        import sys
        from pathlib import Path

        import numpy as np
        import pandas as pd
        import pytest
        from unittest.mock import patch

        # Ensure research/ is importable when pytest runs from the code directory.
        _HERE = Path(__file__).resolve()
        _CODE_DIR = _HERE.parent        # research/strategies/code/<id>/
        _REPO_ROOT = _CODE_DIR.parents[3]
        _RESEARCH_DIR = _REPO_ROOT / "research"
        for _p in (str(_RESEARCH_DIR), str(_REPO_ROOT)):
            if _p not in sys.path:
                sys.path.insert(0, _p)


        def _make_ohlcv(n: int = 200) -> pd.DataFrame:
            idx = pd.date_range("2023-01-01", periods=n, freq="h", tz="UTC")
            rng = np.random.default_rng(42)
            return pd.DataFrame({{
                "open":   rng.standard_normal(n).cumsum() + 1800,
                "high":   rng.standard_normal(n).cumsum() + 1810,
                "low":    rng.standard_normal(n).cumsum() + 1790,
                "close":  rng.standard_normal(n).cumsum() + 1800,
                "volume": np.abs(rng.standard_normal(n)) * 1e6,
            }}, index=idx)


        def _make_factor_df(n: int = 200, factor_names=None) -> pd.DataFrame:
            idx = pd.date_range("2023-01-01", periods=n, freq="h", tz="UTC")
            factor_names = factor_names or ["factor_a"]
            rng = np.random.default_rng(0)
            data = {{name: rng.standard_normal(n) for name in factor_names}}
            return pd.DataFrame(data, index=idx)


        @pytest.fixture
        def ohlcv() -> pd.DataFrame:
            return _make_ohlcv()


        def test_generate_returns_series(ohlcv):
            factor_names = {factor_names_repr}
            factor_df = _make_factor_df(factor_names=factor_names)
            with patch("lib.factor_io.load_factor_values", return_value=factor_df):
                from signal_engine import SignalEngine  # noqa: PLC0415
                engine = SignalEngine()
                result = engine.generate({{"{symbol}": ohlcv}})
            assert isinstance(result, dict)
            assert "{symbol}" in result
            signal = result["{symbol}"]
            assert isinstance(signal, pd.Series)
            assert len(signal) == len(ohlcv)
            # Values must be a subset of {{-1.0, 0.0, 1.0}} (allow NaN in warmup)
            non_nan = signal.dropna()
            assert set(non_nan.unique()).issubset({{-1.0, 0.0, 1.0}})
    """)


# ─── Per-strategy compiler ────────────────────────────────────────────────────


def _compile_one(
    strategy_id: str,
    entry: dict,
    *,
    dry_run: bool = False,
) -> CompileResult:
    """Compile the signal engine for one strategy.

    Steps:
      1. Resolve file paths.
      2. Check manual escape hatch.
      3. Read and validate the strategy YAML.
      4. Compile to signal_engine.py source.
      5. Write files (unless --dry-run).
      6. Run pytest smoke test (unless --dry-run).

    Args:
        strategy_id: Strategy identifier key from strategy_runs.json.
        entry:       Raw dict from strategy_runs.json for this strategy.
        dry_run:     If True, render and validate but do not write any files
                     and do not execute pytest.

    Returns:
        CompileResult with status "ok", "skip", or "fail".
    """
    try:
        # 1. Resolve paths.
        raw_spec_yaml = entry["spec_yaml"]
        # spec_yaml is repo-relative (e.g. "research/strategies/strategy_X.yaml").
        spec_yaml_path = (_REPO_ROOT / raw_spec_yaml).resolve()
        code_dir = _REPO_ROOT / "research" / "strategies" / "code" / strategy_id
        signal_engine_path = code_dir / "signal_engine.py"
        test_path = code_dir / "test_signal_engine.py"

        # 2. Check manual escape hatch.
        if _check_manual_escape_hatch(signal_engine_path):
            print(
                f"\033[33m[stage2b] {strategy_id}: SKIP — "
                "manual escape hatch present\033[0m"
            )
            return CompileResult(strategy_id, "skip", "manual escape hatch")

        # 3. Read and validate the YAML.
        if not spec_yaml_path.exists():
            raise FileNotFoundError(
                f"spec_yaml not found: {spec_yaml_path}\n"
                f"(entry['spec_yaml'] = {raw_spec_yaml!r})"
            )
        content = spec_yaml_path.read_text(encoding="utf-8")
        yaml_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        raw_doc = yaml.safe_load(content)
        spec = StrategySpec.model_validate(raw_doc)

        # 4. Compile.
        source = compile_strategy(spec, yaml_hash=yaml_hash)

        if dry_run:
            print(
                f"\033[36m[stage2b] {strategy_id}: DRY-RUN — "
                "compiled OK, files not written\033[0m"
            )
            return CompileResult(strategy_id, "ok", "dry-run")

        # 5. Write signal_engine.py.
        code_dir.mkdir(parents=True, exist_ok=True)
        signal_engine_path.write_text(source, encoding="utf-8")

        # 6. Write test_signal_engine.py.
        test_source = _render_smoke_test(spec, strategy_id)
        test_path.write_text(test_source, encoding="utf-8")

        # 7. Run pytest.
        result = subprocess.run(
            [sys.executable, "-m", "pytest", str(test_path), "-q", "--tb=short"],
            capture_output=True,
            text=True,
            cwd=str(code_dir),
        )
        if result.returncode != 0:
            output = (result.stdout + "\n" + result.stderr).strip()
            raise RuntimeError(f"pytest smoke test failed:\n{output}")

        return CompileResult(strategy_id, "ok")

    except Exception as exc:  # noqa: BLE001
        return CompileResult(strategy_id, "fail", str(exc))


# ─── Main ─────────────────────────────────────────────────────────────────────


def main() -> None:
    """Stage-2b entry point: compile signal engines, run smoke tests, report."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Stage-2b: compile strategy YAML → signal_engine.py"
    )
    parser.add_argument(
        "--strategy",
        metavar="STRATEGY_ID",
        help="Only compile this strategy (by strategy_id).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Render and validate but do not write files or run pytest.",
    )
    args = parser.parse_args()

    runs_map = load_strategy_runs()
    entries = dict(runs_map.entries)  # strategy_id -> StrategyRunsEntry

    if args.strategy:
        if args.strategy not in entries:
            print(
                f"\033[31m[stage2b] Unknown strategy_id: {args.strategy!r}\033[0m",
                file=sys.stderr,
            )
            sys.exit(1)
        entries = {args.strategy: entries[args.strategy]}

    print("=" * 60)
    print("Stage 2b — Signal Engine Compilation")
    print("=" * 60)

    results: list[CompileResult] = []
    for strategy_id, entry in entries.items():
        # StrategyRunsEntry is a frozen dataclass with MappingProxyType fields;
        # dataclasses.asdict() cannot deep-copy MappingProxyType, so we
        # convert manually to a plain dict that _compile_one expects.
        entry_dict = {
            "symbol": entry.symbol,
            "spec_yaml": entry.spec_yaml,
            "base_run": entry.base_run,
            "regime_runs": dict(entry.regime_runs),
            "stress_runs": dict(entry.stress_runs),
            "oos_runs": list(entry.oos_runs),
            "sweep_run": entry.sweep_run,
        }
        result = _compile_one(strategy_id, entry_dict, dry_run=args.dry_run)
        results.append(result)

    # Print summary.
    print()
    any_fail = False
    for r in results:
        if r.status == "ok":
            label = "(dry-run) " if r.message == "dry-run" else ""
            print(f"\033[32m[stage2b] {r.strategy_id}: OK {label}\033[0m")
        elif r.status == "skip":
            print(f"\033[33m[stage2b] {r.strategy_id}: SKIP\033[0m")
        else:
            print(f"\033[31m[stage2b] {r.strategy_id}: FAIL — {r.message}\033[0m")
            any_fail = True

    total = len(results)
    n_ok = sum(1 for r in results if r.status == "ok")
    n_skip = sum(1 for r in results if r.status == "skip")
    n_fail = sum(1 for r in results if r.status == "fail")
    print(
        f"\nSummary: {n_ok} OK / {n_skip} skipped / {n_fail} failed "
        f"({total} total)"
    )

    if any_fail:
        sys.exit(1)


if __name__ == "__main__":
    main()
