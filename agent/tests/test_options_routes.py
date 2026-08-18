"""API tests for ``POST /options/payoff`` + ``GET /options/chain``.

Deterministic by construction — no network anywhere:

* the payoff route runs the REAL ``OptionsPayoffTool`` (pure math), so happy
  path, multi-leg, validation and tool-error mapping are exercised end to end;
* greeks parity is asserted against a direct ``bs_greeks`` call;
* the chain route's ``OptionsChainTool.execute`` is monkeypatched where the
  route module binds it (``src.api.options_routes.OptionsChainTool``), so the
  Yahoo I/O never happens.

Loopback ``TestClient`` (127.0.0.1) bypasses dev-mode auth, matching the
convention in ``test_alpha_compare_api.py``.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

import api_server
from src.quantlib.options import bs_greeks


def _client() -> TestClient:
    return TestClient(api_server.app, client=("127.0.0.1", 50000))


@pytest.fixture(autouse=True)
def _dev_mode_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("API_AUTH_KEY", raising=False)
    monkeypatch.setattr(api_server, "_API_KEY", "")


def _long_call_body(**over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "legs": [{"option_type": "call", "strike": 100.0, "qty": 1}],
        "entry_spot": 100.0,
        "expiry_days": 30.0,
        "risk_free_rate": 0.05,
        "volatility": 0.3,
        "multiplier": 1.0,
    }
    body.update(over)
    return body


# ── POST /options/payoff — happy path ───────────────────────────────────────


def test_payoff_single_long_call_happy_path() -> None:
    r = _client().post("/options/payoff", json=_long_call_body())

    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"

    summary = body["summary"]
    assert summary["entry_side"] == "debit"
    assert len(summary["breakevens"]) == 1
    assert summary["breakevens"][0] > 100.0

    curve = body["expiry_curve"]
    assert len(curve["spot"]) == len(curve["pnl"])
    assert len(curve["spot"]) == 121  # default spot_points

    grid = body["scenario_grid"]
    assert len(grid["iv_values"]) == 5  # default: 50/75/100/125/150% of entry vol
    assert len(grid["pnl"]) == 5
    assert all(len(row) == len(grid["spot"]) for row in grid["pnl"])

    greeks = body["greeks"]
    assert set(greeks) == {"delta", "gamma", "theta", "vega", "rho"}
    assert 0.0 < greeks["delta"] < 1.0
    assert greeks["theta"] < 0.0


def test_payoff_iron_condor_bounded_two_breakevens() -> None:
    body = _long_call_body(
        legs=[
            {"option_type": "put", "strike": 85.0, "qty": 1},
            {"option_type": "put", "strike": 90.0, "qty": -1},
            {"option_type": "call", "strike": 110.0, "qty": -1},
            {"option_type": "call", "strike": 115.0, "qty": 1},
        ],
    )

    r = _client().post("/options/payoff", json=body)

    assert r.status_code == 200
    summary = r.json()["summary"]
    assert summary["profit_unbounded"] is False
    assert summary["loss_unbounded"] is False
    assert summary["max_profit"] is not None
    assert summary["max_loss"] is not None
    assert len(summary["breakevens"]) == 2


def test_payoff_greeks_match_bs_greeks_with_multiplier() -> None:
    legs = [
        {"option_type": "call", "strike": 100.0, "qty": 2},
        {"option_type": "put", "strike": 95.0, "qty": -1},
    ]
    multiplier = 100.0

    r = _client().post(
        "/options/payoff", json=_long_call_body(legs=legs, multiplier=multiplier)
    )
    assert r.status_code == 200
    got = r.json()["greeks"]

    expected = {key: 0.0 for key in ("delta", "gamma", "theta", "vega", "rho")}
    for leg in legs:
        g = bs_greeks(
            S=100.0, K=leg["strike"], T=30.0 / 365.0, r=0.05, sigma=0.3,
            option_type=leg["option_type"],
        )
        for key in expected:
            expected[key] += leg["qty"] * g[key]
    for key in expected:
        expected[key] *= multiplier

    for key in expected:
        assert got[key] == pytest.approx(expected[key], abs=1e-6), key


# ── POST /options/payoff — validation & tool errors ─────────────────────────


def test_payoff_rejects_negative_strike() -> None:
    body = _long_call_body(
        legs=[{"option_type": "call", "strike": -1.0, "qty": 1}],
    )
    assert _client().post("/options/payoff", json=body).status_code == 422


def test_payoff_rejects_empty_legs() -> None:
    assert _client().post("/options/payoff", json=_long_call_body(legs=[])).status_code == 422


def test_payoff_rejects_zero_qty_and_spot_points_below_min() -> None:
    client = _client()
    zero_qty = _long_call_body(legs=[{"option_type": "call", "strike": 100.0, "qty": 0}])
    assert client.post("/options/payoff", json=zero_qty).status_code == 422

    # spot_points=5 is below the tool's minimum; the pydantic mirror rejects it
    # first, so the route answers 422 (not the tool's 400 envelope).
    small_grid = _long_call_body(spot_points=5)
    assert client.post("/options/payoff", json=small_grid).status_code == 422


def test_payoff_tool_error_maps_to_400() -> None:
    # Passes pydantic (bounds are independently valid) but the tool refuses an
    # inverted chart window: spot_max must be greater than spot_min.
    body = _long_call_body(spot_min=150.0, spot_max=100.0)

    r = _client().post("/options/payoff", json=body)

    assert r.status_code == 400
    payload = r.json()
    assert payload["status"] == "error"
    assert "spot_max" in payload["error"]


def test_payoff_unexpected_tool_exception_maps_to_502(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(self: Any, **kwargs: Any) -> str:
        raise RuntimeError("payoff engine exploded")

    monkeypatch.setattr("src.api.options_routes.OptionsPayoffTool.execute", explode)

    r = _client().post("/options/payoff", json=_long_call_body())

    assert r.status_code == 502
    assert r.json() == {"ok": False, "error": "payoff computation failed"}


# ── GET /options/chain ───────────────────────────────────────────────────────

_OK_CHAIN = json.dumps(
    {
        "ok": True,
        "market": "us",
        "source": "yahoo",
        "data": {
            "ticker": "AAPL",
            "expiration": 1765584000,
            "expirations": [1765584000],
            "calls_count": 1,
            "puts_count": 1,
            "calls": [{"contract_symbol": "AAPL260101C00100000", "strike": 100.0}],
            "puts": [{"contract_symbol": "AAPL260101P00100000", "strike": 100.0}],
        },
    }
)
_ERR_CHAIN = json.dumps({"ok": False, "error": "yahoo options request failed: boom"})


def test_chain_success_returns_tool_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake_execute(self: Any, **kwargs: Any) -> str:
        seen.update(kwargs)
        return _OK_CHAIN

    monkeypatch.setattr("src.api.options_routes.OptionsChainTool.execute", fake_execute)

    r = _client().get("/options/chain", params={"ticker": "AAPL", "expiration": 1765584000})

    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["data"]["ticker"] == "AAPL"
    assert seen == {"ticker": "AAPL", "expiration": 1765584000}


def test_chain_tool_failure_maps_to_502(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.api.options_routes.OptionsChainTool.execute",
        lambda self, **kwargs: _ERR_CHAIN,
    )

    r = _client().get("/options/chain", params={"ticker": "AAPL"})

    assert r.status_code == 502
    assert r.json() == {"ok": False, "error": "yahoo options request failed: boom"}


def test_chain_missing_ticker_is_400(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(self: Any, **kwargs: Any) -> str:  # pragma: no cover - must not run
        raise AssertionError("tool must not be called for a blank ticker")

    monkeypatch.setattr("src.api.options_routes.OptionsChainTool.execute", explode)

    client = _client()
    for params in ({}, {"ticker": ""}, {"ticker": "   "}):
        r = client.get("/options/chain", params=params)
        assert r.status_code == 400
        assert r.json() == {"ok": False, "error": "ticker is required"}
