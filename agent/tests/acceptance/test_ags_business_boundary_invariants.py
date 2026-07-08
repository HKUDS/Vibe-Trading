from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI

from src.alpha_foundry.forward.model import ForwardPlanFrozenError, ForwardTrackingPlan
from src.api.alpha_genesis_routes import register_alpha_genesis_routes


async def _noop_auth() -> None:
    return None


def test_business_boundary_truth_table_covers_required_hidden_surfaces() -> None:
    table_path = Path("docs/ags-business-boundary-truth-table.yaml")
    rows = json.loads(table_path.read_text(encoding="utf-8"))
    surfaces = {row["surface"] for row in rows}

    assert {
        "api",
        "cli",
        "frontend",
        "llm_caller",
        "mcp",
        "scheduler",
        "websocket",
        "upload",
        "artifact_cache",
    }.issubset(surfaces)
    assert all(row["allowed_side_effects"] in ([], ["read_local_artifact"]) for row in rows)
    assert all("live_order_write" in row["forbidden_side_effects"] for row in rows)


def test_alpha_genesis_routes_are_get_only_business_boundary() -> None:
    app = FastAPI()
    register_alpha_genesis_routes(app, require_auth=_noop_auth)

    for path, methods in app.openapi()["paths"].items():
        if "/api/alpha-genesis/" in path:
            assert set(methods) == {"get"}


def test_ags_modules_do_not_import_live_trading_or_runtime_wrappers() -> None:
    checked = [
        *Path("agent/src/alpha_foundry").rglob("*.py"),
        *Path("agent/src/alpha_quality").rglob("*.py"),
        *Path("agent/src/research_ledger").rglob("*.py"),
        Path("agent/src/api/alpha_genesis_routes.py"),
        Path("agent/cli/alpha_genesis.py"),
    ]
    forbidden = (
        "src.live",
        "src.trading",
        "ToolRegistry",
        "AgentLoop",
        "AgentContext",
        "SessionService",
        "place_order",
        "cancel_order",
        "kill_switch",
    )

    offenders: list[str] = []
    for path in checked:
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            if token in text:
                offenders.append(f"{path}:{token}")

    assert offenders == []


def test_forward_plan_state_machine_rejects_illegal_mutation_after_start() -> None:
    plan = ForwardTrackingPlan(
        plan_id="plan-1",
        factor_id="factor-1",
        hypothesis_id="hypothesis-1",
        accepted_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        frozen_factor_definition_hash="sha256:factor",
        frozen_config_hash="",
        observation_frequency="weekly",
        min_observations_required=12,
        expected_rank_ic=0.03,
    ).start()

    with pytest.raises(ForwardPlanFrozenError):
        plan.with_kill_rule_params({"consecutive_negative_ic_n": 99})
