"""Regression tests: local connector profiles auto-resolve a single connection.

The CLI and agent trading tools never carry a ``connection_id``; service-level
local-plugin calls must therefore resolve the operator's single installed
connection for a profile, and refuse ambiguous setups instead of guessing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.trading.connections import ConnectionStore
from src.trading.service import check_connection

_ADAPTER = """\
def check_status(*, credentials, config):
    return {"status": "ok", "configured": bool(credentials), "readonly": True}


def get_account_snapshot(*, credentials, config):
    return {"status": "ok"}


def get_positions(*, credentials, config):
    return {"status": "ok", "positions": []}
"""

_MANIFEST: dict[str, Any] = {
    "schema_version": 1,
    "profile": {
        "id": "fake-live-readonly",
        "connector": "fake",
        "label": "Fake Live · Local Read-Only",
        "environment": "live",
        "readonly": True,
        "capabilities": ["account.read", "positions.read"],
    },
    "entrypoint": "adapter.py",
    "auth": {
        "type": "token",
        "fields": [
            {"name": "api_token", "label": "Token", "secret": True, "required": True}
        ],
    },
}


@pytest.fixture()
def runtime_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "runtime"
    root.mkdir()
    monkeypatch.setattr("src.trading.connections.get_runtime_root", lambda: root)
    monkeypatch.setattr("src.trading.local_plugins.get_runtime_root", lambda: root)
    plugin_dir = root / "connectors" / "fake"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "connector.json").write_text(
        json.dumps(_MANIFEST), encoding="utf-8"
    )
    (plugin_dir / "adapter.py").write_text(_ADAPTER, encoding="utf-8")
    return root


def test_auto_resolves_single_connection(runtime_root: Path) -> None:
    ConnectionStore().create("fake-main", "fake-live-readonly", "Fake")
    report = check_connection("fake-live-readonly")
    assert report["status"] == "ok"
    assert report["configured"] is False


def test_ambiguous_connections_require_explicit_id(runtime_root: Path) -> None:
    store = ConnectionStore()
    store.create("fake-a", "fake-live-readonly", "A")
    store.create("fake-b", "fake-live-readonly", "B")
    with pytest.raises(ValueError, match="connection_id"):
        check_connection("fake-live-readonly")
