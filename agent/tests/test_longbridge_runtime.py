"""Tests for Longbridge transport-neutral connector runtime status.

Task 3: extends the live-trading runtime to surface Longbridge broker_sdk
profiles through the profile registry (not a hard-coded broker list), adds a
read-only idempotent ``POST /live/connectors/{profile_id}/verify`` endpoint,
and a bounded 15-second credential-free cache with fake-clock and force-bypass
coverage.

All tests run against stubs — no network, no real broker SDKs, no raw
credential/broker exception leakage.
"""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import api_server

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _client(tmp_path: Path, monkeypatch) -> TestClient:
    """Build a TestClient with runtime root redirected under tmp_path."""
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path), raising=False)
    monkeypatch.setattr(api_server, "_runner_tasks", {}, raising=False)
    monkeypatch.setattr(api_server, "_runner_factory", None, raising=False)
    # Reset the connector verify cache between tests
    api_server._connector_verify_cache.clear()
    return TestClient(api_server.app, client=("127.0.0.1", 50001))


# ---------------------------------------------------------------------------
# GET /live/status — Longbridge profiles via the registry
# ---------------------------------------------------------------------------


def test_live_status_includes_longbridge_sdk_profile(tmp_path: Path, monkeypatch) -> None:
    """Longbridge live-sdk-readonly appears in /live/status via the profile registry."""
    client = _client(tmp_path, monkeypatch)

    response = client.get("/live/status")

    assert response.status_code == 200
    brokers = {b["auth"]["broker"]: b for b in response.json()["brokers"]}
    assert "longbridge" in brokers
    lb = brokers["longbridge"]
    # Longbridge is a broker_sdk transport — no oauth_token_present, no mandate, runner dead.
    # broker_sdk connectors are NOT in LIVE_BROKER_SERVER_KEYS, so is_live_broker=False
    # (they don't use the OAuth/mandate path).
    assert lb["auth"]["is_live_broker"] is False
    assert lb["mandate"] is None
    assert lb["runner"]["alive"] is False
    assert lb["halted"] is False
    # Transport-neutral fields should be present.
    assert "transport" in lb["auth"]
    assert lb["auth"]["transport"] == "broker_sdk"


def test_longbridge_missing_credentials_maps_not_configured(
    tmp_path: Path, monkeypatch
) -> None:
    """When Longbridge SDK reports no credentials, status shows not_configured."""
    client = _client(tmp_path, monkeypatch)

    # Stub check_connection to return a not-configured report
    monkeypatch.setattr(
        api_server,
        "_check_connector_status",
        lambda profile_id, force=False: {
            "status": "error",
            "configured": False,
            "connection_state": "not_configured",
            "error": "Longbridge connector not configured: missing app_key.",
            "connector": "longbridge",
            "transport": "broker_sdk",
            "profile_id": "longbridge-live-sdk-readonly",
        },
    )

    response = client.get("/live/status", params={"broker": "longbridge"})

    assert response.status_code == 200
    lb = response.json()["brokers"][0]
    assert lb["auth"]["broker"] == "longbridge"
    # The connector verify status should be surfaced.
    assert lb["auth"]["transport"] == "broker_sdk"
    assert lb["auth"]["connection_state"] == "not_configured"


def test_longbridge_valid_check_maps_connected(tmp_path: Path, monkeypatch) -> None:
    """When Longbridge SDK reports ok, status shows connected."""
    client = _client(tmp_path, monkeypatch)

    monkeypatch.setattr(
        api_server,
        "_check_connector_status",
        lambda profile_id, force=False: {
            "status": "ok",
            "configured": True,
            "connection_state": "connected",
            "error": None,
            "connector": "longbridge",
            "transport": "broker_sdk",
            "profile_id": "longbridge-live-sdk-readonly",
            "sdk": {"package": "longbridge", "installed": True},
            "paper_guard": "config_declared",
        },
    )

    response = client.get("/live/status", params={"broker": "longbridge"})

    assert response.status_code == 200
    lb = response.json()["brokers"][0]
    assert lb["auth"]["connection_state"] == "connected"
    assert lb["auth"]["oauth_token_present"] is False
    assert lb["auth"]["profile_id"] == "longbridge-live-sdk-readonly"
    assert lb["auth"]["sdk_installed"] is True
    assert lb["auth"]["environment_identity"] == "config_declared"
    assert lb["auth"]["capabilities"] == [
        "account.read",
        "positions.read",
        "orders.read",
        "quotes.read",
        "history.read",
    ]
    assert lb["auth"]["readonly"] is True


