"""
Extended factor research — 2-year sample, 3 non-price factors, multi-horizon IC.

Factors:
- funding_rate: OKX 8h settlement (forward-filled to hourly)
- oi_change_24h: Bybit hourly OI %change over 24h (proxy for total perp leverage)
- fng: alternative.me daily Fear & Greed Index (forward-filled to hourly)

Horizons: driven by research_config.yaml (default 8h, 24h, 72h, 168h)
Outputs (per symbol):
  research/manifests/factor_<symbol>.json  — structured FactorManifest (JSON)
  research/manifests/factor_<symbol>.md    — markdown audit report

Config: research/research_config.yaml (loaded via pipeline.config.load_config)

Pure-logic helpers (verdict_from_ic, build_factor_manifest, resolve_manifests_dir)
are importable and testable independently of network I/O.
"""

from __future__ import annotations

import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── Path bootstrap ─────────────────────────────────────────────────────────────
# This script lives at <repo-root>/research/factor_extended.py.
# • <repo-root>/research is added so lib.* and pipeline.* are importable.
# • <repo-root>/dashboard/server is added so schemas.py is importable.
_THIS_DIR = Path(__file__).resolve().parent          # research/
_REPO_ROOT = _THIS_DIR.parent                        # repo root

_RESEARCH_DIR = _REPO_ROOT / "research"
_DASHBOARD_SCHEMAS = _REPO_ROOT / "dashboard" / "server"

for _p in (_RESEARCH_DIR, _DASHBOARD_SCHEMAS):
    _ps = str(_p)
    if _ps not in sys.path:
        sys.path.insert(0, _ps)

# ── Standard library & third-party ────────────────────────────────────────────
import pandas as pd

# ── Internal imports ───────────────────────────────────────────────────────────
from lib.ccxt_data import fetch_oi_history_bybit, fetch_funding_history_multiyear
from lib.coingecko_data import fetch_stablecoin_supply
from lib.factor_io import load_features, dump_factor_values
from lib.factor_metrics import FactorResult, add_forward_returns, evaluate_factor
from lib.okx_data import fetch_candles, fetch_funding_history
from lib.report import build_factor_report
from lib.sentiment import fetch_fear_greed
from lib.sources import SOURCE_REGISTRY, TRANSFORM_REGISTRY
from pipeline.config import ResearchConfig, SymbolConfig, _REPO_ROOT as _CFG_REPO_ROOT
from pipeline.config import load_config
from schemas import CandidatesManifest, FactorCandidate, FactorEntry, FactorManifest, FactorVerdict


# ─── Pure-logic helpers (testable) ────────────────────────────────────────────


def resolve_manifests_dir() -> Path:
    """Return the repo-relative path to research/manifests/.

    Uses the same repo-root resolution as pipeline.config (_REPO_ROOT derived
    from __file__), so this never contains a hardcoded Windows user path.
    """
    # _CFG_REPO_ROOT is computed from pipeline/config.py two parents up, giving
    # the same repo root regardless of CWD or OS.
    return _CFG_REPO_ROOT / "research" / "manifests"


def verdict_from_ic(ic: float) -> FactorVerdict:
    """Return the FactorVerdict for a given IC value.

    Rule (loosened 2026-05-27 to widen candidate funnel — see ADR
    project_stage1_verdict_gate_lowering_adr):
        |IC| >= 0.10           -> single_use
        0.03 <= |IC| < 0.10   -> ensemble_only
        |IC| < 0.03            -> reject
        NaN                    -> reject (insufficient data)

    Lower ensemble_only floor (0.05 → 0.03) lets weak-but-positive signals
    survive to stage 2 for ensemble use; previously borderline factors were
    silently dropped, starving downstream strategies of factor diversity.
    """
    if math.isnan(ic):
        return FactorVerdict.REJECT
    abs_ic = abs(ic)
    if abs_ic >= 0.10:
        return FactorVerdict.SINGLE_USE
    if abs_ic >= 0.03:
        return FactorVerdict.ENSEMBLE_ONLY
    return FactorVerdict.REJECT


