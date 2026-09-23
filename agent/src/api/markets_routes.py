"""Market board HTTP routes for the Web UI.

Mounted from ``register_system_routes`` (``agent/src/api/system_routes.py``).

Routes:

- ``GET /markets/kenya/board`` — the latest Nairobi Securities Exchange session
  as one board: every counter on the exchange's Daily Equity Price List with
  its VWAP close, change, range and turnover, plus session breadth.

The board is read from the same source the ``nse_ke`` loader backtests on, so
the numbers a user sees are the numbers a backtest fills against. Responses are
cached in-process: the list is published once per session, so re-reading the
PDF on every page view would only load the exchange's server.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import date
from typing import Any, Optional

from fastapi import Depends, FastAPI, HTTPException, Query

from src.api.security import require_auth

logger = logging.getLogger(__name__)

#: Seconds a built board is served from memory before the list is re-checked.
BOARD_TTL_S = 15 * 60

_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_cache_lock = threading.Lock()


def _num(value: Any) -> Optional[float]:
    """JSON-safe float: NaN / None become ``None``."""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return None if f != f else f  # NaN check without importing math


def build_board(session: date, frame) -> dict[str, Any]:
    """Shape one parsed price list into the board payload.

    Args:
        session: The session date the list belongs to.
        frame: A frame from :func:`backtest.loaders.nse_ke_loader.parse_price_list_text`.

    Returns:
        ``{"as_of", "source", "source_url", "rows", "breadth"}``. Each row carries
        ``code, name, isin, sector, close, prev, change, change_pct, high, low,
        volume, turnover, hi52, lo52, traded``. ``close`` is the session VWAP —
        the NSE's official closing price.
    """
    from backtest.loaders.nse_ke_loader import price_list_url

    rows: list[dict[str, Any]] = []
    advancers = decliners = unchanged = traded = 0
    for rec in frame.to_dict("records"):
        vwap, prev, volume = _num(rec.get("vwap")), _num(rec.get("prev")), _num(rec.get("volume"))
        did_trade = bool(vwap and volume and volume > 0)
        close = vwap if did_trade else prev
        change = change_pct = None
        if did_trade and prev:
            change = round(vwap - prev, 4)
            change_pct = round((vwap / prev - 1.0) * 100.0, 4)
        if did_trade:
            traded += 1
            if change is None or abs(change) < 1e-9:
                unchanged += 1
            elif change > 0:
                advancers += 1
            else:
                decliners += 1
        rows.append({
            "code": rec.get("code"),
            "name": rec.get("name"),
            "isin": rec.get("isin"),
            "sector": rec.get("sector"),
            "close": close,
            "prev": prev,
            "change": change,
            "change_pct": change_pct,
            "high": _num(rec.get("high")),
            "low": _num(rec.get("low")),
            "volume": volume if did_trade else 0.0,
            "turnover": round(vwap * volume, 2) if did_trade else 0.0,
            "hi52": _num(rec.get("hi52")),
            "lo52": _num(rec.get("lo52")),
            "traded": did_trade,
        })
    return {
        "as_of": session.isoformat(),
        "source": "nse_ke",
        "source_url": price_list_url(session),
        "rows": rows,
        "breadth": {
            "listed": len(rows),
            "traded": traded,
            "advancers": advancers,
            "decliners": decliners,
            "unchanged": unchanged,
        },
    }


def register_markets_routes(app: FastAPI) -> None:
    """Mount the market-board routes onto ``app``."""

    @app.get("/markets/kenya/board", dependencies=[Depends(require_auth)])
    async def get_kenya_board(
        session: Optional[str] = Query(
            None,
            alias="date",
            description="Session date YYYY-MM-DD; omit for the latest published list",
            pattern=r"^\d{4}-\d{2}-\d{2}$",
        ),
    ):
        """The NSE board for one session, from the exchange's daily price list."""
        import asyncio

        from backtest.loaders import nse_ke_loader

        if not nse_ke_loader.DataLoader().is_available():
            raise HTTPException(
                status_code=503,
                detail="The NSE board needs the optional 'nse-ke' extra: "
                "pip install 'vibe-trading-ai[nse-ke]'",
            )

        key = session or "latest"
        now = time.monotonic()
        with _cache_lock:
            hit = _cache.get(key)
            if hit and now - hit[0] < BOARD_TTL_S:
                return hit[1]

        def _load() -> tuple[Optional[date], Any]:
            if session:
                try:
                    day = date.fromisoformat(session)
                except ValueError:
                    raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD")
                return day, nse_ke_loader.fetch_price_list(day)
            return nse_ke_loader.latest_price_list()

        try:
            day, frame = await asyncio.to_thread(_load)
        except HTTPException:
            raise
        except Exception:
            logger.exception("NSE board load failed (date=%s)", session)
            raise HTTPException(status_code=502, detail="Could not read the NSE daily price list")

        if day is None or frame is None or frame.empty:
            raise HTTPException(
                status_code=404,
                detail="No readable NSE price list for that session. It may be a "
                "holiday, not yet published, or issued as a scanned image.",
            )

        payload = build_board(day, frame)
        with _cache_lock:
            _cache[key] = (now, payload)
        return payload


def clear_cache() -> None:
    """Drop every cached board (tests)."""
    with _cache_lock:
        _cache.clear()
