"""
research/pipeline/stage0a_features.py
───────────────────────────────────────
Stage-0a runner: Feature Store + Evidence Build.

For each symbol:
  1. Fetch OHLCV candles (OKX) + non-price data (funding/OI/stablecoin)
  2. Compute indicator pool (price-based) + non-price factors
  3. Write feature store (features_<sym>.parquet + meta.json) via dump_features
  4. Compute multi-horizon IC/IR for every feature
  5. Write evidence_<sym>.json via dump_evidence (sorted by descending max |IC|)
  6. Verify outputs + exit code

Exit code:
  0 — all symbols succeeded
  1 — any symbol failed (others continue; failed symbols write no output)

Usage
-----
    # From repo root:
    python -m research.pipeline.stage0a_features

    # From research/ directory (preferred):
    python -m pipeline.stage0a_features

    # Direct invocation:
    python research/pipeline/stage0a_features.py

Architecture
------------
Same thin-orchestration pattern as stage0_discovery.py / stage1_factors.py:
  - Pure-logic helpers at module level (testable, no network I/O except file I/O)
  - _process_symbol() handles one symbol end-to-end
  - verify_outputs() helper
  - compute_exit_code() helper
  - main() entry point with argparse
"""

from __future__ import annotations

import sys
from pathlib import Path

# ── Path bootstrap ─────────────────────────────────────────────────────────────
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
import argparse
import logging
from datetime import datetime, timezone

import pandas as pd

# ── Internal imports ───────────────────────────────────────────────────────────
from pipeline.config import ResearchConfig, SymbolConfig, load_config
from lib.indicators import compute_indicator_pool
from lib.factor_io import dump_features, dump_evidence
from lib.factor_metrics import add_forward_returns, evaluate_factor, FactorResult

# ─── Logging ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="[stage0a] %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

# ─── Evidence category mapping ────────────────────────────────────────────────

_INDICATOR_CATEGORY: dict[str, str] = {
    # momentum
    "rsi_14": "momentum",
    "macd_diff": "momentum",
    "roc_10": "momentum",
    "stoch_k": "momentum",
    # trend
    "ema_cross_9_21": "trend",
    "sma_cross_10_30": "trend",
    "adx_14": "trend",
    # volatility
    "atr_14": "volatility",
    "bb_width_20": "volatility",
    "rolling_std_20": "volatility",
    # volume
    "obv": "volume",
    "mfi_14": "volume",
    "volume_zscore_20": "volume",
    # non-price
    "funding_rate_raw": "funding",
    "oi_change_24h": "oi",
    "stablecoin_supply_z": "stablecoin",
}

_NON_PRICE_FEATURES = {"funding_rate_raw", "oi_change_24h", "stablecoin_supply_z"}


# ─── Pure-logic helpers ────────────────────────────────────────────────────────