def test_live_status_propagates_only_sanitized_sdk_metadata(
    tmp_path: Path, monkeypatch
) -> None:
    """Live status exposes the explicit SDK metadata allowlist and no secrets."""
    client = _client(tmp_path, monkeypatch)
    sentinels = {
        "app_key": "SENTINEL_APP_KEY",
        "app_secret": "SENTINEL_APP_SECRET",
        "access_token": "SENTINEL_ACCESS_TOKEN",
    }

    monkeypatch.setattr(
        api_server,
        "_check_connector_status",
        lambda profile_id, force=False: {
            "status": "ok",
            "profile_id": profile_id,
            "configured": True,
            "credential_source": "environment",
            "sdk_installed": True,
            "sdk": {"package": "longbridge", "installed": True},
            "environment_identity": "config_declared_live",
            "capabilities": [
                "account.read",
                "positions.read",
                "orders.read",
                "quotes.read",
                "history.read",
            ],
            "readonly": True,
            "last_checked_at": "2026-07-16T12:34:56Z",
            "error_code": None,
            "connection_state": "connected",
            "config": sentinels,
            "app_key": sentinels["app_key"],
            "exception": f"raw SDK failure: {sentinels['access_token']}",
        },
    )

    response = client.get("/live/status", params={"broker": "longbridge"})

    assert response.status_code == 200
    auth = response.json()["brokers"][0]["auth"]
    assert auth == {
        "broker": "longbridge",
        "oauth_token_present": False,
        "is_live_broker": False,
        "transport": "broker_sdk",
        "connection_state": "connected",
        "profile_id": "longbridge-live-sdk-readonly",
        "configured": True,
        "credential_source": "environment",
        "sdk_installed": True,
        "environment_identity": "config_declared_live",
        "capabilities": [
            "account.read",
            "positions.read",
            "orders.read",
            "quotes.read",
            "history.read",
        ],
        "readonly": True,
        "last_checked_at": "2026-07-16T12:34:56Z",
        "error_code": None,
    }
    serialized = response.text
    assert "config" not in auth
    assert "app_key" not in auth
    assert "exception" not in auth
    assert all(secret not in serialized for secret in sentinels.values())


def test_live_status_suppresses_secrets_in_allowlisted_text_metadata(
    tmp_path: Path, monkeypatch
) -> None:
    """Report-controlled text/list fields cannot reflect secrets or raw errors."""
    client = _client(tmp_path, monkeypatch)
    sentinels = {
        "configured": "raw SDK failure: SENTINEL_SECRET_IN_CONFIGURED",
        "credential_source": "SENTINEL_APP_SECRET_IN_CREDENTIAL_SOURCE",
        "sdk_installed": "raw SDK failure: SENTINEL_SECRET_IN_SDK_INSTALLED",
        "sdk_nested_installed": "SENTINEL_SECRET_IN_NESTED_SDK_INSTALLED",
        "environment_identity": "SENTINEL_ACCESS_TOKEN_IN_ENVIRONMENT_IDENTITY",
        "paper_guard": "raw SDK failure: SENTINEL_APP_KEY_IN_PAPER_GUARD",
        "capabilities": "SENTINEL_ACCESS_TOKEN_IN_CAPABILITY",
        "readonly": "raw SDK failure: SENTINEL_SECRET_IN_READONLY",
        "last_checked_at": "raw SDK failure: SENTINEL_SECRET_IN_TIMESTAMP",
        "error_code": "raw SDK failure: SENTINEL_SECRET_IN_ERROR_CODE",
        "connection_state": "raw SDK failure: SENTINEL_SECRET_IN_CONNECTION_STATE",
    }

    monkeypatch.setattr(
        api_server,
        "_check_connector_status",
        lambda profile_id, force=False: {
            "profile_id": profile_id,
            "configured": sentinels["configured"],
            "credential_source": sentinels["credential_source"],
            "sdk_installed": sentinels["sdk_installed"],
            "sdk": {"installed": sentinels["sdk_nested_installed"]},
            "environment_identity": sentinels["environment_identity"],
            "paper_guard": sentinels["paper_guard"],
            "capabilities": ["account.read", sentinels["capabilities"]],
            "readonly": sentinels["readonly"],
            "last_checked_at": sentinels["last_checked_at"],
            "error_code": sentinels["error_code"],
            "connection_state": sentinels["connection_state"],
        },
    )

    response = client.get("/live/status", params={"broker": "longbridge"})

    assert response.status_code == 200
    auth = response.json()["brokers"][0]["auth"]
    assert auth["configured"] is None
    assert auth["credential_source"] is None
    assert auth["sdk_installed"] is None
    assert auth["environment_identity"] is None
    assert auth["capabilities"] == [
        "account.read",
        "positions.read",
        "orders.read",
        "quotes.read",
        "history.read",
    ]
    assert auth["last_checked_at"] is None
    assert auth["error_code"] is None
    assert auth["connection_state"] is None
    assert all(value not in response.text for value in sentinels.values())


