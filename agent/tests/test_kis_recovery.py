"""Broker rejections remain errors and explicit token expiry retries once."""

from __future__ import annotations

import json

import pytest
import requests

from src.trading.connectors.kis import sdk as kis


@pytest.fixture
def config():
    return kis.KISConfig(app_key="fixture-key", app_secret="fixture-secret", account_no="12345678", profile="live-readonly")


def _response(status, body):
    response = requests.Response()
    response.status_code = status
    response._content = json.dumps(body).encode()
    return response


@pytest.mark.parametrize("status", [200, 401, 403, 500])
def test_expired_token_refreshes_once_on_explicit_broker_rejection(monkeypatch, config, status):
    responses = iter([
        _response(status, {"rt_cd": "1", "msg1": "기간이 만료된 token 입니다"}),
        _response(200, {"rt_cd": "0", "output1": []}),
    ])
    calls, cleared = [], []
    monkeypatch.setattr(kis, "_headers", lambda *_args: {})
    monkeypatch.setattr(kis, "_clear_token_cache", lambda cfg: cleared.append(cfg))
    def request(*args, **kwargs):
        calls.append(args)
        return next(responses)
    monkeypatch.setattr(kis.requests, "request", request)
    payload, _ = kis._request(config, "GET", "/read", tr_id="fixture")
    assert payload["rt_cd"] == "0"
    assert len(calls) == 2
    assert cleared == [config]


def test_success_http_with_broker_error_is_not_empty_success(monkeypatch, config):
    monkeypatch.setattr(kis, "_headers", lambda *_args: {})
    monkeypatch.setattr(kis.requests, "request", lambda *_args, **_kwargs: _response(200, {"rt_cd": "1", "msg1": "invalid account"}))
    with pytest.raises(kis.KISAPIError, match="invalid account"):
        kis._request(config, "GET", "/read", tr_id="fixture")


def test_incomplete_venue_reads_cannot_look_complete(monkeypatch, config):
    def paginated(_cfg, _path, *, tr_id, params):
        if params["EXCG_ID_DVSN_CD"] == "SOR":
            raise kis.KISAPIError("temporary venue failure")
        return {"output1": []}
    monkeypatch.setattr(kis, "_get_paginated", paginated)
    with pytest.raises(kis.KISAPIError, match="incomplete"):
        kis.get_open_orders(config)


def test_expiry_cannot_retry_indefinitely(monkeypatch, config):
    calls, cleared = [], []
    monkeypatch.setattr(kis, "_headers", lambda *_args: {})
    monkeypatch.setattr(kis, "_clear_token_cache", lambda cfg: cleared.append(cfg))
    def request(*args, **kwargs):
        calls.append(args)
        return _response(200, {"rt_cd": "1", "msg1": "expired token"})
    monkeypatch.setattr(kis.requests, "request", request)
    with pytest.raises(kis.KISAPIError, match="expired token"):
        kis._request(config, "GET", "/read", tr_id="fixture")
    assert len(calls) == 2
    assert len(cleared) == 1


@pytest.mark.parametrize("body", [{"rt_cd": "0"}, {"rt_cd": "0", "output1": None}])
def test_missing_order_list_cannot_mean_no_orders(monkeypatch, config, body):
    monkeypatch.setattr(kis, "_request", lambda *args, **kwargs: (body, {}))
    with pytest.raises(kis.KISAPIError, match="incomplete"):
        kis.get_open_orders(config)
