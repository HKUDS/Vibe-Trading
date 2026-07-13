"""Route-level contracts for the system endpoints.

Exercises the REST surface mounted by ``register_system_routes``:
``/live`` + ``/ready`` (VT-008 liveness/readiness split) and the hardened
``/correlation`` endpoint (VT-005: auth + per-IP rate limit + masked errors).

Each test drives the app through ``TestClient``. The default ``TestClient``
client host (``testclient``) and explicit ``127.0.0.1`` are treated as loopback
callers, so ``require_auth`` passes without a configured API key; a non-loopback
client with a configured key is used to prove the auth gate rejects.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import api_server
from src.api import system_routes


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def local_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Loopback client with no API key configured (dev-mode: auth passes)."""
    monkeypatch.delenv("API_AUTH_KEY", raising=False)
    monkeypatch.setattr(api_server, "_API_KEY", "")
    return TestClient(api_server.app, client=("127.0.0.1", 50000))


@pytest.fixture(autouse=True)
def _reset_correlation_limiter() -> None:
    """Clear the module-level rate limiter so tests never leak hits into each other."""
    system_routes._correlation_rate_limiter.reset()


# ---------------------------------------------------------------------------
# VT-008 — /live, /health alias, /ready
# ---------------------------------------------------------------------------


def test_live_returns_healthy(local_client: TestClient):
    resp = local_client.get("/live")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "healthy"
    assert body["service"] == "Vibe-Trading API"


def test_health_is_backward_compatible_alias(local_client: TestClient):
    resp = local_client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "healthy"


def test_ready_returns_200_when_provider_ready(
    local_client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(system_routes, "_provider_readiness", lambda: (True, "ready"))
    resp = local_client.get("/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ready"
    assert body["service"] == "Vibe-Trading API"


def test_ready_returns_503_when_provider_not_ready(
    local_client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        system_routes,
        "_provider_readiness",
        lambda: (False, "LLM provider not configured"),
    )
    resp = local_client.get("/ready")
    assert resp.status_code == 503
    assert resp.json()["detail"] == "LLM provider not configured"


def test_readiness_helper_real_missing_credential(monkeypatch: pytest.MonkeyPatch):
    """The un-mocked helper flags a configured provider with no credential."""
    import src.providers.llm as llm
    from src.config.accessor import reset_env_config

    # Neutralize the .env reload inside _sync_provider_env so the test fully
    # controls the environment (otherwise a machine-local OPENAI_API_KEY leaks in).
    monkeypatch.setattr(llm, "_ensure_dotenv", lambda: None)
    monkeypatch.setenv("LANGCHAIN_PROVIDER", "openai")
    monkeypatch.setenv("LANGCHAIN_MODEL_NAME", "gpt-4o-mini")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    reset_env_config()

    ready, reason = system_routes._provider_readiness()
    assert ready is False
    assert "credential" in reason.lower()


def test_readiness_helper_real_ready(monkeypatch: pytest.MonkeyPatch):
    """The un-mocked helper reports ready when provider+model+key are present."""
    from src.config.accessor import reset_env_config

    monkeypatch.setenv("LANGCHAIN_PROVIDER", "openai")
    monkeypatch.setenv("LANGCHAIN_MODEL_NAME", "gpt-4o-mini")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key")
    reset_env_config()

    ready, reason = system_routes._provider_readiness()
    assert ready is True
    assert reason == "ready"


def test_readiness_helper_missing_provider(monkeypatch: pytest.MonkeyPatch):
    from src.config.accessor import reset_env_config

    monkeypatch.setenv("LANGCHAIN_PROVIDER", "")
    monkeypatch.setenv("LANGCHAIN_MODEL_NAME", "")
    reset_env_config()

    ready, reason = system_routes._provider_readiness()
    assert ready is False
    assert "provider" in reason.lower()


# ---------------------------------------------------------------------------
# VT-005 — /correlation auth + rate limit + error masking
# ---------------------------------------------------------------------------


def test_correlation_requires_auth_for_remote_client(monkeypatch: pytest.MonkeyPatch):
    """A non-loopback caller with a configured key but no token is rejected."""
    monkeypatch.setattr(api_server, "_API_KEY", "server-secret")
    remote = TestClient(api_server.app, client=("203.0.113.9", 51000))
    resp = remote.get("/correlation", params={"codes": "AAPL,SPY"})
    assert resp.status_code == 401


def test_correlation_allows_local_and_masks_generic_error(
    local_client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    """A generic backend failure must not leak its exception text to the client."""
    import backtest.correlation as corr

    def _boom(**_kwargs):
        raise RuntimeError("sensitive internal detail: db=prod host=10.0.0.5")

    monkeypatch.setattr(corr, "compute_correlation_matrix", _boom)
    resp = local_client.get("/correlation", params={"codes": "AAPL,SPY"})
    assert resp.status_code == 500
    detail = resp.json()["detail"]
    assert detail == "Correlation computation failed"
    assert "sensitive internal detail" not in detail


def test_correlation_value_error_still_surfaces_message(
    local_client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    """Hand-raised validation errors remain user-facing (unchanged behavior)."""
    import backtest.correlation as corr

    def _bad(**_kwargs):
        raise ValueError("Not enough overlapping history")

    monkeypatch.setattr(corr, "compute_correlation_matrix", _bad)
    resp = local_client.get("/correlation", params={"codes": "AAPL,SPY"})
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Not enough overlapping history"


def test_correlation_rate_limit_returns_429(
    local_client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    """Exceeding the per-client window yields 429 with a generic message."""
    import backtest.correlation as corr

    monkeypatch.setattr(
        corr,
        "compute_correlation_matrix",
        lambda **_kwargs: {"labels": ["AAPL", "SPY"], "matrix": [[1.0, 0.5], [0.5, 1.0]]},
    )
    # Tighten the limiter to make the boundary cheap and deterministic.
    monkeypatch.setattr(
        system_routes,
        "_correlation_rate_limiter",
        system_routes._SlidingWindowRateLimiter(max_requests=2, window_seconds=60.0),
    )

    ok1 = local_client.get("/correlation", params={"codes": "AAPL,SPY"})
    ok2 = local_client.get("/correlation", params={"codes": "AAPL,SPY"})
    blocked = local_client.get("/correlation", params={"codes": "AAPL,SPY"})

    assert ok1.status_code == 200
    assert ok2.status_code == 200
    assert blocked.status_code == 429
    assert blocked.json()["detail"] == "Rate limit exceeded, try again later"


def test_correlation_rate_limiter_is_per_client(monkeypatch: pytest.MonkeyPatch):
    """Distinct client IPs get independent budgets."""
    limiter = system_routes._SlidingWindowRateLimiter(max_requests=1, window_seconds=60.0)
    assert limiter.allow("1.1.1.1") is True
    assert limiter.allow("1.1.1.1") is False
    assert limiter.allow("2.2.2.2") is True