def test_live_status_uses_registry_profile_id(tmp_path: Path, monkeypatch) -> None:
    """Status verifies the selected registry profile, never a derived id."""
    client = _client(tmp_path, monkeypatch)
    registry_profile = SimpleNamespace(
        id="longbridge-production-custom-readonly",
        connector="longbridge",
        environment="live",
        transport="broker_sdk",
        capabilities=("account.read",),
        readonly=True,
    )
    monkeypatch.setattr(
        "src.trading.profiles.list_profiles", lambda: [registry_profile]
    )
    checked_profiles: list[str] = []

    def _check_status(profile_id: str, force: bool = False):
        checked_profiles.append(profile_id)
        return {
            "profile_id": profile_id,
            "connection_state": "connected",
        }

    monkeypatch.setattr(api_server, "_check_connector_status", _check_status)

    response = client.get("/live/status", params={"broker": "longbridge"})

    assert response.status_code == 200
    assert checked_profiles == [registry_profile.id]
    assert response.json()["brokers"][0]["auth"]["profile_id"] == registry_profile.id


def test_live_status_accepts_known_metadata_values_and_canonicalizes_timestamp(
    tmp_path: Path, monkeypatch
) -> None:
    """Closed-vocabulary Longbridge metadata and valid UTC timestamps pass."""
    client = _client(tmp_path, monkeypatch)

    monkeypatch.setattr(
        api_server,
        "_check_connector_status",
        lambda profile_id, force=False: {
            "profile_id": profile_id,
            "configured": False,
            "credential_source": "runtime_file",
            "sdk_installed": False,
            "environment_identity": "config_declared",
            "capabilities": ["orders.place"],
            "readonly": False,
            "last_checked_at": "2026-07-16T12:34:56+00:00",
            "error_code": "credentials_partial",
            "connection_state": "error",
        },
    )

    response = client.get("/live/status", params={"broker": "longbridge"})

    assert response.status_code == 200
    auth = response.json()["brokers"][0]["auth"]
    assert auth["configured"] is False
    assert auth["credential_source"] == "runtime_file"
    assert auth["sdk_installed"] is False
    assert auth["environment_identity"] == "config_declared"
    assert auth["capabilities"] == [
        "account.read",
        "positions.read",
        "orders.read",
        "quotes.read",
        "history.read",
    ]
    assert auth["readonly"] is True
    assert auth["last_checked_at"] == "2026-07-16T12:34:56Z"
    assert auth["error_code"] == "credentials_partial"
    assert auth["connection_state"] == "error"


@pytest.mark.parametrize(
    ("error_code", "connection_state"),
    [
        ("credentials_missing", "not_configured"),
        ("credentials_conflict", "error"),
        ("sdk_missing", "error"),
        ("authentication_failed", "error"),
        ("network_unreachable", "error"),
        ("broker_error", "error"),
    ],
)
def test_live_status_accepts_known_longbridge_error_codes(
    tmp_path: Path,
    monkeypatch,
    error_code: str,
    connection_state: str,
) -> None:
    """Every stable Longbridge diagnostic code survives closed-vocabulary mapping."""
    client = _client(tmp_path, monkeypatch)
    monkeypatch.setattr(
        api_server,
        "_check_connector_status",
        lambda profile_id, force=False: {
            "profile_id": profile_id,
            "error_code": error_code,
            "connection_state": connection_state,
        },
    )

    response = client.get("/live/status", params={"broker": "longbridge"})

    assert response.status_code == 200
    auth = response.json()["brokers"][0]["auth"]
    assert auth["error_code"] == error_code
    assert auth["connection_state"] == connection_state


