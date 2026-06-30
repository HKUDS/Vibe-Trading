"""Tests for agent identity verification gate."""

import json
import time
import pytest

from agent.identity.verifier import (
    AgentCredential,
    AgentVerifier,
    StructuralVerifier,
    VerificationResult,
)
from agent.identity.gate import IdentityGate


def _make_token(
    agent_id="agent-1",
    role="quant_desk",
    permissions=None,
    expiry=None,
):
    return json.dumps({
        "agent_id": agent_id,
        "role": role,
        "permissions": permissions or ["read", "trade"],
        "expiry": expiry or (time.time() + 3600),
    })


class TestStructuralVerifier:
    def test_valid_token(self):
        v = StructuralVerifier()
        result = v.verify(_make_token())
        assert result.verified
        assert result.credential.agent_id == "agent-1"

    def test_invalid_json(self):
        v = StructuralVerifier()
        assert not v.verify("bad").verified

    def test_missing_expiry(self):
        v = StructuralVerifier()
        token = json.dumps({"agent_id": "a", "permissions": ["read"]})
        assert not v.verify(token).verified

    def test_expired(self):
        v = StructuralVerifier()
        assert not v.verify(_make_token(expiry=time.time() - 100)).verified


class TestIdentityGate:
    def test_disabled_allows_all(self):
        gate = IdentityGate(enabled=False)
        assert gate.check("", "buy") is None

    def test_enabled_requires_verifier(self):
        with pytest.raises(ValueError):
            IdentityGate(enabled=True)

    def test_missing_token_denied(self):
        gate = IdentityGate(verifier=StructuralVerifier(), enabled=True)
        err = gate.check("", "buy")
        assert err is not None
        assert "required" in err

    def test_valid_trade(self):
        gate = IdentityGate(verifier=StructuralVerifier(), enabled=True)
        err = gate.check(_make_token(permissions=["read", "trade"]), "buy")
        assert err is None

    def test_read_only_denied_trade(self):
        gate = IdentityGate(verifier=StructuralVerifier(), enabled=True)
        err = gate.check(_make_token(permissions=["read"]), "sell")
        assert err is not None
        assert "trade" in err

    def test_admin_denied_for_trader(self):
        gate = IdentityGate(verifier=StructuralVerifier(), enabled=True)
        err = gate.check(_make_token(permissions=["read", "trade"]), "halt_trading")
        assert err is not None
        assert "admin" in err

    def test_decisions_logged(self):
        gate = IdentityGate(verifier=StructuralVerifier(), enabled=True)
        gate.check(_make_token(), "buy")
        assert len(gate.decisions) == 1
        assert gate.decisions[0]["decision"] == "allow"
