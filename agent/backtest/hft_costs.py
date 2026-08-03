"""Bar-proxy HFT execution costs: spread + impact + adverse selection.

Honest limits
-------------
This is **not** a limit-order-book / co-lo simulator. It applies a
turnover-linked cost stack on weight changes so high-turnover styles
pay realistic friction under bar/tick proxies (typically 1m–1H).

When wired through ``BaseEngine``, spread + adverse selection worsen
**fill prices**; nonlinear impact is charged as an equity drag; optional
``participation_cap`` / ``max_adv_participation`` clip turnover before fills.

``fill_slippage_mode`` controls interaction with the engine's native
slippage: ``"additive"`` (default) stacks HFT haircut on top of native
slippage; ``"replace"`` uses only HFT spread + adverse selection so costs
are not double-counted when ``hft_costs`` is the authoritative stack.

Cost per bar (as a fraction of equity)::

    (spread_bps / 1e4) * |Δw|_1
  + (impact_coeff_bps / 1e4) * (|Δw|_1) ** impact_power
  + (adverse_selection_bps / 1e4) * |Δw|_1

``impact_coeff`` is in **bps units** (same scale as ``spread_bps``), so a
value of ``8`` means ~8 bps of impact when |Δw|_1 ** power ≈ 1.

Optional ``participation_cap`` clips per-bar turnover before costs are
charged (proxy for not eating through the book).
``max_adv_participation`` further clips |Δw_i| using rolling dollar ADV
when a volume panel is available (still a bar proxy — not LOB depth).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Mapping, Optional, Tuple

import numpy as np
import pandas as pd

_EPS = 1e-12


_FILL_SLIPPAGE_MODES = frozenset({"additive", "replace"})


@dataclass(frozen=True)
class HftCostModel:
    """Default cost stack for high-turnover / short-horizon research.

    ``spread_bps``, ``impact_coeff`` (bps), and ``adverse_selection_bps`` are
    all in basis-point units — never raw fractions.

    ``fill_slippage_mode``:
      - ``additive`` — HFT fill haircut stacks on engine native slippage
      - ``replace`` — only HFT spread + AS applied (avoids double-counting)
    ``adv_fallback_notional`` — constant dollar ADV used when volume/amount
    panels are missing so ``max_adv_participation`` still clips.
    """

    spread_bps: float = 2.0
    impact_coeff: float = 8.0  # bps at |Δw|_1 ** impact_power == 1
    impact_power: float = 0.5
    adverse_selection_bps: float = 1.5
    participation_cap: Optional[float] = None  # max |Δw|_1 per bar
    max_adv_participation: Optional[float] = None  # max |Δw_i| vs name ADV/$equity
    adv_lookback: int = 20
    fill_slippage_mode: str = "additive"
    adv_fallback_notional: Optional[float] = None
    enabled: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def active(self) -> bool:
        return bool(self.enabled) and (
            self.spread_bps > 0
            or self.impact_coeff > 0
            or self.adverse_selection_bps > 0
            or self.participation_cap is not None
            or self.max_adv_participation is not None
        )

    def replaces_native_slippage(self) -> bool:
        return str(self.fill_slippage_mode).strip().lower() == "replace"

    def fill_slippage_bps(self) -> float:
        """Extra fill haircut (bps) from spread + adverse selection."""
        return float(self.spread_bps) + float(self.adverse_selection_bps)

    def impact_cost_fraction(self, turnover_l1: float) -> float:
        """Nonlinear impact as a fraction of equity for one bar's |Δw|_1."""
        t = max(0.0, float(turnover_l1))
        if t <= _EPS or self.impact_coeff <= 0:
            return 0.0
        return (float(self.impact_coeff) / 10_000.0) * (t ** float(self.impact_power))


