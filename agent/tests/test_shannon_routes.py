"""Snapshot diagnosis preserves explicit weights and actual dates."""
import copy
import json
from unittest.mock import Mock

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest

from src.api import shannon_routes as sr
from src.tools import gildata_srv


@pytest.fixture
def diagnosis():
    return {"status": "completed", "intent": "portfolio_diagnosis", "data": {
        "exposures": {"portfolio": {"SIZE": 1.2, "VOLATILITY": -.7}},
        "holdings": [{"ts_code": "600000.SH", "name": "甲公司", "normalized_weight": .6},
                     {"ts_code": "000001.SZ", "name": "乙公司", "normalized_weight": .4}],
        "missing": [], "risk_attribution": {"top_stock_contributions": {"600000.SH": .2, "000001.SZ": -.01}}},
        "meta": {"actual_factor_date": "2026-10-28", "risk_as_of": "2026-10-28", "requested_holding_count": 2, "included_holding_count": 2}, "warnings": []}


@pytest.fixture
def client(monkeypatch, diagnosis):
    monkeypatch.setenv("GILDATA_TOKEN", "test-token")
    vendor = Mock(return_value=diagnosis)
    monkeypatch.setattr(sr, "call_srv_arguments", vendor)
    app = FastAPI()
    sr.register_shannon_routes(app, lambda: None)
    with TestClient(app) as test_client:
        yield test_client, vendor


def body(**kwargs):
    return {"date": "2026-10-28", "holdings": [{"code": "600000.SH", "weight": .6}, {"code": "000001.SZ", "weight": .4}], **kwargs}


def test_latest_catalog_and_equal_weights_are_explicit(client, diagnosis):
    c, vendor = client
    vendor.side_effect = [{"status": "completed", "data": {"universes": [{"id": "all", "ready": True, "current_as_of": "2026-10-28"}]}}, diagnosis]
    result = c.post("/api/shannon/diagnosis", json={"holdings": [{"code": "600000.SH"}, {"code": "000001.SZ"}]}).json()
    assert result["weight_assumption"] == "equal" and result["requested_date"] == "2026-10-28"
    args = vendor.call_args.args[1]
    assert args["date"] == "2026-10-28" and [h["weight"] for h in args["positions"][0]["holdings"]] == [.5, .5]
    assert vendor.call_count == 2


def test_selected_date_does_not_require_catalog(client, diagnosis):
    c, vendor = client
    original = copy.deepcopy(diagnosis)
    result = c.post("/api/shannon/diagnosis", json=body()).json()
    assert result["weight_assumption"] == "custom"
    assert "analysis_id" not in result
    assert diagnosis == original
    vendor.assert_called_once()
    assert vendor.call_args.args[1]["positions"][0]["date"] == "2026-10-28"


@pytest.mark.parametrize("holdings", [
    [{"code": "600000.SH", "weight": .6}, {"code": "000001.SZ"}],
    [{"code": "600000.SH", "weight": .4}, {"code": "000001.SZ", "weight": .4}],
    [{"code": "600000.SH"}, {"code": "600000.SH"}],
    [{"code": "000300.SH"}], [{"code": "00700.HK"}], [{"code": "AAPL.US"}],
    [{"code": "600000.SH", "weight": 0}], [{"code": "600000.SH", "weight": -1}],
])
def test_invalid_or_partial_allocations_never_reach_vendor(client, holdings):
    c, vendor = client
    assert c.post("/api/shannon/diagnosis", json=body(holdings=holdings)).status_code == 422
    vendor.assert_not_called()


def test_non_trading_date_fallback_is_explicit_but_future_data_rejected(client):
    c, vendor = client
    result = c.post("/api/shannon/diagnosis", json=body(date="2026-10-31"))
    assert result.status_code == 200
    assert result.json()["requested_date"] == "2026-10-31"
    assert result.json()["meta"]["actual_factor_date"] == "2026-10-28"
    assert c.post("/api/shannon/diagnosis", json=body(date="2026-10-27")).status_code == 502


def test_missing_actual_date_is_not_invented(client):
    c, vendor = client
    vendor.return_value = {"status": "completed", "data": {}, "meta": {}}
    assert c.post("/api/shannon/diagnosis", json=body()).status_code == 502


def test_optional_source_never_calls_network_without_token(client, monkeypatch):
    c, vendor = client
    monkeypatch.setenv("GILDATA_TOKEN", "")
    assert c.get("/api/shannon/status").json() == {"configured": False}
    assert c.post("/api/shannon/diagnosis", json=body()).status_code == 503
    vendor.assert_not_called()


def test_vendor_error_is_sanitized(client):
    c, vendor = client
    vendor.side_effect = RuntimeError("secret-token authenticated response")
    result = c.post("/api/shannon/diagnosis", json=body())
    assert result.status_code == 502 and "secret-token" not in result.text


@pytest.mark.parametrize("path", ["market", "stress", "interpretation", "period", "jobs/unowned"])
def test_removed_features_have_no_routes(client, path):
    c, vendor = client
    assert c.post(f"/api/shannon/{path}", json=body()).status_code == 404
    vendor.assert_not_called()
    if path.startswith("jobs/"):
        assert c.get(f"/api/shannon/{path}").status_code == 404


def test_routes_keep_authentication():
    def auth():
        raise HTTPException(401, "authentication required")
    app = FastAPI()
    sr.register_shannon_routes(app, auth)
    with TestClient(app) as c:
        assert c.get("/api/shannon/status").status_code == 401
        assert c.post("/api/shannon/diagnosis", json=body()).status_code == 401


@pytest.mark.parametrize("status", ["completed", "queued", "running"])
def test_transport_preserves_status_and_rejects_rpc_errors(monkeypatch, status):
    monkeypatch.setenv("GILDATA_TOKEN", "test-token")
    payload = {"status": status, "job_id": "job-123", "data": {}, "meta": {"as_of": "2026-10-28"}}
    outer = {"result": {"content": [{"type": "text", "text": json.dumps(payload)}]}}
    post = Mock(return_value=outer)
    monkeypatch.setattr(gildata_srv, "throttled_post_json", post)
    assert gildata_srv.call_srv_arguments("ShannonAnalyze", {"intent": "catalog"}) == payload
    assert post.call_args.kwargs["headers"]["Authorization"] == "Bearer test-token"
    assert "test-token" not in post.call_args.args[0]
    post.return_value = {"result": {"isError": True, "content": [{"text": "secret-token"}]}}
    with pytest.raises(RuntimeError, match="Gildata analysis failed"):
        gildata_srv.call_srv_arguments("ShannonAnalyze", {"intent": "catalog"})
