from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from src.api import connection_routes
from src.trading.connections import ConnectionStore
from src.trading.credentials import CredentialStore


class _MemoryCredentials:
    def __init__(self):
        self.values: dict[tuple[str, str], str] = {}

    def get_password(self, service_name: str, username: str):
        return self.values.get((service_name, username))

    def set_password(self, service_name: str, username: str, password: str):
        self.values[(service_name, username)] = password

    def delete_password(self, service_name: str, username: str):
        self.values.pop((service_name, username), None)


def test_connection_routes_create_list_and_check_without_returning_secrets(
    tmp_path,
    monkeypatch,
):
    store = ConnectionStore(
        tmp_path / "connections.json",
        credential_store=CredentialStore(_MemoryCredentials()),
    )
    monkeypatch.setattr(connection_routes, "ConnectionStore", lambda: store)
    monkeypatch.setattr(
        connection_routes,
        "check_connection",
        lambda profile_id, **kwargs: {
            "status": "ok",
            "profile_id": profile_id,
            "connection_id": kwargs["connection_id"],
        },
    )
    app = FastAPI()
    connection_routes.register_connection_routes(app)
    client = TestClient(app)

    created = client.post(
        "/api/connections",
        json={
            "id": "main-binance",
            "profile_id": "binance-live-sdk-readonly",
            "label": "Main Binance",
        },
    )
    assert created.status_code == 200
    saved = client.post(
        "/api/connections/main-binance/credentials",
        json={
            "values": {
                "api_key": "must-not-leak-key",
                "api_secret": "must-not-leak-secret",
            }
        },
    )
    assert saved.status_code == 200
    listed = client.get("/api/connections").json()
    assert listed["connections"][0]["id"] == "main-binance"
    assert listed["connections"][0]["portfolio_compatibility"]["level"] == "native"
    binance_profiles = [row for row in listed["profiles"] if row.get("connector") == "binance"]
    assert {row["portfolio_compatibility"]["level"] for row in binance_profiles} == {"native"}
    assert "must-not-leak" not in str(listed).lower()
    assert [field["name"] for field in listed["connections"][0]["credential_fields"]] == [
        "api_key",
        "api_secret",
    ]
    checked = client.post("/api/connections/main-binance/check")
    assert checked.json()["report"]["connection_id"] == "main-binance"


def test_connection_routes_reject_credentials_not_declared_by_profile(tmp_path, monkeypatch):
    store = ConnectionStore(
        tmp_path / "connections.json",
        credential_store=CredentialStore(_MemoryCredentials()),
    )
    store.create("main-binance", "binance-live-sdk-readonly", "Main Binance")
    monkeypatch.setattr(connection_routes, "ConnectionStore", lambda: store)
    app = FastAPI()
    connection_routes.register_connection_routes(app)
    client = TestClient(app)

    response = client.post(
        "/api/connections/main-binance/credentials",
        json={"values": {"withdrawal_token": "must-not-be-accepted"}},
    )
    assert response.status_code == 400


@pytest.fixture
def ibkr_endpoint_client(tmp_path, monkeypatch):
    from src.trading import connections
    from src.trading.connectors.ibkr import local
    from src.trading.connectors.futu import sdk as futu

    store = ConnectionStore(tmp_path / "connections.json", credential_store=CredentialStore(_MemoryCredentials()))
    store.create("ibkr-paper", "ibkr-paper-local", "Paper")
    store.create("ibkr-live", "ibkr-live-local-readonly", "Live")
    store.create("ibkr-mcp", "ibkr-live-official-mcp-readonly", "Remote")
    store.create("futu-paper", "futu-paper-sdk", "Futu Paper")
    store.create("futu-live", "futu-live-sdk-readonly", "Futu Live")
    monkeypatch.setattr(connection_routes, "ConnectionStore", lambda: store)
    monkeypatch.setattr(connections, "ConnectionStore", lambda: store)
    monkeypatch.setattr(local, "config_path", lambda: tmp_path / "ibkr-local.json")
    monkeypatch.setattr(futu, "config_path", lambda: tmp_path / "futu.json")
    monkeypatch.setattr(futu, "tcp_port_open", lambda *a, **k: pytest.fail("unexpected Futu access"))
    # Any accidental socket access is a test failure, including saving/listing.
    monkeypatch.setattr(local, "tcp_port_open", lambda *a, **k: pytest.fail("unexpected broker access"))
    app = FastAPI()
    connection_routes.register_connection_routes(app)
    return TestClient(app), store


