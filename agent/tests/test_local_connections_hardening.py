"""Packaging, caching, and eligibility guards for local read-only connections."""

from __future__ import annotations

import builtins
import json
import os
import subprocess
import sys
import tomllib
import types
from pathlib import Path

import pytest

from src.trading import local_plugins
from src.trading.connections import (
    ConnectionStore,
    is_portfolio_connection_profile,
    readonly_profile_catalog,
)
from src.trading.credentials import CredentialStore
from src.trading.local_plugins import clear_plugin_cache, discover_plugins
from src.trading.plugin_scaffold import scaffold_connector
from src.trading.profiles import profile_by_id
from src.trading.types import TradingProfile

ROOT = Path(__file__).resolve().parents[2]
AGENT_DIR = ROOT / "agent"


class _MemoryCredentials:
    """In-memory stand-in for the OS credential vault."""

    def __init__(self):
        self.values: dict[tuple[str, str], str] = {}

    def get_password(self, service_name: str, username: str):
        return self.values.get((service_name, username))

    def set_password(self, service_name: str, username: str, password: str):
        self.values[(service_name, username)] = password

    def delete_password(self, service_name: str, username: str):
        self.values.pop((service_name, username), None)


def _normalized_requirement_name(requirement: str) -> str:
    name = requirement.split(";", 1)[0]
    for marker in ("[", "<", ">", "="):
        name = name.split(marker, 1)[0]
    return name.strip().lower()


# ---------------------------------------------------------------------------
# keyring is an optional extra
# ---------------------------------------------------------------------------


def test_keyring_is_not_a_core_install_dependency() -> None:
    """An OS credential vault is only needed by users who install a plugin."""
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())

    core_dependencies = {
        _normalized_requirement_name(requirement)
        for requirement in pyproject["project"]["dependencies"]
    }
    requirements_txt = {
        _normalized_requirement_name(line)
        for line in (ROOT / "agent" / "requirements.txt").read_text().splitlines()
        if line and not line.startswith("#")
    }
    keyring_extra = {
        _normalized_requirement_name(requirement)
        for requirement in pyproject["project"]["optional-dependencies"]["keyring"]
    }

    assert "keyring" not in core_dependencies
    assert "keyring" not in requirements_txt
    assert "keyring" in keyring_extra


def test_credential_store_names_the_extra_when_keyring_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing optional vault must produce an actionable install hint."""
    real_import = builtins.__import__

    def blocking_import(name, *args, **kwargs):
        if name == "keyring" or name.startswith("keyring."):
            raise ModuleNotFoundError("No module named 'keyring'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocking_import)
    monkeypatch.delitem(sys.modules, "keyring", raising=False)

    with pytest.raises(RuntimeError, match=r'vibe-trading-ai\[keyring\]'):
        CredentialStore().save("main-account", {"api_key": "value"})


@pytest.mark.parametrize("profile_id", ["alpaca-live-sdk-readonly", "ibkr-paper-local"])
def test_delete_connection_without_keyring_installed(tmp_path, monkeypatch, profile_id):
    real_import = builtins.__import__

    def blocking_import(name, *args, **kwargs):
        if name == "keyring" or name.startswith("keyring."):
            raise ModuleNotFoundError("No module named 'keyring'", name="keyring")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocking_import)
    store = ConnectionStore(tmp_path / "connections.json")
    store.create("unused", profile_id, "Unused")
    if profile_id == "alpaca-live-sdk-readonly":
        with pytest.raises(RuntimeError, match="credential vault"):
            store.delete("unused")
        assert store.get("unused").id == "unused"
    else:
        store.delete("unused")
        assert store.list() == []


def test_delete_connection_without_a_keyring_backend(tmp_path, monkeypatch):
    class NoKeyringError(RuntimeError):
        pass

    def unavailable(*args):
        raise NoKeyringError("No recommended backend was available")

    keyring = types.ModuleType("keyring")
    errors = types.ModuleType("keyring.errors")
    errors.NoKeyringError = NoKeyringError
    keyring.delete_password = unavailable
    keyring.get_password = unavailable
    monkeypatch.setitem(sys.modules, "keyring", keyring)
    monkeypatch.setitem(sys.modules, "keyring.errors", errors)
    store = ConnectionStore(tmp_path / "connections.json")
    store.create("unused", "alpaca-live-sdk-readonly", "Unused")
    # Listing may cache the imported keyring module before deletion.
    store.public_list()
    with pytest.raises(RuntimeError, match="backend"):
        store.delete("unused")
    assert store.get("unused").id == "unused"


@pytest.mark.parametrize("error_type", [RuntimeError, PermissionError])
def test_delete_connection_keeps_registry_when_vault_is_locked(tmp_path, error_type):
    class LockedCredentials(_MemoryCredentials):
        def delete_password(self, service_name, username):
            raise error_type("credential vault is locked")

    store = ConnectionStore(tmp_path / "connections.json", credential_store=CredentialStore(LockedCredentials()))
    store.create("protected", "alpaca-live-sdk-readonly", "Protected")
    with pytest.raises(RuntimeError, match="vault is locked"):
        store.delete("protected")
    assert store.get("protected").label == "Protected"


def test_delete_connection_removes_only_its_own_credentials(tmp_path):
    backend = _MemoryCredentials()
    credentials = CredentialStore(backend)
    store = ConnectionStore(tmp_path / "connections.json", credential_store=credentials)
    for connection_id in ["deleted", "retained"]:
        store.create(connection_id, "alpaca-live-sdk-readonly", connection_id)
        credentials.save(connection_id, {"api_key": "key", "secret_key": "secret"})
    store.delete("deleted")
    assert credentials.load("deleted", ["api_key", "secret_key"]) == {}
    assert credentials.load("retained", ["api_key", "secret_key"]) == {"api_key": "key", "secret_key": "secret"}
    assert [row.id for row in store.list()] == ["retained"]


def test_connection_modules_import_without_keyring_installed() -> None:
    """Connection metadata must stay importable on a base install.

    Runs in a child process because re-importing these modules in the test
    process would leave two copies of every profile class behind.
    """
    code = (
        "import sys;"
        "sys.meta_path.insert(0, type('Block', (), {"
        "'find_module': staticmethod(lambda name, path=None: None),"
        "'find_spec': staticmethod("
        "lambda name, path=None, target=None: "
        "(_ for _ in ()).throw(ModuleNotFoundError(name)) "
        "if name.split('.')[0] == 'keyring' else None)})());"
        "import src.trading.connections, src.trading.profiles, "
        "src.api.connection_routes;"
        "print('imported')"
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(AGENT_DIR) + os.pathsep + env.get("PYTHONPATH", "")
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        cwd=str(AGENT_DIR),
        env=env,
        timeout=600,
    )

    assert result.returncode == 0, (
        "the connection modules import keyring eagerly, so a base install "
        f"cannot even list connections: {result.stderr.decode()[-2000:]}"
    )
    assert "imported" in result.stdout.decode()


# ---------------------------------------------------------------------------
# Manifest discovery cache
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolated_plugin_cache():
    """Keep cached discovery results from leaking between tests."""
    clear_plugin_cache()
    yield
    clear_plugin_cache()


def _count_manifest_parses(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    calls = [0]
    real_parse = local_plugins.parse_manifest

    def counting_parse(path: Path):
        calls[0] += 1
        return real_parse(path)

    monkeypatch.setattr(local_plugins, "parse_manifest", counting_parse)
    return calls


def test_discovery_reuses_parsed_manifests_until_one_changes(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Profile lookups re-run discovery, so unchanged manifests must not re-parse."""
    scaffold_connector("cached-broker", tmp_path)
    calls = _count_manifest_parses(monkeypatch)

    first, _ = discover_plugins(tmp_path)
    second, _ = discover_plugins(tmp_path)

    assert calls[0] == 1
    assert [plugin.profile.id for plugin in second] == [
        plugin.profile.id for plugin in first
    ]

    manifest = tmp_path / "cached-broker" / "connector.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["profile"]["label"] = "Cached Broker renamed by the operator"
    manifest.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    refreshed, _ = discover_plugins(tmp_path)

    assert calls[0] == 2
    assert refreshed[0].profile.label == "Cached Broker renamed by the operator"


