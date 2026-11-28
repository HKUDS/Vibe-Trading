"""Exness connector config + signed HTTP client tests (synthetic, no network)."""

from __future__ import annotations

import json

import pytest

from src.config.accessor import reset_env_config
from src.trading.connectors.exness import _client
from src.trading.connectors.exness._client import (
    ExnessAPIError,
    ExnessClient,
    ExnessConfig,
    ExnessConfigError,
    build_config,
    credential_source,
    load_config,
    new_idempotency_key,
    public_config,
    save_config,
)
from tests.exness_fakes import (
    ACCESS_POINT,
    ACCOUNT,
    GATEWAY,
    RFC8032_HEX,
    FakeResponse,
    FakeTransport,
    discovery_route,
    make_config,
)

pytestmark = pytest.mark.unit

_SNAPSHOT = f"/v1/trading/accounts/{ACCOUNT}/snapshot"


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(_client, "get_runtime_root", lambda: tmp_path)
    for name in ("EXNESS_API_KEY", "EXNESS_PRIVATE_KEY", "EXNESS_ACCOUNT_ID", "EXNESS_GATEWAY_URL"):
        monkeypatch.delenv(name, raising=False)
    _client.reset_access_point_cache()
    yield
    _client.reset_access_point_cache()
    _client.set_client_factory(None)


# --- config -----------------------------------------------------------------


def test_default_profile_is_live_readonly_and_every_profile_is_live() -> None:
    cfg = ExnessConfig.from_mapping({})
    assert cfg.profile == "live-readonly"
    assert cfg.environment == "live"
    assert ExnessConfig.from_mapping({"profile": "live"}).environment == "live"


def test_paper_profile_is_rejected() -> None:
    with pytest.raises(ExnessConfigError, match="profile"):
        ExnessConfig.from_mapping({"profile": "paper"})


@pytest.mark.parametrize("bad", ["12a", "../1", "1/../2", "-5", "1 2"])
def test_account_id_must_be_numeric(bad: str) -> None:
    with pytest.raises(ExnessConfigError, match="account_id"):
        ExnessConfig.from_mapping({"account_id": bad})


def test_save_then_load_round_trips_with_owner_only_file(tmp_path) -> None:
    path = save_config(make_config())
    assert path == tmp_path / "exness.json"
    loaded = load_config()
    assert loaded.account_id == ACCOUNT and loaded.private_key == RFC8032_HEX


def test_env_overlays_file_values(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    (tmp_path / "exness.json").write_text(json.dumps({"api_key": "exnsk-file", "account_id": "1"}), encoding="utf-8")
    monkeypatch.setenv("EXNESS_API_KEY", "exnsk-env")
    reset_env_config()
    cfg = load_config()
    assert cfg.api_key == "exnsk-env"
    assert cfg.account_id == "1"
    assert credential_source() == "environment"


def test_invalid_json_file_raises_config_error(tmp_path) -> None:
    (tmp_path / "exness.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ExnessConfigError):
        load_config()


def test_build_config_applies_profile_and_drops_caller_overrides(tmp_path) -> None:
    save_config(make_config())
    cfg = build_config({"profile": "live"}, {"api_key": "exnsk-injected", "gateway_url": "https://evil.example"})
    assert cfg.profile == "live"
    assert cfg.api_key == "exnsk-synthetic-example"
    assert cfg.gateway_url == GATEWAY


def test_only_operation_wait_is_overridable_and_it_is_capped(tmp_path) -> None:
    save_config(make_config())
    cfg = build_config({"profile": "live"}, {"operation_wait_seconds": 3600, "deviation_points": 999,
                                             "private_key": "x"})
    assert cfg.operation_wait_seconds == _client.MAX_OPERATION_WAIT_SECONDS
    assert cfg.deviation_points == 10
    assert cfg.private_key == RFC8032_HEX


def test_public_config_never_contains_secret_values() -> None:
    cfg = make_config()
    rendered = json.dumps(public_config(cfg))
    assert "exnsk-synthetic-example" not in rendered
    assert RFC8032_HEX not in rendered
    assert ACCOUNT not in rendered
    assert public_config(cfg)["api_key_configured"] is True
    assert repr(cfg).count(RFC8032_HEX) == 0


def test_idempotency_key_format() -> None:
    key = new_idempotency_key()
    assert 5 <= len(key) <= 128
    assert all(ch.isalnum() or ch in "._-~" for ch in key)
    assert key != new_idempotency_key()


# --- host pinning -------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://gw.exness-api.com",
        "https://evil.example",
        "https://exness.com.evil.example",
        "https://user:pw@gw.exness-api.com",
        "https://notexness.com",
        "ftp://gw.exness.com",
    ],
)
def test_untrusted_gateway_is_refused_before_any_request(url: str) -> None:
    transport = FakeTransport({})
    client = ExnessClient(make_config(gateway_url=url), transport=transport)
    with pytest.raises(ExnessConfigError, match="gateway_url"):
        client.get(_SNAPSHOT)
    assert transport.calls == []


