from __future__ import annotations

import json
import os

import pytest

from src.trading.connections import ConnectionStore
from src.trading.credentials import CredentialStore
from src.trading.local_plugins import discover_plugins, parse_manifest
from src.trading.plugin_scaffold import scaffold_connector, validate_connector


class _MemoryCredentials:
    def __init__(self):
        self.values: dict[tuple[str, str], str] = {}

    def get_password(self, service_name: str, username: str):
        return self.values.get((service_name, username))

    def set_password(self, service_name: str, username: str, password: str):
        self.values[(service_name, username)] = password

    def delete_password(self, service_name: str, username: str):
        self.values.pop((service_name, username), None)


def test_connection_registry_never_serializes_credentials(tmp_path):
    credentials = CredentialStore(_MemoryCredentials())
    store = ConnectionStore(tmp_path / "connections.json", credential_store=credentials)
    connection = store.create(
        "main-binance",
        "binance-live-sdk-readonly",
        "Main Binance",
    )
    credentials.save(connection.id, {"api_key": "secret-value"})

    payload = (tmp_path / "connections.json").read_text(encoding="utf-8")
    assert "secret-value" not in payload
    assert connection.credential_ref == "keyring://vibe-trading/main-binance"
    if os.name == "posix":
        assert (tmp_path / "connections.json").stat().st_mode & 0o777 == 0o600


def test_connection_registry_normalizes_ids_before_duplicate_checks(tmp_path):
    store = ConnectionStore(
        tmp_path / "connections.json",
        credential_store=CredentialStore(_MemoryCredentials()),
    )
    store.create("main-account", "binance-live-sdk-readonly", "Main account")

    with pytest.raises(ValueError, match="already exists"):
        store.create(" MAIN-ACCOUNT ", "binance-live-sdk-readonly", "Replacement")

    assert store.get("main-account").label == "Main account"


def test_connection_registry_rejects_control_characters_in_labels(tmp_path):
    store = ConnectionStore(
        tmp_path / "connections.json",
        credential_store=CredentialStore(_MemoryCredentials()),
    )

    with pytest.raises(ValueError, match="printable"):
        store.create("main-account", "binance-live-sdk-readonly", "Main\naccount")


def test_scaffold_generates_a_valid_readonly_connector(tmp_path):
    target = scaffold_connector("sample-broker", tmp_path)
    plugin = validate_connector(target)

    assert plugin.profile.id == "sample-broker-live-readonly"
    assert plugin.profile.readonly is True
    assert {"account.read", "positions.read"}.issubset(plugin.profile.capabilities)
    assert [field.name for field in plugin.credential_fields] == [
        "api_key",
        "api_secret",
    ]


def test_manifest_rejects_write_capabilities(tmp_path):
    target = scaffold_connector("unsafe-broker", tmp_path)
    manifest = target / "connector.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["profile"]["capabilities"].append("orders.place")
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="read capabilities only"):
        parse_manifest(manifest)


def test_manifest_rejects_unknown_non_read_capabilities(tmp_path):
    target = scaffold_connector("unsafe-operation", tmp_path)
    manifest = target / "connector.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["profile"]["capabilities"].append("trade.execute")
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="trade.execute"):
        parse_manifest(manifest)


def test_discovery_isolates_invalid_local_plugins(tmp_path):
    scaffold_connector("good-broker", tmp_path)
    bad = tmp_path / "bad-broker"
    bad.mkdir()
    (bad / "connector.json").write_text("{}", encoding="utf-8")

    plugins, errors = discover_plugins(tmp_path)

    assert [plugin.profile.connector for plugin in plugins] == ["good-broker"]
    assert errors[0]["directory"] == "bad-broker"


def test_installed_local_plugin_runs_through_the_trading_read_interface(
    tmp_path,
    monkeypatch,
):
    from src.trading import connections, local_plugins
    from src.trading.service import get_account, get_positions

    monkeypatch.setattr(local_plugins, "get_runtime_root", lambda: tmp_path)
    monkeypatch.setattr(connections, "get_runtime_root", lambda: tmp_path)
    target = scaffold_connector("sample", tmp_path / "connectors")
    manifest = target / "connector.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["auth"]["fields"] = []
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    (target / "adapter.py").write_text(
        """
def check_status(*, credentials, config):
    return {"status": "ok", "readonly": True}

def get_account_snapshot(*, credentials, config):
    return {"account": {"portfolio_value": "42", "currency": "USD"}}

def get_positions(*, credentials, config):
    return {"positions": [{"symbol": "DEMO", "quantity": 1, "current_price": 42}]}
""",
        encoding="utf-8",
    )
    registry = ConnectionStore()
    registry.create("my-sample", "sample-live-readonly", "My Sample")

    assert get_account("sample-live-readonly", connection_id="my-sample")["account"]["portfolio_value"] == "42"
    assert get_positions("sample-live-readonly", connection_id="my-sample")["positions"][0]["symbol"] == "DEMO"


