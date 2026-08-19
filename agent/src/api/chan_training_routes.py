"""Chan-theory training sessions, instrument synchronization, and review APIs."""

from __future__ import annotations

import random
import re
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from backtest.loaders._http import throttled_get
from backtest.loaders.sec_edgar_client import list_company_tickers
from src.api.market_routes import (
    _canonical_us_symbol,
    _fetch_stock_bars_a_share,
    _fetch_stock_bars_us,
    _normalise_stock_bars,
    canonical_a_share_code,
)
from src.api.security import require_auth
from src.chan_training_analysis import CHAN_ANALYSIS_VERSION, build_chan_analysis, calculate_analysis_window
from src.chan_training_agent import run_chan_analysis
from src.chan_training_store import ChanTrainingStore
from src.session.models import Principal


class TrainingSessionCreateRequest(BaseModel):
    market: str = Field(pattern="^(a_share|us)$")
    period: str = Field(pattern="^(1d|1w)$")
    initial_capital: str | float | int = Field(default="100000")
    window_size: int = Field(default=60, ge=2, le=500)
    commission_enabled: bool = False
    commission_rate: str | float | int = "0.0003"
    stamp_enabled: bool = False
    stamp_rate: str | float | int = "0.0005"
    transfer_enabled: bool = False
    transfer_rate: str | float | int = "0.00001"


class InstrumentSyncRequest(BaseModel):
    market: str = Field(default="all", pattern="^(a_share|us|all)$")


class TrainingStateRequest(BaseModel):
    cursor: int = Field(ge=0)


class TrainingTradeRequest(BaseModel):
    side: str = Field(pattern="^(buy|sell)$")
    ratio: str = Field(pattern="^(1/2|1/3|1/4|1|clear)$")


_EASTMONEY_LIST_URL = "https://push2.eastmoney.com/api/qt/clist/get"
_EASTMONEY_PAGE_SIZE = 5000
_EASTMONEY_MIN_INTERVAL = 1.0
_A_SHARE_NAME_EXCLUSIONS = ("ETF", "LOF", "基金", "债", "指数", "转债", "退市")


def _scope(principal: Principal) -> str:
    return principal.subject


