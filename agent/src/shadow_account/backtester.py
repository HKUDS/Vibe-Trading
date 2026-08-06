"""Shadow Account — multi-market backtest driver + delta-PnL attribution.

Responsibilities:
    1. Pick representative symbols per market based on the user's preferred
       markets (with a liquid-basket fallback).
    2. Group the selection by settlement currency, render one run_dir per
       currency pool (via ``codegen.write_run_dir``) and call
       ``src.tools.backtest_tool.run_backtest`` once per pool.
    3. Parse the emitted artifacts (metrics JSON / equity CSV) back into a
       ``ShadowBacktestResult``.
    4. Compute attribution: noise trades, missed signals, early/late exits,
       overtrading — each as signed PnL.

The attribution algorithm is deliberately arithmetic-only: no LLM, no
simulation rebuild. This keeps the numbers auditable and reproducible.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pandas as pd

from backtest.engines._market_hooks import code_currency
from src.shadow_account.codegen import write_run_dir
from src.shadow_account.models import (
    AttributionBreakdown,
    ShadowBacktestResult,
    ShadowProfile,
)
from src.shadow_account.storage import runs_dir
from src.tools.trade_journal_parsers import parse_file, records_to_dataframe
from src.tools.trade_journal_tool import pair_trades_fifo

logger = logging.getLogger(__name__)

SUPPORTED_MARKETS: tuple[str, ...] = ("china_a", "hk", "us", "crypto")

_LIQUID_BASKETS: dict[str, list[str]] = {
    "china_a": ["600519.SH", "000858.SZ", "300750.SZ", "600036.SH", "000001.SZ"],
    "hk":      ["00700.HK", "09988.HK", "03690.HK", "00388.HK", "01810.HK"],
    "us":      ["AAPL.US", "MSFT.US", "NVDA.US", "AMZN.US", "GOOGL.US"],
    "crypto":  ["BTC-USDT", "ETH-USDT", "SOL-USDT", "BNB-USDT", "XRP-USDT"],
}


# ---------------- Code selection ----------------

def select_multi_market_codes(
    profile: ShadowProfile,
    *,
    per_market_count: int = 5,
    markets: tuple[str, ...] = SUPPORTED_MARKETS,
) -> dict[str, list[str]]:
    """Pick representative tickers for each target market.

    Priority:
        1. If the profile's source_market is in the target set and is in the
           liquid basket, surface it first.
        2. Fill remaining markets from their liquid basket.

    Args:
        profile: Shadow profile (source_market guides prioritization).
        per_market_count: Cap per market (clamped to basket size).
        markets: Markets to include.

    Returns:
        Dict market → list of codes, non-empty for every requested market
        that has a known basket.
    """
    selection: dict[str, list[str]] = {}
    for market in markets:
        basket = _LIQUID_BASKETS.get(market)
        if not basket:
            continue
        selection[market] = basket[: max(1, per_market_count)]
    return selection


def flatten_codes(selection: dict[str, list[str]]) -> list[str]:
    """Flatten per-market selection into a unique, order-preserving code list."""
    seen: set[str] = set()
    out: list[str] = []
    for codes in selection.values():
        for c in codes:
            if c not in seen:
                out.append(c)
                seen.add(c)
    return out


def _group_selection_by_currency(
    selection: dict[str, list[str]],
) -> dict[str, dict[str, list[str]]]:
    """Group a per-market selection by settlement currency.

    The composite backtest engine refuses a code set that spans currencies
    (its shared capital pool has no FX translation), so multi-market shadow
    runs are split into one backtest per currency pool. Markets that settle
    in the same currency (us + crypto → USD) share one pool.

    Args:
        selection: Dict market → list of codes.

    Returns:
        ``{currency: {market: [codes]}}`` preserving market insertion order
        within each group and first-seen currency order across groups.
        Codes are grouped per-code, so a market whose codes span currencies
        is split across groups. Empty code lists produce no entries.
    """
    groups: dict[str, dict[str, list[str]]] = {}
    for market, codes in selection.items():
        for code in codes:
            currency = code_currency(code)
            groups.setdefault(currency, {}).setdefault(market, []).append(code)
    return groups


def _usable_metrics(combined: dict[str, Any]) -> bool:
    """True when a combined metrics dict carries real numbers (not an error)."""
    return bool(combined) and "error" not in combined


def _headline_index(
    group_results: list[tuple[str, dict[str, float]]],
    selection: dict[str, list[str]],
    source_market: str,
) -> int:
    """Pick the headline currency group for combined metrics + attribution.

    Preference order:
        1. The group holding the profile's source-market codes, when it has
           usable metrics — the journal's realized PnL is denominated in that
           market's currency, so only this pool makes delta-PnL meaningful.
        2. The first group with usable metrics (deterministic fallback).
        3. Index 0 (all groups failed — keeps the error-reporting path).

    Args:
        group_results: ``(currency, combined)`` pairs in run order.
        selection: Original per-market selection.
        source_market: Profile's dominant journal market.

    Returns:
        Index into ``group_results``.
    """
    source_codes = selection.get(source_market) or []
    if source_codes:
        source_currency = code_currency(source_codes[0])
        for i, (currency, combined) in enumerate(group_results):
            if currency == source_currency and _usable_metrics(combined):
                return i
    for i, (_, combined) in enumerate(group_results):
        if _usable_metrics(combined):
            return i
    return 0


# ---------------- Backtest execution ----------------

def run_shadow_backtest(
    profile: ShadowProfile,
    *,
    window_start: str,
    window_end: str,
    markets: tuple[str, ...] = SUPPORTED_MARKETS,
    per_market_count: int = 5,
    source: str = "auto",
    initial_capital: float = 1_000_000.0,
    journal_path: str | Path | None = None,
    run_backtest_fn: Any | None = None,
) -> ShadowBacktestResult:
    """Drive a multi-market backtest from a ShadowProfile.

    Markets are backtested per settlement currency: the composite engine
    refuses a mixed-currency code set (its shared capital pool has no FX
    translation), so the selection is split into one run per currency pool —
    e.g. the default four markets produce three runs: CNY (china_a),
    HKD (hk) and USD (us + crypto sharing one pool). Each pool starts with
    the full ``initial_capital``; there is no cross-currency aggregation.

    Args:
        profile: ShadowProfile to replay.
        window_start / window_end: ISO dates.
        markets: Target market buckets.
        per_market_count: Codes per market.
        source: Loader source (``auto`` routes by suffix).
        initial_capital: Starting cash per currency pool.
        journal_path: Original journal path (used to compute attribution
            against the user's realized trades). Attribution is skipped if
            None or the file is missing.
        run_backtest_fn: Injection point for tests — callable(run_dir_str)
            returning the same JSON payload as
            ``src.tools.backtest_tool.run_backtest``. Defaults to the real
            entrypoint.

    Returns:
        ShadowBacktestResult with per-market metrics from each market's own
        currency pool, combined metrics from the headline pool (the profile's
        source-market currency when available — the only pool whose PnL is
        comparable with the journal), one equity curve per pool plus a
        ``combined`` alias of the headline curve, and attribution (zeros when
        unavailable).
    """
    selection = select_multi_market_codes(
        profile, per_market_count=per_market_count, markets=markets,
    )
    groups = _group_selection_by_currency(selection)
    if not groups:
        raise ValueError("No codes available for requested markets.")

    base_dir = runs_dir(profile.shadow_id)
    backtest_fn = run_backtest_fn or _default_run_backtest_fn()

    # One backtest per currency pool; a failing pool degrades to an error
    # row without aborting the others.
    group_results: list[
        tuple[str, dict[str, dict[str, float]], dict[str, float], list[tuple[str, float]]]
    ] = []
    for currency, sub_selection in groups.items():
        codes = flatten_codes(sub_selection)
        group_run_dir = base_dir / currency
        write_run_dir(
            profile,
            group_run_dir,
            codes=codes,
            start_date=window_start,
            end_date=window_end,
            source=source,
            initial_capital=initial_capital,
        )
        payload = json.loads(backtest_fn(str(group_run_dir)))
        per_market, combined, curves = _summarize_artifacts(
            payload=payload, run_dir=group_run_dir, selection=sub_selection,
        )
        group_results.append(
            (currency, per_market, combined, curves.get("combined") or []),
        )

    headline = _headline_index(
        [(currency, combined) for currency, _, combined, _ in group_results],
        selection,
        profile.source_market,
    )
    headline_currency, _, headline_combined, headline_points = group_results[headline]

    per_market: dict[str, dict[str, float]] = {}
    for _, group_per_market, _, _ in group_results:
        per_market.update(group_per_market)

    combined = dict(headline_combined)
    if len(group_results) > 1 and _usable_metrics(combined):
        combined["_currency_note"] = (
            f"headline metrics are the {headline_currency} currency pool; "
            f"{len(group_results)} currency pools ran — other pools are "
            "reported in per_market rows (no FX conversion)"
        )

    equity_curves: dict[str, list[tuple[str, float]]] = {
        currency: points
        for currency, _, _, points in group_results
        if points
    }
    if headline_points:
        equity_curves["combined"] = headline_points

    attribution, shadow_pnl, real_pnl = _attribution_or_zero(
        profile=profile,
        journal_path=journal_path,
        combined=combined,
    )

    result = ShadowBacktestResult(
        shadow_id=profile.shadow_id,
        per_market=per_market,
        combined=combined,
        equity_curves=equity_curves,
        attribution=attribution,
        shadow_total_pnl=shadow_pnl,
        real_total_pnl=real_pnl,
        delta_pnl=round(shadow_pnl - real_pnl, 2),
    )
    _cache_result(base_dir, result)
    return result


def load_cached_result(shadow_id: str) -> ShadowBacktestResult | None:
    """Load the last cached backtest result for a shadow, if any."""
    cache_path = runs_dir(shadow_id) / "shadow_result.json"
    if not cache_path.exists():
        return None
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    attr = data.get("attribution") or {}
    return ShadowBacktestResult(
        shadow_id=data["shadow_id"],
        per_market=data.get("per_market") or {},
        combined=data.get("combined") or {},
        equity_curves={
            k: [(str(pt[0]), float(pt[1])) for pt in v]
            for k, v in (data.get("equity_curves") or {}).items()
        },
        attribution=AttributionBreakdown(
            missed_signals_pnl=float(attr.get("missed_signals_pnl", 0.0)),
            noise_trades_pnl=float(attr.get("noise_trades_pnl", 0.0)),
            early_exit_pnl=float(attr.get("early_exit_pnl", 0.0)),
            late_exit_pnl=float(attr.get("late_exit_pnl", 0.0)),
            overtrading_pnl=float(attr.get("overtrading_pnl", 0.0)),
            counterfactual_trades=tuple(attr.get("counterfactual_trades") or ()),
        ),
        shadow_total_pnl=float(data.get("shadow_total_pnl", 0.0)),
        real_total_pnl=float(data.get("real_total_pnl", 0.0)),
        delta_pnl=float(data.get("delta_pnl", 0.0)),
    )


def _cache_result(run_dir: Path, result: ShadowBacktestResult) -> None:
    """Persist a ShadowBacktestResult so downstream tools don't re-backtest."""
    from dataclasses import asdict as _asdict

    payload = _asdict(result)
    try:
        (run_dir / "shadow_result.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
    except OSError as exc:  # pragma: no cover — disk failure is non-fatal
        logger.warning("Failed to cache shadow result: %s", exc)


def _default_run_backtest_fn():
    from src.tools.backtest_tool import run_backtest
    return run_backtest


# ---------------- Artifact parsing ----------------

def _summarize_artifacts(
    *,
    payload: dict[str, Any],
    run_dir: Path,
    selection: dict[str, list[str]],
) -> tuple[dict[str, dict[str, float]], dict[str, float], dict[str, list[tuple[str, float]]]]:
    """Turn raw backtest output into (per_market, combined, equity_curves).

    Gracefully degrades when artifacts are missing (e.g. data fetch failed):
    returns empty dicts and a combined dict containing the error reason.
    """
    artifacts = payload.get("artifacts") or {}
    status = payload.get("status", "error")

    combined = _load_metrics(artifacts, run_dir)
    equity_points = _load_equity_curve(artifacts, run_dir)

    # Only surface an error when we genuinely have no metrics. A non-ok
    # status with usable metrics typically means a transient data-source
    # warning (e.g. yfinance flaked on one market) — downgrading to ok is
    # more faithful to what the user actually has.
    if not combined and status != "ok":
        combined = {"error": payload.get("stderr", "")[-200:] or "backtest failed"}

    per_market = _per_market_breakdown(combined, selection)
    equity_curves = {"combined": equity_points} if equity_points else {}
    return per_market, combined, equity_curves


def _load_metrics(artifacts: dict[str, str], run_dir: Path) -> dict[str, float]:
    """Pull a numeric metrics dict from the run_dir.

    Looks for ``metrics.json`` first (preferred), then ``metrics.csv``.
    Unknown shape → empty dict (caller treats as failure).
    """
    for key in ("metrics.json", "metrics", "metrics.csv"):
        path_str = artifacts.get(key)
        if not path_str:
            continue
        path = Path(path_str)
        if not path.exists():
            continue
        try:
            if path.suffix == ".json":
                data = json.loads(path.read_text(encoding="utf-8"))
                return _coerce_numeric(data)
            if path.suffix == ".csv":
                df = pd.read_csv(path)
                if df.empty:
                    return {}
                row = df.iloc[-1].to_dict()
                return _coerce_numeric(row)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            logger.warning("Failed to parse metrics %s: %s", path, exc)

    # Fallback: scan run_dir for a metrics file.
    for path in run_dir.glob("**/metrics.*"):
        try:
            if path.suffix == ".json":
                return _coerce_numeric(json.loads(path.read_text(encoding="utf-8")))
            if path.suffix == ".csv":
                df = pd.read_csv(path)
                if not df.empty:
                    return _coerce_numeric(df.iloc[-1].to_dict())
        except Exception:
            continue
    return {}


def _load_equity_curve(artifacts: dict[str, str], run_dir: Path) -> list[tuple[str, float]]:
    """Load the equity curve as [(iso_date, equity), ...]."""
    candidates: list[Path] = []
    for key in ("equity.csv", "equity", "equity_curve.csv"):
        path_str = artifacts.get(key)
        if path_str:
            candidates.append(Path(path_str))
    candidates.extend(run_dir.glob("**/equity*.csv"))

    seen: set[Path] = set()
    for path in candidates:
        if path in seen or not path.exists():
            continue
        seen.add(path)
        try:
            df = pd.read_csv(path)
        except (OSError, pd.errors.ParserError) as exc:
            logger.warning("Failed to read equity csv %s: %s", path, exc)
            continue
        if df.empty:
            continue
        date_col = next((c for c in df.columns if c.lower() in ("date", "datetime", "timestamp")), df.columns[0])
        equity_col = next(
            (c for c in df.columns if c.lower() in ("equity", "equity_curve", "value", "net_value")),
            df.columns[-1],
        )
        return [(str(row[date_col]), float(row[equity_col])) for _, row in df.iterrows()]
    return []


def _coerce_numeric(data: dict[str, Any]) -> dict[str, float]:
    """Keep only the scalar numeric fields from a metrics dict."""
    out: dict[str, float] = {}
    for key, value in data.items():
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            out[str(key)] = float(value)
    return out


def _per_market_breakdown(
    combined: dict[str, float],
    selection: dict[str, list[str]],
) -> dict[str, dict[str, float]]:
    """Project one currency pool's combined metrics into its markets.

    Markets within a pool genuinely shared the capital pool, so they share
    its metrics; each market's row is completed from its own pool's run.
    Error payloads yield empty rows rather than propagating the error dict.
    """
    if not _usable_metrics(combined):
        return {market: {} for market in selection}
    return {market: dict(combined) for market in selection}


# ---------------- Attribution ----------------

def _attribution_or_zero(
    *,
    profile: ShadowProfile,
    journal_path: str | Path | None,
    combined: dict[str, float],
) -> tuple[AttributionBreakdown, float, float]:
    """Compute attribution if the journal is available, else return zeros."""
    shadow_pnl = float(combined.get("total_return_abs") or combined.get("total_pnl") or 0.0)
    if not journal_path:
        return _zero_attribution(), shadow_pnl, 0.0
    path = Path(journal_path)
    if not path.exists():
        return _zero_attribution(), shadow_pnl, 0.0

    try:
        _, records = parse_file(path)
        trades_df = records_to_dataframe(records)
        roundtrips = pair_trades_fifo(trades_df)
    except Exception as exc:
        logger.warning("Attribution skipped — journal parse failed: %s", exc)
        return _zero_attribution(), shadow_pnl, 0.0

    if not roundtrips:
        return _zero_attribution(), shadow_pnl, 0.0

    return _compute_attribution(profile=profile, roundtrips=roundtrips, shadow_pnl=shadow_pnl)


def _zero_attribution() -> AttributionBreakdown:
    return AttributionBreakdown(
        missed_signals_pnl=0.0,
        noise_trades_pnl=0.0,
        early_exit_pnl=0.0,
        late_exit_pnl=0.0,
        overtrading_pnl=0.0,
        counterfactual_trades=(),
    )


def _compute_attribution(
    *,
    profile: ShadowProfile,
    roundtrips: list[dict[str, Any]],
    shadow_pnl: float,
) -> tuple[AttributionBreakdown, float, float]:
    """Attribute the delta between user's real PnL and shadow PnL.

    Decomposition (signed — positive means shadow would have earned more):

        noise_trades_pnl   = -Σ realized_pnl on rule-violating trades
                             (user's unexplained losses that shadow avoids)
        early_exit_pnl     = +Σ shortfall on winning trades exited before
                              the median rule holding range
        late_exit_pnl      = +Σ excess loss on losing trades held past the
                              median rule holding range
        overtrading_pnl    = -Σ realized_pnl on trades beyond the shadow's
                              expected trade budget (1 trade per 2*hold_days)
        missed_signals_pnl = shadow_pnl - real_pnl - (noise+early+late+over)
                              (residual — everything the above can't explain)

    ``counterfactual_trades`` lists the top-5 |impact| roundtrips for
    Section 6 of the report.
    """
    rule_hold_lo, rule_hold_hi = _aggregate_holding_range(profile)
    noise = 0.0
    early = 0.0
    late = 0.0
    real_pnl = 0.0
    counterfactuals: list[dict[str, Any]] = []

    for rt in roundtrips:
        pnl = float(rt["pnl"])
        real_pnl += pnl
        hold = float(rt["hold_days"])
        within_rule = rule_hold_lo <= hold <= rule_hold_hi
        impact = 0.0
        reason = ""
        if not within_rule:
            noise += -pnl
            impact += -pnl
            reason = "rule_violation"
        if pnl > 0 and hold < rule_hold_lo:
            shortfall = pnl * max(0.0, (rule_hold_lo - hold) / max(rule_hold_lo, 1))
            early += shortfall
            impact += shortfall
            reason = reason or "early_exit"
        if pnl < 0 and hold > rule_hold_hi:
            excess = -pnl * max(0.0, (hold - rule_hold_hi) / max(rule_hold_hi, 1))
            late += excess
            impact += excess
            reason = reason or "late_exit"
        if impact != 0.0:
            counterfactuals.append({
                "symbol": rt["symbol"],
                "buy_dt": str(rt["buy_dt"]),
                "sell_dt": str(rt["sell_dt"]),
                "hold_days": hold,
                "pnl": round(pnl, 2),
                "impact": round(impact, 2),
                "reason": reason,
            })

    overtrading = _overtrading_pnl(profile=profile, roundtrips=roundtrips)
    explained = noise + early + late + overtrading
    missed = round(shadow_pnl - real_pnl - explained, 2)

    counterfactuals.sort(key=lambda r: abs(r["impact"]), reverse=True)
    top5 = tuple(counterfactuals[:5])

    return (
        AttributionBreakdown(
            missed_signals_pnl=round(missed, 2),
            noise_trades_pnl=round(noise, 2),
            early_exit_pnl=round(early, 2),
            late_exit_pnl=round(late, 2),
            overtrading_pnl=round(overtrading, 2),
            counterfactual_trades=top5,
        ),
        round(shadow_pnl, 2),
        round(real_pnl, 2),
    )


def _aggregate_holding_range(profile: ShadowProfile) -> tuple[float, float]:
    """Union holding-day ranges across all rules (lo=min, hi=max)."""
    if not profile.rules:
        return (1.0, 30.0)
    los = [r.holding_days_range[0] for r in profile.rules]
    his = [r.holding_days_range[1] for r in profile.rules]
    return (float(min(los)), float(max(his)))


def _overtrading_pnl(
    *,
    profile: ShadowProfile,
    roundtrips: list[dict[str, Any]],
) -> float:
    """Excess-frequency PnL: trades beyond the shadow's expected budget.

    Shadow runs roughly 1 trade per ``2 * median_hold_days`` bars. We
    compare against the user's actual roundtrip count over the same span.
    Excess trades' PnL is totaled with a negative sign (shadow would've
    skipped them, so real PnL — positive or negative — is "noise").
    """
    if not roundtrips:
        return 0.0
    median_hold, _ = profile.typical_holding_days
    if median_hold <= 0:
        return 0.0
    span_days = (
        pd.Timestamp(roundtrips[-1]["sell_dt"]) - pd.Timestamp(roundtrips[0]["buy_dt"])
    ).total_seconds() / 86400.0
    expected = max(1.0, span_days / max(2 * median_hold, 1.0))
    actual = len(roundtrips)
    if actual <= expected:
        return 0.0
    # Penalize the cheapest (lowest |pnl|) extras — those look like noise.
    extras = sorted(roundtrips, key=lambda rt: abs(float(rt["pnl"])))
    extra_count = int(actual - expected)
    extra_pnl = sum(float(rt["pnl"]) for rt in extras[:extra_count])
    return -extra_pnl


__all__ = [
    "SUPPORTED_MARKETS",
    "flatten_codes",
    "load_cached_result",
    "run_shadow_backtest",
    "select_multi_market_codes",
]