def test_untrusted_access_point_is_refused() -> None:
    routes = {
        ("GET", f"/v1/trading/access-point?account_id={ACCOUNT}"): FakeResponse(
            200, {"access_point": "https://attacker.example", "account_id": ACCOUNT}
        )
    }
    transport = FakeTransport(routes)
    with pytest.raises(ExnessAPIError, match="access point"):
        ExnessClient(make_config(), transport=transport).get(_SNAPSHOT)
    assert transport.targets() == [f"/v1/trading/access-point?account_id={ACCOUNT}"]


# --- signed requests ------------------------------------------------------------


def test_discovery_then_signed_get_to_access_point_without_redirects() -> None:
    transport = FakeTransport({**discovery_route(), ("GET", _SNAPSHOT): FakeResponse(200, {"orders": []})})
    payload = ExnessClient(make_config(), transport=transport).get(_SNAPSHOT)
    assert payload == {"orders": []}
    discovery, call = transport.calls
    assert discovery["host"] == GATEWAY
    assert call["host"] == ACCESS_POINT
    for c in transport.calls:
        assert c["allow_redirects"] is False
        assert c["headers"]["EXN-IDEMPOTENCY-KEY"] == ""
        assert c["headers"]["User-Agent"]
        assert c["timeout"] == 15.0


def test_access_point_is_cached_across_clients() -> None:
    transport = FakeTransport({**discovery_route(), ("GET", _SNAPSHOT): FakeResponse(200, {})})
    ExnessClient(make_config(), transport=transport).get(_SNAPSHOT)
    ExnessClient(make_config(), transport=transport).get(_SNAPSHOT)
    assert transport.targets().count(f"/v1/trading/access-point?account_id={ACCOUNT}") == 1


_DISCOVERY = f"/v1/trading/access-point?account_id={ACCOUNT}"


def test_access_point_survives_a_new_process_via_disk_cache(tmp_path) -> None:
    transport = FakeTransport({**discovery_route(), ("GET", _SNAPSHOT): FakeResponse(200, {})})
    ExnessClient(make_config(), transport=transport).get(_SNAPSHOT)
    _client._ACCESS_POINT_CACHE.clear()  # simulate a fresh CLI process
    ExnessClient(make_config(), transport=transport).get(_SNAPSHOT)
    assert transport.targets().count(_DISCOVERY) == 1
    cached = json.loads((tmp_path / "exness-access-point.json").read_text(encoding="utf-8"))
    assert "exnsk" not in json.dumps(cached)