def test_builtin_sdk_connections_use_isolated_keyring_credentials(
    tmp_path,
    monkeypatch,
):
    from src.trading import connections
    from src.trading.profiles import profile_by_id
    from src.trading.service import _sdk_config, _sdk_module

    credentials = CredentialStore(_MemoryCredentials())

    class CredentialFactory:
        reference = staticmethod(CredentialStore.reference)

        def __new__(cls):
            return credentials

    monkeypatch.setattr(connections, "get_runtime_root", lambda: tmp_path)
    monkeypatch.setattr(connections, "CredentialStore", CredentialFactory)
    store = ConnectionStore()
    store.create("binance-one", "binance-live-sdk-readonly", "Binance one")
    store.create("binance-two", "binance-live-sdk-readonly", "Binance two")
    credentials.save(
        "binance-one",
        {"api_key": "first-key", "api_secret": "first-secret"},
    )
    credentials.save(
        "binance-two",
        {"api_key": "second-key", "api_secret": "second-secret"},
    )

    profile = profile_by_id("binance-live-sdk-readonly")
    module = _sdk_module("binance")
    first = _sdk_config(profile, module, {"connection_id": "binance-one"})
    second = _sdk_config(profile, module, {"connection_id": "binance-two"})

    assert (first.api_key, first.api_secret) == ("first-key", "first-secret")
    assert (second.api_key, second.api_secret) == ("second-key", "second-secret")


def test_builtin_sdk_connection_rejects_partial_vault_set(tmp_path, monkeypatch):
    from src.trading import connections
    from src.trading.profiles import profile_by_id
    from src.trading.service import _sdk_config, _sdk_module

    credentials = CredentialStore(_MemoryCredentials())

    class CredentialFactory:
        reference = staticmethod(CredentialStore.reference)

        def __new__(cls):
            return credentials

    monkeypatch.setattr(connections, "get_runtime_root", lambda: tmp_path)
    monkeypatch.setattr(connections, "CredentialStore", CredentialFactory)
    ConnectionStore().create(
        "partial-okx",
        "okx-live-sdk-readonly",
        "Partial OKX",
    )
    credentials.save("partial-okx", {"api_key": "only-one-field"})

    with pytest.raises(ValueError, match="api_secret, passphrase"):
        _sdk_config(
            profile_by_id("okx-live-sdk-readonly"),
            _sdk_module("okx"),
            {"connection_id": "partial-okx"},
        )


def test_mcp_connector_discovery_exposes_onboarding_contract_without_values():
    from src.tools.trading_connector_tool import TradingConnectionsTool

    payload = json.loads(TradingConnectionsTool().execute())
    okx = next(profile for profile in payload["profiles"] if profile["id"] == "okx-live-sdk-readonly")

    assert okx["onboarding"]["dependency"] == "python-okx"
    assert [field["name"] for field in okx["onboarding"]["credential_fields"]] == [
        "api_key",
        "api_secret",
        "passphrase",
    ]
    assert "credential_values" not in okx["onboarding"]


# ---------------------------------------------------------------------------
# Per-call overrides must pass the connector's own allowlist (#1250 follow-up)
# ---------------------------------------------------------------------------


def _vault_store(tmp_path, connection_id, profile_id):
    credentials = CredentialStore(_MemoryCredentials())
    store = ConnectionStore(tmp_path / "connections.json", credential_store=credentials)
    store.create(connection_id, profile_id, "Test")
    return store, credentials


def test_connection_scoped_overrides_obey_the_connector_allowlist(tmp_path, monkeypatch):
    """A vault-backed call must not widen what a caller may override.

    Every SDK connector narrows overrides on purpose: OKX and Binance both
    exclude ``readonly`` ("always true for this layer") and ``timeout``, and
    Longbridge's overlay is ``profile``/``region`` only so a caller "cannot mix
    or bypass the shared resolver". ``build_config`` enforces that; a config
    built from a raw merged mapping would not — and ``overrides`` is the one
    part of that payload that arrives from an MCP tool argument or REST body.
    """
    import src.trading.connections as conns
    from src.trading import service
    from src.trading.connectors.okx import sdk as okx_sdk
    from src.trading.profiles import profile_by_id

    store, credentials = _vault_store(tmp_path, "main-okx", "okx-live-sdk-readonly")
    credentials.save("main-okx", {"api_key": "k", "api_secret": "s", "passphrase": "p"})
    monkeypatch.setattr(conns, "ConnectionStore", lambda *a, **k: store)

    profile = profile_by_id("okx-live-sdk-readonly")
    out_of_allowlist = {"readonly": False, "timeout": 999.0}

    # The connector's own builder drops them...
    legacy = okx_sdk.build_config(profile.config, out_of_allowlist)
    assert legacy.readonly is True
    assert legacy.timeout == 15.0

    # ...and so must the vault-backed path.
    vaulted = service._sdk_config(
        profile, okx_sdk, {"connection_id": "main-okx", **out_of_allowlist}
    )
    assert vaulted.readonly is True
    assert vaulted.timeout == 15.0
    # An allowlisted override still works.
    assert (
        service._sdk_config(
            profile, okx_sdk, {"connection_id": "main-okx", "expected_uid": "uid-1"}
        ).expected_uid
        == "uid-1"
    )
    # And the vault credentials really were used, or the assertions are vacuous.
    assert vaulted.api_key == "k"


def test_every_sdk_connector_declares_an_override_allowlist():
    """A connector added without one must fail closed, and be noticed here."""
    import importlib
    import pkgutil

    from src.trading import connectors as connectors_pkg
    from src.trading.service import _allowed_override_keys

    missing = []
    for info in pkgutil.iter_modules(connectors_pkg.__path__):
        try:
            module = importlib.import_module(
                f"src.trading.connectors.{info.name}.sdk"
            )
        except ModuleNotFoundError:
            continue  # connector without an SDK surface
        if not hasattr(module, "build_config"):
            continue  # not a per-call-config connector
        if not _allowed_override_keys(module):
            missing.append(info.name)
    assert missing == [], (
        f"SDK connectors without an override allowlist: {missing}. "
        "_allowed_override_keys fails closed, so their per-call overrides are "
        "silently dropped — declare _OVERRIDE_KEYS."
    )