def test_live_status_normalizes_same_profile_malformed_metadata(
    tmp_path: Path, monkeypatch
) -> None:
    """Malformed same-profile values are suppressed without response failure."""
    client = _client(tmp_path, monkeypatch)

    monkeypatch.setattr(
        api_server,
        "_check_connector_status",
        lambda profile_id, force=False: {
            "profile_id": profile_id,
            "configured": "true",
            "credential_source": ["environment"],
            "sdk_installed": {"installed": True},
            "sdk": {"installed": "yes"},
            "environment_identity": {"kind": "config_declared"},
            "paper_guard": ["config_declared"],
            "capabilities": {"account.read": True},
            "readonly": "true",
            "last_checked_at": "not-a-timestamp",
            "error_code": ["authentication_failed"],
            "connection_state": {"state": "connected"},
        },
    )

    response = client.get("/live/status", params={"broker": "longbridge"})

    assert response.status_code == 200
    auth = response.json()["brokers"][0]["auth"]
    assert auth["profile_id"] == "longbridge-live-sdk-readonly"
    assert auth["configured"] is None
    assert auth["credential_source"] is None
    assert auth["sdk_installed"] is None
    assert auth["environment_identity"] is None
    assert auth["capabilities"] == [
        "account.read",
        "positions.read",
        "orders.read",
        "quotes.read",
        "history.read",
    ]
    assert auth["readonly"] is True
    assert auth["last_checked_at"] is None
    assert auth["error_code"] is None
    assert auth["connection_state"] is None


def test_live_status_suppresses_unrepresentable_timestamp_only(
    tmp_path: Path, monkeypatch
) -> None:
    """UTC conversion overflow cannot discard otherwise valid safe metadata."""
    client = _client(tmp_path, monkeypatch)

    monkeypatch.setattr(
        api_server,
        "_check_connector_status",
        lambda profile_id, force=False: {
            "profile_id": profile_id,
            "configured": True,
            "credential_source": "environment",
            "sdk_installed": True,
            "environment_identity": "config_declared",
            "last_checked_at": "0001-01-01T00:00:00+23:59",
            "error_code": None,
            "connection_state": "connected",
        },
    )

    response = client.get("/live/status", params={"broker": "longbridge"})

    assert response.status_code == 200
    auth = response.json()["brokers"][0]["auth"]
    assert auth["configured"] is True
    assert auth["credential_source"] == "environment"
    assert auth["sdk_installed"] is True
    assert auth["environment_identity"] == "config_declared"
    assert auth["last_checked_at"] is None
    assert auth["connection_state"] == "connected"


def test_live_status_normalizes_null_permission_metadata_from_safe_registry_profile(
    tmp_path: Path, monkeypatch
) -> None:
    """Null report permissions fall back to a complete typed registry declaration."""
    client = _client(tmp_path, monkeypatch)
    registry_profile = SimpleNamespace(
        id="longbridge-production-custom-readonly",
        connector="longbridge",
        environment="live",
        transport="broker_sdk",
        capabilities=("account.read", "positions.read"),
        readonly=True,
    )
    monkeypatch.setattr(
        "src.trading.profiles.list_profiles", lambda: [registry_profile]
    )
    monkeypatch.setattr(
        api_server,
        "_check_connector_status",
        lambda profile_id, force=False: {
            "profile_id": profile_id,
            "configured": True,
            "connection_state": "connected",
            "capabilities": None,
            "readonly": None,
        },
    )

    response = client.get("/live/status", params={"broker": "longbridge"})

    assert response.status_code == 200
    auth = response.json()["brokers"][0]["auth"]
    assert auth["capabilities"] == ["account.read", "positions.read"]
    assert auth["readonly"] is True


