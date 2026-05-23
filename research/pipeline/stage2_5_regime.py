"""
research/pipeline/stage2_5_regime.py
──────────────────────────────────────
Stage-2.5 runner: Market Regime Detection.

Per symbol in research_config.yaml this runner:
  1. Loads config via pipeline.config.load_config().
  2. Fetches daily close (from hourly OKX candles) and funding rate history.
  3. Computes market regime labels via lib.regime.compute_regime().
  4. Writes research/manifests/regime_<symbol>.json with the structured output.
  5. Verifies all outputs exist and are well-formed.
  6. Prints a per-symbol summary; exits 0 on success, non-zero on failure.

Usage
-----
    # From repo root:
    python -m research.pipeline.stage2_5_regime

    # From research/ directory (preferred):
    python -m pipeline.stage2_5_regime

    # Direct script invocation:
    python research/pipeline/stage2_5_regime.py

Design note
-----------
This follows the stage-runner pattern from stage1_factors.py and
stage2_strategies.py: config load -> stage work -> pure testable verification
-> summary + exit code.

``_REPO_ROOT`` is imported from ``pipeline.config`` (not recomputed here) so
all stages agree on exactly one repo-root definition.

──────────────────────────────────────────────────────────────────────────────
regime_<symbol>.json  —  schema (version 1)
──────────────────────────────────────────────────────────────────────────────
{
    "schema_version": 1,

    "symbol": "BTC",           // uppercase symbol short name

    "generated_at": "<ISO-8601 UTC>",

    "detector_params": {       // the compute_regime() kwargs actually used
        "ema_window": 200,
        "slope_window": 20,
        "funding_window_hours": 720,
        "funding_mania_threshold": 0.0003,
        "bear_persistence_days": 20,
        "bear_persistence_threshold": 0.55
    },

    "current_regime": "bull",  // regime label on the last daily bar;
                               //   one of "bull" | "bear" | "neutral"

    "distribution": {          // fraction of total daily bars in each regime
        "bull": 0.42,          //   (float, 0-1; sums to 1.0; all three labels
        "bear": 0.18,          //   always present even if 0.0)
        "neutral": 0.40
    },

    "period_days": 365,        // number of calendar days spanned by the data
                               //   (= last_date - first_date).days + 1
    "total_daily_bars": 310,   // actual number of daily bars in the series

    "breakdown": [             // per-bar regime log (dashboard regime timeline)
        {"date": "2024-01-01", "regime": "bull"},
        {"date": "2024-01-02", "regime": "neutral"},
        ...
    ]
}

Notes:
- ``distribution`` always contains all three keys (bull / bear / neutral);
  a regime with zero occurrences is represented as 0.0, not omitted.
- ``period_days`` measures the calendar span (last - first + 1 day), which
  may exceed ``total_daily_bars`` because weekends / missing data reduce the
  bar count on daily spot series.
- The ``breakdown`` list is ordered chronologically and is included so the
  dashboard can render a regime timeline without re-running the detector.
- There is intentionally NO pydantic model for this file: design D3 mandated
  pydantic schemas only for factor / strategy / testnet manifests.  The backend
  serves this JSON as-is via GET /api/regime.
──────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import dataclasses
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── Path bootstrap ─────────────────────────────────────────────────────────────
# This module lives at <repo-root>/research/pipeline/stage2_5_regime.py.
# Bootstrap research/ onto sys.path so imports work regardless of CWD or
# how this script is invoked.
_THIS_FILE = Path(__file__).resolve()
_PIPELINE_DIR = _THIS_FILE.parent          # research/pipeline/
_RESEARCH_DIR = _PIPELINE_DIR.parent       # research/

for _p in (_RESEARCH_DIR,):
    _ps = str(_p)
    if _ps not in sys.path:
        sys.path.insert(0, _ps)

# ── Internal imports ───────────────────────────────────────────────────────────
# Per code-review request from earlier stages: import _REPO_ROOT from
# pipeline.config rather than recomputing it, so all stages agree on one
# repo-root definition.
from pipeline.config import _REPO_ROOT, ResearchConfig, SymbolConfig, load_config  # noqa: E402

# ── Dashboard schemas (FactorManifest) ─────────────────────────────────────────
# dashboard/server/schemas.py lives at <repo-root>/dashboard/server/schemas.py.
# Add the repo-root to sys.path so the import resolves regardless of CWD.
_REPO_ROOT_STR = str(_REPO_ROOT)
if _REPO_ROOT_STR not in sys.path:
    sys.path.insert(0, _REPO_ROOT_STR)

from dashboard.server.schemas import FactorManifest  # noqa: E402

# ── Standard library ───────────────────────────────────────────────────────────
import pandas as pd

# ─── Detector defaults (mirrors regime_validate.py v1 parameters) ─────────────

#: EMA span used by default (200-day EMA -> long-term trend).
DEFAULT_EMA_WINDOW: int = 200

#: EMA slope lookback window in bars (20 daily bars ≈ 1 month).
DEFAULT_SLOPE_WINDOW: int = 20

#: Funding rolling mean window in hours (30 days × 24 h = 720 h).
DEFAULT_FUNDING_WINDOW_HOURS: int = 30 * 24

#: Funding mean threshold above/below which mania/capitulation flips regime.
DEFAULT_FUNDING_MANIA_THRESHOLD: float = 3e-4

#: Bear-persistence lookback (days).
DEFAULT_BEAR_PERSISTENCE_DAYS: int = 20

#: Fraction of bear bars required in the lookback window to confirm bear.
DEFAULT_BEAR_PERSISTENCE_THRESHOLD: float = 0.55

#: The full parameter dict applied by default (mirrors regime_validate.py v1).
DEFAULT_DETECTOR_PARAMS: dict = {
    "ema_window": DEFAULT_EMA_WINDOW,
    "slope_window": DEFAULT_SLOPE_WINDOW,
    "funding_window_hours": DEFAULT_FUNDING_WINDOW_HOURS,
    "funding_mania_threshold": DEFAULT_FUNDING_MANIA_THRESHOLD,
    "bear_persistence_days": DEFAULT_BEAR_PERSISTENCE_DAYS,
    "bear_persistence_threshold": DEFAULT_BEAR_PERSISTENCE_THRESHOLD,
}

#: All valid regime label strings.
_ALL_LABELS: tuple[str, ...] = ("bull", "bear", "neutral")

#: Required top-level keys in a regime manifest.
_REQUIRED_MANIFEST_KEYS: frozenset[str] = frozenset(
    {
        "schema_version",
        "symbol",
        "generated_at",
        "detector_params",
        "current_regime",
        "distribution",
        "period_days",
        "total_daily_bars",
        "breakdown",
    }
)


# ─── Data containers ──────────────────────────────────────────────────────────


@dataclasses.dataclass
class RegimeCheckResult:
    """Result of checking one symbol's regime manifest on disk."""

    symbol: str
    exists: bool
    valid: bool
    error: str | None = None  # description if valid=False

    @property
    def ok(self) -> bool:
        return self.exists and self.valid