def test_expired_disk_cache_is_rediscovered(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    transport = FakeTransport({**discovery_route(), ("GET", _SNAPSHOT): FakeResponse(200, {})})
    ExnessClient(make_config(), transport=transport).get(_SNAPSHOT)
    _client._ACCESS_POINT_CACHE.clear()
    real_time = _client.time.time
    monkeypatch.setattr(_client.time, "time", lambda: real_time() + _client.ACCESS_POINT_TTL_SECONDS + 1)
    ExnessClient(make_config(), transport=transport).get(_SNAPSHOT)
    assert transport.targets().count(_DISCOVERY) == 2


def test_tampered_disk_cache_host_is_ignored(tmp_path) -> None:
    import time as _time

    key = f"{GATEWAY}|{ACCOUNT}"
    (tmp_path / "exness-access-point.json").write_text(
        json.dumps({key: {"access_point": "https://attacker.example", "resolved_at": _time.time()}}),
        encoding="utf-8",
    )
    transport = FakeTransport({**discovery_route(), ("GET", _SNAPSHOT): FakeResponse(200, {})})
    ExnessClient(make_config(), transport=transport).get(_SNAPSHOT)
    assert transport.targets()[0] == _DISCOVERY
    assert all(c["host"] != "https://attacker.example" for c in transport.calls)


def test_corrupt_disk_cache_is_ignored(tmp_path) -> None:
    (tmp_path / "exness-access-point.json").write_text("{not json", encoding="utf-8")
    transport = FakeTransport({**discovery_route(), ("GET", _SNAPSHOT): FakeResponse(200, {})})
    ExnessClient(make_config(), transport=transport).get(_SNAPSHOT)
    assert transport.targets()[0] == _DISCOVERY


def test_query_string_is_signed_exactly_as_sent() -> None:
    target = f"/v1/market-data/accounts/{ACCOUNT}/candles?instrument=EURUSD&timeframe=M1"
    transport = FakeTransport({**discovery_route(), ("GET", target): FakeResponse(200, {"candles": []})})
    ExnessClient(make_config(), transport=transport).get(
        f"/v1/market-data/accounts/{ACCOUNT}/candles", params={"instrument": "EURUSD", "timeframe": "M1"}
    )
    import base64

    data = transport.calls[-1]["headers"]["EXN-DATA"]
    signed = json.loads(base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)))
    assert signed["path"] == target


def test_post_sends_exact_signed_body_with_idempotency_key() -> None:
    path = f"/v1/trading/accounts/{ACCOUNT}/positions"
    transport = FakeTransport(
        {**discovery_route(), ("POST", path): FakeResponse(202, {"operation_id": "9", "status": "accepted"})}
    )
    result = ExnessClient(make_config(), transport=transport).post(
        path, {"instrument": "EURUSD", "side": "buy", "volume": "0.01"}, idempotency_key="vt-test-1"
    )
    assert result["operation_id"] == "9"
    call = transport.calls[-1]
    assert call["data"] == b'{"instrument":"EURUSD","side":"buy","volume":"0.01"}'
    assert call["headers"]["EXN-IDEMPOTENCY-KEY"] == "vt-test-1"


@pytest.mark.parametrize("segment", ["..", ".", "EUR/USD", "a b", "", "x?y=1"])
def test_unsafe_path_segments_are_refused(segment: str) -> None:
    client = ExnessClient(make_config(), transport=FakeTransport({}))
    with pytest.raises(ExnessAPIError, match="path segment"):
        client.account_path("configuration", "instruments", segment, "conditions")


def test_mutation_without_idempotency_key_is_refused() -> None:
    with pytest.raises(ValueError):
        ExnessClient(make_config(), transport=FakeTransport({})).post("/x", {}, idempotency_key="")


def test_missing_credentials_raise_before_network() -> None:
    transport = FakeTransport({})
    with pytest.raises(ExnessConfigError, match="private_key"):
        ExnessClient(make_config(private_key=""), transport=transport).get(_SNAPSHOT)
    assert transport.calls == []


# --- errors ---------------------------------------------------------------------


def test_api_error_body_maps_to_code_and_stable_message() -> None:
    transport = FakeTransport(
        {**discovery_route(),
         ("GET", _SNAPSHOT): FakeResponse(403, {"code": 1002, "error_message": "AUTH_PERMISSION_DENIED"})}
    )
    with pytest.raises(ExnessAPIError) as excinfo:
        ExnessClient(make_config(), transport=transport).get(_SNAPSHOT)
    assert excinfo.value.status == 403
    assert excinfo.value.code == 1002
    assert excinfo.value.error_message == "AUTH_PERMISSION_DENIED"