def build_factor_manifest(
    symbol: str,
    period_days: int,
    horizons_h: list[int],
    factor_results: list[FactorResult],
    generated_at: datetime,
) -> FactorManifest:
    """Build and validate a FactorManifest from evaluated FactorResult objects.

    Verdict horizon decision: the verdict for each factor is driven by the
    maximum |IC| across all horizons for that factor.  Using the maximum gives
    the most generous but still evidence-grounded assessment — if a factor is
    predictive at even one horizon it should not be globally rejected.  This
    choice is documented here so reviewers can change it to e.g. median |IC|.

    cross_regime_ic and stability are set to None here (task 2.3 fills them).
    """
    # Group FactorResult objects by factor name.
    factors_map: dict[str, list[FactorResult]] = {}
    for r in factor_results:
        factors_map.setdefault(r.factor, []).append(r)

    factor_entries: list[FactorEntry] = []
    for factor_name, results in factors_map.items():
        ic_by_horizon: dict[int, float] = {}
        # Reconstruct horizon int from the "8h" / "24h" string stored in FactorResult.
        for r in results:
            h_int = int(r.horizon.rstrip("h"))
            ic_by_horizon[h_int] = r.ic

        # Use the single IR from the last result (evaluate_factor returns one IR
        # per horizon; we pick the horizon with the maximum |IC| for IR too).
        best_result = max(
            results,
            key=lambda r: 0.0 if math.isnan(r.ic) else abs(r.ic),
        )
        ir_value = best_result.ir if not math.isnan(best_result.ir) else 0.0
        n_samples = best_result.n_samples

        # Verdict: driven by maximum |IC| across horizons (see docstring above).
        max_ic = best_result.ic
        verdict = verdict_from_ic(max_ic)

        factor_entries.append(
            FactorEntry(
                name=factor_name,
                ic_by_horizon=ic_by_horizon,
                ir=ir_value,
                sample_size=n_samples,
                cross_regime_ic=None,   # task 2.3 fills this
                stability=None,          # task 2.3 fills this
                verdict=verdict,
            )
        )

    return FactorManifest(
        schema_version=1,
        symbol=symbol.upper(),
        generated_at=generated_at,
        period_days=period_days,
        horizons_h=list(horizons_h),
        factors=factor_entries,
    )


# ─── Candidate loading & series computation ───────────────────────────────────


def _load_candidates(manifests_dir: Path, sym: str) -> CandidatesManifest | None:
    """Load candidates_<sym>.json if it exists. Returns None if not found."""
    path = manifests_dir / f"candidates_{sym}.json"
    if not path.exists():
        return None
    return CandidatesManifest.model_validate_json(path.read_text(encoding="utf-8"))


def _compute_candidate_series(
    cand: FactorCandidate,
    candles: pd.DataFrame,
    funding: pd.DataFrame,
    oi_hist: pd.DataFrame,
    stablecoin: pd.DataFrame | None = None,
) -> pd.Series | None:
    """Compute a transformed factor series for a single FactorCandidate.

    Uses already-fetched data (no additional network calls).
    Returns None if the data source is unavailable or data is missing.
    Raises ValueError if cand.transform is not in TRANSFORM_REGISTRY.
    """
    spec = SOURCE_REGISTRY.get(cand.data_source)
    if spec is None or spec.status != "available" or spec.fetcher is None:
        print(f"  WARN: data_source '{cand.data_source}' unavailable, skipping {cand.name}")
        return None

    # Extract raw series from already-fetched data based on data_source key.
    if cand.data_source == "okx_funding":
        raw = funding["funding_rate"]
    elif cand.data_source == "okx_candles":
        raw = candles["close"]
    elif cand.data_source == "bybit_oi":
        if oi_hist.empty:
            print(f"  WARN: bybit_oi data empty, skipping {cand.name}")
            return None
        raw = oi_hist["oi"]
    elif cand.data_source == "coingecko_stablecoin_supply":
        if stablecoin is None or stablecoin.empty:
            print(f"  WARN: coingecko_stablecoin_supply data empty, skipping {cand.name}")
            return None
        raw = stablecoin["stablecoin_supply"]
    else:
        print(f"  WARN: no pre-fetched handler for data_source '{cand.data_source}', skipping {cand.name}")
        return None

    if cand.transform not in TRANSFORM_REGISTRY:
        raise ValueError(
            f"transform '{cand.transform}' not in TRANSFORM_REGISTRY "
            f"(available: {list(TRANSFORM_REGISTRY.keys())})"
        )

    transformed = TRANSFORM_REGISTRY[cand.transform](raw)

    # Align to candle index via reindex + forward-fill.
    aligned = transformed.reindex(candles.index, method="ffill")
    return aligned