def build_feature_dict(
    candles: pd.DataFrame,
    config: ResearchConfig,
    funding_df: pd.DataFrame | None = None,
    oi_df: pd.DataFrame | None = None,
    stablecoin_df: pd.DataFrame | None = None,
) -> dict[str, pd.Series]:
    """Compute all features and return as a dict of name → Series.

    Price-based: indicator pool from compute_indicator_pool.
    Non-price: funding_rate_raw, oi_change_24h, stablecoin_supply_z.

    Parameters
    ----------
    candles:
        OHLCV DataFrame with UTC DatetimeIndex. Must have open/high/low/close/volume.
    config:
        ResearchConfig (used for indicator_pool list).
    funding_df:
        DataFrame indexed by UTC time with 'funding_rate' column.  Optional.
    oi_df:
        DataFrame indexed by UTC time with 'open_interest' column.  Optional.
    stablecoin_df:
        DataFrame indexed by UTC time with 'stablecoin_supply' column.  Optional.

    Returns
    -------
    dict[str, pd.Series]  — all values aligned to candles.index.
    """
    features: dict[str, pd.Series] = {}

    # ── Price-based indicator pool ────────────────────────────────────────────
    indicators = compute_indicator_pool(candles, config)
    features.update(indicators)

    candle_idx = candles.index

    # ── funding_rate_raw ─────────────────────────────────────────────────────
    if funding_df is not None and not funding_df.empty and "funding_rate" in funding_df.columns:
        raw = funding_df["funding_rate"].reindex(candle_idx, method="ffill")
        raw.name = "funding_rate_raw"
        features["funding_rate_raw"] = raw

    # ── oi_change_24h ─────────────────────────────────────────────────────────
    if oi_df is not None and not oi_df.empty and "open_interest" in oi_df.columns:
        oi_aligned = oi_df["open_interest"].reindex(candle_idx, method="ffill")
        oi_change = oi_aligned.pct_change(periods=24)
        oi_change.name = "oi_change_24h"
        features["oi_change_24h"] = oi_change

    # ── stablecoin_supply_z ──────────────────────────────────────────────────
    if (
        stablecoin_df is not None
        and not stablecoin_df.empty
        and "stablecoin_supply" in stablecoin_df.columns
    ):
        sc_aligned = stablecoin_df["stablecoin_supply"].reindex(candle_idx, method="ffill")
        # 30-day rolling z-score (720 hours)
        roll_mean = sc_aligned.rolling(720, min_periods=30).mean()
        roll_std = sc_aligned.rolling(720, min_periods=30).std()
        sc_z = (sc_aligned - roll_mean) / roll_std.replace(0, float("nan"))
        sc_z.name = "stablecoin_supply_z"
        features["stablecoin_supply_z"] = sc_z

    return features


def compute_evidence_entries(
    candles: pd.DataFrame,
    feature_dict: dict[str, pd.Series],
    horizons_h: tuple[int, ...],
    price_col: str = "close",
) -> list[dict]:
    """Compute multi-horizon IC/IR for every feature and return evidence entries.

    Parameters
    ----------
    candles:
        OHLCV DataFrame with UTC DatetimeIndex and price_col column.
    feature_dict:
        Dict of feature_name → pd.Series (aligned to candles.index).
    horizons_h:
        Forward-return horizons in hours.
    price_col:
        Column in candles to use as price for forward returns.

    Returns
    -------
    List of evidence entry dicts (unsorted).
    Each entry has: feature_key, category, ic_by_horizon, ir, sample_size.
    """
    # Build base DataFrame with price column
    base_df = pd.DataFrame({"price": candles[price_col]}, index=candles.index)
    # Add forward returns once for all horizons
    base_df = add_forward_returns(base_df, "price", list(horizons_h))

    entries: list[dict] = []
    for feat_name, feat_series in feature_dict.items():
        # Attach the feature column
        df = base_df.copy()
        df[feat_name] = feat_series

        results: list[FactorResult] = evaluate_factor(df, feat_name, list(horizons_h))

        # Build ic_by_horizon dict: {horizon_int: ic_float}
        ic_by_horizon: dict[int, float | None] = {}
        ir_values: list[float] = []
        sample_sizes: list[int] = []

        for r in results:
            h = int(r.horizon.rstrip("h"))
            ic_val = float(r.ic) if r.ic == r.ic else None  # NaN → None
            ic_by_horizon[h] = ic_val
            if r.ir == r.ir and r.ir is not None:  # not NaN
                ir_values.append(float(r.ir))
            sample_sizes.append(r.n_samples)

        # Aggregate IR: mean across horizons (ignore NaN)
        agg_ir: float | None = (
            float(sum(ir_values) / len(ir_values)) if ir_values else None
        )
        agg_sample = max(sample_sizes) if sample_sizes else 0

        category = _INDICATOR_CATEGORY.get(feat_name, "unknown")

        entries.append(
            {
                "feature_key": feat_name,
                "category": category,
                "ic_by_horizon": ic_by_horizon,
                "ir": agg_ir,
                "sample_size": agg_sample,
            }
        )

    return entries


