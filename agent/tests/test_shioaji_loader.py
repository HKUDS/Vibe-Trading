"""Tests for the Task 7 shioaji loader skeleton."""

from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace
from unittest.mock import patch

from backtest.loaders.registry import FALLBACK_CHAINS, LOADER_REGISTRY, resolve_loader


def _reload_module():
    module = importlib.import_module("backtest.loaders.shioaji_loader")
    return importlib.reload(module)


def test_import_without_credentials_does_not_crash(monkeypatch) -> None:
    monkeypatch.delenv("SHIOAJI_API_KEY", raising=False)
    monkeypatch.delenv("SHIOAJI_SECRET_KEY", raising=False)

    module = _reload_module()

    assert module.DataLoader().is_available() is False


def test_is_available_false_when_key_missing(monkeypatch) -> None:
    monkeypatch.delenv("SHIOAJI_API_KEY", raising=False)
    monkeypatch.setenv("SHIOAJI_SECRET_KEY", "secret")

    module = _reload_module()

    assert module.DataLoader().is_available() is False


def test_is_available_false_when_secret_missing(monkeypatch) -> None:
    monkeypatch.setenv("SHIOAJI_API_KEY", "key")
    monkeypatch.delenv("SHIOAJI_SECRET_KEY", raising=False)

    module = _reload_module()

    assert module.DataLoader().is_available() is False


def test_is_available_true_with_stubbed_sdk_and_credentials(monkeypatch) -> None:
    class FakeShioaji:
        def __init__(self) -> None:
            self.created = True

    monkeypatch.setenv("SHIOAJI_API_KEY", "key")
    monkeypatch.setenv("SHIOAJI_SECRET_KEY", "secret")
    monkeypatch.setitem(sys.modules, "shioaji", SimpleNamespace(Shioaji=FakeShioaji))

    module = _reload_module()
    loader = module.DataLoader()

    assert loader.is_available() is True


def test_resolve_loader_can_pick_shioaji_without_real_account(monkeypatch) -> None:
    class FakeShioaji:
        def __init__(self) -> None:
            self.created = True

    monkeypatch.setenv("SHIOAJI_API_KEY", "key")
    monkeypatch.setenv("SHIOAJI_SECRET_KEY", "secret")
    monkeypatch.setitem(sys.modules, "shioaji", SimpleNamespace(Shioaji=FakeShioaji))

    from backtest.loaders import registry as reg

    monkeypatch.setattr(reg, "_registered", False)
    sys.modules.pop("backtest.loaders.shioaji_loader", None)
    with patch.dict(LOADER_REGISTRY, {}, clear=True):
        with patch.dict(FALLBACK_CHAINS, {"tw_stock": ["shioaji", "finmind"]}, clear=False):
            assert resolve_loader("tw_stock").name == "shioaji"