def test_rate_limit_surfaces_retry_after_without_retrying() -> None:
    transport = FakeTransport(
        {**discovery_route(),
         ("GET", _SNAPSHOT): FakeResponse(429, {"code": 3015, "error_message": "REQUEST_RATE_LIMIT"},
                                          headers={"Retry-After": "7"})}
    )
    with pytest.raises(ExnessAPIError) as excinfo:
        ExnessClient(make_config(), transport=transport).get(_SNAPSHOT)
    assert excinfo.value.retry_after == 7.0
    assert transport.targets("GET").count(_SNAPSHOT) == 1


def test_get_rate_limit_with_short_retry_after_is_retried_once(monkeypatch: pytest.MonkeyPatch) -> None:
    slept: list[float] = []
    monkeypatch.setattr(_client, "_sleep", slept.append)
    limited = FakeResponse(429, {"code": 3015, "error_message": "REQUEST_RATE_LIMIT"}, headers={"Retry-After": "0.5"})
    transport = FakeTransport({**discovery_route(), ("GET", _SNAPSHOT): [limited, FakeResponse(200, {"ok": 1})]})
    assert ExnessClient(make_config(), transport=transport).get(_SNAPSHOT) == {"ok": 1}
    assert slept == [0.5]
    assert transport.targets("GET").count(_SNAPSHOT) == 2


def test_get_rate_limit_retries_at_most_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_client, "_sleep", lambda _s: None)
    limited = FakeResponse(429, {"code": 3015, "error_message": "REQUEST_RATE_LIMIT"})
    transport = FakeTransport({**discovery_route(), ("GET", _SNAPSHOT): [limited, limited, FakeResponse(200, {})]})
    with pytest.raises(ExnessAPIError):
        ExnessClient(make_config(), transport=transport).get(_SNAPSHOT)
    assert transport.targets("GET").count(_SNAPSHOT) == 2


def test_mutations_are_never_retried_on_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_client, "_sleep", lambda _s: None)
    path = f"/v1/trading/accounts/{ACCOUNT}/positions"
    limited = FakeResponse(429, {"code": 3015, "error_message": "REQUEST_RATE_LIMIT"}, headers={"Retry-After": "0.1"})
    transport = FakeTransport({**discovery_route(), ("POST", path): [limited, FakeResponse(202, {})]})
    with pytest.raises(ExnessAPIError):
        ExnessClient(make_config(), transport=transport).post(path, {"a": 1}, idempotency_key="vt-x1")
    assert transport.targets("POST").count(path) == 1


def test_redirect_is_an_error_not_followed() -> None:
    transport = FakeTransport(
        {**discovery_route(), ("GET", _SNAPSHOT): FakeResponse(302, None, headers={"Location": "https://x"})}
    )
    with pytest.raises(ExnessAPIError, match="redirect"):
        ExnessClient(make_config(), transport=transport).get(_SNAPSHOT)


def test_non_json_error_is_truncated_and_redacted() -> None:
    html = "<html>blocked token=supersecretvalue " + "x" * 5000 + "</html>"
    transport = FakeTransport({**discovery_route(), ("GET", _SNAPSHOT): FakeResponse(403, None, text=html)})
    with pytest.raises(ExnessAPIError) as excinfo:
        ExnessClient(make_config(), transport=transport).get(_SNAPSHOT)
    message = str(excinfo.value)
    assert len(message) < 400
    assert "supersecretvalue" not in message


def test_network_error_message_does_not_leak_headers() -> None:
    import requests

    def _boom(method, url, **kwargs):
        raise requests.ConnectionError("connection reset")

    with pytest.raises(ExnessAPIError, match="network error") as excinfo:
        ExnessClient(make_config(), transport=_boom).get(_SNAPSHOT)
    assert "exnsk-synthetic-example" not in str(excinfo.value)