def test_discovery_cache_is_keyed_on_the_plugin_root(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A test or operator that repoints the runtime root must see its own plugins."""
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    scaffold_connector("first-broker", first_root)
    scaffold_connector("second-broker", second_root)

    monkeypatch.setattr(local_plugins, "get_runtime_root", lambda: tmp_path / "first")
    monkeypatch.setattr(local_plugins, "plugin_root", lambda: first_root)
    assert [plugin.profile.connector for plugin in discover_plugins()[0]] == [
        "first-broker"
    ]

    monkeypatch.setattr(local_plugins, "plugin_root", lambda: second_root)
    assert [plugin.profile.connector for plugin in discover_plugins()[0]] == [
        "second-broker"
    ]


def test_discovery_of_a_new_plugin_invalidates_the_cached_result(tmp_path) -> None:
    """Installing a connector changes the manifest set, so discovery refreshes."""
    scaffold_connector("early-broker", tmp_path)
    assert [plugin.profile.connector for plugin in discover_plugins(tmp_path)[0]] == [
        "early-broker"
    ]

    scaffold_connector("later-broker", tmp_path)

    assert sorted(
        plugin.profile.connector for plugin in discover_plugins(tmp_path)[0]
    ) == ["early-broker", "later-broker"]


# ---------------------------------------------------------------------------
# Connection profile eligibility
# ---------------------------------------------------------------------------


def test_discovery_only_profile_cannot_back_a_portfolio_connection(
    tmp_path, monkeypatch
) -> None:
    """A tool-discovery profile cannot serve account or position reads."""
    profile = TradingProfile(
        id="discovery-only-test",
        connector="test",
        label="Discovery only",
        environment="live",
        transport="remote_mcp",
        capabilities=("mcp.read.discovery",),
        readonly=True,
        config={"server": "test"},
    )
    monkeypatch.setattr("src.trading.connections.profile_by_id", lambda _: profile)
    assert profile.readonly is True
    assert profile.capabilities == ("mcp.read.discovery",)
    assert is_portfolio_connection_profile(profile) is False

    store = ConnectionStore(
        tmp_path / "connections.json",
        credential_store=CredentialStore(_MemoryCredentials()),
    )
    with pytest.raises(ValueError, match="not eligible"):
        store.create("ibkr-main", profile.id, "IBKR main")

    assert profile.id not in {row.get("id") for row in readonly_profile_catalog()}


def test_readonly_broker_sdk_profile_backs_a_portfolio_connection(tmp_path) -> None:
    """A read-only SDK profile that exposes both reads stays eligible."""
    profile = profile_by_id("binance-live-sdk-readonly")
    assert is_portfolio_connection_profile(profile) is True

    store = ConnectionStore(
        tmp_path / "connections.json",
        credential_store=CredentialStore(_MemoryCredentials()),
    )
    connection = store.create("main-binance", profile.id, "Main Binance")

    assert connection.profile_id == "binance-live-sdk-readonly"
    assert profile.id in {row.get("id") for row in readonly_profile_catalog()}
