"""Composable weight constraints applied on top of any optimizer.

Portfolio Studio step 2 (#456): per-name cap, per-name floor, and per-group
exposure caps that work with every optimizer, not only the bounds baked into
``turnover_aware``. Configured via ``constraints`` in config.json::

    "constraints": [
        {"type": "max_weight", "cap": 0.25},
        {"type": "min_weight", "floor": 0.02},
        {"type": "group_exposure",
         "groups": {"AAPL": "tech", "MSFT": "tech", "XOM": "energy"},
         "caps": {"tech": 0.6}}
    ]

The layer runs on the optimizer's output frame (signed weights, one row per
rebalance date). Magnitudes are adjusted and signs are preserved, so
long/short books work too. Constraints apply in config order, and the layer
only acts on names that are already active: it reshapes allocations, it
never opens or closes positions. Off by default, so existing configs behave
exactly as before.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Sequence

import numpy as np
import pandas as pd

_EPS = 1e-9
_TOL = 1e-12
_MAX_PASSES = 50


def _bounded_fraction(value: Any, name: str) -> float:
    """Validate a (0, 1] fraction from config, rejecting bools and junk."""
    if isinstance(value, (bool, np.bool_)):
        raise ValueError(f"{name} must be numeric, not boolean")
    try:
        v = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not np.isfinite(v) or not 0.0 < v <= 1.0:
        raise ValueError(f"{name} must be finite and in (0, 1]")
    return v


class MaxWeight:
    """Per-name cap with pro-rata redistribution of the clipped excess.

    Clipped weight is handed to the names still under the cap, in
    proportion to their current size, until everything fits. When the cap
    cannot hold the book (n_active * cap < gross), every name lands on the
    cap and gross exposure shrinks accordingly.
    """

    def __init__(self, cap: float) -> None:
        self.cap = cap

    def apply(self, w: np.ndarray, codes: Sequence[str]) -> np.ndarray:
        del codes  # per-name rule, codes unused
        w = w.astype(float).copy()
        for _ in range(_MAX_PASSES):
            over = w > self.cap + _TOL
            if not over.any():
                break
            excess = float((w[over] - self.cap).sum())
            w[over] = self.cap
            room = w < self.cap - _TOL
            base = float(w[room].sum())
            if not room.any() or base <= _TOL:
                break
            w[room] += w[room] / base * excess
        return w


class MinWeight:
    """Per-name floor: active names below ``floor`` are lifted to it.

    The lift is funded pro-rata by the names above the floor (each gives
    up weight in proportion to how far it sits above the floor), so gross
    exposure is preserved. If the book cannot fund the floor
    (floor * n_active > gross), the date degrades to equal weights.
    """

    def __init__(self, floor: float) -> None:
        self.floor = floor

    def apply(self, w: np.ndarray, codes: Sequence[str]) -> np.ndarray:
        del codes
        w = w.astype(float).copy()
        for _ in range(_MAX_PASSES):
            below = (w > _EPS) & (w < self.floor - _TOL)
            if not below.any():
                break
            need = float((self.floor - w[below]).sum())
            above = w > self.floor + _TOL
            avail = float((w[above] - self.floor).sum())
            if avail <= _TOL:
                n = len(w)
                return np.full(n, w.sum() / n) if n else w
            w[below] = self.floor
            w[above] -= (w[above] - self.floor) / avail * need
        return w


class GroupExposure:
    """Cap the summed weight of each configured group.

    A group over its cap is scaled down pro-rata; the freed exposure is
    not redistributed (pushing it elsewhere could break another group's
    cap), so gross exposure shrinks by the clipped amount. Names absent
    from ``groups`` are unconstrained.
    """

    def __init__(self, groups: Mapping[str, str], caps: Mapping[str, float]) -> None:
        self.groups: Dict[str, str] = dict(groups)
        self.caps: Dict[str, float] = dict(caps)

    def apply(self, w: np.ndarray, codes: Sequence[str]) -> np.ndarray:
        w = w.astype(float).copy()
        for group, cap in self.caps.items():
            idx = [i for i, c in enumerate(codes) if self.groups.get(c) == group]
            if not idx:
                continue
            total = float(w[idx].sum())
            if total > cap + _TOL:
                w[idx] *= cap / total
        return w


_TYPES = ("max_weight", "min_weight", "group_exposure")


def _build_constraint(spec: Mapping[str, Any]) -> Any:
    if not isinstance(spec, Mapping):
        raise ValueError(f"constraint spec must be a mapping, got {type(spec).__name__}")
    kind = spec.get("type")
    if kind == "max_weight":
        if "cap" not in spec:
            raise ValueError("max_weight constraint requires 'cap'")
        return MaxWeight(_bounded_fraction(spec["cap"], "max_weight cap"))
    if kind == "min_weight":
        if "floor" not in spec:
            raise ValueError("min_weight constraint requires 'floor'")
        return MinWeight(_bounded_fraction(spec["floor"], "min_weight floor"))
    if kind == "group_exposure":
        groups = spec.get("groups")
        caps = spec.get("caps")
        if not isinstance(groups, Mapping) or not groups:
            raise ValueError("group_exposure constraint requires a non-empty 'groups' mapping")
        if any(not isinstance(c, str) or not isinstance(g, str) for c, g in groups.items()):
            raise ValueError("groups must map string asset codes to string group names")
        if not isinstance(caps, Mapping) or not caps:
            raise ValueError("group_exposure constraint requires a non-empty 'caps' mapping")
        unknown = set(caps) - set(groups.values())
        if unknown:
            raise ValueError(
                "caps reference groups with no mapped assets: " + ", ".join(sorted(unknown))
            )
        return GroupExposure(
            groups,
            {g: _bounded_fraction(c, f"cap for group {g!r}") for g, c in caps.items()},
        )
    raise ValueError(
        f"unknown constraint type {kind!r}; expected one of {', '.join(_TYPES)}"
    )


def load_constraints(config: Mapping[str, Any]) -> List[Any]:
    """Build the constraint list from ``config['constraints']`` (empty if unset)."""
    raw = config.get("constraints")
    if raw in (None, []):
        return []
    if not isinstance(raw, list):
        raise ValueError("constraints must be a list of constraint specs")
    return [_build_constraint(spec) for spec in raw]


def apply_constraints_frame(
    frame: pd.DataFrame, constraints: Sequence[Any]
) -> pd.DataFrame:
    """Apply constraints row by row to a signed weight frame.

    Args:
        frame: Optimizer output (dates x codes), signed weights.
        constraints: Constraint objects from ``load_constraints``.

    Returns:
        Adjusted frame with signs preserved and zero rows/cells untouched.
    """
    if not constraints:
        return frame
    out = frame.copy()
    for dt in frame.index:
        row = frame.loc[dt]
        codes = [c for c in row.index if abs(row[c]) > _EPS]
        if not codes:
            continue
        signs = np.sign(row[codes].to_numpy(dtype=float))
        mags = np.abs(row[codes].to_numpy(dtype=float))
        for con in constraints:
            mags = con.apply(mags, codes)
        out.loc[dt, codes] = signs * mags
    return out
