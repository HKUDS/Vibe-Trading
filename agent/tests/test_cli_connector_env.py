"""Regression (#901): the ``connector`` CLI path must load ``~/.vibe-trading/.env``.

``EnvConfig`` reads only ``os.environ``; ``_ensure_dotenv()`` is what populates it
from ``~/.vibe-trading/.env``. ``main()`` routes the ``connector`` group straight to
``_dispatch_connector`` without the interactive TUI's preflight, so nothing loaded
the file — and every connector resolving credentials through ``get_env_config()``
(Longbridge's app key / secret / access token, Futu's ``FUTU_TRADE_PWD_MD5``)
reported them as missing despite a valid file on disk.
"""

from __future__ import annotations

import argparse

import pytest

from cli import _legacy

pytestmark = pytest.mark.unit

_CREDENTIAL_ENV_VARS = (
    "LONGBRIDGE_APP_KEY",
    "LONGBRIDGE_APP_SECRET",
    "LONGBRIDGE_ACCESS_TOKEN",
)


def test_dispatch_connector_loads_dotenv_before_running_the_subcommand(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The dotenv load must happen before the subcommand reads any config."""
    calls: list[str] = []

    def _record_list() -> int:
        calls.append("list")
        return 0

    monkeypatch.setattr(
        "src.providers.llm._ensure_dotenv", lambda: calls.append("dotenv")
    )
    monkeypatch.setattr(_legacy, "cmd_connector_list", _record_list)

    assert (
        _legacy._dispatch_connector(argparse.Namespace(connector_command="list")) == 0
    )
    assert calls == ["dotenv", "list"]


def test_connector_path_resolves_longbridge_credentials_from_dotenv(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Credentials living only in the ``.env`` file resolve after a dispatch."""
    from src.trading.connectors.longbridge.credentials import (
        resolve_longbridge_credentials,
    )

    env_file = tmp_path / ".env"
    env_file.write_text(
        "LONGBRIDGE_APP_KEY=key-from-file\n"
        "LONGBRIDGE_APP_SECRET=secret-from-file\n"
        "LONGBRIDGE_ACCESS_TOKEN=token-from-file\n",
        encoding="utf-8",
    )
    # An empty runtime root keeps the legacy ``longbridge.json`` out of the
    # resolution, so the environment is the only possible source.
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()

    for name in _CREDENTIAL_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("src.providers.llm._ENV_CANDIDATES", [env_file])
    monkeypatch.setattr("src.providers.llm._dotenv_loaded", False)
    monkeypatch.setattr(_legacy, "cmd_connector_list", lambda: 0)

    before = resolve_longbridge_credentials(runtime_root=runtime_root)
    assert before.credentials is None, "precondition: credentials must start unset"

    _legacy._dispatch_connector(argparse.Namespace(connector_command="list"))

    after = resolve_longbridge_credentials(runtime_root=runtime_root)
    assert after.source == "environment"
    assert after.missing_fields == ()
    assert after.credentials is not None
    assert after.credentials.app_key == "key-from-file"


def test_dispatch_connector_never_overrides_a_real_environment_variable(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """``override=False``: an exported variable outranks the ``.env`` file."""
    from src.trading.connectors.longbridge.credentials import (
        resolve_longbridge_credentials,
    )

    env_file = tmp_path / ".env"
    env_file.write_text(
        "LONGBRIDGE_APP_KEY=key-from-file\n"
        "LONGBRIDGE_APP_SECRET=secret-from-file\n"
        "LONGBRIDGE_ACCESS_TOKEN=token-from-file\n",
        encoding="utf-8",
    )
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()

    monkeypatch.setenv("LONGBRIDGE_APP_KEY", "key-from-shell")
    monkeypatch.delenv("LONGBRIDGE_APP_SECRET", raising=False)
    monkeypatch.delenv("LONGBRIDGE_ACCESS_TOKEN", raising=False)
    monkeypatch.setattr("src.providers.llm._ENV_CANDIDATES", [env_file])
    monkeypatch.setattr("src.providers.llm._dotenv_loaded", False)
    monkeypatch.setattr(_legacy, "cmd_connector_list", lambda: 0)

    _legacy._dispatch_connector(argparse.Namespace(connector_command="list"))

    resolution = resolve_longbridge_credentials(runtime_root=runtime_root)
    assert resolution.credentials is not None
    assert resolution.credentials.app_key == "key-from-shell"
    assert resolution.credentials.app_secret == "secret-from-file"
