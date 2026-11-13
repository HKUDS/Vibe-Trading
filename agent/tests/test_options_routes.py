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
import math
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


def test_payoff_rejects_boolean_qty() -> None:
    body = _long_call_body(
        legs=[{"option_type": "call", "strike": 100.0, "qty": True}],
    )
    assert _client().post("/options/payoff", json=body).status_code == 422


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


def _surface_body(**over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "observations": [
            {"strike": 90.0, "time_to_expiry": 0.1, "implied_volatility": 0.25},
            {"strike": 110.0, "time_to_expiry": 0.1, "implied_volatility": 0.35},
            {"strike": 90.0, "time_to_expiry": 0.2, "implied_volatility": 0.30},
            {"strike": 110.0, "time_to_expiry": 0.2, "implied_volatility": 0.40},
        ],
        "spot": 100.0,
        "strikes": [90.0, 100.0, 110.0],
        "expiries": [0.1, 0.15, 0.2],
    }
    body.update(over)
    return body


def test_volatility_surface_happy_path_uses_real_interpolation() -> None:
    r = _client().post("/options/volatility-surface", json=_surface_body())

    assert r.status_code == 200
    body = r.json()
    assert body["strikes"] == [90.0, 100.0, 110.0]
    assert body["expiries"] == [0.1, 0.15, 0.2]
    assert body["interpolation"]["extrapolation"] == "rejected"
    assert len(body["points"]) == 9
    assert sum(point["source"] == "observed" for point in body["points"]) == 4
    middle = next(point for point in body["points"] if point["strike"] == 100.0 and point["time_to_expiry"] == 0.15)
    assert middle["source"] == "interpolated"
    weight = math.log(100.0 / 90.0) / math.log(110.0 / 90.0)
    lower_iv = 0.25 + (0.35 - 0.25) * weight
    upper_iv = 0.30 + (0.40 - 0.30) * weight
    lower_variance = lower_iv**2 * 0.1
    upper_variance = upper_iv**2 * 0.2
    expected_variance = (lower_variance + upper_variance) / 2
    assert middle["total_variance"] == pytest.approx(expected_variance)
    assert middle["implied_volatility"] == pytest.approx((expected_variance / 0.15) ** 0.5)


def test_volatility_surface_rejects_extrapolation() -> None:
    r = _client().post("/options/volatility-surface", json=_surface_body(strikes=[120.0]))

    assert r.status_code == 400
    assert "no extrapolation" in r.json()["error"]


def test_volatility_surface_rejects_duplicate_quotes() -> None:
    observations = _surface_body()["observations"]
    observations.append(observations[0])

    r = _client().post("/options/volatility-surface", json=_surface_body(observations=observations))

    assert r.status_code == 400
    assert "duplicate" in r.json()["error"]


def test_volatility_surface_rejects_invalid_schema() -> None:
    body = _surface_body()
    body["observations"][0]["strike"] = -1.0

    assert _client().post("/options/volatility-surface", json=body).status_code == 422


def test_volatility_surface_unexpected_exception_maps_to_502(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def explode(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("surface engine exploded")

    monkeypatch.setattr("src.api.options_routes.implied_volatility_surface", explode)

    r = _client().post("/options/volatility-surface", json=_surface_body())

    assert r.status_code == 502
    assert r.json() == {"ok": False, "error": "volatility surface computation failed"}


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


@pytest.mark.parametrize(
    ("days", "status"),
    [
        ([30], 200),
        ([45], 200),
        ([60], 200),
        ([30, 45], 200),
        ([75], 400),
        ([90], 400),
        ([30, 75], 400),
        (None, 400),
    ],
)
def test_surface_strike_coverage_uses_only_required_expiry_slices(
    days: list[int] | None, status: int
) -> None:
    """Unrelated narrow slices do not forbid a covered requested grid."""
    observations = [
        {"strike": strike, "time_to_expiry": expiry / 365, "implied_volatility": 0.25}
        for expiry, strikes in [(30, [90, 110]), (60, [90, 110]), (90, [100, 110])]
        for strike in strikes
    ]
    body: dict[str, Any] = {"spot": 100, "observations": observations, "strikes": [90]}
    if days is not None:
        body["expiries"] = [day / 365 for day in days]
    response = _client().post("/options/volatility-surface", json=body)
    assert response.status_code == status
    if status == 200:
        assert len(response.json()["points"]) == len(days)
    else:
        assert "extrapolation" in response.json()["error"]


def test_covered_stock_is_in_payoff_and_delta() -> None:
    body = _long_call_body(legs=[{"option_type": "call", "strike": 110, "qty": -1, "premium": 2}],
                           underlying_qty=1, price_as_of="2026-11-12", multiplier=100)
    result = _client().post("/options/payoff", json=body)
    assert result.status_code == 200
    data = result.json()
    assert data["summary"]["profit_unbounded"] is False
    assert data["summary"]["loss_unbounded"] is False
    assert data["calculation_basis"]["underlying_shares"] == 100
    naked = _client().post("/options/payoff", json={**body, "underlying_qty": 0}).json()
    assert data["greeks"]["delta"] - naked["greeks"]["delta"] == pytest.approx(100)


def test_exact_expiry_prices_use_the_real_engine():
    from tests.test_numeric_calculation_contract import collar
    response = _client().post("/options/payoff", json=collar(expiry_spot_values=[160, 180]))
    assert response.status_code == 200
    rows = response.json()["expiry_scenarios"]
    assert [row["spot"] for row in rows] == [160, 180]
    assert rows[0]["return_percent"] == pytest.approx(-5.536795234370298)
    assert rows[1]["return_percent"] == pytest.approx(6.4976232023587475)