# ─── Pure-logic helpers (testable, network-free) ──────────────────────────────


def check_factor_manifest_gate(manifests_dir: Path, symbol: str) -> None:
    """Prerequisite gate: verify that stage 1 has produced a valid factor manifest.

    Stage 2.5 must NOT run for a symbol until stage 1 has completed and written
    ``factor_<symbol>.json``.  This function enforces that ordering by reading
    and validating the factor manifest before the regime computation starts.

    The regime algorithm does NOT use factor IC data — this is a pure ordering
    gate, not an algorithmic input.

    Args:
        manifests_dir: Path to the research/manifests/ directory.
        symbol:        Short lowercase symbol name, e.g. "btc".

    Raises:
        FileNotFoundError: If ``factor_<symbol>.json`` is missing.  The error
            message explicitly names ``stage1_factors`` so it is clear which
            upstream stage must be run first.
        ValueError: If the file exists but cannot be parsed as JSON, or does
            not validate as a FactorManifest.
    """
    path = manifests_dir / f"factor_{symbol}.json"

    if not path.exists():
        raise FileNotFoundError(
            f"stage 1 has not produced a valid factor manifest for {symbol!r} — "
            f"run stage1_factors first (expected: {path})"
        )

    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"factor manifest for {symbol!r} is not valid JSON: {exc} — "
            f"re-run stage1_factors to regenerate it"
        ) from exc

    try:
        FactorManifest.model_validate(data)
    except Exception as exc:  # noqa: BLE001 — pydantic ValidationError
        raise ValueError(
            f"factor manifest for {symbol!r} failed FactorManifest schema validation: {exc} — "
            f"re-run stage1_factors to regenerate it"
        ) from exc


