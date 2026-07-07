from __future__ import annotations

import pytest

from src.governance.budget import BudgetExceeded, BudgetManager, BudgetSnapshot
from src.governance.manifest import RiskLevel


def test_budget_manager_tracks_tool_calls_and_network_calls() -> None:
    budget = BudgetManager(BudgetSnapshot(max_tool_calls=2, max_network_calls=1))

    budget.record_tool_call(risk_level=RiskLevel.R2_NETWORK)
    budget.record_tool_call(risk_level=RiskLevel.R0_READ)

    assert budget.snapshot.tool_calls == 2
    assert budget.snapshot.network_calls == 1


def test_budget_manager_rejects_tool_call_over_limit() -> None:
    budget = BudgetManager(BudgetSnapshot(max_tool_calls=1))

    budget.record_tool_call(risk_level=RiskLevel.R0_READ)

    with pytest.raises(BudgetExceeded):
        budget.record_tool_call(risk_level=RiskLevel.R0_READ)


def test_budget_manager_rejects_network_call_over_limit() -> None:
    budget = BudgetManager(BudgetSnapshot(max_network_calls=1))

    budget.record_tool_call(risk_level=RiskLevel.R2_NETWORK)

    with pytest.raises(BudgetExceeded):
        budget.record_tool_call(risk_level=RiskLevel.R2_NETWORK)


def test_budget_manager_tracks_artifacts_and_external_mcp() -> None:
    budget = BudgetManager(
        BudgetSnapshot(max_artifacts_written=1, max_external_mcp_calls=1)
    )

    budget.record_artifact_written(512)
    budget.record_external_mcp_call()

    assert budget.snapshot.artifacts_written == 1
    assert budget.snapshot.external_mcp_calls == 1
    with pytest.raises(BudgetExceeded):
        budget.record_artifact_written(1)
    with pytest.raises(BudgetExceeded):
        budget.record_external_mcp_call()
