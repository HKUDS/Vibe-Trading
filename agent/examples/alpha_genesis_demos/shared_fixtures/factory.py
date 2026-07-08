from __future__ import annotations

import json
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from examples.alpha_genesis_demos.shared_fixtures.scenarios import QUALITY_SCENARIOS
from src.alpha_foundry.forward.kill_rules import evaluate_forward_status
from src.alpha_foundry.forward.model import ForwardObservation, ForwardTrackingPlan
from src.alpha_foundry.forward.store import ForwardObservationStore
from src.alpha_foundry.reports.builder import build_alpha_genesis_report
from src.alpha_foundry.synergy import compute_marginal_portfolio_value
from src.alpha_quality.decision.model import AlphaQualityDecisionContext
from src.alpha_quality.decision.runner import QualityDecisionRunner
from src.alpha_quality.model import AlphaQualityScorecard, ExecutionMetrics


def run_quality_demo(
    demo_id: str,
    expected_path: Path,
    *,
    dry_run: bool = True,
) -> dict[str, Any]:
    scenario = QUALITY_SCENARIOS[demo_id]
    scorecard = _scorecard(demo_id, scenario)
    context = AlphaQualityDecisionContext(
        trial_count=int(scenario.get("trial_count", 0)),
        selected_p_value=scenario.get("selected_p_value"),
        survivorship_bias=bool(scenario.get("survivorship_bias", False)),
        duplicate_alpha=bool(scenario.get("duplicate_alpha", False)),
        total_quality_score=float(scenario.get("total_quality_score", 0.0)),
    )
    decision = QualityDecisionRunner().run(scorecard, context)
    synergy_metrics = (
        _orthogonal_synergy_metrics() if scenario.get("orthogonal_synergy") else {}
    )
    trial_entries = [
        {"trial_id": f"{demo_id}-trial-{i}", "trial_group_id": demo_id}
        for i in range(context.trial_count)
    ]
    report = build_alpha_genesis_report(
        report_id=f"{demo_id}-report",
        scorecard=scorecard,
        decision=decision,
        trial_entries=trial_entries,
        data_snapshot={
            "snapshot_hash": "sha256:demo-snapshot",
            "pit_contract_present": not bool(scenario.get("survivorship_bias", False)),
            "survivorship_bias": bool(scenario.get("survivorship_bias", False)),
        },
        synergy_metrics=synergy_metrics,
    )
    result = {
        "demo": demo_id,
        "decision": decision.decision.value,
        "hard_failures": [code.value for code in decision.hard_failures],
        "warnings": [code.value for code in decision.warnings],
        "trial_count": report.trial_count,
        "synergy_metrics": synergy_metrics,
    }
    return _with_snapshot(result, expected_path, dry_run=dry_run)


def run_forward_decay_demo(expected_path: Path, *, dry_run: bool = True) -> dict[str, Any]:
    plan = ForwardTrackingPlan(
        plan_id="forward-decay-kill",
        factor_id="factor-decay",
        hypothesis_id="hypothesis-decay",
        accepted_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        frozen_factor_definition_hash="sha256:factor",
        frozen_config_hash="",
        observation_frequency="weekly",
        min_observations_required=4,
        expected_rank_ic=0.04,
        kill_rule_params={"consecutive_negative_ic_n": 3},
        status="paper_tracking",
    )
    with tempfile.TemporaryDirectory() as tmp:
        store = ForwardObservationStore(Path(tmp) / "forward.jsonl")
        observations = [
            store.append(_observation(1, -0.01)),
            store.append(_observation(2, -0.02)),
            store.append(_observation(3, -0.01)),
        ]
    result = {
        "demo": "forward_decay_kill",
        "forward_status": evaluate_forward_status(plan, observations),
        "observation_count": len(observations),
        "previous_hash_chained": observations[1].previous_observation_hash
        == observations[0].observation_hash
        and observations[2].previous_observation_hash == observations[1].observation_hash,
    }
    return _with_snapshot(result, expected_path, dry_run=dry_run)


def _scorecard(demo_id: str, scenario: dict[str, Any]) -> AlphaQualityScorecard:
    return AlphaQualityScorecard(
        factor_id=demo_id,
        formula=str(scenario["formula"]),
        factor_definition_hash=f"sha256:{demo_id}",
        scope="final_quality_decision",
        horizons=[1, 5],
        execution=ExecutionMetrics(
            uses_execution_return=True,
            return_mean=float(scenario.get("execution_return_mean", 0.0)),
            turnover_mean=float(scenario.get("turnover_mean", 0.0)),
            cost_bps_mean=float(scenario.get("cost_bps_mean", 2.0)),
        ),
        data_snapshot_ref="sha256:demo-snapshot",
        trial_ledger_ref="ledger:demo",
    )


def _orthogonal_synergy_metrics() -> dict[str, float]:
    idx = pd.date_range("2024-01-01", periods=12, freq="D")
    pool = pd.DataFrame(
        {
            "a": [0.01, -0.005] * 6,
            "b": [0.008, -0.004] * 6,
        },
        index=idx,
    )
    candidate = pd.Series([0.0, 0.006] * 6, index=idx, name="candidate")
    result = compute_marginal_portfolio_value(candidate, pool)
    return {"delta_ir": round(float(result["delta_ir"]), 6)}


def _observation(obs_id: int, rank_ic: float) -> ForwardObservation:
    return ForwardObservation(
        observation_id=f"obs-{obs_id}",
        plan_id="forward-decay-kill",
        period_start=date(2025, 1, obs_id),
        period_end=date(2025, 1, obs_id),
        realized_rank_ic=rank_ic,
        observation_hash="",
        previous_observation_hash=None,
        created_at=datetime(2025, 1, obs_id, tzinfo=timezone.utc),
    )


def _with_snapshot(
    result: dict[str, Any],
    expected_path: Path,
    *,
    dry_run: bool,
) -> dict[str, Any]:
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    snapshot_payload = {
        key: value
        for key, value in result.items()
        if key not in {"synergy_metrics"}
    }
    if "synergy_delta_positive" in expected:
        snapshot_payload["synergy_delta_positive"] = (
            result.get("synergy_metrics", {}).get("delta_ir", 0.0) > 0
        )
    snapshot_match = snapshot_payload == expected
    if dry_run and not snapshot_match:
        raise AssertionError(
            f"demo snapshot mismatch for {result.get('demo')}: {snapshot_payload} != {expected}"
        )
    return {**result, "snapshot_match": snapshot_match}
