"""Read-only market-data routes that were previously agent-tool only."""

from __future__ import annotations

import json
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query

from src.api.security import require_auth
from src.integrations.iwencai_client import (
    IwencaiError,
    IwencaiNotConfigured,
    normalize_query_response,
    query2data,
)
from src.tools.fund_flow_tool import FundFlowTool
from src.tools.technical_indicator_tool import TechnicalIndicatorTool


def _tool_result(tool: Any, **kwargs: Any) -> dict[str, Any]:
    try:
        payload = json.loads(tool.execute(**kwargs))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail="data tool returned invalid JSON") from exc
    except Exception as exc:  # noqa: BLE001 - convert provider failures to REST errors
        raise HTTPException(status_code=502, detail=f"data provider unavailable: {exc}") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=502, detail="data tool returned an invalid envelope")
    if payload.get("ok") is False:
        raise HTTPException(status_code=502, detail=str(payload.get("error") or "data provider unavailable"))
    return payload


def _query_iwencai(
    query: str,
    *,
    page: int,
    limit: int,
    skill_id: str,
) -> dict[str, Any]:
    try:
        payload = query2data(query, page=page, limit=limit, skill_id=skill_id)
    except IwencaiNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except IwencaiError as exc:
        status = 502 if exc.status_code is None or exc.status_code >= 500 else exc.status_code
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    if "text_response" in payload and "datas" not in payload:
        raise HTTPException(status_code=502, detail=str(payload["text_response"]))
    return normalize_query_response(payload, query=query, page=page, limit=limit)


def _compose_query(*parts: str | None, suffix: str = "") -> str:
    values = [str(value).strip() for value in parts if value and str(value).strip()]
    if suffix and suffix not in values:
        values.append(suffix)
    if not values:
        raise HTTPException(status_code=422, detail="query or a symbol/type is required")
    return " ".join(values)


def register_extended_market_routes(app: FastAPI) -> None:
    """Register read-only routes for technical, flow, basic-info and events data."""

    @app.get("/market/stocks/{symbol}/technical-indicators", dependencies=[Depends(require_auth)])
    def market_stock_technical_indicators(
        symbol: str,
        interval: str = Query("1d", pattern="^(1d|1wk|1mo)$"),
        lookback: int = Query(200, ge=10, le=500),
    ) -> dict[str, Any]:
        return _tool_result(
            TechnicalIndicatorTool(),
            symbol=symbol,
            interval=interval,
            lookback=lookback,
        )

    @app.get("/market/fund-flow", dependencies=[Depends(require_auth)])
    def market_fund_flow(
        symbols: str = Query(..., min_length=1, max_length=1200),
        period: str = Query("daily", pattern="^(daily|min)$"),
        days: int = Query(30, ge=1, le=250),
    ) -> dict[str, Any]:
        codes = [item.strip() for item in symbols.split(",") if item.strip()]
        if not codes:
            raise HTTPException(status_code=422, detail="symbols must contain at least one symbol")
        return _tool_result(FundFlowTool(), codes=codes, period=period, days=days)

    @app.get("/market/stocks/{symbol}/fund-flow", dependencies=[Depends(require_auth)])
    def market_stock_fund_flow(
        symbol: str,
        period: str = Query("daily", pattern="^(daily|min)$"),
        days: int = Query(30, ge=1, le=250),
    ) -> dict[str, Any]:
        return _tool_result(FundFlowTool(), codes=[symbol], period=period, days=days)

    @app.get("/market/basic-info", dependencies=[Depends(require_auth)])
    def market_basic_info(
        query: str | None = Query(None, max_length=500),
        symbol: str | None = Query(None, max_length=32),
        asset_type: str | None = Query(None, max_length=32),
        page: int = Query(1, ge=1, le=10000),
        limit: int = Query(10, ge=1, le=100),
    ) -> dict[str, Any]:
        normalized = _compose_query(symbol, asset_type, query, suffix="基本资料")
        return _query_iwencai(
            normalized,
            page=page,
            limit=limit,
            skill_id="hithink-basicinfo-query",
        )

    @app.get("/market/events", dependencies=[Depends(require_auth)])
    def market_events(
        query: str | None = Query(None, max_length=500),
        symbol: str | None = Query(None, max_length=32),
        event_type: str | None = Query(None, max_length=64),
        page: int = Query(1, ge=1, le=10000),
        limit: int = Query(10, ge=1, le=100),
    ) -> dict[str, Any]:
        normalized = _compose_query(symbol, event_type, query)
        return _query_iwencai(
            normalized,
            page=page,
            limit=limit,
            skill_id="hithink-event-query",
        )
