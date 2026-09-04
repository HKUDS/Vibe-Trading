from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

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