# ─── Legacy path (hardcoded 3 factors) ───────────────────────────────────────


def _run_symbol_legacy(
    sym: SymbolConfig,
    cfg: ResearchConfig,
    manifests_dir: Path,
    funding: pd.DataFrame,
    candles: pd.DataFrame,
    oi_hist: pd.DataFrame,
    fng: pd.DataFrame,
    df: pd.DataFrame,
) -> list[FactorResult]:
    """Evaluate the 3 hardcoded factors: funding_rate, oi_change_24h, fng.

    Takes already-fetched data and a df that already has forward returns added.
    Returns list[FactorResult].
    """
    horizons = list(cfg.horizons_h)
    print("\n[evaluate] computing IC/IR for each factor x horizon")
    all_results: list[FactorResult] = []
    factor_series_dict: dict[str, pd.Series] = {}
    for factor in ["funding_rate", "oi_change_24h", "fng"]:
        if df[factor].isna().all():
            print(f"  {factor}: all NaN, skipping")
            continue
        factor_series_dict[factor] = df[factor]
        res = evaluate_factor(df, factor, horizons)
        for r in res:
            print(f"  {factor:>16} @ {r.horizon:>5}: IC={r.ic:+.4f} IR={r.ir:+.3f} n={r.n_samples}")
        all_results.extend(res)

    if factor_series_dict:
        try:
            from lib.factor_io import dump_factor_values
            dump_factor_values(sym.name, factor_series_dict, manifests_dir)
        except Exception as exc:
            print(f"[stage1] {sym.name}: factor_values parquet dump failed — {exc}", file=sys.stderr)

    return all_results


# ─── Dynamic path (candidates from stage0) ────────────────────────────────────


def _load_series_from_features(
    cand: FactorCandidate,
    features_df: pd.DataFrame,
) -> pd.Series | None:
    """Return the pre-computed series for *cand* from the features store.

    Pure logic — makes no network calls, applies no transforms.

    Returns
    -------
    pd.Series
        The column ``cand.feature_key`` from *features_df*.
    None
        If ``cand.feature_key`` is None (warns) or the key is absent in
        *features_df* (warns with the missing key name).
    """
    if cand.feature_key is None:
        print(f"  WARN: {cand.name} has no feature_key, skipping")
        return None
    if cand.feature_key not in features_df.columns:
        print(f"  WARN: feature_key '{cand.feature_key}' not found in features store, skipping {cand.name}")
        return None
    return features_df[cand.feature_key]


def _run_symbol_dynamic(
    sym: SymbolConfig,
    cfg: ResearchConfig,
    manifests_dir: Path,
    candidates: CandidatesManifest,
    funding: pd.DataFrame,
    candles: pd.DataFrame,
    oi_hist: pd.DataFrame,
    df: pd.DataFrame,
    stablecoin: pd.DataFrame | None = None,
) -> list[FactorResult]:
    """Evaluate factors from a CandidatesManifest (stage0 output).

    Takes already-fetched data and a df that already has forward returns added.
    Returns list[FactorResult].
    """
    horizons = list(cfg.horizons_h)
    print(f"\n[evaluate] computing IC/IR for {len(candidates.candidates)} candidate factors x horizon")

    # Load pre-computed feature series from the features store.
    try:
        features_df = load_features(sym.name, manifests_dir)
    except FileNotFoundError as exc:
        print(f"\033[93m[stage1] WARNING: {exc} — all candidates will be skipped\033[0m")
        features_df = pd.DataFrame()

    all_results: list[FactorResult] = []
    factor_series_dict: dict[str, pd.Series] = {}
    for cand in candidates.candidates:
        series = _load_series_from_features(cand, features_df)
        if series is None:
            print(f"  {cand.name}: skipped (no series from feature store)")
            continue
        df[cand.name] = series
        if df[cand.name].isna().all():
            print(f"  {cand.name}: all NaN, skipping")
            continue
        factor_series_dict[cand.name] = series
        res = evaluate_factor(df, cand.name, horizons)
        for r in res:
            print(f"  {cand.name:>24} @ {r.horizon:>5}: IC={r.ic:+.4f} IR={r.ir:+.3f} n={r.n_samples}")
        all_results.extend(res)

    if not all_results:
        # All candidates were skipped — warn but return empty so caller decides fallback.
        print(f"\033[93m[stage1] WARNING: all dynamic candidates skipped for {sym.name}, manifest will have 0 factors\033[0m")

    if factor_series_dict:
        try:
            dump_factor_values(sym.name, factor_series_dict, manifests_dir)
        except Exception as exc:
            print(f"[stage1] {sym.name}: factor_values parquet dump failed — {exc}", file=sys.stderr)

    return all_results