def build_regime_manifest(
    symbol: str,
    regime_series: "pd.Series",
    detector_params: dict,
) -> dict:
    """Build the regime_<symbol>.json payload from a computed regime Series.

    This is a pure function — no I/O, no network. The caller supplies the
    regime label series (daily index, values "bull"/"bear"/"neutral") and the
    detector params actually used; this function assembles the structured dict.

    The returned dict is JSON-serialisable (all values are str / int / float /
    list / dict with those leaf types).

    Args:
        symbol:        Short lowercase symbol name (e.g. "btc"). Stored as
                       uppercase in the output.
        regime_series: Daily pd.Series of regime labels (DatetimeIndex, object
                       dtype). Must be non-empty and sorted chronologically.
        detector_params: The kwargs passed to compute_regime() for this run.
                       Stored verbatim so the manifest is self-documenting.

    Returns:
        A dict conforming to the regime_<symbol>.json schema (see module
        docstring for the full shape).
    """
    s = regime_series.sort_index().dropna()

    # ── distribution ──────────────────────────────────────────────────────────
    n = len(s)
    counts = s.value_counts()
    distribution: dict[str, float] = {
        label: float(counts.get(label, 0)) / n for label in _ALL_LABELS
    }

    # ── period_days: calendar span ────────────────────────────────────────────
    first_date = s.index[0]
    last_date = s.index[-1]
    # timedelta.days gives the number of full calendar days between the two
    # timestamps; adding 1 includes both endpoints.
    # The production caller always supplies a DatetimeIndex, so this must not
    # raise AttributeError.  We let any wrong-type error propagate naturally
    # rather than silently falling back to a semantically wrong value.
    period_days = (last_date - first_date).days + 1

    # ── per-bar breakdown ─────────────────────────────────────────────────────
    breakdown: list[dict] = []
    for ts, label in s.items():
        # Normalise timestamp to a date string — handles both Timestamp and
        # plain datetime objects safely.
        if hasattr(ts, "date"):
            date_str = ts.date().isoformat()
        else:
            date_str = str(ts)[:10]
        breakdown.append({"date": date_str, "regime": str(label)})

    return {
        "schema_version": 1,
        "symbol": symbol.upper(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "detector_params": detector_params,
        "current_regime": str(s.iloc[-1]),
        "distribution": distribution,
        "period_days": period_days,
        "total_daily_bars": n,
        "breakdown": breakdown,
    }


def check_regime_manifest(manifests_dir: Path, symbol: str) -> RegimeCheckResult:
    """Verify that regime_<symbol>.json exists and is well-formed.

    Well-formed means:
      - Valid JSON.
      - Contains all required top-level keys (see _REQUIRED_MANIFEST_KEYS).
      - ``distribution`` is a dict.
      - ``breakdown`` is a list.

    Args:
        manifests_dir: Path to the research/manifests/ directory.
        symbol:        Short lowercase symbol name, e.g. "btc".

    Returns:
        RegimeCheckResult describing whether the manifest is present and valid.
    """
    path = manifests_dir / f"regime_{symbol}.json"

    if not path.exists():
        return RegimeCheckResult(
            symbol=symbol,
            exists=False,
            valid=False,
            error="file not found",
        )

    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        return RegimeCheckResult(
            symbol=symbol,
            exists=True,
            valid=False,
            error=f"JSON parse error: {exc}",
        )

    if not isinstance(data, dict):
        return RegimeCheckResult(
            symbol=symbol,
            exists=True,
            valid=False,
            error="top-level JSON value is not an object",
        )

    # Required key check
    missing = _REQUIRED_MANIFEST_KEYS - data.keys()
    if missing:
        return RegimeCheckResult(
            symbol=symbol,
            exists=True,
            valid=False,
            error=f"missing required keys: {sorted(missing)}",
        )

    # Type checks for structured fields
    if not isinstance(data["distribution"], dict):
        return RegimeCheckResult(
            symbol=symbol,
            exists=True,
            valid=False,
            error=f"'distribution' must be a dict, got {type(data['distribution']).__name__}",
        )

    if not isinstance(data["breakdown"], list):
        return RegimeCheckResult(
            symbol=symbol,
            exists=True,
            valid=False,
            error=f"'breakdown' must be a list, got {type(data['breakdown']).__name__}",
        )

    # Validate current_regime is one of the three canonical labels
    current_regime = data.get("current_regime")
    if current_regime not in _ALL_LABELS:
        return RegimeCheckResult(
            symbol=symbol,
            exists=True,
            valid=False,
            error=(
                f"current_regime {current_regime!r} is not a canonical label; "
                f"must be one of {_ALL_LABELS}"
            ),
        )

    return RegimeCheckResult(symbol=symbol, exists=True, valid=True)


def verify_outputs(
    manifests_dir: Path,
    symbols: list[str],
) -> list[RegimeCheckResult]:
    """Check all expected regime manifests after the stage runs.

    Args:
        manifests_dir: Path to research/manifests/.
        symbols:       List of short lowercase symbol names, e.g. ["btc", "eth"].

    Returns:
        List of RegimeCheckResult, one per symbol, in input order.
    """
    return [check_regime_manifest(manifests_dir, sym) for sym in symbols]


def compute_exit_code(results: list[RegimeCheckResult]) -> int:
    """Return 0 if at least one result was produced and all are ok; 1 otherwise.

    An empty result list is a failure: the stage produced no manifests.

    Args:
        results: List of RegimeCheckResult from verify_outputs().

    Returns:
        0 on full success (>=1 symbol, all ok); 1 otherwise.
    """
    if not results:
        return 1
    return 0 if all(r.ok for r in results) else 1


def print_summary(results: list[RegimeCheckResult]) -> None:
    """Print a human-readable per-symbol summary to stdout.

    Args:
        results: List of RegimeCheckResult from verify_outputs().
    """
    print("\n" + "=" * 60)
    print("Stage-2.5 output verification summary")
    print("=" * 60)
    if not results:
        print("  (no regime manifests were generated)")

    for r in results:
        status = "OK" if r.ok else "FAIL"
        if r.ok:
            msg = "regime manifest present and valid"
        elif not r.exists:
            msg = f"MISSING — {r.error}"
        else:
            msg = f"INVALID — {r.error}"
        print(f"  [{status}] {r.symbol}: {msg}")

    total = len(results)
    passed = sum(1 for r in results if r.ok)
    print(f"\n{passed}/{total} symbols passed.")
    if total == 0 or passed < total:
        print("Stage 2.5 FAILED: one or more regime manifests are missing or invalid.")
    else:
        print("Stage 2.5 PASSED: all regime manifests present and valid.")
    print("=" * 60)


# ─── Per-symbol orchestration (thin shell, not unit-tested) ───────────────────


def _run_regime_for_symbol(
    sym: SymbolConfig,
    cfg: ResearchConfig,
    manifests_dir: Path,
) -> None:
    """Fetch data, compute regime, write manifest for one symbol.

    This function IS intentionally NOT unit-tested because it calls the
    network (OKX candle fetch + funding history fetch) and lib.regime
    (which requires a warmup period of data).

    Args:
        sym:           SymbolConfig for this symbol.
        cfg:           Full ResearchConfig (provides period_days etc.).
        manifests_dir: research/manifests/ — where the JSON is written.
    """
    # Import here (inside function) so the module is importable in tests
    # without requiring the full data-fetch dependency graph to be available.
    from lib.okx_data import fetch_candles, fetch_funding_history  # noqa: PLC0415
    from lib.regime import compute_regime, daily_close_from_hourly  # noqa: PLC0415

    period_days = cfg.period

    print(f"\n{'='*60}")
    print(f"[regime] Symbol: {sym.name.upper()}")
    print(f"{'='*60}")

    # ── Prerequisite gate: stage 1 factor manifest must exist and be valid ──
    # This enforces the D2-mandated stage ordering: stage 2.5 must not run
    # for a symbol before stage 1 has successfully produced its outputs.
    print(f"[0/2] Checking stage-1 prerequisite: factor_{sym.name}.json …")
    check_factor_manifest_gate(manifests_dir, sym.name)
    print(f"      prerequisite OK — factor manifest present and valid")

    print(f"[1/3] Fetching hourly candles (last {period_days}d) from OKX…")
    candles = fetch_candles(sym.okx_swap, period_days, bar="1H", use_history_endpoint=True)
    print(f"      rows: {len(candles)}")

    print(f"[2/3] Fetching funding rate history (last {period_days}d) from OKX…")
    funding = fetch_funding_history(sym.okx_swap, period_days)
    print(f"      rows: {len(funding)}")

    # ── Step 3: compute regime ────────────────────────────────────────────────
    print(f"[3/3] Computing regime labels …")

    # Build daily close series from hourly candles.
    daily_close = daily_close_from_hourly(candles, col="close")
    print(f"[regime] Daily close bars: {len(daily_close)}")

    # Align funding to hourly index then carry forward to daily when reindexed.
    # compute_regime accepts funding at any native interval; it reindexes
    # internally to align with the daily close index.
    fund_series: pd.Series = funding["funding_rate"]

    # Compute regime using v1 parameters (with bear-persistence smoothing).
    regime_df = compute_regime(
        daily_close,
        funding_rate=fund_series,
        ema_window=DEFAULT_EMA_WINDOW,
        slope_window=DEFAULT_SLOPE_WINDOW,
        funding_window_hours=DEFAULT_FUNDING_WINDOW_HOURS,
        funding_mania_threshold=DEFAULT_FUNDING_MANIA_THRESHOLD,
        bear_persistence_days=DEFAULT_BEAR_PERSISTENCE_DAYS,
        bear_persistence_threshold=DEFAULT_BEAR_PERSISTENCE_THRESHOLD,
    )

    regime_series = regime_df["regime"]

    # Print distribution for immediate visibility.
    dist = regime_series.value_counts(normalize=True)
    print(f"[regime] distribution: " + "  ".join(
        f"{lbl}={dist.get(lbl, 0.0)*100:.1f}%" for lbl in _ALL_LABELS
    ))
    print(f"[regime] current (latest bar): {regime_series.iloc[-1]!r}")

    # Build manifest dict.
    manifest = build_regime_manifest(
        symbol=sym.name,
        regime_series=regime_series,
        detector_params=DEFAULT_DETECTOR_PARAMS.copy(),
    )

    # Write to disk.
    manifests_dir.mkdir(parents=True, exist_ok=True)
    out_path = manifests_dir / f"regime_{sym.name}.json"
    out_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[regime] wrote → {out_path.name}")


def main() -> None:
    """Stage-2.5 entry point: orchestrate, verify, report, exit."""
    cfg: ResearchConfig = load_config()
    symbols = cfg.symbol_names()
    manifests_dir = _REPO_ROOT / "research" / "manifests"

    print("=" * 60)
    print("Stage 2.5 — Market Regime Detection")
    print("=" * 60)
    print(f"Config: period={cfg.period}d  symbols={symbols}")
    print(f"Output directory: {manifests_dir}")

    for sym in cfg.symbols:
        try:
            _run_regime_for_symbol(sym, cfg, manifests_dir)
        except Exception as exc:  # noqa: BLE001
            # One symbol failing must not abort the others; verify_outputs
            # below will surface the gap as a non-zero exit code.
            print(f"[regime] {sym.name}: FAILED — {exc}")

    results = verify_outputs(manifests_dir, symbols)
    print_summary(results)
    sys.exit(compute_exit_code(results))


if __name__ == "__main__":
    main()