def load_hft_cost_model(config: Mapping[str, Any]) -> Optional[HftCostModel]:
    """Parse ``config['hft_costs']`` (None if unset/off)."""
    raw = config.get("hft_costs")
    if raw in (None, {}, False):
        return None
    if not isinstance(raw, Mapping):
        raise ValueError("hft_costs must be a mapping")
    enabled = bool(raw.get("enabled", True))
    if not enabled:
        return None

    def _pos(name: str, default: float) -> float:
        v = raw.get(name, default)
        if isinstance(v, (bool, np.bool_)):
            raise ValueError(f"{name} must be numeric, not boolean")
        try:
            out = float(v)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be numeric") from exc
        if not np.isfinite(out) or out < 0:
            raise ValueError(f"{name} must be finite and >= 0")
        return out

    part = raw.get("participation_cap")
    part_f: Optional[float] = None
    if part is not None:
        part_f = _pos("participation_cap", float(part))
        if part_f <= 0:
            raise ValueError("participation_cap must be > 0 when set")

    power = _pos("impact_power", float(raw.get("impact_power", 0.5)))
    if power <= 0:
        raise ValueError("impact_power must be > 0")

    adv_part = raw.get("max_adv_participation")
    adv_part_f: Optional[float] = None
    if adv_part is not None:
        adv_part_f = _pos("max_adv_participation", float(adv_part))
        if adv_part_f <= 0 or adv_part_f > 1.0:
            raise ValueError("max_adv_participation must be in (0, 1]")

    adv_lb = int(raw.get("adv_lookback", 20))
    if adv_lb < 2:
        raise ValueError(f"adv_lookback must be >= 2, got {adv_lb}")

    mode_raw = raw.get("fill_slippage_mode", "additive")
    mode = str(mode_raw).strip().lower() if mode_raw is not None else "additive"
    if mode not in _FILL_SLIPPAGE_MODES:
        raise ValueError(
            f"fill_slippage_mode must be one of {sorted(_FILL_SLIPPAGE_MODES)}, got {mode_raw!r}"
        )

    fallback = raw.get("adv_fallback_notional")
    fallback_f: Optional[float] = None
    if fallback is not None:
        fallback_f = _pos("adv_fallback_notional", float(fallback))
        if fallback_f <= 0:
            raise ValueError("adv_fallback_notional must be > 0 when set")

    model = HftCostModel(
        spread_bps=_pos("spread_bps", float(raw.get("spread_bps", 2.0))),
        impact_coeff=_pos("impact_coeff", float(raw.get("impact_coeff", 8.0))),
        impact_power=power,
        adverse_selection_bps=_pos("adverse_selection_bps", float(raw.get("adverse_selection_bps", 1.5))),
        participation_cap=part_f,
        max_adv_participation=adv_part_f,
        adv_lookback=adv_lb,
        fill_slippage_mode=mode,
        adv_fallback_notional=fallback_f,
        enabled=True,
    )
    return model if model.active() else None


def default_hft_cost_model(*, aggressive: bool = False) -> HftCostModel:
    """Sensible defaults; ``aggressive`` raises spread/impact/AS for stress."""
    if aggressive:
        return HftCostModel(
            spread_bps=5.0,
            impact_coeff=15.0,
            impact_power=0.5,
            adverse_selection_bps=4.0,
            participation_cap=0.4,
            max_adv_participation=0.15,
            fill_slippage_mode="replace",
        )
    return HftCostModel()


