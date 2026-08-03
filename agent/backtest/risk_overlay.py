"""Causal risk overlays on target weight matrices (pre-execution).

Applied after signal alignment / optimizer output and before bar-by-bar fills.
Controls are intentionally bar/tick-proxy — they do **not** simulate exchange
co-location, queue priority, or nanosecond latency. They do enforce risk
budgets that matter for high-turnover / short-horizon styles:

  - volatility targeting
  - gross leverage / net exposure / per-name concentration caps
  - inventory mean-reversion pull toward flat (strength scales with |net|)
  - turnover throttles
  - drawdown kill-switch with cooldown + hysteresis re-arm
  - per-name stop-loss scaling on adverse marked moves (close, or OHLC high/low proxy)
  - intrabar-ish proxies: partial fills + next-bar open slippage haircut
  - per-name trailing vol budgets and portfolio trailing CVaR budgets
  - correlation-aware cluster gross caps (highly correlated names share a budget)
  - turnover-aware cost feedback into sizing (shrink Δw when implied cost is high)
  - optional trailing vol governor that only downscales spike regimes vs vol_target

Config via ``config.json``::

    "risk_overlay": {
      "enabled": true,
      "vol_target": 0.12,
      "vol_lookback": 20,
      "vol_governor_lookback": 60,
      "vol_governor_spike_ratio": 1.5,
      "max_gross_leverage": 1.0,
      "max_net_exposure": 0.5,
      "max_name_weight": 0.25,
      "max_corr_cluster_gross": 0.6,
      "corr_cluster_threshold": 0.75,
      "corr_lookback": 40,
      "max_turnover": 0.35,
      "turnover_cost_feedback": 0.002,
      "turnover_cost_bps": 10.0,
      "max_drawdown_kill": 0.12,
      "kill_cooldown_bars": 5,
      "kill_reset_drawdown": 0.03,
      "stop_loss": 0.04,
      "ohlc_stop": true,
      "inventory_mean_reversion": 0.15,
      "partial_fill_rate": 0.7,
      "next_bar_open_slippage_bps": 5.0,
      "max_name_vol": 0.60,
      "name_vol_lookback": 20,
      "max_portfolio_cvar": 0.04,
      "cvar_lookback": 40,
      "cvar_alpha": 0.95,
      "bars_per_year": 252
    }

Off by default so existing configs behave unchanged.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Mapping, Optional, Tuple

import numpy as np
import pandas as pd

_EPS = 1e-12


@dataclass(frozen=True)
class RiskOverlayConfig:
    """Parsed risk-overlay knobs (all optional; None = inactive)."""

    enabled: bool = True
    vol_target: Optional[float] = None
    vol_lookback: int = 20
    # Longer lookback governor: only downscales when short vol spikes vs long vol.
    vol_governor_lookback: Optional[int] = None
    vol_governor_spike_ratio: float = 1.5
    max_gross_leverage: Optional[float] = None
    max_net_exposure: Optional[float] = None
    max_name_weight: Optional[float] = None
    # Cap combined |w| among names whose trailing pairwise corr exceeds threshold.
    max_corr_cluster_gross: Optional[float] = None
    corr_cluster_threshold: float = 0.75
    corr_lookback: int = 40
    max_turnover: Optional[float] = None
    # Shrink Δw when implied turnover×bps cost exceeds this equity fraction.
    turnover_cost_feedback: Optional[float] = None
    turnover_cost_bps: float = 10.0
    max_drawdown_kill: Optional[float] = None
    kill_cooldown_bars: int = 0
    kill_reset_drawdown: Optional[float] = None
    stop_loss: Optional[float] = None
    ohlc_stop: bool = False  # use bar high/low for stop trigger when available
    inventory_mean_reversion: Optional[float] = None
    # Intrabar / next-bar proxies (bar fidelity only — not LOB).
    partial_fill_rate: Optional[float] = None
    next_bar_open_slippage_bps: Optional[float] = None
    # Risk budgets.
    max_name_vol: Optional[float] = None
    name_vol_lookback: int = 20
    max_portfolio_cvar: Optional[float] = None
    cvar_lookback: int = 40
    cvar_alpha: float = 0.95
    bars_per_year: int = 252

    def active(self) -> bool:
        if not self.enabled:
            return False
        return any(
            v is not None
            for v in (
                self.vol_target,
                self.vol_governor_lookback,
                self.max_gross_leverage,
                self.max_net_exposure,
                self.max_name_weight,
                self.max_corr_cluster_gross,
                self.max_turnover,
                self.turnover_cost_feedback,
                self.max_drawdown_kill,
                self.stop_loss,
                self.inventory_mean_reversion,
                self.partial_fill_rate,
                self.next_bar_open_slippage_bps,
                self.max_name_vol,
                self.max_portfolio_cvar,
            )
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _finite_positive(name: str, value: Any, *, allow_none: bool = True) -> Optional[float]:
    if value is None:
        if allow_none:
            return None
        raise ValueError(f"{name} is required")
    if isinstance(value, (bool, np.bool_)):
        raise ValueError(f"{name} must be numeric, not boolean")
    try:
        v = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not np.isfinite(v) or v <= 0:
        raise ValueError(f"{name} must be finite and > 0")
    return v


def _finite_nonneg(name: str, value: Any, *, allow_none: bool = True) -> Optional[float]:
    if value is None:
        if allow_none:
            return None
        raise ValueError(f"{name} is required")
    if isinstance(value, (bool, np.bool_)):
        raise ValueError(f"{name} must be numeric, not boolean")
    try:
        v = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not np.isfinite(v) or v < 0:
        raise ValueError(f"{name} must be finite and >= 0")
    return v


def _finite_unit_interval(name: str, value: Any, *, allow_none: bool = True) -> Optional[float]:
    """Parse (0, 1] fill fraction / rate."""
    if value is None:
        if allow_none:
            return None
        raise ValueError(f"{name} is required")
    if isinstance(value, (bool, np.bool_)):
        raise ValueError(f"{name} must be numeric, not boolean")
    try:
        v = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not np.isfinite(v) or v <= 0 or v > 1.0:
        raise ValueError(f"{name} must be in (0, 1], got {v}")
    return v


def load_risk_overlay(config: Mapping[str, Any]) -> Optional[RiskOverlayConfig]:
    """Build overlay config from ``config['risk_overlay']`` (None if unset/off)."""
    raw = config.get("risk_overlay")
    if raw in (None, {}, False):
        return None
    if not isinstance(raw, Mapping):
        raise ValueError("risk_overlay must be a mapping")
    enabled = bool(raw.get("enabled", True))
    lookback = int(raw.get("vol_lookback", 20))
    if lookback < 2:
        raise ValueError(f"vol_lookback must be >= 2, got {lookback}")
    cooldown = int(raw.get("kill_cooldown_bars", 0))
    if cooldown < 0:
        raise ValueError(f"kill_cooldown_bars must be >= 0, got {cooldown}")
    bpy = int(raw.get("bars_per_year", config.get("bars_per_year", 252) or 252))
    if bpy < 1:
        raise ValueError(f"bars_per_year must be >= 1, got {bpy}")
    name_lb = int(raw.get("name_vol_lookback", lookback))
    if name_lb < 2:
        raise ValueError(f"name_vol_lookback must be >= 2, got {name_lb}")
    cvar_lb = int(raw.get("cvar_lookback", 40))
    if cvar_lb < 5:
        raise ValueError(f"cvar_lookback must be >= 5, got {cvar_lb}")
    cvar_alpha = float(raw.get("cvar_alpha", 0.95))
    if not (0.5 < cvar_alpha < 1.0):
        raise ValueError(f"cvar_alpha must be in (0.5, 1), got {cvar_alpha}")

    gov_lb_raw = raw.get("vol_governor_lookback")
    gov_lb: Optional[int] = None
    if gov_lb_raw is not None:
        gov_lb = int(gov_lb_raw)
        if gov_lb < 2:
            raise ValueError(f"vol_governor_lookback must be >= 2, got {gov_lb}")

    spike_ratio = float(raw.get("vol_governor_spike_ratio", 1.5))
    if not np.isfinite(spike_ratio) or spike_ratio < 1.0:
        raise ValueError(f"vol_governor_spike_ratio must be finite and >= 1, got {spike_ratio}")

    corr_thr = float(raw.get("corr_cluster_threshold", 0.75))
    if not np.isfinite(corr_thr) or not (0.0 < corr_thr <= 1.0):
        raise ValueError(f"corr_cluster_threshold must be in (0, 1], got {corr_thr}")
    corr_lb = int(raw.get("corr_lookback", 40))
    if corr_lb < 5:
        raise ValueError(f"corr_lookback must be >= 5, got {corr_lb}")

    turnover_bps = float(raw.get("turnover_cost_bps", 10.0))
    if not np.isfinite(turnover_bps) or turnover_bps < 0:
        raise ValueError(f"turnover_cost_bps must be finite and >= 0, got {turnover_bps}")

    cfg = RiskOverlayConfig(
        enabled=enabled,
        vol_target=_finite_positive("vol_target", raw.get("vol_target")),
        vol_lookback=lookback,
        vol_governor_lookback=gov_lb,
        vol_governor_spike_ratio=spike_ratio,
        max_gross_leverage=_finite_positive("max_gross_leverage", raw.get("max_gross_leverage")),
        max_net_exposure=_finite_nonneg("max_net_exposure", raw.get("max_net_exposure")),
        max_name_weight=_finite_positive("max_name_weight", raw.get("max_name_weight")),
        max_corr_cluster_gross=_finite_positive("max_corr_cluster_gross", raw.get("max_corr_cluster_gross")),
        corr_cluster_threshold=corr_thr,
        corr_lookback=corr_lb,
        max_turnover=_finite_positive("max_turnover", raw.get("max_turnover")),
        turnover_cost_feedback=_finite_positive("turnover_cost_feedback", raw.get("turnover_cost_feedback")),
        turnover_cost_bps=turnover_bps,
        max_drawdown_kill=_finite_positive("max_drawdown_kill", raw.get("max_drawdown_kill")),
        kill_cooldown_bars=cooldown,
        kill_reset_drawdown=_finite_positive("kill_reset_drawdown", raw.get("kill_reset_drawdown")),
        stop_loss=_finite_positive("stop_loss", raw.get("stop_loss")),
        ohlc_stop=bool(raw.get("ohlc_stop", False)),
        inventory_mean_reversion=_finite_nonneg("inventory_mean_reversion", raw.get("inventory_mean_reversion")),
        partial_fill_rate=_finite_unit_interval("partial_fill_rate", raw.get("partial_fill_rate")),
        next_bar_open_slippage_bps=_finite_nonneg("next_bar_open_slippage_bps", raw.get("next_bar_open_slippage_bps")),
        max_name_vol=_finite_positive("max_name_vol", raw.get("max_name_vol")),
        name_vol_lookback=name_lb,
        max_portfolio_cvar=_finite_positive("max_portfolio_cvar", raw.get("max_portfolio_cvar")),
        cvar_lookback=cvar_lb,
        cvar_alpha=cvar_alpha,
        bars_per_year=bpy,
    )
    if not cfg.active():
        return None
    return cfg


def _clip_exposure_caps(
    w: np.ndarray,
    config: RiskOverlayConfig,
    *,
    diagnostics: Optional[Dict[str, Any]] = None,
    diag_prefix: str = "",
) -> np.ndarray:
    """Enforce name / gross / net caps. Safe to call repeatedly after scaling.

    Order: per-name → gross → net. Net scaling preserves relative weights and
    can leave gross below its cap (intentional — directional inventory first).
    """
    out = w
    if config.max_name_weight is not None:
        cap = float(config.max_name_weight)
        over = np.abs(out) > cap + _EPS
        if over.any():
            out = out.copy()
            out[over] = np.sign(out[over]) * cap
            if diagnostics is not None:
                key = f"{diag_prefix}name_clips" if diag_prefix else "name_clips"
                diagnostics[key] = int(diagnostics.get(key, 0)) + 1

    if config.max_gross_leverage is not None:
        gross = float(np.sum(np.abs(out)))
        lim = float(config.max_gross_leverage)
        if gross > lim + _EPS:
            out = out * (lim / gross)
            if diagnostics is not None:
                key = f"{diag_prefix}gross_clips" if diag_prefix else "gross_clips"
                diagnostics[key] = int(diagnostics.get(key, 0)) + 1

    if config.max_net_exposure is not None:
        net = float(np.sum(out))
        lim = float(config.max_net_exposure)
        if abs(net) > lim + _EPS and abs(net) > _EPS:
            out = out * (lim / abs(net))
            if diagnostics is not None:
                key = f"{diag_prefix}net_clips" if diag_prefix else "net_clips"
                diagnostics[key] = int(diagnostics.get(key, 0)) + 1
            # Net scale can re-inflate per-name / gross — one more pass.
            if config.max_name_weight is not None:
                cap = float(config.max_name_weight)
                over = np.abs(out) > cap + _EPS
                if over.any():
                    out = out.copy()
                    out[over] = np.sign(out[over]) * cap
            if config.max_gross_leverage is not None:
                gross = float(np.sum(np.abs(out)))
                lim_g = float(config.max_gross_leverage)
                if gross > lim_g + _EPS:
                    out = out * (lim_g / gross)
    return out


def _corr_clusters_at_bar(
    corr_mats: np.ndarray,
    t: int,
    threshold: float,
    n_names: int,
) -> list[list[int]]:
    """Connected components where |corr_ij| >= threshold (union-find)."""
    parent = list(range(n_names))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[rj] = ri

    if t < 0 or t >= corr_mats.shape[0]:
        return [[i] for i in range(n_names)]
    mat = corr_mats[t]
    thr = float(threshold)
    for i in range(n_names):
        for j in range(i + 1, n_names):
            c = mat[i, j]
            if np.isfinite(c) and abs(float(c)) >= thr:
                union(i, j)
    groups: Dict[int, list[int]] = {}
    for i in range(n_names):
        groups.setdefault(find(i), []).append(i)
    return list(groups.values())


def _clip_corr_clusters(
    w: np.ndarray,
    clusters: list[list[int]],
    max_cluster_gross: float,
) -> tuple[np.ndarray, int]:
    """Scale each correlated cluster so sum(|w|) ≤ max_cluster_gross."""
    out = w.copy()
    clips = 0
    lim = float(max_cluster_gross)
    for members in clusters:
        if len(members) < 2:
            continue
        gross = float(np.sum(np.abs(out[members])))
        if gross > lim + _EPS:
            out[members] *= lim / gross
            clips += 1
    return out, clips


def _precompute_trailing_corr(
    returns: pd.DataFrame,
    lookback: int,
) -> np.ndarray:
    """Causal trailing pairwise corr (uses returns through t-1 via shift)."""
    lagged = returns.shift(1)
    n_bars, n_names = lagged.shape
    out = np.full((n_bars, n_names, n_names), np.nan, dtype=float)
    arr = lagged.to_numpy(dtype=float)
    min_p = max(5, lookback // 2)
    for t in range(n_bars):
        start = max(0, t - lookback)
        window = arr[start:t]
        if window.shape[0] < min_p:
            continue
        with np.errstate(invalid="ignore", divide="ignore"):
            c = np.corrcoef(window, rowvar=False)
        if c.shape == (n_names, n_names):
            out[t] = c
    return out


def _rolling_vol(returns: pd.Series, lookback: int, bars_per_year: int) -> pd.Series:
    vol = returns.rolling(lookback, min_periods=max(2, lookback // 2)).std()
    return vol * np.sqrt(float(bars_per_year))


def _rolling_cvar(returns: pd.Series, lookback: int, alpha: float) -> pd.Series:
    """Causal trailing CVaR (positive = loss). Uses only past window ending at t-1 via shift."""
    r = returns.astype(float)

    def _es(window: np.ndarray) -> float:
        w = window[np.isfinite(window)]
        if len(w) < max(5, lookback // 4):
            return float("nan")
        losses = -w
        cutoff = float(np.quantile(losses, alpha))
        tail = losses[losses >= cutoff]
        return float(np.mean(tail)) if len(tail) else cutoff

    # shift(1): CVaR used at bar t only sees returns through t-1.
    lagged = r.shift(1)
    return lagged.rolling(lookback, min_periods=max(5, lookback // 4)).apply(_es, raw=True)


def apply_risk_overlay(
    positions: pd.DataFrame,
    returns: pd.DataFrame,
    *,
    config: RiskOverlayConfig,
    close: Optional[pd.DataFrame] = None,
    open_: Optional[pd.DataFrame] = None,
    high: Optional[pd.DataFrame] = None,
    low: Optional[pd.DataFrame] = None,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Apply causal risk overlays to a signed weight frame.

    Args:
        positions: Target weights (dates × codes), typically gross ≤ 1.
        returns: Per-asset bar returns aligned to ``positions``.
        config: Overlay knobs.
        close: Optional close prices (used for stop-loss when present).
        open_: Optional open prices for next-bar-open slippage proxy.
        high: Optional high prices for OHLC stop proxy (longs use low, shorts high).
        low: Optional low prices for OHLC stop proxy.

    Returns:
        (adjusted positions, diagnostics dict).
    """
    if not config.active():
        return positions, {"applied": False, "reason": "inactive"}

    pos = positions.astype(float).copy()
    rets = returns.reindex(index=pos.index, columns=pos.columns).fillna(0.0)
    n_bars, n_names = pos.shape
    diagnostics: Dict[str, Any] = {
        "applied": True,
        "config": config.to_dict(),
        "n_bars": int(n_bars),
        "n_names": int(n_names),
        "kill_events": 0,
        "kill_rearms": 0,
        "stop_events": 0,
        "ohlc_stop_events": 0,
        "turnover_clips": 0,
        "turnover_cost_clips": 0,
        "vol_scales_applied": 0,
        "vol_governor_scales": 0,
        "partial_fill_bars": 0,
        "name_vol_clips": 0,
        "cvar_scales": 0,
        "corr_cluster_clips": 0,
        "name_clips": 0,
        "gross_clips": 0,
        "net_clips": 0,
        "open_slippage_haircuts": 0,
        "fidelity": (
            "bar_proxy — no LOB / co-lo / queue priority; "
            "partial_fill, next_bar_open_slippage, and ohlc_stop are "
            "intrabar-ish approximations only"
        ),
    }

    # Portfolio return proxy for vol targeting / kill switch (uses *pre*-overlay
    # weights lagged one bar — causal: scale for bar t uses info through t-1).
    peak = 1.0
    equity = 1.0
    cooldown_left = 0
    kill_armed = True  # hysteresis: False until DD recovers past kill_reset
    prev = np.zeros(n_names, dtype=float)

    # Entry marks for stop-loss (per name).
    entry_price = np.full(n_names, np.nan)
    entry_dir = np.zeros(n_names, dtype=float)
    close_arr: Optional[np.ndarray] = None
    if close is not None and config.stop_loss is not None:
        close_aligned = close.reindex(index=pos.index, columns=pos.columns)
        close_arr = close_aligned.to_numpy(dtype=float)

    high_arr: Optional[np.ndarray] = None
    low_arr: Optional[np.ndarray] = None
    use_ohlc_stop = bool(config.ohlc_stop) and config.stop_loss is not None
    if use_ohlc_stop and high is not None and low is not None:
        high_arr = high.reindex(index=pos.index, columns=pos.columns).to_numpy(dtype=float)
        low_arr = low.reindex(index=pos.index, columns=pos.columns).to_numpy(dtype=float)
    elif use_ohlc_stop:
        use_ohlc_stop = False  # fall back to close-only stops

    # Next-bar open vs prior close gap proxy (adverse haircut on new risk).
    open_gap: Optional[np.ndarray] = None
    if open_ is not None and config.next_bar_open_slippage_bps is not None and close is not None:
        open_a = open_.reindex(index=pos.index, columns=pos.columns).to_numpy(dtype=float)
        close_a = close.reindex(index=pos.index, columns=pos.columns).to_numpy(dtype=float)
        # Gap at t: open[t]/close[t-1] - 1; pad first bar with 0.
        gap = np.zeros_like(open_a)
        gap[1:] = open_a[1:] / np.where(close_a[:-1] > 0, close_a[:-1], np.nan) - 1.0
        open_gap = np.nan_to_num(gap, nan=0.0)

    out = pos.to_numpy(dtype=float).copy()
    rets_arr = rets.to_numpy(dtype=float)

    ann_vol = None
    gov_vol = None
    short_vol_for_gov = None
    if config.vol_target is not None or config.vol_governor_lookback is not None:
        port_rets = (pos.shift(1).fillna(0.0) * rets).sum(axis=1)
        if config.vol_target is not None:
            ann_vol = _rolling_vol(port_rets, config.vol_lookback, config.bars_per_year)
        if config.vol_governor_lookback is not None:
            gov_vol = _rolling_vol(port_rets, int(config.vol_governor_lookback), config.bars_per_year)
            # Short leg for spike detection: reuse vol_target series when present.
            short_vol_for_gov = ann_vol if ann_vol is not None else _rolling_vol(
                port_rets, config.vol_lookback, config.bars_per_year
            )

    name_ann_vol: Optional[pd.DataFrame] = None
    if config.max_name_vol is not None:
        # Causal trailing per-name vol from lagged asset returns.
        lagged_rets = rets.shift(1)
        name_ann_vol = lagged_rets.rolling(
            config.name_vol_lookback, min_periods=max(2, config.name_vol_lookback // 2)
        ).std() * np.sqrt(float(config.bars_per_year))

    port_cvar: Optional[pd.Series] = None
    if config.max_portfolio_cvar is not None:
        port_rets_for_cvar = (pos.shift(1).fillna(0.0) * rets).sum(axis=1)
        port_cvar = _rolling_cvar(port_rets_for_cvar, config.cvar_lookback, config.cvar_alpha)

    corr_mats: Optional[np.ndarray] = None
    if config.max_corr_cluster_gross is not None and n_names >= 2:
        corr_mats = _precompute_trailing_corr(rets, config.corr_lookback)

    fill_rate = float(config.partial_fill_rate) if config.partial_fill_rate is not None else 1.0
    slip_bps = float(config.next_bar_open_slippage_bps) if config.next_bar_open_slippage_bps is not None else 0.0
    reset_dd = float(config.kill_reset_drawdown) if config.kill_reset_drawdown is not None else None
    cost_feedback = float(config.turnover_cost_feedback) if config.turnover_cost_feedback is not None else None
    cost_bps_frac = float(config.turnover_cost_bps) / 10_000.0

    for t in range(n_bars):
        target = out[t].copy()  # desired from signal/optimizer (pre-stateful clips)
        w = target.copy()

        # ── Kill-switch cooldown: stay flat ──
        if cooldown_left > 0:
            w[:] = 0.0
            cooldown_left -= 1
            out[t] = w
            prev = w
            continue

        # ── Hysteresis: stay de-risked until DD recovers ──
        if not kill_armed:
            # Scale inventory hard toward flat while disarmed.
            w *= 0.25
            if config.inventory_mean_reversion is not None:
                net = float(np.sum(w))
                gross = float(np.sum(np.abs(w)))
                if abs(net) > _EPS and gross > _EPS:
                    pull = min(1.0, float(config.inventory_mean_reversion) * 2.0)
                    w = w - pull * net * (np.abs(w) / gross)

        # ── Inventory mean-reversion: pull net exposure toward 0 ──
        # Strength scales with |net| so large inventory is pulled harder.
        if config.inventory_mean_reversion is not None and config.inventory_mean_reversion > 0:
            net = float(np.sum(w))
            if abs(net) > _EPS:
                gross = float(np.sum(np.abs(w)))
                if gross > _EPS:
                    intensity = float(config.inventory_mean_reversion) * (1.0 + min(2.0, abs(net)))
                    intensity = min(1.0, intensity)
                    w = w - intensity * net * (np.abs(w) / gross)

        # ── Per-name trailing vol budget ──
        if config.max_name_vol is not None and name_ann_vol is not None:
            row = name_ann_vol.iloc[t].to_numpy(dtype=float)
            lim = float(config.max_name_vol)
            for j in range(n_names):
                v = row[j] if j < len(row) else float("nan")
                if np.isfinite(v) and v > lim + _EPS and abs(w[j]) > _EPS:
                    w[j] *= lim / v
                    diagnostics["name_vol_clips"] += 1

        # ── Correlation cluster gross caps ──
        if config.max_corr_cluster_gross is not None and corr_mats is not None:
            clusters = _corr_clusters_at_bar(
                corr_mats, t, config.corr_cluster_threshold, n_names
            )
            w, n_clips = _clip_corr_clusters(w, clusters, float(config.max_corr_cluster_gross))
            diagnostics["corr_cluster_clips"] += n_clips

        # ── Name / gross / net exposure (pre-scale) ──
        w = _clip_exposure_caps(w, config, diagnostics=diagnostics)

        # ── Vol targeting (scale using trailing portfolio vol) ──
        if config.vol_target is not None and ann_vol is not None:
            v = float(ann_vol.iloc[t]) if t < len(ann_vol) else float("nan")
            if np.isfinite(v) and v > _EPS:
                scale = float(config.vol_target) / v
                # Cap aggressive leverage from vol targeting alone.
                scale = min(scale, 3.0)
                w *= scale
                diagnostics["vol_scales_applied"] += 1

        # ── Trailing vol governor: only downscale spike regimes ──
        # Compares short-horizon vol to longer governor lookback; when
        # short >> long * spike_ratio, shrink further (never leverages up).
        if (
            config.vol_governor_lookback is not None
            and gov_vol is not None
            and short_vol_for_gov is not None
        ):
            short_v = float(short_vol_for_gov.iloc[t]) if t < len(short_vol_for_gov) else float("nan")
            long_v = float(gov_vol.iloc[t]) if t < len(gov_vol) else float("nan")
            ratio = float(config.vol_governor_spike_ratio)
            if np.isfinite(short_v) and np.isfinite(long_v) and long_v > _EPS:
                if short_v > long_v * ratio + _EPS:
                    gov_scale = (long_v * ratio) / short_v
                    w *= gov_scale
                    diagnostics["vol_governor_scales"] += 1

        # ── Portfolio trailing CVaR budget ──
        if config.max_portfolio_cvar is not None and port_cvar is not None:
            cv = float(port_cvar.iloc[t]) if t < len(port_cvar) else float("nan")
            lim = float(config.max_portfolio_cvar)
            if np.isfinite(cv) and cv > lim + _EPS:
                scale = lim / cv
                w *= scale
                diagnostics["cvar_scales"] += 1

        # Re-enforce ALL exposure caps after vol / governor / CVaR scale.
        w = _clip_exposure_caps(w, config, diagnostics=diagnostics, diag_prefix="post_scale_")

        # ── Next-bar open slippage haircut on new risk ──
        # Proxy: when opening/increasing risk into an adverse open gap, shrink
        # the increment (assumes fill nearer next open, not prior close).
        if open_gap is not None and slip_bps > 0:
            gap = open_gap[t]
            adverse = gap * np.sign(w - prev)
            # Adverse when gap moves against the new trade direction.
            thr = slip_bps / 10_000.0
            for j in range(n_names):
                incr = w[j] - prev[j]
                if abs(incr) < _EPS:
                    continue
                if adverse[j] > thr:
                    # Haircut the increment proportional to how far gap exceeds thr.
                    hair = min(1.0, adverse[j] / max(thr, _EPS) - 1.0)
                    hair = min(0.9, max(0.0, hair))
                    w[j] = prev[j] + incr * (1.0 - hair)
                    diagnostics["open_slippage_haircuts"] += 1

        # ── Stop-loss: flatten names with adverse move from entry ──
        if config.stop_loss is not None and close_arr is not None:
            px = close_arr[t]
            stop = float(config.stop_loss)
            for j in range(n_names):
                if abs(w[j]) < _EPS:
                    entry_price[j] = np.nan
                    entry_dir[j] = 0.0
                    continue
                if not np.isfinite(px[j]) or px[j] <= 0:
                    continue
                # New / flipped position → reset entry.
                if not np.isfinite(entry_price[j]) or entry_dir[j] == 0.0 or np.sign(w[j]) != np.sign(entry_dir[j]):
                    entry_price[j] = px[j]
                    entry_dir[j] = float(np.sign(w[j]))
                    continue
                hit = False
                if use_ohlc_stop and high_arr is not None and low_arr is not None:
                    # Long: stop if bar low trades through entry*(1-stop).
                    # Short: stop if bar high trades through entry*(1+stop).
                    if entry_dir[j] > 0:
                        thr_px = entry_price[j] * (1.0 - stop)
                        lo = low_arr[t, j]
                        if np.isfinite(lo) and lo <= thr_px:
                            hit = True
                    else:
                        thr_px = entry_price[j] * (1.0 + stop)
                        hi = high_arr[t, j]
                        if np.isfinite(hi) and hi >= thr_px:
                            hit = True
                    if hit:
                        diagnostics["ohlc_stop_events"] += 1
                if not hit:
                    move = (px[j] / entry_price[j] - 1.0) * entry_dir[j]
                    hit = move <= -stop
                if hit:
                    w[j] = 0.0
                    entry_price[j] = np.nan
                    entry_dir[j] = 0.0
                    diagnostics["stop_events"] += 1

        # ── Turnover-aware cost feedback into sizing ──
        if cost_feedback is not None and cost_bps_frac > _EPS:
            delta = w - prev
            turnover = float(np.sum(np.abs(delta)))
            implied_cost = turnover * cost_bps_frac
            if implied_cost > cost_feedback + _EPS and turnover > _EPS:
                scale = cost_feedback / implied_cost
                w = prev + delta * scale
                diagnostics["turnover_cost_clips"] += 1

        # ── Partial fill: only a fraction of intended Δw executes this bar ──
        if fill_rate < 1.0 - _EPS:
            delta = w - prev
            if float(np.sum(np.abs(delta))) > _EPS:
                w = prev + delta * fill_rate
                diagnostics["partial_fill_bars"] += 1

        # ── Turnover throttle ──
        if config.max_turnover is not None:
            delta = w - prev
            turnover = float(np.sum(np.abs(delta)))
            lim = float(config.max_turnover)
            if turnover > lim + _EPS and turnover > _EPS:
                w = prev + delta * (lim / turnover)
                diagnostics["turnover_clips"] += 1

        # Final exposure pass after turnover / partial-fill (never exceed caps).
        w = _clip_exposure_caps(w, config, diagnostics=diagnostics, diag_prefix="final_")

        # ── Drawdown kill-switch on causal overlay equity proxy ──
        if t > 0:
            realized = float(np.dot(prev, rets_arr[t]))
            equity *= 1.0 + realized
            peak = max(peak, equity)
        dd = (equity - peak) / max(peak, _EPS)

        # Re-arm hysteresis after recovery (DD shallower than reset threshold).
        if not kill_armed and reset_dd is not None:
            if dd > -reset_dd:
                kill_armed = True
                diagnostics["kill_rearms"] += 1

        if kill_armed and config.max_drawdown_kill is not None and dd <= -float(config.max_drawdown_kill):
            w[:] = 0.0
            diagnostics["kill_events"] += 1
            cooldown_left = int(config.kill_cooldown_bars)
            # Do NOT reset peak — hysteresis keeps switch disarmed until recovery.
            if reset_dd is not None:
                kill_armed = False
            else:
                # Legacy behaviour: re-arm after cooldown by resetting peak.
                peak = equity

        out[t] = w
        prev = w.copy()

    result = pd.DataFrame(out, index=pos.index, columns=pos.columns)
    diagnostics["final_gross_mean"] = round(float(result.abs().sum(axis=1).mean()), 6)
    diagnostics["final_net_mean"] = round(float(result.sum(axis=1).mean()), 6)
    diagnostics["final_turnover_mean"] = round(float(result.diff().abs().sum(axis=1).fillna(0.0).mean()), 6)
    return result, diagnostics


def simulate_strategy_pnl(
    positions: pd.DataFrame,
    returns: pd.DataFrame,
    *,
    cost_bps: float = 0.0,
    initial_capital: float = 1.0,
    hft_costs: Any = None,
) -> pd.Series:
    """Simple next-bar PnL from weights (for overlay A/B demos, not engine fills).

    When ``hft_costs`` (an ``HftCostModel``) is provided, spread+impact+adverse
    selection replace the flat ``cost_bps`` path.
    """
    pos = positions.astype(float)
    rets = returns.reindex(index=pos.index, columns=pos.columns).fillna(0.0)
    lagged = pos.shift(1).fillna(0.0)
    port = (lagged * rets).sum(axis=1)

    if hft_costs is not None:
        from backtest.hft_costs import HftCostModel, apply_hft_costs_to_returns

        model = hft_costs if isinstance(hft_costs, HftCostModel) else hft_costs
        net, _ = apply_hft_costs_to_returns(port, pos, model=model)
    else:
        turnover = pos.diff().abs().sum(axis=1).fillna(0.0)
        costs = turnover * (float(cost_bps) / 10_000.0)
        net = port - costs

    equity = float(initial_capital) * (1.0 + net).cumprod()
    return pd.Series(equity, index=pos.index, name="equity")


def overlay_ab_comparison(
    positions: pd.DataFrame,
    returns: pd.DataFrame,
    *,
    overlay: RiskOverlayConfig,
    close: Optional[pd.DataFrame] = None,
    open_: Optional[pd.DataFrame] = None,
    high: Optional[pd.DataFrame] = None,
    low: Optional[pd.DataFrame] = None,
    cost_bps: float = 5.0,
    hft_costs: Any = None,
    initial_capital: float = 1_000_000.0,
) -> Dict[str, Any]:
    """Compare unconstrained vs risk-overlay equity / drawdown / ruin proxy."""
    base_eq = simulate_strategy_pnl(
        positions,
        returns,
        cost_bps=cost_bps,
        hft_costs=hft_costs,
        initial_capital=initial_capital,
    )
    adj, diag = apply_risk_overlay(
        positions,
        returns,
        config=overlay,
        close=close,
        open_=open_,
        high=high,
        low=low,
    )
    adj_eq = simulate_strategy_pnl(
        adj,
        returns,
        cost_bps=cost_bps,
        hft_costs=hft_costs,
        initial_capital=initial_capital,
    )

    def _mdd(eq: pd.Series) -> float:
        peak = eq.cummax()
        return float(((eq - peak) / peak.replace(0, 1)).min())

    def _ruin(eq: pd.Series, level: float = 0.5) -> float:
        return float(np.mean(eq.to_numpy(dtype=float) <= initial_capital * level))

    base_rets = base_eq.pct_change().dropna().to_numpy(dtype=float)
    adj_rets = adj_eq.pct_change().dropna().to_numpy(dtype=float)

    def _sharpe(r: np.ndarray, bpy: int) -> float:
        if len(r) < 2:
            return 0.0
        return float(np.mean(r) / (np.std(r) + 1e-15) * np.sqrt(bpy))

    def _score(
        eq: pd.Series,
        mdd: float,
        *,
        dd_penalty: float = 2.0,
    ) -> float:
        # Risk-first score: total return − dd_penalty × |max_dd|.
        # Prefer this over annualised Sharpe on short-horizon proxies where
        # delevering a still-negative book can spuriously worsen Sharpe.
        total_ret = float(eq.iloc[-1] / eq.iloc[0] - 1.0) if len(eq) else 0.0
        return total_ret - dd_penalty * abs(mdd)

    bpy = overlay.bars_per_year
    base_mdd = _mdd(base_eq)
    adj_mdd = _mdd(adj_eq)
    base_score = _score(base_eq, base_mdd)
    adj_score = _score(adj_eq, adj_mdd)

    return {
        "baseline": {
            "total_return": round(float(base_eq.iloc[-1] / base_eq.iloc[0] - 1.0), 6),
            "max_drawdown": round(base_mdd, 6),
            "sharpe": round(_sharpe(base_rets, bpy), 4),
            "risk_adjusted_score": round(base_score, 4),
            "ruin_proxy": round(_ruin(base_eq), 6),
        },
        "overlay": {
            "total_return": round(float(adj_eq.iloc[-1] / adj_eq.iloc[0] - 1.0), 6),
            "max_drawdown": round(adj_mdd, 6),
            "sharpe": round(_sharpe(adj_rets, bpy), 4),
            "risk_adjusted_score": round(adj_score, 4),
            "ruin_proxy": round(_ruin(adj_eq), 6),
        },
        "diagnostics": diag,
        "improvement": {
            # Positive ⇒ overlay |max_dd| is smaller (less severe).
            "drawdown_reduction": round(abs(base_mdd) - abs(adj_mdd), 6),
            "sharpe_delta": round(_sharpe(adj_rets, bpy) - _sharpe(base_rets, bpy), 4),
            "risk_adjusted_score_delta": round(adj_score - base_score, 4),
            "ruin_reduction": round(_ruin(base_eq) - _ruin(adj_eq), 6),
        },
        "cost_path": "hft_costs" if hft_costs is not None else f"flat_bps={cost_bps}",
    }
