"""Tests for the invinoveritas /review advisory provider (#317 follow-up).

All tests are offline: an :class:`httpx.MockTransport` stands in for the network
so the provider's request shape and response mapping are exercised without any
live call. Covers verdict mapping, the fail-open contract (402 / non-2xx /
timeout / unknown verdict), proof passthrough, auth header, the request
contract sent to /review, and orchestrator aggregation.
"""

from __future__ import annotations

import json
from typing import Any, Callable

import httpx

from src.live.advisory import (
    AdvisoryContext,
    AdvisoryOrchestrator,
    Verdict,
)
from src.live.advisory.invinoveritas import InvinoveritasAdvisory


def _context(**overrides: Any) -> AdvisoryContext:
    base: dict[str, Any] = {
        "symbol": "AAPL",
        "side": "buy",
        "notional_usd": 750.0,
        "account_equity": 5000.0,
        "utilization_ratio": 0.15,
        "open_position_count": 2,
        "total_exposure_usd": 1800.0,
        "funding_usd": 5000.0,
    }
    base.update(overrides)
    return AdvisoryContext(**base)


def _provider(
    handler: Callable[[httpx.Request], httpx.Response],
    **kwargs: Any,
) -> InvinoveritasAdvisory:
    """Build a provider whose HTTP calls are served by *handler* (no network)."""
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return InvinoveritasAdvisory(client=client, **kwargs)


def _json_handler(
    body: dict[str, Any],
    status_code: int = 200,
    capture: list[httpx.Request] | None = None,
) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        if capture is not None:
            capture.append(request)
        return httpx.Response(status_code, json=body)

    return handler


def test_provider_id_default() -> None:
    provider = InvinoveritasAdvisory()
    assert provider.provider_id == "invinoveritas"


def test_approve_maps_to_approve() -> None:
    provider = _provider(_json_handler({"verdict": "approve", "summary": "looks fine"}))
    result = provider.review(_context())
    assert result.verdict is Verdict.APPROVE
    assert result.provider == "invinoveritas"
    assert result.summary == "looks fine"


def test_reject_maps_and_carries_concerns() -> None:
    body = {
        "verdict": "reject",
        "confidence": 0.9,
        "summary": "over-sized for this account",
        "issues": [
            {"severity": "high", "title": "notional exceeds prudent fraction of equity"},
            {"severity": "medium", "title": "concentration in a single name"},
        ],
    }
    provider = _provider(_json_handler(body))
    result = provider.review(_context())
    assert result.verdict is Verdict.REJECT
    assert result.confidence == 0.9
    assert result.concerns == (
        "[high] notional exceeds prudent fraction of equity",
        "[medium] concentration in a single name",
    )


def test_revise_is_soft_concern_not_reject() -> None:
    provider = _provider(_json_handler({"verdict": "revise", "summary": "tighten the size"}))
    result = provider.review(_context())
    assert result.verdict is Verdict.APPROVE_WITH_CONCERNS


def test_approve_with_concerns_maps() -> None:
    provider = _provider(_json_handler({"verdict": "approve_with_concerns"}))
    result = provider.review(_context())
    assert result.verdict is Verdict.APPROVE_WITH_CONCERNS


def test_payment_required_fails_open() -> None:
    provider = _provider(_json_handler({"error": "payment required"}, status_code=402))
    result = provider.review(_context())
    assert result.verdict is Verdict.REVIEW_UNAVAILABLE
    assert "payment" in result.summary.lower()


def test_server_error_fails_open() -> None:
    provider = _provider(_json_handler({"error": "boom"}, status_code=500))
    result = provider.review(_context())
    assert result.verdict is Verdict.REVIEW_UNAVAILABLE
    assert "500" in result.summary


def test_timeout_fails_open() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    provider = _provider(handler)
    result = provider.review(_context())
    assert result.verdict is Verdict.REVIEW_UNAVAILABLE
    assert "timed out" in result.summary


def test_unknown_verdict_fails_open() -> None:
    provider = _provider(_json_handler({"verdict": "maybe"}))
    result = provider.review(_context())
    assert result.verdict is Verdict.REVIEW_UNAVAILABLE


def test_proof_passthrough_into_detail() -> None:
    body = {
        "verdict": "approve",
        "proof": {"verify_url": "https://api.babyblueviper.com/verify-proof?id=abc", "sig": "deadbeef"},
    }
    provider = _provider(_json_handler(body))
    result = provider.review(_context())
    assert result.detail["proof"]["sig"] == "deadbeef"
    assert result.detail["verify_url"] == "https://api.babyblueviper.com/verify-proof?id=abc"


def test_request_contract_sent_to_review() -> None:
    captured: list[httpx.Request] = []
    provider = _provider(
        _json_handler({"verdict": "approve"}, capture=captured),
        api_key="ivk_test_key",
    )
    provider.review(_context(symbol="BTC-USDT", side="sell", notional_usd=1234.5))

    assert len(captured) == 1
    request = captured[0]
    assert request.url.path == "/review"
    assert request.headers["Authorization"] == "Bearer ivk_test_key"
    sent = json.loads(request.content)
    assert sent["artifact_type"] == "trade"
    assert sent["sign"] is True
    assert "BTC-USDT" in sent["artifact"]
    assert "SELL" in sent["artifact"]
    # Account state must reach the reviewer so the verdict is capital-scale-aware.
    assert "equity" in sent["context"].lower()
    assert len(sent["context"]) <= 4000


def test_orchestrator_worst_case_with_invinoveritas_reject() -> None:
    from src.live.advisory.mock import MockAdvisory

    invino = _provider(_json_handler({"verdict": "reject", "summary": "no"}))
    orchestrator = AdvisoryOrchestrator([MockAdvisory(verdict=Verdict.APPROVE), invino])
    aggregated = orchestrator.review(_context())
    assert aggregated.verdict is Verdict.REJECT
    assert len(aggregated.results) == 2


def test_no_api_key_sends_no_auth_header(monkeypatch: Any) -> None:
    """With no api_key and no env var, no Authorization header is sent (no secret leaks)."""
    monkeypatch.delenv("INVINOVERITAS_API_KEY", raising=False)
    captured: list[httpx.Request] = []
    provider = _provider(_json_handler({"verdict": "approve"}, capture=captured))
    provider.review(_context())
    assert len(captured) == 1
    assert "authorization" not in {k.lower() for k in captured[0].headers}


def test_non_json_body_fails_open() -> None:
    """A 200 with an unparseable body must fail open (ValueError path), never block."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html>not json</html>")

    provider = _provider(handler)
    result = provider.review(_context())
    assert result.verdict is Verdict.REVIEW_UNAVAILABLE
    assert "unparseable" in result.summary.lower()


def test_env_var_fallback_for_key_and_base_url(monkeypatch: Any) -> None:
    """api_key and base_url fall back to env vars when not passed explicitly."""
    monkeypatch.setenv("INVINOVERITAS_API_KEY", "ivk_env_key")
    monkeypatch.setenv("INVINOVERITAS_BASE_URL", "https://review.example.test")
    captured: list[httpx.Request] = []
    # No api_key / base_url passed → constructor must read the env.
    provider = _provider(_json_handler({"verdict": "approve"}, capture=captured))
    provider.review(_context())
    assert len(captured) == 1
    request = captured[0]
    assert request.headers["Authorization"] == "Bearer ivk_env_key"
    assert request.url.host == "review.example.test"
