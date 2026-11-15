"""HTTP auth and capability routing without the conflicted main API entry."""

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from src.data_gateway.api import register_gateway_routes


def test_gateway_routes_use_host_auth():
    app = FastAPI()

    def denied():
        raise HTTPException(401, "required")

    register_gateway_routes(app, denied)
    with TestClient(app) as client:
        assert client.get("/data/options?ticker=AAPL").status_code == 401
        assert client.get("/data/status").status_code == 401
        assert client.get("/data/stream?topics=crypto:BTC-USDT").status_code == 401
        assert client.get("/data/subscriptions").status_code == 401


def test_http_wraps_gateway_and_preserves_stale_status(monkeypatch):
    class Gateway:
        def options_chain(self, ticker, expiration, **kwargs):
            return {"ok": True, "data": {"ticker": ticker}, "gateway": {"cache": "stale"}}

    monkeypatch.setattr("src.data_gateway.api.get_gateway", lambda: Gateway())
    app = FastAPI()
    register_gateway_routes(app, lambda: None)
    with TestClient(app) as client:
        assert client.get("/data/options?ticker=AAPL").json()["gateway"]["cache"] == "stale"
        assert client.get("/data/options?ticker=AAPL&expiration=-1").status_code == 422
        assert client.get("/data/stream?topics=unknown:ANY").status_code == 422
        assert (
            client.post(
                "/data/bars", json={"codes": ["AAPL.US"], "start_date": "2026-01-02", "end_date": "2026-01-01"}
            ).status_code
            == 422
        )
