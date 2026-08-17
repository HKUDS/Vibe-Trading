"""Contract tests for the frontend-facing extended market routes."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import extended_market_routes as routes
from src.api.security import require_auth


def _client() -> TestClient:
    app = FastAPI()
    routes.register_extended_market_routes(app)
    app.dependency_overrides[require_auth] = lambda: object()
    return TestClient(app)


def test_technical_indicator_route_exposes_tool_payload(monkeypatch) -> None:
    monkeypatch.setattr(
        routes.TechnicalIndicatorTool,
        "execute",
        lambda _self, **kwargs: '{"ok": true, "symbol": "600519.SH", "indicators": {"rsi_14": 55.2}}',
    )

    response = _client().get(
        "/market/stocks/600519.SH/technical-indicators?interval=1d&lookback=120"
    )

    assert response.status_code == 200
    assert response.json()["indicators"]["rsi_14"] == 55.2


def test_fund_flow_route_supports_batch_symbols(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_execute(_self, **kwargs):
        captured.update(kwargs)
        return '{"ok": true, "period": "daily", "data": {}}'

    monkeypatch.setattr(routes.FundFlowTool, "execute", fake_execute)

    response = _client().get(
        "/market/fund-flow?symbols=600519.SH,000001.SZ&period=daily&days=20"
    )

    assert response.status_code == 200
    assert captured == {
        "codes": ["600519.SH", "000001.SZ"],
        "period": "daily",
        "days": 20,
    }


def test_basic_info_route_uses_query2data_and_paginates(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_query(query, **kwargs):
        captured.update(query=query, **kwargs)
        return {"datas": [{"基金简称": "测试基金"}], "code_count": 21}

    monkeypatch.setattr(routes, "query2data", fake_query)

    response = _client().get(
        "/market/basic-info?asset_type=基金&query=费率&page=2&limit=10"
    )

    assert response.status_code == 200
    body = response.json()
    assert captured == {
        "query": "基金 费率 基本资料",
        "page": 2,
        "limit": 10,
        "skill_id": "hithink-basicinfo-query",
    }
    assert body["has_more"] is True
    assert body["returned_count"] == 1


def test_event_route_requires_a_query_source() -> None:
    response = _client().get("/market/events")

    assert response.status_code == 422
    assert "query or a symbol/type is required" in response.json()["detail"]


def test_event_route_maps_missing_iwencai_key_to_service_unavailable(monkeypatch) -> None:
    def missing_key(*_args, **_kwargs):
        raise routes.IwencaiNotConfigured("missing key")

    monkeypatch.setattr(routes, "query2data", missing_key)

    response = _client().get("/market/events?symbol=600519.SH&event_type=业绩预告")

    assert response.status_code == 503
    assert response.json()["detail"] == "missing key"