def test_live_status_does_not_assert_readonly_without_complete_safe_capabilities(
    tmp_path: Path, monkeypatch
) -> None:
    """Malformed report and registry capabilities keep the permission claim unknown."""
    client = _client(tmp_path, monkeypatch)
    registry_profile = SimpleNamespace(
        id="longbridge-production-custom-readonly",
        connector="longbridge",
        environment="live",
        transport="broker_sdk",
        capabilities=(),
        readonly=True,
    )
    monkeypatch.setattr(
        "src.trading.profiles.list_profiles", lambda: [registry_profile]
    )
    monkeypatch.setattr(
        api_server,
        "_check_connector_status",
        lambda profile_id, force=False: {
            "profile_id": profile_id,
            "configured": True,
            "connection_state": "connected",
            "capabilities": {"account.read": True},
            "readonly": "true",
        },
    )

    response = client.get("/live/status", params={"broker": "longbridge"})

    assert response.status_code == 200
    auth = response.json()["brokers"][0]["auth"]
    assert auth["capabilities"] is None
    assert auth["readonly"] is None


def test_live_status_metadata_fallbacks_require_matching_profile(
    tmp_path: Path, monkeypatch
) -> None:
    """Registry metadata stays fail-closed when verify identifies another profile."""
    client = _client(tmp_path, monkeypatch)

    profile_id_sentinel = "raw SDK failure: SENTINEL_SECRET_IN_PROFILE_ID"
    monkeypatch.setattr(
        api_server,
        "_check_connector_status",
        lambda profile_id, force=False: {
            "status": "ok",
            "profile_id": profile_id_sentinel,
            "configured": True,
            "connection_state": "connected",
            "credential_source": "environment",
            "sdk_installed": True,
            "environment_identity": "config_declared_live",
            "capabilities": ["orders.place"],
            "readonly": False,
            "last_checked_at": "2026-07-16T12:34:56Z",
            "error_code": "authentication_failed",
        },
    )

    response = client.get("/live/status", params={"broker": "longbridge"})

    assert response.status_code == 200
    auth = response.json()["brokers"][0]["auth"]
    for field in (
        "profile_id",
        "configured",
        "connection_state",
        "credential_source",
        "sdk_installed",
        "environment_identity",
        "capabilities",
        "readonly",
        "last_checked_at",
        "error_code",
    ):
        assert auth[field] is None
    assert profile_id_sentinel not in response.text


# ---------------------------------------------------------------------------
# POST /live/connectors/{profile_id}/verify — read-only, idempotent
# ---------------------------------------------------------------------------


def test_verify_endpoint_is_readonly_and_idempotent(tmp_path: Path, monkeypatch) -> None:
    """Verify is read-only (GET-like safety), idempotent, and never needs a mandate."""
    client = _client(tmp_path, monkeypatch)

    # Two calls with the same profile return the same result
    payload = {"profile_id": "longbridge-live-sdk-readonly"}

    monkeypatch.setattr(
        api_server,
        "_check_connector_status",
        lambda profile_id, force=False: {
            "status": "ok",
            "configured": True,
            "connection_state": "connected",
            "error": None,
            "connector": "longbridge",
            "transport": "broker_sdk",
            "profile_id": profile_id,
        },
    )

    r1 = client.post("/live/connectors/longbridge-live-sdk-readonly/verify")
    r2 = client.post("/live/connectors/longbridge-live-sdk-readonly/verify")

    assert r1.status_code == 200
    assert r2.status_code == 200
    body1 = r1.json()
    body2 = r2.json()
    # Idempotent: same status, no side effects
    assert body1["status"] == body2["status"]
    assert body1["connection_state"] == body2["connection_state"]


