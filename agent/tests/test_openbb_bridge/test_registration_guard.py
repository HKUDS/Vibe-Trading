"""Regressions for the optional-extra registration guard.

``openbb-ai`` lives in the optional ``openbb`` extra, so ``api_server`` must come
up cleanly on a base install. These tests do not need the SDK — that is the
point — so they deliberately skip the module-level ``importorskip`` the rest of
the suite uses.
"""

from __future__ import annotations

import sys

import pytest
from fastapi import FastAPI

from src.openbb_bridge import try_register_openbb_routes


class _BlockOpenBBAI:
    """A meta-path finder that makes ``import openbb_ai`` fail as if absent."""

    def find_module(self, fullname, path=None):  # pragma: no cover - legacy API
        return None

    def find_spec(self, fullname, path=None, target=None):
        if fullname == "openbb_ai" or fullname.startswith("openbb_ai."):
            raise ModuleNotFoundError(f"No module named {fullname!r}")
        return None


@pytest.fixture
def without_openbb_ai(monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulate a base install with no ``openbb`` extra."""
    for name in list(sys.modules):
        if name.startswith("openbb_ai") or name.startswith("src.openbb_bridge."):
            monkeypatch.delitem(sys.modules, name)
    monkeypatch.setattr(sys, "meta_path", [_BlockOpenBBAI(), *sys.meta_path])


def test_registration_is_a_no_op_without_the_extra(without_openbb_ai: None):
    app = FastAPI()

    assert try_register_openbb_routes(app) is False
    assert not [route for route in app.routes if getattr(route, "path", "") == "/v1/query"]


def test_registration_mounts_both_routes_with_the_extra():
    pytest.importorskip("openbb_ai")
    app = FastAPI()
    # register_openbb_routes resolves auth off the host module, so import it.
    import api_server  # noqa: F401

    assert try_register_openbb_routes(app) is True
    paths = {getattr(route, "path", "") for route in app.routes}
    assert {"/agents.json", "/v1/query"} <= paths


def test_registration_failure_never_escapes(monkeypatch: pytest.MonkeyPatch):
    """A broken bridge must not take the core API down."""
    pytest.importorskip("openbb_ai")
    from src.openbb_bridge import routes as bridge_routes

    def _boom(app):
        raise RuntimeError("bridge exploded")

    monkeypatch.setattr(bridge_routes, "register_openbb_routes", _boom)

    assert try_register_openbb_routes(FastAPI()) is False
