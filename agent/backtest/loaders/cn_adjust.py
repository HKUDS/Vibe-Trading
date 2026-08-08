"""Corporate-action adjustment for Tushare A-share and fund bars.

Tushare's ``daily`` and ``fund_daily`` endpoints return *unadjusted* prices, so
a close-to-close return taken across an ex-date spans the mechanical price drop
of a split, bonus issue or dividend rather than the instrument's actual move.
Measured against Tushare's own ``pct_chg`` over 2020-2024: 300750.SZ on
2023-04-26 reads -41.82% raw against a true +5.40%, 300124.SZ -34.26% against
-1.01%, 601012.SH -24.21% against +6.46%. The error is always negative, because
prices only ever gap down on an ex-date, so it is a systematic contaminant of
returns rather than noise.

The matching factor series comes from ``pro.adj_factor`` for equities and
``pro.fund_adj`` for funds; both carry the same ``(trade_date, adj_factor)``
schema. Factors are cumulative and rise across a corporate action — verified on
600519.SH 2022-06-30, where the factor steps 7.4740 -> 7.5546 as the stock goes
ex-dividend.

This module is the single implementation; the backtest loader and the alpha
bench both route through it rather than re-deriving the convention.
"""

from __future__ import annotations

import pandas as pd


def apply_qfq(df: pd.DataFrame, factor: pd.DataFrame | None) -> pd.DataFrame | None:
    """Forward-adjust raw Tushare daily bars for corporate actions.

    ``pro.daily`` returns *unadjusted* prices, so a close-to-close return taken
    across an ex-date spans the mechanical price drop of a split, bonus issue or
    dividend rather than the stock's actual move. Measured against Tushare's own
    ``pct_chg`` on CSI300 members: 300750.SZ on 2023-04-26 reads -41.82% raw
    against a true +5.40%, 300124.SZ on 2021-06-04 reads -34.26% against -1.01%,
    601012.SH on 2022-06-06 reads -24.21% against +6.46%. The error is always
    negative, so it is a systematic contaminant of every cross-sectional IC the
    bench reports, not noise.

    Prices are scaled to the last bar in the window (前复权), matching the
    ``adjust="qfq"`` convention the akshare and tencent loaders already use.
    ``volume`` is divided by the same ratio so share counts stay on one basis
    and the ``amount``-derived VWAP keeps the same relationship to ``close``;
    ``amount`` is a cash figure and is left untouched.

    Args:
        df: Raw daily bars indexed by trade date.
        factor: ``pro.adj_factor`` rows for the same symbol and window.

    Returns:
        The adjusted frame, or ``None`` when the adjustment factors are missing
        or unusable — the caller drops the symbol rather than benching it on
        contaminated prices.
    """
    if factor is None or getattr(factor, "empty", True):
        return None
    if "adj_factor" not in factor.columns or "trade_date" not in factor.columns:
        return None
    series = factor.copy()
    series["trade_date"] = pd.to_datetime(series["trade_date"], errors="coerce")
    series = (
        series.dropna(subset=["trade_date"])
        .set_index("trade_date")["adj_factor"]
        .astype(float)
        .sort_index()
    )
    series = series.reindex(df.index).ffill().bfill()
    if series.isna().any() or (series <= 0).any():
        return None

    ratio = series / series.iloc[-1]
    out = df.copy()
    for col in ("open", "high", "low", "close"):
        if col in out.columns:
            out[col] = out[col] * ratio
    if "volume" in out.columns:
        out["volume"] = out["volume"] / ratio
    return out