def test_verify_rejects_non_live_and_remote_mcp_profiles(tmp_path: Path, monkeypatch) -> None:
    """Verify must reject paper profiles, remote_mcp live profiles, and unknown IDs
    with the correct HTTP status *before* calling check_connection.

    Rejected profiles:
      - ``longbridge-paper-sdk``: environment=paper → 400
      - ``robinhood-live-mcp``: transport=remote_mcp → 400
      - ``unknown-profile-id``: not in registry → 404

    The underlying ``check_connection`` must NEVER be called for any rejected profile.
    """
    client = _client(tmp_path, monkeypatch)
    check_calls: list[str] = []

    def _spy_check_connection(profile_id, **kwargs):
        check_calls.append(profile_id)
        return {
            "status": "ok",
            "configured": True,
            "connection_state": "connected",
            "error": None,
            "connector": "longbridge",
            "transport": "broker_sdk",
            "profile_id": profile_id,
        }

    monkeypatch.setattr("src.trading.service.check_connection", _spy_check_connection)

    # Paper profile → 400 (environment != live)
    r_paper = client.post("/live/connectors/longbridge-paper-sdk/verify")
    assert r_paper.status_code == 400
    assert "not a live profile" in r_paper.json()["detail"].lower()

    # Remote MCP live profile → 400 (transport != broker_sdk)
    r_mcp = client.post("/live/connectors/robinhood-live-mcp/verify")
    assert r_mcp.status_code == 400
    assert "broker_sdk" in r_mcp.json()["detail"].lower()

    # Unknown profile → 404
    r_unknown = client.post("/live/connectors/unknown-profile-id/verify")
    assert r_unknown.status_code == 404
    assert "unknown" in r_unknown.json()["detail"].lower()

    # check_connection must NOT have been called for any rejected profile
    assert check_calls == [], (
        f"check_connection was called for rejected profiles: {check_calls}"
    )


# ---------------------------------------------------------------------------
# Verify: credential-free cache with fake clock
# ---------------------------------------------------------------------------


def test_verify_cache_hit_and_expiry(tmp_path: Path, monkeypatch) -> None:
    """Cache returns same result within 15s window; expires after."""
    client = _client(tmp_path, monkeypatch)
    call_count = {"n": 0}

    def _stub_check_connection(profile_id, **kwargs):
        call_count["n"] += 1
        return {
            "status": "ok",
            "configured": True,
            "connection_state": "connected",
            "error": None,
            "connector": "longbridge",
            "transport": "broker_sdk",
            "profile_id": profile_id,
        }

    monkeypatch.setattr("src.trading.service.check_connection", _stub_check_connection)

    # First call — cache miss
    r1 = client.post("/live/connectors/longbridge-live-sdk-readonly/verify")
    assert r1.status_code == 200
    assert call_count["n"] == 1

    # Second call — cache hit (no new check_connection call)
    r2 = client.post("/live/connectors/longbridge-live-sdk-readonly/verify")
    assert r2.status_code == 200
    assert call_count["n"] == 1  # still 1

    # Simulate time advancing past 15s TTL
    api_server._connector_verify_cache._clock = lambda: time.time() + 20

    r3 = client.post("/live/connectors/longbridge-live-sdk-readonly/verify")
    assert r3.status_code == 200
    assert call_count["n"] == 2  # cache expired, new call


def test_verify_force_bypass_cache(tmp_path: Path, monkeypatch) -> None:
    """force=True bypasses the cache and forces a fresh check."""
    client = _client(tmp_path, monkeypatch)
    call_count = {"n": 0}

    def _stub_check_connection(profile_id, **kwargs):
        call_count["n"] += 1
        return {
            "status": "ok",
            "configured": True,
            "connection_state": "connected",
            "error": None,
            "connector": "longbridge",
            "transport": "broker_sdk",
            "profile_id": profile_id,
        }

    monkeypatch.setattr("src.trading.service.check_connection", _stub_check_connection)

    # First call
    r1 = client.post("/live/connectors/longbridge-live-sdk-readonly/verify")
    assert call_count["n"] == 1

    # force=True bypasses cache
    r2 = client.post("/live/connectors/longbridge-live-sdk-readonly/verify?force=true")
    assert call_count["n"] == 2
    assert r2.status_code == 200


# ---------------------------------------------------------------------------
# Backward compatibility: Robinhood OAuth fields remain
# ---------------------------------------------------------------------------


def test_live_status_selects_readonly_sdk_profile_independent_of_registry_order(
    tmp_path: Path, monkeypatch
) -> None:
    """A live readonly SDK profile wins deterministically over a trading profile."""
    client = _client(tmp_path, monkeypatch)
    profiles = [
        SimpleNamespace(
            id="longbridge-live-trade-readonly",
            connector="longbridge",
            environment="live",
            transport="broker_sdk",
            capabilities=("account.read", "orders.place.requires_mandate"),
            readonly=False,
        ),
        SimpleNamespace(
            id="longbridge-live-observer",
            connector="longbridge",
            environment="live",
            transport="broker_sdk",
            capabilities=("account.read",),
            readonly=True,
        ),
    ]
    monkeypatch.setattr("src.trading.profiles.list_profiles", lambda: profiles)
    checked_profiles: list[str] = []

    def _check_status(profile_id: str, force: bool = False):
        checked_profiles.append(profile_id)
        return {"profile_id": profile_id, "connection_state": "connected"}

    monkeypatch.setattr(api_server, "_check_connector_status", _check_status)

    response = client.get("/live/status", params={"broker": "longbridge"})

    assert response.status_code == 200
    assert checked_profiles == ["longbridge-live-observer"]
    assert response.json()["brokers"][0]["auth"]["readonly"] is True


