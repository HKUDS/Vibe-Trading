"""Tests for the session Principal and the auth surface that produces it.

The point of these tests is not that a Principal exists. It is that the
Principal cannot claim an attribution the authentication layer did not earn --
which is the only thing that makes it better than no principal at all.
"""

from __future__ import annotations

import pytest

from src.api.security import LOOPBACK_SUBJECT, SHARED_KEY_SUBJECT
from src.session.models import (
    ATTRIBUTABLE_AUTH_METHODS,
    AuthMethod,
    Principal,
    Session,
    SessionStatus,
)


# --- the honesty invariant ---


def test_a_shared_key_principal_is_not_attributable():
    # Everyone holding the one static bearer key authenticates identically, so
    # no action taken under it can be attributed to a named human.
    principal = Principal(subject=SHARED_KEY_SUBJECT, auth_method=AuthMethod.SHARED_KEY)
    assert principal.attributable is False


def test_a_loopback_principal_is_not_attributable():
    principal = Principal(subject=LOOPBACK_SUBJECT, auth_method=AuthMethod.LOOPBACK_TRUST)
    assert principal.attributable is False


def test_only_federated_identity_is_attributable():
    assert ATTRIBUTABLE_AUTH_METHODS == frozenset({AuthMethod.FEDERATED_IDENTITY})
    named = Principal(subject="alice@example.com", auth_method=AuthMethod.FEDERATED_IDENTITY)
    assert named.attributable is True


def test_attributable_cannot_be_set_by_the_caller():
    # A caller-settable flag is a caller-settable lie.
    with pytest.raises(TypeError):
        Principal(  # type: ignore[call-arg]
            subject="alice",
            auth_method=AuthMethod.SHARED_KEY,
            attributable=True,
        )


def test_attributable_cannot_be_mutated_after_construction():
    principal = Principal(subject="x", auth_method=AuthMethod.SHARED_KEY)
    with pytest.raises(Exception):
        principal.attributable = True  # type: ignore[misc]


def test_a_tampered_stored_flag_is_recomputed_not_trusted():
    # A record written by an older version, or edited by hand, must not be able
    # to assert attribution its auth method never supported.
    forged = {
        "subject": "alice",
        "auth_method": AuthMethod.SHARED_KEY.value,
        "attributable": True,
        "tenant": None,
        "display_name": None,
    }
    assert Principal.from_dict(forged).attributable is False


def test_an_empty_subject_is_rejected():
    for bad in ("", "   "):
        with pytest.raises(ValueError, match="non-empty subject"):
            Principal(subject=bad, auth_method=AuthMethod.SHARED_KEY)


def test_unknown_auth_method_rejected():
    with pytest.raises(ValueError):
        Principal.from_dict({"subject": "a", "auth_method": "telepathy"})


# --- serialization round trip ---


def test_principal_round_trips_through_dict():
    original = Principal(
        subject="alice@example.com",
        auth_method=AuthMethod.FEDERATED_IDENTITY,
        tenant="desk-a",
        display_name="Alice",
    )
    restored = Principal.from_dict(original.to_dict())
    assert restored == original
    assert restored.attributable is True


def test_serialized_form_carries_attributable_explicitly():
    # A consumer reading the JSON must not have to know the enum table to learn
    # whether the identity is real.
    data = Principal(subject="x", auth_method=AuthMethod.SHARED_KEY).to_dict()
    assert data["attributable"] is False
    assert data["auth_method"] == "shared_key"


# --- Session integration, backward compatible ---


def test_a_session_without_an_owner_still_constructs():
    session = Session(title="legacy")
    assert session.owner is None


def test_an_old_serialized_session_with_no_owner_key_still_loads():
    old = {
        "session_id": "abc123",
        "title": "before principals existed",
        "status": "active",
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
        "last_attempt_id": None,
        "config": {},
    }
    session = Session.from_dict(old)
    assert session.owner is None
    assert session.status is SessionStatus.ACTIVE
    assert session.session_id == "abc123"


def test_a_session_with_an_owner_round_trips():
    principal = Principal(subject=SHARED_KEY_SUBJECT, auth_method=AuthMethod.SHARED_KEY)
    session = Session(title="owned", owner=principal)
    restored = Session.from_dict(session.to_dict())

    assert restored.owner == principal
    assert restored.owner is not None and restored.owner.attributable is False


def test_session_to_dict_is_json_serializable():
    import json

    session = Session(
        title="t",
        owner=Principal(subject="x", auth_method=AuthMethod.LOOPBACK_TRUST),
    )
    text = json.dumps(session.to_dict())
    assert '"attributable": false' in text


def test_unknown_owner_and_unattributable_owner_are_different_states():
    # None means "we do not know who"; an unattributable principal means "we
    # know the request was authorised but cannot name a person". Collapsing the
    # two would lose the distinction a governance review needs.
    unknown = Session(title="a")
    unattributable = Session(
        title="b", owner=Principal(subject=LOOPBACK_SUBJECT, auth_method=AuthMethod.LOOPBACK_TRUST)
    )
    assert unknown.owner is None
    assert unattributable.owner is not None
    assert unattributable.owner.attributable is False


# --- the auth surface returns one ---


def test_validate_api_auth_returns_a_shared_key_principal(monkeypatch):
    from src.api import security

    monkeypatch.setattr(security, "_configured_api_key", lambda: "secret-key")

    class _Cred:
        credentials = "secret-key"

    class _Req:
        method = "GET"
        headers: dict[str, str] = {}

        class client:  # noqa: N801
            host = "127.0.0.1"

    principal = security._validate_api_auth(request=_Req(), cred=_Cred())
    assert principal.auth_method is AuthMethod.SHARED_KEY
    assert principal.subject == SHARED_KEY_SUBJECT
    assert principal.attributable is False


def test_validate_api_auth_returns_a_loopback_principal_when_no_key(monkeypatch):
    from src.api import security

    monkeypatch.setattr(security, "_configured_api_key", lambda: "")
    monkeypatch.setattr(security, "_is_local_client", lambda request: True)

    class _Req:
        method = "GET"
        headers: dict[str, str] = {}

    principal = security._validate_api_auth(request=_Req(), cred=None)
    assert principal.auth_method is AuthMethod.LOOPBACK_TRUST
    assert principal.attributable is False


def test_a_bad_credential_still_raises_and_returns_no_principal(monkeypatch):
    from fastapi import HTTPException

    from src.api import security

    monkeypatch.setattr(security, "_configured_api_key", lambda: "secret-key")

    class _Cred:
        credentials = "wrong"

    class _Req:
        method = "GET"
        headers: dict[str, str] = {}

    with pytest.raises(HTTPException) as excinfo:
        security._validate_api_auth(request=_Req(), cred=_Cred())
    assert excinfo.value.status_code == 401
