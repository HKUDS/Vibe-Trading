"""The model-governance fields must be reachable through the SDM tools.

`ModelRecord` existed as a tested store schema while the three agent-facing SDM
tools exposed none of it, so an agent registering a factor could not record an
owner, a validator or a limitation even though the columns were there. A
governance field nothing can write to is the same as no governance field.
"""

from __future__ import annotations

import json
import pathlib
import tempfile

import pytest


@pytest.fixture
def tools(monkeypatch):
    """Fresh store per test, so registrations cannot leak between them."""
    db = pathlib.Path(tempfile.mkdtemp()) / "store.db"
    monkeypatch.setenv("VIBE_TRADING_STRATEGY_STORE_DB_PATH", str(db))
    import src.strategy_store._shared as shared

    monkeypatch.setattr(shared, "_STORE", None, raising=False)
    from src.tools.sdm_register_tool import SdmRegisterTool
    from src.tools.sdm_status_tool import SdmStatusTool

    return SdmRegisterTool(), SdmStatusTool()


def _register(reg, **kwargs):
    base = {"artifact_type": "factor", "universe": "csi300"}
    base.update(kwargs)
    return json.loads(reg.execute(**base))


def _detail(status, artifact_id):
    return json.loads(status.execute(action="detail", artifact_id=artifact_id))["artifact"]


# --- an artifact with no governance data says so ---


def test_an_artifact_without_governance_is_reported_as_unregistered(tools):
    reg, status = tools
    result = _register(reg, name="plain")
    assert result["status"] == "ok"

    governance = _detail(status, result["artifact"]["id"])["governance"]
    assert governance["registered"] is False
    assert "unregistered model" in governance["note"]


def test_the_governance_block_is_present_even_when_empty(tools):
    # Omitting the block when there is nothing in it would hide the finding.
    reg, status = tools
    result = _register(reg, name="plain2")
    assert "governance" in _detail(status, result["artifact"]["id"])


# --- intended_use and limitations are mandatory once any field is claimed ---


@pytest.mark.parametrize(
    "partial",
    [
        {"developer": "alice"},
        {"owner": "bob"},
        {"model_tier": "tier_1_critical"},
        {"intended_use": "x"},          # limitations missing
        {"limitations": "y"},           # intended_use missing
        {"validator": "carol", "approver": "dave"},
    ],
)
def test_partial_governance_is_refused(tools, partial):
    reg, _ = tools
    result = _register(reg, name=f"partial_{abs(hash(str(partial)))}", **partial)
    assert result["status"] == "error"
    assert "intended_use" in result["error"] or "limitations" in result["error"]


def test_a_complete_registration_is_accepted_and_stored(tools):
    reg, status = tools
    result = _register(
        reg,
        name="complete",
        developer="alice",
        owner="bob",
        validator="carol",
        approver="dave",
        model_tier="tier_2_significant",
        intended_use="CSI300 cross-sectional stock selection",
        limitations="not valid below 50m average daily turnover",
    )
    assert result["status"] == "ok"

    artifact = _detail(status, result["artifact"]["id"])
    assert artifact["model_tier"] == "tier_2_significant"
    assert artifact["validation_status"] == "unvalidated"
    assert artifact["limitations"].startswith("not valid below")
    assert artifact["governance"]["registered"] is True


# --- four eyes ---


def test_developer_approving_their_own_model_is_flagged(tools):
    reg, status = tools
    result = _register(
        reg, name="selfapproved", developer="alice", approver="alice",
        intended_use="x", limitations="y",
    )
    governance = _detail(status, result["artifact"]["id"])["governance"]
    assert governance["four_eyes_violation"] is True
    assert "same person" in governance["note"]


def test_two_different_people_are_not_flagged(tools):
    reg, status = tools
    result = _register(
        reg, name="twoperson", developer="alice", approver="bob",
        intended_use="x", limitations="y",
    )
    assert _detail(status, result["artifact"]["id"])["governance"]["four_eyes_violation"] is False


def test_a_four_eyes_violation_is_reported_not_refused(tools):
    # Whether to block self-approval is firm policy, not this tool's call. It
    # must be visible, and it must not be silently prevented either.
    reg, _ = tools
    result = _register(
        reg, name="allowed", developer="alice", approver="alice",
        intended_use="x", limitations="y",
    )
    assert result["status"] == "ok"


# --- state machine ---


def test_registering_straight_into_approved_is_refused(tools):
    reg, _ = tools
    result = _register(
        reg, name="jump", developer="a", approver="b",
        intended_use="x", limitations="y", validation_status="approved",
    )
    assert result["status"] == "error"
    assert "approved" in result["error"].lower()


def test_registering_as_in_validation_is_allowed(tools):
    reg, status = tools
    result = _register(
        reg, name="inval", developer="a", approver="b",
        intended_use="x", limitations="y", validation_status="in_validation",
    )
    assert result["status"] == "ok"
    assert _detail(status, result["artifact"]["id"])["validation_status"] == "in_validation"


def test_an_unknown_tier_is_refused(tools):
    reg, _ = tools
    result = _register(
        reg, name="badtier", model_tier="tier_9_imaginary",
        intended_use="x", limitations="y",
    )
    assert result["status"] == "error"


# --- the schema itself must advertise the fields ---


def test_every_governance_field_is_in_the_tool_schema(tools):
    reg, _ = tools
    properties = reg.parameters["properties"]
    for field in reg._GOVERNANCE_FIELDS:
        assert field in properties, f"{field} is not reachable through the tool schema"


def test_validation_date_is_never_auto_filled(tools):
    # Stamping a validation date on a model nobody validated fabricates exactly
    # the evidence the field exists to carry.
    reg, status = tools
    result = _register(
        reg, name="nodate", developer="a", approver="b",
        intended_use="x", limitations="y",
    )
    assert _detail(status, result["artifact"]["id"])["validation_date"] is None