def test_live_status_prefers_unique_suffixed_declared_readonly_profile(
    tmp_path: Path, monkeypatch
) -> None:
    """One canonical -readonly profile wins over another declared observer profile."""
    client = _client(tmp_path, monkeypatch)
    profiles = [
        SimpleNamespace(
            id="longbridge-live-observer",
            connector="longbridge",
            environment="live",
            transport="broker_sdk",
            capabilities=("positions.read",),
            readonly=True,
        ),
        SimpleNamespace(
            id="longbridge-live-sdk-readonly",
            connector="longbridge",
            environment="live",
            transport="broker_sdk",
            capabilities=("account.read",),
            readonly=True,
        ),
    ]
    monkeypatch.setattr("src.trading.profiles.list_profiles", lambda: profiles)
    checked_profiles: list[str] = []

    def _check_status(profile_id: str, force: bool = False):
        checked_profiles.append(profile_id)
        return {"profile_id": profile_id, "connection_state": "connected"}

    monkeypatch.setattr(api_server, "_check_connector_status", _check_status)

    response = client.get("/live/status", params={"broker": "longbridge"})

    assert response.status_code == 200
    assert checked_profiles == ["longbridge-live-sdk-readonly"]
    assert response.json()["brokers"][0]["auth"]["capabilities"] == ["account.read"]


def test_live_status_rejects_malformed_registry_profile_id(
    tmp_path: Path, monkeypatch
) -> None:
    """A non-string trusted-registry profile ID fails closed without verification."""
    client = _client(tmp_path, monkeypatch)
    malformed_profile = SimpleNamespace(
        id=123,
        connector="longbridge",
        environment="live",
        transport="broker_sdk",
        capabilities=("account.read",),
        readonly=True,
    )
    monkeypatch.setattr(
        "src.trading.profiles.list_profiles", lambda: [malformed_profile]
    )
    checked_profiles: list[object] = []
    monkeypatch.setattr(
        api_server,
        "_check_connector_status",
        lambda profile_id, force=False: checked_profiles.append(profile_id) or {},
    )

    response = client.get("/live/status", params={"broker": "longbridge"})

    assert response.status_code == 200
    assert checked_profiles == []
    auth = response.json()["brokers"][0]["auth"]
    assert auth["transport"] == "broker_sdk"
    assert auth["profile_id"] is None
    assert auth["capabilities"] is None
    assert auth["readonly"] is None


def test_live_status_rejects_ambiguous_readonly_sdk_profiles(
    tmp_path: Path, monkeypatch
) -> None:
    """Multiple live SDK readonly profiles fail closed without verifying either."""
    client = _client(tmp_path, monkeypatch)
    profiles = [
        SimpleNamespace(
            id="longbridge-live-alpha-observer",
            connector="longbridge",
            environment="live",
            transport="broker_sdk",
            capabilities=("account.read",),
            readonly=True,
        ),
        SimpleNamespace(
            id="longbridge-live-beta-observer",
            connector="longbridge",
            environment="live",
            transport="broker_sdk",
            capabilities=("positions.read",),
            readonly=True,
        ),
    ]
    monkeypatch.setattr("src.trading.profiles.list_profiles", lambda: profiles)
    checked_profiles: list[str] = []
    monkeypatch.setattr(
        api_server,
        "_check_connector_status",
        lambda profile_id, force=False: checked_profiles.append(profile_id) or {},
    )

    response = client.get("/live/status", params={"broker": "longbridge"})

    assert response.status_code == 200
    assert checked_profiles == []
    auth = response.json()["brokers"][0]["auth"]
    assert auth["transport"] == "broker_sdk"
    for field in (
        "profile_id",
        "configured",
        "connection_state",
        "credential_source",
        "sdk_installed",
        "environment_identity",
        "capabilities",
        "readonly",
        "last_checked_at",
        "error_code",
    ):
        assert auth[field] is None