def test_ibkr_endpoint_persists_per_connection_and_is_used_for_reads(ibkr_endpoint_client):
    from src.trading.service import _ibkr_config
    from src.trading.profiles import profile_by_id

    client, store = ibkr_endpoint_client
    defaults = {row["id"]: row for row in client.get("/api/connections").json()["connections"]}
    assert defaults["ibkr-paper"]["effective_endpoint"] == {"host": "127.0.0.1", "port": 7497}
    assert defaults["ibkr-live"]["effective_endpoint"] == {"host": "127.0.0.1", "port": 7496}
    response = client.put("/api/connections/ibkr-paper/endpoint", json={"host": " host.docker.internal ", "port": 4002})
    assert response.status_code == 200
    # Re-read the persisted file; the other connection stays on its defaults.
    assert store.get("ibkr-paper").endpoint == {"host": "host.docker.internal", "port": 4002}
    listed = {row["id"]: row for row in client.get("/api/connections").json()["connections"]}
    assert listed["ibkr-paper"]["effective_endpoint"] == {"host": "host.docker.internal", "port": 4002}
    assert listed["ibkr-live"]["effective_endpoint"] == {"host": "127.0.0.1", "port": 7496}
    assert "effective_endpoint" not in listed["ibkr-mcp"]
    cfg = _ibkr_config(profile_by_id("ibkr-paper-local"), {"connection_id": "ibkr-paper"})
    assert (cfg.host, cfg.port, cfg.profile, cfg.readonly) == ("host.docker.internal", 4002, "paper", True)
    override = _ibkr_config(profile_by_id("ibkr-paper-local"), {"connection_id": "ibkr-paper", "port": 7497})
    assert override.port == 7497
    # Existing callers without a connection id keep the original defaults.
    assert _ibkr_config(profile_by_id("ibkr-paper-local"), {}).port == 7497


@pytest.mark.parametrize("host", ["", "   ", "https://localhost", "localhost:4002", "host/path", "host name", "user@host", "a" * 254])
def test_ibkr_endpoint_rejects_invalid_host(ibkr_endpoint_client, host):
    client, store = ibkr_endpoint_client
    response = client.put("/api/connections/ibkr-paper/endpoint", json={"host": host, "port": 4002})
    assert response.status_code in {400, 422}
    assert store.get("ibkr-paper").endpoint is None


@pytest.mark.parametrize("port", [0, 65536, 1.5, True, "4002", None])
def test_ibkr_endpoint_rejects_invalid_port(ibkr_endpoint_client, port):
    client, store = ibkr_endpoint_client
    assert client.put("/api/connections/ibkr-paper/endpoint", json={"host": "localhost", "port": port}).status_code == 422
    assert store.get("ibkr-paper").endpoint is None


@pytest.mark.parametrize("host,port", [("::1", 1), ("192.168.1.10", 65535), ("gateway.local", 4002)])
def test_ibkr_endpoint_accepts_hosts_and_port_boundaries(ibkr_endpoint_client, host, port):
    client, store = ibkr_endpoint_client
    assert client.put("/api/connections/ibkr-paper/endpoint", json={"host": host, "port": port}).status_code == 200
    assert store.get("ibkr-paper").endpoint == {"host": host, "port": port}


def test_ibkr_endpoint_rejects_remote_profiles_and_extra_settings(ibkr_endpoint_client):
    client, _ = ibkr_endpoint_client
    assert client.put("/api/connections/ibkr-mcp/endpoint", json={"host": "localhost", "port": 4002}).status_code == 400
    assert client.put("/api/connections/missing/endpoint", json={"host": "localhost", "port": 4002}).status_code == 400
    assert client.put("/api/connections/ibkr-paper/endpoint", json={"host": "localhost", "port": 4002, "readonly": False}).status_code == 422


def test_ibkr_endpoint_requires_settings_write_auth(ibkr_endpoint_client, monkeypatch):
    from src.api import security

    client, store = ibkr_endpoint_client
    monkeypatch.setattr(security, "_configured_api_key", lambda: "test-settings-key")
    assert client.put("/api/connections/ibkr-paper/endpoint", json={"host": "localhost", "port": 4002}).status_code == 401
    assert store.get("ibkr-paper").endpoint is None


def test_ibkr_endpoint_preserves_legacy_configuration_until_overridden(ibkr_endpoint_client, tmp_path):
    from src.trading.connectors.ibkr import local
    from src.trading.profiles import profile_by_id
    from src.trading.service import _ibkr_config

    client, _ = ibkr_endpoint_client
    local.config_path().write_text('{"host":"legacy.local","port":4002,"profile":"paper","client_id":123}')
    listed = {row["id"]: row for row in client.get("/api/connections").json()["connections"]}
    assert listed["ibkr-paper"]["effective_endpoint"] == {"host": "legacy.local", "port": 4002}
    assert listed["ibkr-live"]["effective_endpoint"]["port"] == 7496
    assert client.put("/api/connections/ibkr-paper/endpoint", json={"host": "custom.local", "port": 7497}).status_code == 200
    config = _ibkr_config(profile_by_id("ibkr-paper-local"), {"connection_id": "ibkr-paper"})
    assert (config.host, config.port, config.client_id, config.readonly) == ("custom.local", 7497, 123, True)
    with pytest.raises(ValueError, match="profile does not match"):
        _ibkr_config(profile_by_id("ibkr-live-local-readonly"), {"connection_id": "ibkr-paper"})