# ─── Per-symbol orchestration ──────────────────────────────────────────────────


def run_symbol(sym: SymbolConfig, cfg: ResearchConfig, manifests_dir: Path) -> None:
    """Fetch data, evaluate factors, write JSON manifest + markdown report for one symbol."""
    period_days = cfg.period
    horizons = list(cfg.horizons_h)

    print(f"\n{'='*60}")
    print(f"Symbol: {sym.name.upper()} ({sym.okx_swap} / {sym.ccxt_bybit})")
    print(f"{'='*60}")

    print(f"[1/5] funding history (last {period_days}d, ccxt multi-year)")
    funding = fetch_funding_history_multiyear(
        ccxt_symbol=sym.ccxt_bybit, days=period_days, exchange="binance",
        okx_swap=sym.okx_swap,
    )
    print(f"     rows: {len(funding)}  range: {funding.index.min()} ~ {funding.index.max()}")

    print(f"[2/5] hourly candles (history endpoint, last {period_days}d)")
    candles = fetch_candles(sym.okx_swap, period_days, bar="1H", use_history_endpoint=True)
    print(f"     rows: {len(candles)}  range: {candles.index.min()} ~ {candles.index.max()}")

    print(f"[3/5] Bybit hourly OI history (last {period_days}d)")
    try:
        oi_hist = fetch_oi_history_bybit(sym.ccxt_bybit, days=period_days, timeframe="1h")
        print(f"     rows: {len(oi_hist)}  range: {oi_hist.index.min()} ~ {oi_hist.index.max()}")
    except Exception as e:
        print(f"     WARN: OI fetch failed ({e}); continuing without OI")
        oi_hist = pd.DataFrame(columns=["oi", "oi_usd"])

    print(f"[4/5] Fear & Greed (last {period_days}d)")
    fng = fetch_fear_greed(days=period_days)
    print(f"     rows: {len(fng)}  range: {fng.index.min()} ~ {fng.index.max()}")

    # CoinGecko free tier caps daily history at 365 days per call.
    cg_days = min(period_days, 365)
    print(f"[5/5] CoinGecko stablecoin supply (last {cg_days}d — capped by free tier)")
    try:
        stablecoin = fetch_stablecoin_supply(days=cg_days)
        if stablecoin.empty:
            print("     WARN: stablecoin supply empty, downstream candidates referencing it will skip")
        else:
            print(
                f"     rows: {len(stablecoin)}  range: "
                f"{stablecoin.index.min()} ~ {stablecoin.index.max()}"
            )
    except Exception as e:  # noqa: BLE001
        print(f"     WARN: stablecoin supply fetch failed ({e}); continuing without it")
        stablecoin = pd.DataFrame(columns=["stablecoin_supply"])

    # Align everything onto hourly candle index
    print("\n[align] joining factors to hourly candle index")
    df = pd.DataFrame(index=candles.index)
    df["close"] = candles["close"]

    fund_h = funding.reindex(candles.index, method="ffill").bfill()
    df["funding_rate"] = fund_h["funding_rate"]

    if not oi_hist.empty:
        oi_h = oi_hist.reindex(candles.index, method="ffill")
        df["oi"] = oi_h["oi"]
        df["oi_change_24h"] = df["oi"].pct_change(24)  # stationarize OI
    else:
        df["oi_change_24h"] = pd.NA

    fng_h = fng.reindex(candles.index, method="ffill").bfill()
    df["fng"] = fng_h["fng"]

    df = add_forward_returns(df, "close", horizons)

    # ── Decision table (D5 from design.md) ────────────────────────────────────
    #   RESEARCH_LEGACY_FACTORS=1   → always legacy
    #   RESEARCH_LEGACY_FACTORS=0   → candidates required (raise if missing)
    #   RESEARCH_LEGACY_FACTORS not set + candidates exists → dynamic
    #   RESEARCH_LEGACY_FACTORS not set + candidates_<sym>.failed.json exists → legacy + warn
    #   RESEARCH_LEGACY_FACTORS not set + candidates missing (no json, no failed.json) → legacy + warn
    legacy_env = os.environ.get("RESEARCH_LEGACY_FACTORS", "")
    candidates_manifest = _load_candidates(manifests_dir, sym.name)
    failed_path = manifests_dir / f"candidates_{sym.name}.failed.json"

    if legacy_env == "1":
        # Forced legacy
        print(f"[stage1] {sym.name}: LEGACY MODE (forced via env)")
        all_results = _run_symbol_legacy(sym, cfg, manifests_dir, funding, candles, oi_hist, fng, df)
    elif legacy_env == "0" and candidates_manifest is None:
        # Explicitly require dynamic mode, but candidates missing
        raise FileNotFoundError(f"RESEARCH_LEGACY_FACTORS=0 but candidates_{sym.name}.json not found")
    elif candidates_manifest is not None:
        # Normal dynamic mode
        print(f"[stage1] {sym.name}: DYNAMIC mode ({len(candidates_manifest.candidates)} candidates)")
        all_results = _run_symbol_dynamic(
            sym, cfg, manifests_dir, candidates_manifest,
            funding, candles, oi_hist, df,
            stablecoin=stablecoin,
        )
    else:
        # Fallback to legacy (candidates missing or failed)
        reason = "stage0 failed" if failed_path.exists() else "candidates missing"
        print(f"\033[93m[stage1] {sym.name}: LEGACY MODE — {reason}, using hardcoded factors\033[0m")
        all_results = _run_symbol_legacy(sym, cfg, manifests_dir, funding, candles, oi_hist, fng, df)

    generated_at = datetime.now(timezone.utc)

    # ── JSON manifest ──────────────────────────────────────────────────────────
    manifests_dir.mkdir(parents=True, exist_ok=True)
    manifest = build_factor_manifest(
        symbol=sym.name,
        period_days=period_days,
        horizons_h=horizons,
        factor_results=all_results,
        generated_at=generated_at,
    )
    json_path = manifests_dir / f"factor_{sym.name}.json"
    json_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    print(f"\n[manifest] JSON -> {json_path}")

    # ── Markdown report (Tier-2 audit attachment) ──────────────────────────────
    data_summary = {
        "Sample": f"{sym.okx_swap}, hourly, ~{period_days} days",
        "Funding": f"{len(funding)} rows (OKX 8h)",
        "Candles": f"{len(candles)} rows (OKX hourly)",
        "OI": f"{len(oi_hist)} rows (Bybit hourly)" if not oi_hist.empty else "unavailable",
        "F&G": f"{len(fng)} rows (alternative.me daily)",
        "Horizons tested": ", ".join(f"{h}h" for h in horizons),
    }
    caveats = [
        "OI 來源 Bybit、funding & candles 來源 OKX；不同交易所微小差異但模式高度相關。",
        "F&G 為日頻、forward-fill 到 hourly，可能高估該因子的有效樣本量。",
        "funding 為 8h 頻、forward-fill 到 hourly 同樣造成自相關膨脹，IR 偏樂觀。",
        "OI 用 24h pct change（差分化）使其平穩；原始 OI 為趨勢序列、與價格高度共線。",
        "Spearman IC 不考慮交易成本與滑點，**不代表策略獲利**。",
        "未做 multiple-testing 校正：3 因子 × 4 horizon = 12 檢定，部分 |IC| 可能為偽。",
        f"Verdict 規則：|IC| 取所有 horizon 中最大值；≥0.10 → single_use，[0.03,0.10) → ensemble_only，<0.03 → reject。",
    ]

    md = build_factor_report(
        title=f"Extended Factor Research — {sym.okx_swap}",
        period_days=period_days,
        data_summary=data_summary,
        factor_results=all_results,
        caveats=caveats,
    )
    md_path = manifests_dir / f"factor_{sym.name}.md"
    md_path.write_text(md, encoding="utf-8")
    print(f"[report]   MD  -> {md_path}")


# ─── Entry point ───────────────────────────────────────────────────────────────


def main() -> None:
    cfg = load_config()
    manifests_dir = resolve_manifests_dir()

    print(f"Research config: period={cfg.period}d  horizons={list(cfg.horizons_h)}  symbols={cfg.symbol_names()}")

    for sym in cfg.symbols:
        run_symbol(sym, cfg, manifests_dir)

    print("\n[done] all symbols processed.")


if __name__ == "__main__":
    main()