def test_live_status_preserves_first_transport_for_multi_profile_non_sdk_broker(
    tmp_path: Path, monkeypatch
) -> None:
    """IBKR keeps its first live transport while SDK selection scans independently."""
    client = _client(tmp_path, monkeypatch)
    profiles = [
        SimpleNamespace(
            id="ibkr-live-local-readonly",
            connector="ibkr",
            environment="live",
            transport="local_tws",
            capabilities=("account.read",),
            readonly=True,
        ),
        SimpleNamespace(
            id="ibkr-live-official-mcp-readonly",
            connector="ibkr",
            environment="live",
            transport="remote_mcp",
            capabilities=("mcp.read.discovery",),
            readonly=True,
        ),
    ]
    monkeypatch.setattr("src.trading.profiles.list_profiles", lambda: profiles)

    response = client.get("/live/status", params={"broker": "ibkr"})

    assert response.status_code == 200
    assert response.json()["brokers"][0]["auth"]["transport"] == "local_tws"


def test_existing_robinhood_oauth_fields_remain_compatible(
    tmp_path: Path, monkeypatch
) -> None:
    """Robinhood status still exposes oauth_token_present — no regression."""
    client = _client(tmp_path, monkeypatch)

    response = client.get("/live/status", params={"broker": "robinhood"})

    assert response.status_code == 200
    rh = response.json()["brokers"][0]
    assert rh["auth"]["broker"] == "robinhood"
    assert rh["auth"]["oauth_token_present"] is False
    assert rh["auth"]["is_live_broker"] is True
    # transport field should also be present now
    assert "transport" in rh["auth"]
    # Robinhood is remote_mcp, not broker_sdk
    assert rh["auth"]["transport"] == "remote_mcp"


# ---------------------------------------------------------------------------
# Longbridge verify never needs a mandate, runner is unavailable
# ---------------------------------------------------------------------------


def test_longbridge_verify_never_needs_mandate_and_runner_unavailable(
    tmp_path: Path, monkeypatch
) -> None:
    """Longbridge verify is read-only; no mandate required, runner is unavailable."""
    client = _client(tmp_path, monkeypatch)

    # Verify call succeeds without any mandate
    r = client.post("/live/connectors/longbridge-live-sdk-readonly/verify")
    # It may fail because _check_connector_status is not yet implemented (RED phase)
    # or return an error status — but it must NOT return 409 (mandate required)
    assert r.status_code != 409

    # Runner start must fail for longbridge
    r2 = client.post("/live/runner/start", json={"broker": "longbridge"})
    assert r2.status_code == 400
    assert "runner" in r2.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Cache contains no credentials (structural check)
# ---------------------------------------------------------------------------


def test_cache_contains_no_credentials(tmp_path: Path, monkeypatch) -> None:
    """The verify cache entry must never store credential material.

    Patches the underlying ``src.trading.service.check_connection`` so the
    real cache wrapper (``_ConnectorVerifyCache``) is exercised, NOT the
    top-level ``_check_connector_status`` function (which would bypass the
    cache entirely).
    """
    client = _client(tmp_path, monkeypatch)

    def _stub_check(profile_id, **kwargs):
        return {
            "status": "ok",
            "configured": True,
            "connection_state": "connected",
            "error": None,
            "connector": "longbridge",
            "transport": "broker_sdk",
            "profile_id": profile_id,
            "config": {"app_key": "FAKE***", "app_secret": "***redacted***"},
        }

    monkeypatch.setattr("src.trading.service.check_connection", _stub_check)

    client.post("/live/connectors/longbridge-live-sdk-readonly/verify")

    # Inspect the cache directly — must exercise the real cache wrapper
    cache_entry = api_server._connector_verify_cache.get("longbridge-live-sdk-readonly")
    assert cache_entry is not None
    serialized = str(cache_entry)
    assert "FAKE" not in serialized
    assert "redacted" not in serialized
    # Cache should only store status-level fields, not config details
    assert "app_key" not in serialized
    assert "app_secret" not in serialized
