"""Contracts for resetting the cached IM channel runtime singleton."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import api_server
from src.api import state


class FakeSessionService:
    """SessionService placeholder for channel runtime reset tests."""


def _stub_channel_runtime_deps(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    config: dict[str, Any],
) -> None:
    """Isolate the runtime singleton from real config files and session stores.

    ``state._get_channel_runtime`` resolves ``load_channels_config`` and
    ``_get_session_service`` in its own module globals, so those are the
    attributes to patch (the ``api_server`` host attrs stay in play as the
    compatibility surface the function also consults).
    """
    import src.channels.config as channel_config
    import src.channels.pairing.store as pairing_store

    del tmp_path  # the config loader is stubbed; no file is read
    monkeypatch.setattr(channel_config, "load_channels_config", lambda: dict(config))
    monkeypatch.setattr(
        pairing_store, "_store_path", lambda: Path("unused-pairing.json")
    )

    monkeypatch.setattr(api_server, "_channel_runtime", None)
    monkeypatch.setattr(api_server, "_channel_bus", None)
    monkeypatch.setattr(api_server, "_channel_manager", None)

    monkeypatch.setattr(state, "_channel_runtime", None)
    monkeypatch.setattr(state, "_channel_bus", None)
    monkeypatch.setattr(state, "_channel_manager", None)
    monkeypatch.setattr(state, "_get_session_service", lambda: FakeSessionService())


def test_reset_channel_runtime_clears_globals_and_host_attrs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_channel_runtime_deps(
        tmp_path,
        monkeypatch,
        {"reply_timeout_s": 600.0, "telegram": {"enabled": False}},
    )

    runtime = state._get_channel_runtime()

    assert runtime is not None
    assert state._channel_runtime is runtime
    assert state._channel_bus is not None
    assert state._channel_manager is not None
    assert api_server._channel_runtime is runtime
    assert api_server._channel_bus is state._channel_bus
    assert api_server._channel_manager is state._channel_manager

    state.reset_channel_runtime()

    assert state._channel_runtime is None
    assert state._channel_bus is None
    assert state._channel_manager is None
    assert api_server._channel_runtime is None
    assert api_server._channel_bus is None
    assert api_server._channel_manager is None


def test_channel_runtime_rebuilds_from_current_config_after_reset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config: dict[str, Any] = {"reply_timeout_s": 600.0, "telegram": {"enabled": False}}
    _stub_channel_runtime_deps(tmp_path, monkeypatch, config)

    first = state._get_channel_runtime()
    assert first.config.reply_timeout_s == 600.0

    state.reset_channel_runtime()

    # The on-disk section changed while the singleton was down.
    config["reply_timeout_s"] = 42.0
    second = state._get_channel_runtime()

    assert second is not first
    assert second.config.reply_timeout_s == 42.0
    assert state._channel_runtime is second
    assert api_server._channel_runtime is second


def test_reset_channel_runtime_before_any_build_still_allows_a_build(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_channel_runtime_deps(
        tmp_path,
        monkeypatch,
        {"reply_timeout_s": 600.0, "telegram": {"enabled": False}},
    )

    state.reset_channel_runtime()

    assert api_server._channel_runtime is None
    runtime = state._get_channel_runtime()

    assert runtime is not None
    assert state._channel_runtime is runtime