def _training_bars(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    bars = _normalise_stock_bars(raw)
    result: list[dict[str, Any]] = []
    closes: list[float] = []
    for item in bars:
        if not item.get("time") or item.get("close") is None:
            continue
        closes.append(float(item["close"]))
        indicators: dict[str, float | None] = {}
        for period in (5, 10, 20, 60):
            values = closes[-period:]
            indicators[f"ma{period}"] = sum(values) / period if len(values) == period else None
        result.append({**item, "indicators": indicators})
    return result


def _a_share_exchange(code: str, market_code: Any) -> str:
    if str(market_code) == "1" or code.startswith(("6", "9")):
        return "SH"
    if code.startswith(("4", "8", "92")):
        return "BJ"
    return "SZ"


def _fetch_a_share_instruments_eastmoney() -> list[dict[str, Any]]:
    """Fetch the current A-share equity universe and names from Eastmoney."""
    result: list[dict[str, Any]] = []
    page = 1
    headers = {"Referer": "https://quote.eastmoney.com/", "Accept": "application/json"}
    while page <= 20:
        response = throttled_get(
            _EASTMONEY_LIST_URL,
            host_key="eastmoney-training-universe",
            min_interval=_EASTMONEY_MIN_INTERVAL,
            params={
                "pn": str(page), "pz": str(_EASTMONEY_PAGE_SIZE), "po": "1", "np": "1",
                "fltt": "2", "invt": "2", "fid": "f12",
                "fs": "m:0+t:6,m:0+t:80,m:0+t:81,m:1+t:2",
                "fields": "f12,f13,f14",
            },
            headers=headers,
            timeout=30.0,
        )
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        diff = data.get("diff") if isinstance(data, dict) else None
        rows = list(diff.values()) if isinstance(diff, dict) else (diff or [])
        if not rows:
            break
        for row in rows:
            if not isinstance(row, dict):
                continue
            code = str(row.get("f12") or "").strip()
            name = str(row.get("f14") or "").strip()
            if not re.fullmatch(r"\d{6}", code) or not name or any(term in name.upper() for term in _A_SHARE_NAME_EXCLUSIONS):
                continue
            exchange = _a_share_exchange(code, row.get("f13"))
            result.append({
                "market": "a_share", "symbol": f"{code}.{exchange}", "name": name,
                "exchange": exchange, "asset_type": "equity", "source": "eastmoney",
            })
        if len(rows) < _EASTMONEY_PAGE_SIZE:
            break
        page += 1
    unique = {item["symbol"]: item for item in result}
    return list(unique.values())


def _fetch_a_share_instruments_akshare() -> list[dict[str, Any]]:
    """Fetch the current A-share list through exchange-backed AkShare APIs.

    AkShare's combined list uses the Shanghai, Shenzhen, and Beijing exchange
    list endpoints instead of Eastmoney's push2 CDN.  It is therefore a useful
    fallback when the application's Eastmoney proxy connection is unavailable.
    """
    import akshare as ak

    # AkShare's BSE helper emits a tqdm progress bar while it walks official
    # exchange pages; keep that implementation detail out of the API logs.
    with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
        frame = ak.stock_info_a_code_name()
    rows = frame.to_dict(orient="records") if hasattr(frame, "to_dict") else []
    result: list[dict[str, Any]] = []
    for row in rows:
        code = str(row.get("code") or row.get("证券代码") or "").strip().zfill(6)
        name = str(row.get("name") or row.get("证券简称") or "").strip()
        if not re.fullmatch(r"\d{6}", code) or not name:
            continue
        exchange = _a_share_exchange(code, None)
        result.append({
            "market": "a_share", "symbol": f"{code}.{exchange}", "name": name,
            "exchange": exchange, "asset_type": "equity", "source": "akshare-exchange",
        })
    unique = {item["symbol"]: item for item in result}
    if not unique:
        raise RuntimeError("AkShare returned an empty A-share instrument list")
    return list(unique.values())


def _fetch_a_share_instruments() -> list[dict[str, Any]]:
    """Fetch A-share instruments with an Eastmoney -> exchange fallback."""
    try:
        return _fetch_a_share_instruments_eastmoney()
    except Exception as primary_exc:
        try:
            return _fetch_a_share_instruments_akshare()
        except Exception as fallback_exc:
            raise RuntimeError(
                "A-share instrument sources are unavailable: "
                f"Eastmoney={primary_exc}; exchange fallback={fallback_exc}"
            ) from fallback_exc


def _fetch_us_instruments() -> list[dict[str, Any]]:
    """Fetch the current SEC reporting-company ticker/name universe."""
    result: list[dict[str, Any]] = []
    for item in list_company_tickers():
        ticker = str(item.get("symbol") or "").strip().upper()
        name = str(item.get("name") or "").strip()
        if not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,14}", ticker) or not name:
            continue
        result.append({
            "market": "us", "symbol": f"{ticker}.US", "name": name,
            "exchange": "US", "asset_type": "equity", "source": "sec",
        })
    return result


def _sync_instruments(store: ChanTrainingStore, market: str) -> dict[str, Any]:
    markets = ("a_share", "us") if market == "all" else (market,)
    counts: dict[str, int] = {}
    sources: dict[str, list[str]] = {}
    for item_market in markets:
        rows = _fetch_a_share_instruments() if item_market == "a_share" else _fetch_us_instruments()
        counts[item_market] = store.upsert_instruments(rows)
        sources[item_market] = sorted({str(row.get("source") or "unknown") for row in rows})
    return {"market": market, "counts": counts, "sources": sources, "available": store.count_instruments()}


def _choose_session_data(store: ChanTrainingStore, market: str, period: str, window_size: int) -> tuple[str, str, list[dict[str, Any]]]:
    pool = store.list_instruments(market)
    if not pool:
        raise LookupError(f"{market} instrument pool is empty; synchronize instruments before starting training")
    random.shuffle(pool)
    errors: list[str] = []
    for instrument in pool:
        symbol = str(instrument["symbol"])
        name = str(instrument["name"])
        try:
            canonical = canonical_a_share_code(symbol, stock_only=True) if market == "a_share" else _canonical_us_symbol(symbol)
            raw = _fetch_stock_bars_a_share(canonical, period) if market == "a_share" else _fetch_stock_bars_us(canonical, period)
            bars = _training_bars(raw)
            if len(bars) < max(window_size, 60):
                errors.append(f"{symbol}: insufficient bars")
                continue
            return canonical, name, bars
        except Exception as exc:
            errors.append(f"{symbol}: {exc}")
    detail = "; ".join(errors[:3])
    raise RuntimeError(f"no eligible training stock was available from the synchronized pool{(': ' + detail) if detail else ''}")