def sort_evidence_by_ic(entries: list[dict]) -> list[dict]:
    """Sort evidence entries by descending max |IC| across all horizons."""

    def max_abs_ic(entry: dict) -> float:
        ics = entry.get("ic_by_horizon", {}).values()
        valid = [abs(v) for v in ics if v is not None]
        return max(valid) if valid else 0.0

    return sorted(entries, key=max_abs_ic, reverse=True)


def build_evidence_payload(
    symbol: str,
    sorted_entries: list[dict],
) -> dict:
    """Wrap sorted evidence entries into the self-contained evidence payload dict."""
    return {
        "caveat": "僅篩選用途；未做交易成本與 multiple-testing 校正",
        "symbol": symbol,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "evidence": sorted_entries,
    }


def verify_outputs(manifests_dir: Path, symbols: list[str]) -> list[str]:
    """Check that expected output files exist for every symbol.

    Returns list of missing file paths (empty list = all good).
    """
    missing: list[str] = []
    for sym in symbols:
        sym_lower = sym.lower()
        expected = [
            manifests_dir / f"features_{sym_lower}.parquet",
            manifests_dir / f"features_{sym_lower}.meta.json",
            manifests_dir / f"evidence_{sym_lower}.json",
        ]
        for fp in expected:
            if not fp.exists():
                missing.append(str(fp))
    return missing


def compute_exit_code(results: dict[str, bool]) -> int:
    """Return 0 if all symbols succeeded, 1 if any failed."""
    return 0 if all(results.values()) else 1


# ─── Symbol processing ────────────────────────────────────────────────────────


def _fetch_non_price_data(
    sym_cfg: SymbolConfig,
    period_days: int,
) -> tuple[pd.DataFrame | None, pd.DataFrame | None, pd.DataFrame | None]:
    """Fetch funding, OI, and stablecoin data.  Returns (funding_df, oi_df, stablecoin_df).

    Each may be None if the fetch fails — caller should handle gracefully.
    """
    from lib.ccxt_data import fetch_funding_rate_history_ccxt

    try:
        from lib.ccxt_data import fetch_oi_history_bybit
    except ImportError:
        fetch_oi_history_bybit = None  # type: ignore[assignment]

    from lib.coingecko_data import fetch_stablecoin_supply

    funding_df: pd.DataFrame | None = None
    oi_df: pd.DataFrame | None = None
    stablecoin_df: pd.DataFrame | None = None

    # ── Funding rate ─────────────────────────────────────────────────────────
    try:
        funding_df = fetch_funding_rate_history_ccxt(
            exchange_name="binance",
            symbol=sym_cfg.ccxt_bybit,
            days=period_days,
        )
        log.info("%s: fetched funding rate (%d rows)", sym_cfg.name, len(funding_df))
    except Exception as exc:
        log.warning("%s: funding fetch failed: %s — skipping funding_rate_raw", sym_cfg.name, exc)

    # ── OI ───────────────────────────────────────────────────────────────────
    if fetch_oi_history_bybit is not None:
        try:
            oi_df = fetch_oi_history_bybit(
                symbol=sym_cfg.ccxt_bybit,
                days=period_days,
            )
            log.info("%s: fetched OI (%d rows)", sym_cfg.name, len(oi_df))
        except Exception as exc:
            log.warning("%s: OI fetch failed: %s — skipping oi_change_24h", sym_cfg.name, exc)

    # ── Stablecoin supply ────────────────────────────────────────────────────
    try:
        stablecoin_df = fetch_stablecoin_supply(days=min(period_days, 365))
        log.info("%s: fetched stablecoin supply (%d rows)", sym_cfg.name, len(stablecoin_df))
    except Exception as exc:
        log.warning(
            "%s: stablecoin fetch failed: %s — skipping stablecoin_supply_z", sym_cfg.name, exc
        )

    return funding_df, oi_df, stablecoin_df