def build_dollar_volume_panel(
    data_map: Mapping[str, Any],
    close: pd.DataFrame,
    codes: Optional[list] = None,
    *,
    adv_fallback_notional: Optional[float] = None,
) -> Tuple[Optional[pd.DataFrame], Dict[str, Any]]:
    """Build a dollar-volume panel for ADV participation clipping.

    Preference per name:
      1. ``close * volume`` when volume is present
      2. ``amount`` column when present (already dollar notional on many CN loaders)
      3. constant ``adv_fallback_notional`` when configured
      4. otherwise the name is omitted (clipping skipped for that name)

    Returns ``(panel_or_None, diagnostics)`` with per-code source labels.
    """
    use_codes = list(codes) if codes is not None else list(close.columns)
    sources: Dict[str, str] = {}
    dv_cols: Dict[str, pd.Series] = {}
    fallback = float(adv_fallback_notional) if adv_fallback_notional is not None else None
    if fallback is not None and (not np.isfinite(fallback) or fallback <= 0):
        raise ValueError("adv_fallback_notional must be finite and > 0")

    for code in use_codes:
        frame = data_map.get(code) if isinstance(data_map, Mapping) else None
        px = close[code] if code in close.columns else None
        if px is None:
            sources[code] = "missing_price"
            continue
        px = px.astype(float)
        used = False
        if frame is not None and hasattr(frame, "columns"):
            if "volume" in frame.columns:
                vol = frame["volume"].reindex(close.index).astype(float)
                vol_arr = vol.to_numpy(dtype=float)
                finite = vol_arr[np.isfinite(vol_arr)]
                # Treat all-zero / all-NaN volume as missing so amount/fallback can win.
                if finite.size and float(np.max(np.abs(finite))) > _EPS:
                    dv_cols[code] = (px * vol).fillna(0.0)
                    sources[code] = "volume"
                    used = True
            if not used and "amount" in frame.columns:
                amt = frame["amount"].reindex(close.index).astype(float)
                amt_arr = amt.to_numpy(dtype=float)
                finite_amt = amt_arr[np.isfinite(amt_arr)]
                if finite_amt.size and float(np.max(np.abs(finite_amt))) > _EPS:
                    dv_cols[code] = amt.fillna(0.0)
                    sources[code] = "amount"
                    used = True
        if not used and fallback is not None:
            dv_cols[code] = pd.Series(fallback, index=close.index, dtype=float)
            sources[code] = "fallback_notional"
            used = True
        if not used:
            sources[code] = "missing"

    diag: Dict[str, Any] = {
        "dollar_volume_sources": sources,
        "n_with_volume": sum(1 for v in sources.values() if v == "volume"),
        "n_with_amount": sum(1 for v in sources.values() if v == "amount"),
        "n_with_fallback": sum(1 for v in sources.values() if v == "fallback_notional"),
        "n_missing": sum(1 for v in sources.values() if v in {"missing", "missing_price"}),
    }
    if not dv_cols:
        return None, diag
    return pd.DataFrame(dv_cols), diag


def apply_hft_fill_slippage(
    price: float,
    direction: int,
    *,
    model: HftCostModel,
) -> float:
    """Worsen a fill price by spread + adverse-selection bps (live engine path).

    ``direction`` is +1 when buying / covering, -1 when selling / shorting —
    same convention as ``BaseEngine.apply_slippage``.
    """
    if not model.active() or price == 0:
        return float(price)
    bps = model.fill_slippage_bps()
    if bps <= 0:
        return float(price)
    # Buying pays up; selling receives less.
    signed = 1 if int(direction) >= 0 else -1
    return float(price) * (1.0 + signed * bps / 10_000.0)