def register_chan_training_routes(app: FastAPI) -> None:
    store = ChanTrainingStore()
    analysis_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="chan-analysis")

    @app.post("/chan-training/instruments/sync", dependencies=[Depends(require_auth)])
    def sync_instruments(payload: InstrumentSyncRequest, principal: Principal = Depends(require_auth)) -> dict[str, Any]:
        del principal
        try:
            return _sync_instruments(store, payload.market)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"instrument synchronization failed: {exc}") from exc

    @app.get("/chan-training/instruments", dependencies=[Depends(require_auth)])
    def list_instruments(market: str | None = Query(default=None), principal: Principal = Depends(require_auth)) -> dict[str, Any]:
        del principal
        if market not in {None, "a_share", "us"}:
            raise HTTPException(status_code=400, detail="market must be a_share or us")
        if market:
            return {"market": market, "count": store.count_instruments(market)}
        return {"counts": store.count_instruments()}

    @app.post("/chan-training/sessions", dependencies=[Depends(require_auth)])
    def create_session(payload: TrainingSessionCreateRequest, principal: Principal = Depends(require_auth)) -> dict[str, Any]:
        try:
            symbol, name, bars = _choose_session_data(store, payload.market, payload.period, payload.window_size)
            currency = "CNY" if payload.market == "a_share" else "USD"
            config = payload.model_dump() | {"symbol": symbol, "name": name, "currency": currency}
            analysis = build_chan_analysis(bars)
            return store.create_session(_scope(principal), config, bars, analysis)
        except LookupError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/chan-training/sessions", dependencies=[Depends(require_auth)])
    def list_sessions(principal: Principal = Depends(require_auth)) -> dict[str, Any]:
        return {"items": store.list_sessions(_scope(principal))}

    @app.get("/chan-training/sessions/{session_id}", dependencies=[Depends(require_auth)])
    def get_session(session_id: str, principal: Principal = Depends(require_auth)) -> dict[str, Any]:
        try:
            return store.get_session(_scope(principal), session_id, include_hidden=False)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.delete("/chan-training/sessions/{session_id}", dependencies=[Depends(require_auth)])
    def delete_session(session_id: str, principal: Principal = Depends(require_auth)) -> dict[str, Any]:
        try:
            store.delete_session(_scope(principal), session_id)
            return {"deleted": True, "id": session_id}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/chan-training/sessions/{session_id}/review", dependencies=[Depends(require_auth)])
    def review_session(session_id: str, principal: Principal = Depends(require_auth)) -> dict[str, Any]:
        try:
            return store.get_session(_scope(principal), session_id, include_hidden=True)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.patch("/chan-training/sessions/{session_id}/state", dependencies=[Depends(require_auth)])
    def save_state(session_id: str, payload: TrainingStateRequest, principal: Principal = Depends(require_auth)) -> dict[str, Any]:
        try:
            return store.save_state(_scope(principal), session_id, payload.cursor)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/chan-training/sessions/{session_id}/trades", dependencies=[Depends(require_auth)])
    def execute_trade(session_id: str, payload: TrainingTradeRequest, principal: Principal = Depends(require_auth)) -> dict[str, Any]:
        try:
            return store.execute_trade(_scope(principal), session_id, payload.side, payload.ratio)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/chan-training/sessions/{session_id}/finish", dependencies=[Depends(require_auth)])
    def finish_session(session_id: str, principal: Principal = Depends(require_auth)) -> dict[str, Any]:
        try:
            return store.finish(_scope(principal), session_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/chan-training/sessions/{session_id}/analysis", status_code=202, dependencies=[Depends(require_auth)])
    def create_analysis(session_id: str, principal: Principal = Depends(require_auth)) -> dict[str, Any]:
        scope = _scope(principal)
        try:
            session = store.get_session(scope, session_id, include_hidden=True)
            bars = session.get("bars") or []
            trades = session.get("trades") or []
            window = calculate_analysis_window(bars, trades, session.get("current_cursor"))
            snapshot = {
                "source": "training_session_snapshot", "immutable": True,
                "symbol": session.get("symbol"), "period": session.get("period"),
                "bar_count": len(bars), "first_available": bars[0].get("time") if bars else None,
                "last_available": bars[-1].get("time") if bars else None,
                "missing": bool(window.get("missing")),
            }
            run = store.create_analysis_run(scope, session_id, window=window, snapshot_summary=snapshot, analysis_version=CHAN_ANALYSIS_VERSION, model={"provider": "configured", "async": True})
            analysis_executor.submit(run_chan_analysis, store, scope, run["id"])
            return run
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/chan-training/sessions/{session_id}/analysis", dependencies=[Depends(require_auth)])
    def get_analysis(session_id: str, principal: Principal = Depends(require_auth)) -> dict[str, Any]:
        try:
            run = store.get_analysis_run(_scope(principal), session_id)
            return run or {"status": "not_started", "session_id": session_id, "report": None}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
