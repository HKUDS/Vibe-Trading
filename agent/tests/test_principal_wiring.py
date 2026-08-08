"""The Principal must actually reach a stored Session.

`Session.owner` and `_validate_api_auth` returning a Principal were both added
without anything connecting them, so every session's owner was None. A field
that is always None carries the same information as no field, which is why the
wiring needs its own tests rather than relying on the unit tests of each half.
"""

from __future__ import annotations

import pathlib
import tempfile

import pytest
from fastapi.testclient import TestClient

from src.session.events import EventBus
from src.session.models import AuthMethod, Principal, Session
from src.session.service import SessionService
from src.session.store import SessionStore


def _service(root: pathlib.Path) -> SessionService:
    """Build a SessionService against a throwaway runtime root."""
    return SessionService(
        store=SessionStore(root / "sessions"),
        event_bus=EventBus(),
        runs_dir=root / "runs",
    )


@pytest.fixture
def runtime_root(monkeypatch):
    root = pathlib.Path(tempfile.mkdtemp())
    monkeypatch.setenv("VIBE_TRADING_HOME", str(root))
    return root


# --- the service accepts and stores an owner ---


def test_create_session_records_the_owner(runtime_root):
    service = _service(runtime_root)
    principal = Principal(subject="alice@example.com", auth_method=AuthMethod.FEDERATED_IDENTITY)

    session = service.create_session(title="owned", owner=principal)

    assert session.owner == principal
    assert session.owner.attributable is True


def test_create_session_without_an_owner_still_works(runtime_root):
    # The CLI and internal paths have no request context; None means "unknown".
    service = _service(runtime_root)
    assert service.create_session(title="cli").owner is None


def test_the_owner_survives_a_round_trip_through_the_store(runtime_root):
    service = _service(runtime_root)
    principal = Principal(
        subject="shared-key-holder", auth_method=AuthMethod.SHARED_KEY, tenant="desk-a"
    )
    created = service.create_session(title="persisted", owner=principal)

    # A fresh store reading from disk, not the in-memory object.
    reloaded = SessionStore(runtime_root / "sessions").get_session(created.session_id)

    assert reloaded is not None
    assert reloaded.owner == principal
    assert reloaded.owner.tenant == "desk-a"
    assert reloaded.owner.attributable is False


def test_a_session_stored_before_owners_existed_still_loads(runtime_root):
    # Backward compatibility: an on-disk record with no owner key at all.
    store = SessionStore(runtime_root / "sessions")
    legacy = Session(title="legacy")
    store.create_session(legacy)

    path = next((runtime_root / "sessions").rglob("session.json"))
    import json

    data = json.loads(path.read_text())
    data.pop("owner", None)
    path.write_text(json.dumps(data))

    reloaded = SessionStore(runtime_root / "sessions").get_session(legacy.session_id)
    assert reloaded is not None
    assert reloaded.owner is None


# --- the API route threads it through ---


def test_creating_a_session_over_http_records_how_it_was_authorised(runtime_root):
    import importlib

    import api_server

    importlib.reload(api_server)
    client = TestClient(api_server.app)

    response = client.post("/sessions", json={"title": "http owned", "config": {}})
    assert response.status_code == 201

    service = api_server._get_session_service()
    session = service.get_session(response.json()["session_id"])

    assert session.owner is not None
    assert session.owner.auth_method is AuthMethod.LOOPBACK_TRUST
    # The honesty invariant survives the whole path: loopback trust authorises
    # but does not identify, so nothing downstream may treat this as a person.
    assert session.owner.attributable is False


def test_require_auth_hands_back_a_principal(runtime_root):
    import asyncio

    from src.api.security import require_auth

    class _Req:
        method = "GET"
        headers: dict[str, str] = {}

        class client:  # noqa: N801
            host = "127.0.0.1"

    principal = asyncio.run(require_auth(_Req(), None))
    assert isinstance(principal, Principal)
    assert principal.attributable is False