def clip_turnover_participation(
    positions: pd.DataFrame,
    *,
    participation_cap: float,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Causal clip of per-bar |Δw|_1 to ``participation_cap``."""
    pos = positions.astype(float).copy()
    arr = pos.to_numpy(dtype=float)
    n_bars, n_names = arr.shape
    out = arr.copy()
    prev = np.zeros(n_names, dtype=float)
    clips = 0
    cap = float(participation_cap)
    for t in range(n_bars):
        w = out[t].copy()
        delta = w - prev
        turnover = float(np.sum(np.abs(delta)))
        if turnover > cap + _EPS and turnover > _EPS:
            w = prev + delta * (cap / turnover)
            clips += 1
        out[t] = w
        prev = w.copy()
    result = pd.DataFrame(out, index=pos.index, columns=pos.columns)
    return result, {"participation_clips": clips, "participation_cap": cap}


def clip_adv_participation(
    positions: pd.DataFrame,
    *,
    dollar_volume: pd.DataFrame,
    max_adv_participation: float,
    adv_lookback: int = 20,
    equity: float = 1.0,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Causal per-name clip: |Δw_i| * equity ≤ max_adv_participation * ADV$_i.

    ``dollar_volume`` should be price × volume (or a volume proxy). Uses a
    trailing mean of past bars only (shifted), so bar t never sees its own
    volume. When ADV is missing/zero the name is left unchanged.
    """
    pos = positions.astype(float).copy()
    dv = dollar_volume.reindex(index=pos.index, columns=pos.columns).astype(float)
    # Causal ADV: mean of dollar volume through t-1.
    adv = dv.shift(1).rolling(int(adv_lookback), min_periods=max(2, int(adv_lookback) // 2)).mean()
    arr = pos.to_numpy(dtype=float)
    adv_arr = adv.to_numpy(dtype=float)
    n_bars, n_names = arr.shape
    out = arr.copy()
    prev = np.zeros(n_names, dtype=float)
    clips = 0
    cap = float(max_adv_participation)
    eq = max(float(equity), _EPS)
    for t in range(n_bars):
        w = out[t].copy()
        for j in range(n_names):
            delta = w[j] - prev[j]
            adv_j = adv_arr[t, j] if np.isfinite(adv_arr[t, j]) else float("nan")
            if not np.isfinite(adv_j) or adv_j <= _EPS or abs(delta) < _EPS:
                continue
            # Max absolute weight change affordable at this participation rate.
            max_dw = (cap * adv_j) / eq
            if abs(delta) > max_dw + _EPS:
                w[j] = prev[j] + np.sign(delta) * max_dw
                clips += 1
        out[t] = w
        prev = w.copy()
    result = pd.DataFrame(out, index=pos.index, columns=pos.columns)
    return result, {
        "adv_participation_clips": clips,
        "max_adv_participation": cap,
        "adv_lookback": int(adv_lookback),
    }


def prepare_positions_for_hft_costs(
    positions: pd.DataFrame,
    *,
    model: HftCostModel,
    dollar_volume: Optional[pd.DataFrame] = None,
    equity: float = 1.0,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Apply participation + ADV clips before live fills / cost charging."""
    pos = positions.astype(float)
    diag: Dict[str, Any] = {"model": model.to_dict(), "fidelity": "bar_proxy — no LOB"}
    if model.participation_cap is not None:
        pos, part_diag = clip_turnover_participation(pos, participation_cap=model.participation_cap)
        diag.update(part_diag)
    if model.max_adv_participation is not None and dollar_volume is not None and not dollar_volume.empty:
        pos, adv_diag = clip_adv_participation(
            pos,
            dollar_volume=dollar_volume,
            max_adv_participation=model.max_adv_participation,
            adv_lookback=model.adv_lookback,
            equity=equity,
        )
        diag.update(adv_diag)
    return pos, diag


def hft_cost_series(
    positions: pd.DataFrame,
    *,
    model: HftCostModel,
    dollar_volume: Optional[pd.DataFrame] = None,
    equity: float = 1.0,
) -> pd.Series:
    """Per-bar cost fraction from weight changes under ``model``."""
    if not model.active():
        return pd.Series(0.0, index=positions.index, name="hft_cost")

    pos, _ = prepare_positions_for_hft_costs(
        positions.astype(float),
        model=model,
        dollar_volume=dollar_volume,
        equity=equity,
    )

    turnover = pos.diff().abs().sum(axis=1).fillna(0.0)
    as_tax = float(model.adverse_selection_bps) / 10_000.0
    spread = float(model.spread_bps) / 10_000.0
    impact = pd.Series(
        [model.impact_cost_fraction(float(t)) for t in turnover.to_numpy(dtype=float)],
        index=turnover.index,
    )
    costs = turnover * (spread + as_tax) + impact
    costs.name = "hft_cost"
    return costs


def apply_hft_costs_to_returns(
    port_returns: pd.Series,
    positions: pd.DataFrame,
    *,
    model: HftCostModel,
    dollar_volume: Optional[pd.DataFrame] = None,
    equity: float = 1.0,
) -> Tuple[pd.Series, Dict[str, Any]]:
    """Subtract HFT cost stack from portfolio bar returns."""
    costs = hft_cost_series(positions, model=model, dollar_volume=dollar_volume, equity=equity)
    aligned = costs.reindex(port_returns.index).fillna(0.0)
    net = port_returns.astype(float) - aligned
    diag = {
        "model": model.to_dict(),
        "mean_cost": round(float(aligned.mean()), 8),
        "total_cost": round(float(aligned.sum()), 6),
        "mean_turnover": round(float(positions.diff().abs().sum(axis=1).fillna(0.0).mean()), 6),
    }
    return net, diag
