"""
research/pipeline/stage1_factors.py
────────────────────────────────────
Stage-1 runner: Factor Analysis.

Orchestrates the full stage-1 pipeline end-to-end:
  1. factor_extended.main() — IC/IR per factor, writes factor_<symbol>.json
  2. factor_regime.main()   — cross-regime IC enrichment, updates factor_<symbol>.json

Then verifies all expected outputs exist and validate against FactorManifest, reports
per-symbol success/failure, and exits non-zero if anything is missing or invalid.

Usage
-----
    # From repo root:
    python -m research.pipeline.stage1_factors

    # From research/ directory (preferred):
    python -m pipeline.stage1_factors

    # Direct script invocation:
    python research/pipeline/stage1_factors.py

Design note
-----------
This is the FIRST stage runner. It establishes the pattern for stages 2-5:
  - thin orchestration shell (no heavy computation here)
  - testable pure functions extracted for output verification + exit-code logic
  - main() calls the heavy workers then verify_outputs() then report_and_exit()

Do NOT abstract a shared base class prematurely. Let the pattern become visible
across 2-3 runners first.
"""

from __future__ import annotations

import sys
from pathlib import Path

# ── Path bootstrap ─────────────────────────────────────────────────────────────
# This module lives at <repo-root>/research/pipeline/stage1_factors.py.
# Bootstrap research/ and dashboard/server/ onto sys.path so imports work
# regardless of CWD or how this script is invoked.
_THIS_FILE = Path(__file__).resolve()
_PIPELINE_DIR = _THIS_FILE.parent          # research/pipeline/
_RESEARCH_DIR = _PIPELINE_DIR.parent       # research/
_REPO_ROOT = _RESEARCH_DIR.parent          # repo root
_DASHBOARD_SCHEMAS = _REPO_ROOT / "dashboard" / "server"

for _p in (_RESEARCH_DIR, _DASHBOARD_SCHEMAS):
    _ps = str(_p)
    if _ps not in sys.path:
        sys.path.insert(0, _ps)

# ── Standard library ───────────────────────────────────────────────────────────
import dataclasses
import json

# ── Internal imports ───────────────────────────────────────────────────────────
from pipeline.config import ResearchConfig, load_config
from schemas import FactorManifest


# ─── Pure-logic helpers (testable, network-free) ──────────────────────────────


@dataclasses.dataclass
class ManifestCheckResult:
    """Result of checking a single symbol's factor manifest."""

    symbol: str
    exists: bool
    valid: bool
    error: str | None = None  # validation error message if valid=False

    @property
    def ok(self) -> bool:
        return self.exists and self.valid


def check_manifest(manifests_dir: Path, symbol: str) -> ManifestCheckResult:
    """Check that factor_<symbol>.json exists and validates as FactorManifest.

    Args:
        manifests_dir: Path to the manifests directory.
        symbol:        Short lowercase symbol name, e.g. "btc".

    Returns:
        ManifestCheckResult describing whether the manifest is present and valid.
    """
    path = manifests_dir / f"factor_{symbol}.json"

    if not path.exists():
        return ManifestCheckResult(symbol=symbol, exists=False, valid=False, error="file not found")

    try:
        raw = path.read_text(encoding="utf-8")
        FactorManifest.model_validate_json(raw)
    except Exception as exc:  # noqa: BLE001
        return ManifestCheckResult(symbol=symbol, exists=True, valid=False, error=str(exc))

    return ManifestCheckResult(symbol=symbol, exists=True, valid=True)


def verify_outputs(
    manifests_dir: Path,
    symbols: list[str],
) -> list[ManifestCheckResult]:
    """Check all expected factor manifests after stage-1 runs.

    Args:
        manifests_dir: Path to research/manifests/.
        symbols:       List of short lowercase symbol names from config, e.g. ["btc", "eth"].

    Returns:
        List of ManifestCheckResult, one per symbol, in input order.
    """
    return [check_manifest(manifests_dir, sym) for sym in symbols]


def compute_exit_code(results: list[ManifestCheckResult]) -> int:
    """Return 0 if all results are ok, 1 otherwise.

    Args:
        results: List of ManifestCheckResult from verify_outputs().

    Returns:
        0 on full success; 1 if any manifest is missing or invalid.
    """
    return 0 if all(r.ok for r in results) else 1


def print_summary(results: list[ManifestCheckResult]) -> None:
    """Print a human-readable per-symbol summary to stdout.

    Args:
        results: List of ManifestCheckResult from verify_outputs().
    """
    print("\n" + "=" * 60)
    print("Stage-1 output verification summary")
    print("=" * 60)
    for r in results:
        status = "OK" if r.ok else "FAIL"
        if r.ok:
            msg = "manifest present and valid"
        elif not r.exists:
            msg = f"MISSING — {r.error}"
        else:
            msg = f"INVALID — {r.error}"
        print(f"  [{status}] {r.symbol}: {msg}")

    total = len(results)
    passed = sum(1 for r in results if r.ok)
    print(f"\n{passed}/{total} symbols passed.")
    if passed < total:
        print("Stage 1 FAILED: one or more manifests are missing or invalid.")
    else:
        print("Stage 1 PASSED: all manifests present and valid.")
    print("=" * 60)


# ─── Stage orchestration (thin shell, not unit-tested) ────────────────────────


def _run_stage1_work() -> None:
    """Invoke factor_extended.main() then factor_regime.main().

    Both main() functions call load_config() internally and loop over all config
    symbols — so this runner does NOT re-pass config; it simply calls them.

    Why import instead of subprocess?
      - Faster (no interpreter startup) and easier to surface tracebacks.
      - Both modules already guard against re-adding paths (idempotent bootstrap).
      - Both main() are clean: they do no work at import time.
    """
    print("\n[stage1] Step 1/2: factor_extended — computing IC/IR per factor")
    print("-" * 60)
    import factor_extended  # noqa: PLC0415 (import inside function is intentional)
    factor_extended.main()

    print("\n[stage1] Step 2/2: factor_regime — cross-regime IC enrichment")
    print("-" * 60)
    import factor_regime  # noqa: PLC0415
    factor_regime.main()


def main() -> None:
    """Stage-1 entry point: orchestrate, verify, report, exit."""
    cfg: ResearchConfig = load_config()
    symbols = cfg.symbol_names()
    manifests_dir = _REPO_ROOT / "research" / "manifests"

    print("=" * 60)
    print("Stage 1 — Factor Analysis")
    print("=" * 60)
    print(f"Config: period={cfg.period}d  horizons={list(cfg.horizons_h)}  symbols={symbols}")
    print(f"Output directory: {manifests_dir}")

    # Run the two analysis scripts
    _run_stage1_work()

    # Verify outputs
    results = verify_outputs(manifests_dir, symbols)
    print_summary(results)

    exit_code = compute_exit_code(results)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
