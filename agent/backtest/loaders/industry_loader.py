"""CN industry classification loader from Tushare ``index_member_all`` (SW2021).

Supplies the wide ``sector`` label frame the industry-neutralized CN value
alphas z-score against (issue #1789 follow-up #2): one label per symbol per
trading day, point-in-time via each membership row's ``in_date``/``out_date``.

PIT semantics: symbol ``s`` carries label ``L`` on date ``d`` iff a membership
row exists with ``in_date <= d`` and (``out_date`` is null OR ``d < out_date``)
— ``in_date`` inclusive, ``out_date`` exclusive. If overlapping rows ever claim
the same ``(s, d)``, the LATER ``in_date`` wins; on equal ``in_date`` the row
with the later (or null = current) ``out_date`` wins. Both rules are fixed so
the frame is deterministic regardless of API row order.

Taxonomy caveat: SW2021 classifications are applied retroactively to history —
a name reclassified in 2021 carries its 2021 industry back through the whole
window. This is the same class of caveat the csi300 bench already discloses
for PIT index membership, not a lookahead in the price/valuation data.

Endpoint contract (pinned by tests, verified live 2026-10-12):
``index_member_all`` accepts ONLY the documented ``l1_code``/``l2_code``/
``l3_code``/``ts_code``/``is_new`` filters — passing ``src`` (undocumented)
silently returns an empty 200-row-columns frame, so ``src`` is used for
``index_classify`` in the truncation fallback only. ``is_new`` defaults to
"Y" server-side (current members, no out_date rows), so the historical
half ("N") is fetched separately and concatenated — without it every label
would be today's classification and the PIT claim above false.

Truncation guard: ``index_member_all`` documents a 2000-row cap per call.
A live full-permission token returns the whole snapshot in one call (~5900
current + ~2000 historical rows), but a response of exactly 2000 rows is
treated as truncated and refetched per L1 industry (``index_classify`` then
one ``index_member_all(l1_code=..., is_new=...)`` call per industry).

Degradation: a provider failure after backoff warns and returns an all-None
frame aligned to ``index`` x ``symbols`` — the caller benches without the
sector tag (``requires_sector`` alphas SkipAlpha) instead of crashing. A
missing/placeholder ``TUSHARE_TOKEN`` raises ``RuntimeError`` like every
sibling loader; no label is ever invented.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd

from backtest.loaders.tushare import (
    TUSHARE_TOKEN_PLACEHOLDERS,
    _call_with_backoff,
)

logger = logging.getLogger(__name__)

#: Shenwan classification levels ``index_member_all`` serves name columns for.
INDUSTRY_LEVELS: tuple[str, ...] = ("L1", "L2", "L3")

_LEVEL_NAME_COLUMN = {"L1": "l1_name", "L2": "l2_name", "L3": "l3_name"}

#: Documented per-call row cap of ``index_member_all``; a snapshot of exactly
#: this size is treated as truncated and triggers the per-L1 refetch.
_SNAPSHOT_ROW_CAP = 2000

#: Sentinel standing in for a null ``out_date`` (still a member). Inside the
#: ``datetime64[ns]`` range so int64 comparisons against trading days work.
_OPEN_ENDED = pd.Timestamp("2262-01-01")


def validate_industry_params(level: str, src: str) -> str:
    """Validate the requested classification level and source.

    Args:
        level: Shenwan level, one of :data:`INDUSTRY_LEVELS`.
        src: Classification source, e.g. ``"SW2021"``; must be non-empty.

    Returns:
        The ``index_member_all`` name column serving ``level``.

    Raises:
        ValueError: If ``level`` is unknown or ``src`` is empty.
    """
    if level not in INDUSTRY_LEVELS:
        raise ValueError(
            f"unsupported industry level {level!r}; expected one of {list(INDUSTRY_LEVELS)}"
        )
    if not isinstance(src, str) or not src.strip():
        raise ValueError(f"src must be a non-empty string, got {src!r}")
    return _LEVEL_NAME_COLUMN[level]


def _build_api() -> Any:
    """Build a Tushare pro API client from the configured token.

    Raises:
        RuntimeError: If ``TUSHARE_TOKEN`` is unset or a placeholder.
    """
    import tushare as ts

    from src.config.accessor import get_env_config

    token = get_env_config().data.tushare_token.strip()
    if token in TUSHARE_TOKEN_PLACEHOLDERS:
        raise RuntimeError(
            "TUSHARE_TOKEN not configured; required for industry classification"
        )
    return ts.pro_api(token)


def _fetch_membership_part(api: Any, src: str, is_new: str) -> pd.DataFrame | None:
    """Fetch one ``is_new`` half of the snapshot, refetching per L1 if truncated."""
    frame = _call_with_backoff(api.index_member_all, is_new=is_new)
    if frame is None or len(frame) != _SNAPSHOT_ROW_CAP:
        return frame
    logger.warning(
        "index_member_all(is_new=%s) returned exactly %d rows (documented per-call cap); "
        "refetching per L1 industry",
        is_new,
        _SNAPSHOT_ROW_CAP,
    )
    classify = _call_with_backoff(api.index_classify, level="L1", src=src)
    if classify is None or classify.empty or "index_code" not in classify.columns:
        raise RuntimeError(
            "index_classify served no L1 codes for the per-industry refetch"
        )
    parts = []
    for code in classify["index_code"].astype(str):
        part = _call_with_backoff(api.index_member_all, l1_code=code, is_new=is_new)
        if part is not None and not part.empty:
            parts.append(part)
    if not parts:
        return None
    return pd.concat(parts, ignore_index=True)


def _fetch_membership(api: Any, src: str) -> pd.DataFrame | None:
    """Fetch the full PIT membership snapshot (current "Y" + historical "N").

    Args:
        api: Tushare pro API (real or injected fake).
        src: Classification source — passed to ``index_classify`` only;
            ``index_member_all`` rejects an undocumented ``src`` with a
            silently empty response (see the module docstring).

    Returns:
        The concatenated membership rows, or None if nothing was served.

    Raises:
        Exception: The endpoint's own exception after backoff — the caller
            decides whether that degrades or propagates.
    """
    parts = []
    for is_new in ("Y", "N"):
        part = _fetch_membership_part(api, src, is_new)
        if part is not None and not part.empty:
            parts.append(part)
    if not parts:
        return None
    return pd.concat(parts, ignore_index=True)


def load_industry_frame_with_coverage(
    *,
    symbols: Sequence[str],
    start: str,
    end: str,
    index: pd.DatetimeIndex,
    api: Any | None = None,
    level: str = "L1",
    src: str = "SW2021",
) -> tuple[pd.DataFrame, float]:
    """Load PIT industry labels as a wide frame plus a coverage fraction.

    Args:
        symbols: Panel symbols; only names present in the membership data get
            a label, the rest stay NaN.
        start: Period start (YYYY-MM-DD). Accepted for loader-contract
            symmetry with ``valuation_loader``; PIT evaluation uses the actual
            ``index`` dates, so an index reaching outside the window is still
            labelled correctly.
        end: Period end (YYYY-MM-DD), same contract note as ``start``.
        index: Price-panel trading-day index the frame aligns to.
        api: Optional pre-built Tushare pro API (tests inject fakes here).
        level: Shenwan level, one of :data:`INDUSTRY_LEVELS`.
        src: Classification source, e.g. ``"SW2021"``.

    Returns:
        ``(frame, coverage)`` — ``frame`` is ``dates x symbols`` with the
        industry NAME (str) where a membership row covers the date and NaN
        where none does (never an invented label); ``coverage`` is the
        fraction of ``symbols`` with at least one label anywhere in the frame.

    Raises:
        ValueError: If ``level`` or ``src`` is invalid.
        RuntimeError: If no API is injected and ``TUSHARE_TOKEN`` is missing.
    """
    name_column = validate_industry_params(level, src)
    columns = list(symbols)
    empty = pd.DataFrame(np.nan, index=index, columns=columns, dtype=object)
    if not columns or len(index) == 0:
        return empty, 0.0
    logger.debug("industry frame requested for %s..%s (%d symbols)", start, end, len(columns))

    if api is None:
        api = _build_api()
    try:
        membership = _fetch_membership(api, src)
    except Exception as exc:  # noqa: BLE001 - degrade, never crash the caller
        logger.warning(
            "index_member_all industry fetch failed (%s); returning unmapped frame", exc
        )
        return empty, 0.0

    if (
        membership is None
        or membership.empty
        or "ts_code" not in membership.columns
        or name_column not in membership.columns
        # Without the PIT interval columns no membership can be established —
        # degrade rather than guess a mapping from names alone.
        or "in_date" not in membership.columns
        or "out_date" not in membership.columns
    ):
        logger.warning(
            "index_member_all served no usable membership rows (src=%s, level=%s)",
            src,
            level,
        )
        return empty, 0.0

    rows = membership[membership["ts_code"].isin(columns)].copy()
    in_dt = pd.to_datetime(rows.get("in_date"), format="%Y%m%d", errors="coerce")
    out_dt = pd.to_datetime(rows.get("out_date"), format="%Y%m%d", errors="coerce")
    labels = rows[name_column]
    # A row with no in_date can never satisfy in_date <= d, and a row with no
    # label has nothing to serve — dropped, never defaulted.
    usable = in_dt.notna() & labels.notna() & (labels.astype(str).str.strip() != "")
    rows, in_dt, labels = rows[usable], in_dt[usable], labels[usable]
    out_dt = out_dt[usable].fillna(_OPEN_ENDED)
    if rows.empty:
        return empty, 0.0

    # Later in_date wins, then later/open out_date: a fixed sort makes the
    # per-date winner independent of API row order (dict(zip) keeps the last).
    order = np.lexsort((out_dt.to_numpy(dtype="int64"), in_dt.to_numpy(dtype="int64")))
    codes = rows["ts_code"].to_numpy()[order]
    ordered_labels = labels.to_numpy()[order]
    in_ns = in_dt.to_numpy(dtype="int64")[order]
    out_ns = out_dt.to_numpy(dtype="int64")[order]

    position = {symbol: j for j, symbol in enumerate(columns)}
    values = np.full((len(index), len(columns)), np.nan, dtype=object)
    for i, day_ns in enumerate(index.asi8):
        applicable = (in_ns <= day_ns) & (day_ns < out_ns)
        if not applicable.any():
            continue
        for symbol, label in dict(zip(codes[applicable], ordered_labels[applicable])).items():
            values[i, position[symbol]] = label

    frame = pd.DataFrame(values, index=index, columns=columns)
    coverage = float(frame.notna().any(axis=0).mean())
    if coverage < 1.0:
        logger.warning(
            "industry coverage %.1f%% of %d requested symbols (src=%s, level=%s)",
            coverage * 100,
            len(columns),
            src,
            level,
        )
    return frame, coverage


def load_industry_frame(
    *,
    symbols: Sequence[str],
    start: str,
    end: str,
    index: pd.DatetimeIndex,
    api: Any | None = None,
    level: str = "L1",
    src: str = "SW2021",
) -> pd.DataFrame:
    """Load PIT industry labels as a wide ``dates x symbols`` frame.

    Thin wrapper over :func:`load_industry_frame_with_coverage` for callers
    that do not need the coverage fraction; same contract, same degradation.
    """
    frame, _ = load_industry_frame_with_coverage(
        symbols=symbols, start=start, end=end, index=index, api=api, level=level, src=src
    )
    return frame
