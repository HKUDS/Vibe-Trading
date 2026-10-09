"""Tests for the registry-only mStock read-only first cut (#1367)."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from src.trading import profiles, service
from src.trading.connections import is_portfolio_connection_profile

pytestmark = pytest.mark.unit

_CONNECTOR_ROOT = Path(__file__).resolve().parents[1] / "src" / "trading" / "connectors" / "mstock"
_PROFILE_ID = "mstock-live-rest-readonly"


def test_mstock_profile_is_registered_and_readonly() -> None:
    profile = profiles.profile_by_id(_PROFILE_ID)

    assert profile.connector == "mstock"
    assert profile.environment == "live"
    assert profile.transport == "broker_sdk"
    assert profile.readonly is True
    assert profile.config == {"auth_flavor": "typeb"}
    assert profile.capabilities == ("account.read", "positions.read")
    assert is_portfolio_connection_profile(profile) is True


def test_mstock_profile_has_no_order_path_capability() -> None:
    profile = profiles.profile_by_id(_PROFILE_ID)
    declared = {p.id for p in profiles.list_profiles() if p.connector == "mstock"}

    assert declared == {_PROFILE_ID}
    assert not any(
        capability.startswith(("orders.", "runner.", "positions.close."))
        for capability in profile.capabilities
    )
    assert "orders.place" not in profile.capabilities
    assert "orders.place.requires_mandate" not in profile.capabilities


@pytest.mark.parametrize("operation", ["place_order", "cancel_order"])
def test_mstock_order_service_refuses_before_a_connector_sdk(operation: str) -> None:
    result = getattr(service, operation)(
        "RELIANCE",
        _PROFILE_ID,
        side="buy" if operation == "place_order" else None,
        quantity=1,
    )

    assert result["status"] == "error"
    assert result["profile_id"] == _PROFILE_ID
    assert result["connector"] == "mstock"
    assert result["environment"] == "live"
    assert "does not support orders." in result["error"]


def test_mstock_is_bounded_live_not_paper_capped() -> None:
    tier_path = _CONNECTOR_ROOT.parents[3] / "tests" / "test_paper_capped_connectors_refuse_live.py"
    tree = ast.parse(tier_path.read_text(encoding="utf-8"))
    tiers = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not isinstance(target, ast.Name) or target.id not in {"_LIVE_CAPABLE", "_PAPER_CAPPED"}:
                continue
            value = node.value
            if isinstance(value, ast.Call) and getattr(value.func, "id", "") == "frozenset":
                value = value.args[0]
            tiers[target.id] = frozenset(ast.literal_eval(value))

    assert "mstock" in tiers["_LIVE_CAPABLE"]
    assert "mstock" not in tiers["_PAPER_CAPPED"]


def test_first_cut_adds_no_http_auth_or_order_surface() -> None:
    assert not (_CONNECTOR_ROOT / "sdk.py").exists()
    for path in _CONNECTOR_ROOT.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        function_names = {
            node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        imported_roots = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_roots.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_roots.add(node.module.split(".")[0])

        assert not function_names & {"place_order", "cancel_order", "authenticate"}
        assert not imported_roots & {"httpx", "requests", "aiohttp", "urllib"}
