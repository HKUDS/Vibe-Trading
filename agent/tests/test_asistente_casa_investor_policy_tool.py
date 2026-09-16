"""Regression tests for the Asistente Casa investor-policy agent bridge."""

from __future__ import annotations

import json

import pytest

from src.tools import build_registry
from src.tools import asistente_casa_investor_policy_tool as module
from src.tools.asistente_casa_investor_policy_tool import AsistenteCasaInvestorPolicyTool


class _Response:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self._body


def _policy():
    return {
        "schema": "asistente-casa.investor-policy.v1",
        "base_profile_id": 3,
        "tactical_profile_id": None,
        "targets": [
            {
                "dimension": "sector",
                "item_key": "Energia",
                "target_pct": 40,
                "min_pct": 30,
                "max_pct": 55,
                "hard_constraint": False,
                "enabled": True,
            }
        ],
    }


def test_tool_is_registered_and_readonly():
    registry = build_registry()
    tool = registry.get("asistente_casa_investor_policy")
    assert tool is not None
    assert tool.is_readonly is True


def test_tool_returns_canonical_policy(monkeypatch):
    monkeypatch.setenv("ASISTENTE_CASA_BASE_URL", "http://asistente-casa.test:8000")
    monkeypatch.setenv("ASISTENTE_CASA_API_KEY", "test-secret")

    seen = {}

    def fake_urlopen(request, timeout):
        seen["url"] = request.full_url
        seen["api_key"] = request.get_header("X-vibe-api-key")
        seen["timeout"] = timeout
        return _Response(_policy())

    monkeypatch.setattr(module, "urlopen", fake_urlopen)
    result = json.loads(AsistenteCasaInvestorPolicyTool().execute())

    assert result["status"] == "ok"
    assert result["source"] == "asistente-casa"
    assert result["policy"]["base_profile_id"] == 3
    assert result["policy"]["targets"][0]["max_pct"] == 55
    assert seen["url"].endswith("/inversiones/vibe/investor-policy")
    assert seen["api_key"] == "test-secret"


def test_tool_fails_closed_on_wrong_schema(monkeypatch):
    monkeypatch.setenv("ASISTENTE_CASA_BASE_URL", "http://asistente-casa.test:8000")
    monkeypatch.setenv("ASISTENTE_CASA_API_KEY", "test-secret")
    bad = _policy()
    bad["schema"] = "unexpected.v2"
    monkeypatch.setattr(module, "urlopen", lambda request, timeout: _Response(bad))

    with pytest.raises(RuntimeError, match="unexpected investor policy schema"):
        AsistenteCasaInvestorPolicyTool().execute()


def test_tool_fails_closed_when_targets_are_missing(monkeypatch):
    monkeypatch.setenv("ASISTENTE_CASA_BASE_URL", "http://asistente-casa.test:8000")
    monkeypatch.setenv("ASISTENTE_CASA_API_KEY", "test-secret")
    bad = _policy()
    bad["targets"] = []
    monkeypatch.setattr(module, "urlopen", lambda request, timeout: _Response(bad))

    with pytest.raises(RuntimeError, match="targets are missing"):
        AsistenteCasaInvestorPolicyTool().execute()
