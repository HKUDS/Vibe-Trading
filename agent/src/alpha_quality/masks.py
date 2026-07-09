from __future__ import annotations

from typing import Literal
from typing import cast

import pandas as pd


def _shape_from_panel(panel: dict[str, pd.DataFrame]) -> tuple[pd.Index, pd.Index]:
    for value in panel.values():
        if isinstance(value, pd.DataFrame):
            return value.index, value.columns
    raise ValueError("panel must contain at least one DataFrame")


def _bool_frame(
    panel: dict[str, pd.DataFrame], name: str, index: pd.Index, columns: pd.Index
) -> pd.DataFrame:
    value = panel.get(name)
    if isinstance(value, pd.DataFrame):
        return value.reindex(index=index, columns=columns).fillna(False).astype(bool)
    return pd.DataFrame(False, index=index, columns=columns)


def build_ashare_tradability_mask(
    panel: dict[str, pd.DataFrame],
    *,
    side: Literal["long", "short", "long_short"] = "long",
    min_listing_days: int = 20,
    min_amount: float | None = None,
) -> pd.DataFrame:
    index, columns = _shape_from_panel(panel)
    mask = pd.DataFrame(True, index=index, columns=columns)
    st_flag = _bool_frame(panel, "st_flag", index, columns)
    suspended = _bool_frame(panel, "suspended", index, columns)
    mask &= ~st_flag
    mask &= ~suspended

    if side in {"long", "long_short"}:
        mask &= ~_bool_frame(panel, "limit_up", index, columns)
    if side in {"short", "long_short"}:
        mask &= ~_bool_frame(panel, "limit_down", index, columns)

    listed_days = panel.get("listed_days")
    if isinstance(listed_days, pd.DataFrame):
        aligned = listed_days.reindex(index=index, columns=columns)
        mask &= aligned >= min_listing_days

    amount = panel.get("amount")
    if min_amount is not None and isinstance(amount, pd.DataFrame):
        aligned_amount = amount.reindex(index=index, columns=columns)
        mask &= aligned_amount >= min_amount

    return mask.fillna(False).astype(bool)


def coverage_by_date(mask: pd.DataFrame) -> pd.Series:
    if mask.empty:
        return pd.Series(dtype=float)
    coverage = cast(pd.Series, mask.astype(bool).mean(axis=1))
    return coverage.astype(float)