def test_futu_endpoint_defaults_persistence_and_native_read_dispatch(ibkr_endpoint_client, monkeypatch):
    from src.trading import service
    from src.trading.connectors.futu import sdk as futu
    from src.trading.profiles import profile_by_id

    client, store = ibkr_endpoint_client
    listed = {row["id"]: row for row in client.get("/api/connections").json()["connections"]}
    for name in ("futu-paper", "futu-live"):
        assert listed[name]["effective_endpoint"] == {"host": "127.0.0.1", "port": 11111}
    assert client.put("/api/connections/futu-paper/endpoint", json={"host": "opend.local", "port": 11112}).status_code == 200
    assert store.get("futu-paper").endpoint == {"host": "opend.local", "port": 11112}
    listed = {row["id"]: row for row in client.get("/api/connections").json()["connections"]}
    assert listed["futu-paper"]["effective_endpoint"] == {"host": "opend.local", "port": 11112}
    assert listed["futu-live"]["effective_endpoint"] == {"host": "127.0.0.1", "port": 11111}
    assert listed["ibkr-paper"]["effective_endpoint"] == {"host": "127.0.0.1", "port": 7497}
    calls = []

    def read(config):
        calls.append((config.host, config.port, config.profile))
        return {"status": "ok"}

    monkeypatch.setattr(futu, "check_status", read)
    monkeypatch.setattr(futu, "get_account_snapshot", read)
    monkeypatch.setattr(futu, "get_positions", read)
    monkeypatch.setattr(futu, "get_quote", lambda symbol, *, config, **kwargs: read(config))
    assert client.post("/api/connections/futu-paper/check").status_code == 200
    service.get_account("futu-paper-sdk", connection_id="futu-paper")
    service.get_positions("futu-paper-sdk", connection_id="futu-paper")
    service.get_quote("AAPL", "futu-paper-sdk", connection_id="futu-paper")
    assert calls == [("opend.local", 11112, "paper")] * 4
    override = service._sdk_config(profile_by_id("futu-paper-sdk"), futu, {"connection_id": "futu-paper", "port": 11113})
    assert override.port == 11113


def test_futu_endpoint_keeps_legacy_gateway_settings_and_live_profile(ibkr_endpoint_client):
    from src.trading import service
    from src.trading.connectors.futu import sdk as futu
    from src.trading.profiles import profile_by_id

    client, _ = ibkr_endpoint_client
    futu.config_path().write_text('{"host":"legacy.local","port":11114,"filter_trdmarket":"US","acc_id":123}')
    listed = {row["id"]: row for row in client.get("/api/connections").json()["connections"]}
    assert listed["futu-live"]["effective_endpoint"] == {"host": "legacy.local", "port": 11114}
    assert client.put("/api/connections/futu-live/endpoint", json={"host": "opend.local", "port": 11115}).status_code == 200
    config = service._sdk_config(profile_by_id("futu-live-sdk-readonly"), futu, {"connection_id": "futu-live"})
    assert (config.host, config.port, config.profile, config.filter_trdmarket, config.acc_id) == ("opend.local", 11115, "live-readonly", "US", 123)
    assert service._sdk_config(profile_by_id("futu-live-sdk-readonly"), futu, {}).host == "legacy.local"


@pytest.mark.parametrize("connector,filename", [("ibkr", "ibkr-local.json"), ("futu", "futu.json")])
def test_connection_list_isolates_invalid_gateway_config(ibkr_endpoint_client, tmp_path, connector, filename):
    client, _ = ibkr_endpoint_client
    before = {row["id"]: row for row in client.get("/api/connections").json()["connections"]}
    (tmp_path / filename).write_text("{invalid json", encoding="utf-8")

    response = client.get("/api/connections")

    assert response.status_code == 200
    after = {row["id"]: row for row in response.json()["connections"]}
    assert after.keys() == before.keys()
    for connection_id, row in after.items():
        if row["connector"] == connector and row["transport"] != "remote_mcp":
            assert filename in row["endpoint_error"]
            assert "effective_endpoint" not in row
        else:
            assert row == before[connection_id]


@pytest.mark.parametrize("overrides,expected_port", [({}, 11112), ({"port": 11113}, 11113)])
def test_futu_tool_preserves_saved_endpoint_for_unsupplied_fields(ibkr_endpoint_client, monkeypatch, overrides, expected_port):
    from src.tools.trading_connector_tool import TradingCheckTool
    from src.trading.connectors.futu import sdk as futu

    client, _ = ibkr_endpoint_client
    assert client.put("/api/connections/futu-paper/endpoint", json={"host": "opend.local", "port": 11112}).status_code == 200
    calls = []

    def check(config):
        calls.append((config.host, config.port, config.profile))
        return {"status": "ok"}

    monkeypatch.setattr(futu, "check_status", check)
    result = json.loads(TradingCheckTool().execute(
        connection="futu-paper-sdk", connection_id="futu-paper", **overrides,
    ))

    assert result["status"] == "ok"
    assert calls == [("opend.local", expected_port, "paper")]