def _process_symbol(
    sym_cfg: SymbolConfig,
    cfg: ResearchConfig,
    manifests_dir: Path,
) -> bool:
    """Build feature store + evidence for one symbol.

    Returns True on success, False on failure.
    """
    from lib.okx_data import fetch_candles

    sym = sym_cfg.name
    log.info("=== Processing symbol: %s ===", sym.upper())

    try:
        # ── 1. Fetch OHLCV ───────────────────────────────────────────────────
        log.info("%s: fetching OHLCV candles from OKX...", sym)
        candles = fetch_candles(
            symbol=sym_cfg.okx_swap,
            days=cfg.period,
            bar=cfg.interval,
        )
        if candles is None or candles.empty:
            log.error("%s: candles are empty — skipping symbol", sym)
            return False
        log.info("%s: candles fetched (%d rows)", sym, len(candles))

        # ── 2. Fetch non-price data ──────────────────────────────────────────
        funding_df, oi_df, stablecoin_df = _fetch_non_price_data(sym_cfg, cfg.period)

        # ── 3. Compute feature dict ──────────────────────────────────────────
        log.info("%s: computing feature pool...", sym)
        feature_dict = build_feature_dict(
            candles=candles,
            config=cfg,
            funding_df=funding_df,
            oi_df=oi_df,
            stablecoin_df=stablecoin_df,
        )
        if not feature_dict:
            log.error("%s: feature dict is empty — skipping symbol", sym)
            return False
        log.info("%s: computed %d features", sym, len(feature_dict))

        # ── 4. Write feature store ───────────────────────────────────────────
        dump_features(sym, feature_dict, manifests_dir)

        # ── 5. Compute multi-horizon IC/IR ───────────────────────────────────
        log.info("%s: computing multi-horizon IC/IR...", sym)
        entries = compute_evidence_entries(candles, feature_dict, cfg.horizons_h)
        sorted_entries = sort_evidence_by_ic(entries)

        # ── 6. Write evidence JSON ───────────────────────────────────────────
        evidence_payload = build_evidence_payload(sym, sorted_entries)
        dump_evidence(sym, evidence_payload, manifests_dir)
        log.info(
            "%s: evidence written (%d entries, top=%s)",
            sym,
            len(sorted_entries),
            sorted_entries[0]["feature_key"] if sorted_entries else "—",
        )

        return True

    except Exception as exc:
        log.error("%s: unexpected error — %s", sym, exc, exc_info=True)
        return False


# ─── Entry point ─────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Stage-0a: Build feature store and evidence table for each symbol."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to research_config.yaml (default: research/research_config.yaml)",
    )
    parser.add_argument(
        "--manifests-dir",
        type=Path,
        default=None,
        help="Override output directory for manifests (default: research/manifests)",
    )
    args = parser.parse_args()

    cfg = load_config(args.config)

    # Resolve manifests directory
    if args.manifests_dir is not None:
        manifests_dir = args.manifests_dir.resolve()
    else:
        manifests_dir = _REPO_ROOT / cfg.feature_store_path

    log.info("Manifests directory: %s", manifests_dir)
    log.info("Symbols: %s", [s.name for s in cfg.symbols])
    log.info("Horizons: %s", list(cfg.horizons_h))

    results: dict[str, bool] = {}
    for sym_cfg in cfg.symbols:
        ok = _process_symbol(sym_cfg, cfg, manifests_dir)
        results[sym_cfg.name] = ok
        status = "OK" if ok else "FAILED"
        log.info("Symbol %s: %s", sym_cfg.name.upper(), status)

    # Verify outputs
    succeeded_syms = [sym for sym, ok in results.items() if ok]
    missing = verify_outputs(manifests_dir, succeeded_syms)
    if missing:
        log.error("Missing expected output files:\n  %s", "\n  ".join(missing))
        for sym in [sym for sym, ok in results.items() if ok]:
            results[sym] = False

    exit_code = compute_exit_code(results)
    if exit_code == 0:
        log.info("Stage-0a complete. All symbols succeeded.")
    else:
        failed = [sym for sym, ok in results.items() if not ok]
        log.error("Stage-0a finished with errors. Failed symbols: %s", failed)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
