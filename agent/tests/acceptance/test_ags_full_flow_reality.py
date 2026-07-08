from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.alpha_foundry.reports.builder import build_alpha_genesis_report
from src.alpha_quality.decision.model import AlphaQualityDecisionContext, QualityDecision
from src.alpha_quality.decision.runner import QualityDecisionRunner
from src.alpha_quality.model import AlphaQualityScorecard, ExecutionMetrics
from src.api.alpha_genesis_routes import register_alpha_genesis_routes
from src.research_ledger.data_snapshot import build_data_snapshot
from src.research_ledger.trial_ledger import TrialLedger, TrialLedgerEntry


async def _noop_auth() -> None:
    return None


def _scorecard() -> AlphaQualityScorecard:
    return AlphaQualityScorecard(
        factor_id="candidate-full-flow",
        formula="rank(delta(close, 1))",
        factor_definition_hash="sha256:factor",
        scope="final_quality_decision",
        horizons=[1, 5],
        execution=ExecutionMetrics(
            uses_execution_return=True,
            return_mean=0.012,
            turnover_mean=0.25,
            cost_bps_mean=2.0,
        ),
        data_snapshot_ref="sha256:snapshot",
        trial_ledger_ref="ledger:full-flow",
    )


def _entry(trial_id: str, status: str, decision: str) -> TrialLedgerEntry:
    return TrialLedgerEntry(
        trial_id=trial_id,
        trial_group_id="group-full-flow",
        parent_trial_id=None,
        candidate_id="candidate-full-flow",
        parent_seed_id="seed-1",
        formula="rank(delta(close, 1))",
        formula_hash="sha256:formula",
        data_snapshot_hash="sha256:snapshot",
        universe_hash="sha256:universe",
        split_id="train_valid",
        data_scope="train_valid",
        search_space_hash="sha256:space",
        objective="marginal_net_portfolio_value",
        random_seed=7,
        n_candidates_seen_so_far=1,
        status=status,  # type: ignore[arg-type]
        decision=decision,  # type: ignore[arg-type]
        reason_codes=[],
        metrics_summary={"rank_ic": 0.03},
        previous_entry_hash=None,
        entry_hash="",
        created_at=datetime(2025, 1, 1, tzinfo=timezone.utc).isoformat(),
    )


def test_alpha_genesis_full_flow_uses_production_builders_and_redacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    panel = {
        "close": pd.DataFrame(
            {"AAA": [10.0, 10.4], "BBB": [20.0, 19.8]},
            index=pd.date_range("2025-01-01", periods=2, freq="D"),
        ),
        "_meta": {
            "calendar": "SSE",
            "timezone": "Asia/Shanghai",
            "pit_contract_present": True,
            "survivorship_bias": False,
        },
    }
    snapshot = build_data_snapshot(
        panel,
        universe="fixture",
        period="2025-01",
        source_config={"api_key": "sk-live-secret", "provider": "fixture"},
    )

    ledger = TrialLedger(tmp_path / "ledger.sqlite")
    for status, decision in (
        ("success", "candidate_zoo"),
        ("reject", "reject"),
        ("skip", "none"),
        ("error", "none"),
    ):
        ledger.append(_entry(f"trial-{status}", status, decision))
    assert ledger.verify_hash_chain()

    scorecard = _scorecard()
    decision = QualityDecisionRunner().run(
        scorecard,
        AlphaQualityDecisionContext(
            trial_entries=ledger.query(),
            pit_contract_present=snapshot.pit_contract_present,
            survivorship_bias=snapshot.survivorship_bias,
            total_quality_score=0.55,
        ),
    )
    assert decision.decision == QualityDecision.CANDIDATE_ZOO

    report = build_alpha_genesis_report(
        report_id="full-flow",
        scorecard=scorecard,
        decision=decision,
        trial_entries=ledger.query(),
        data_snapshot=snapshot.to_dict(),
        source_config={"api_key": "sk-live-secret"},
    )
    payload = report.to_dict()
    encoded = report.to_json()

    assert payload["schema_version"] == "alpha_genesis_report.v1"
    assert payload["trial_count"] == 4
    assert payload["data_snapshot_hash"].startswith("sha256:")
    assert "sk-live-secret" not in encoded
    assert "production-ready" in encoded
    assert "not production-ready" in encoded
    assert "live-ready" not in encoded

    report_root = tmp_path / "reports"
    report_root.mkdir()
    (report_root / "full-flow.json").write_text(report.to_json(), encoding="utf-8")
    (report_root / "candidate-full-flow.scorecard.json").write_text(scorecard.to_json(), encoding="utf-8")
    (report_root / "candidate-full-flow.decision.json").write_text(decision.to_json(), encoding="utf-8")
    monkeypatch.setenv("VIBE_TRADING_ALPHA_GENESIS_REPORT_DIR", str(report_root))

    app = FastAPI()
    register_alpha_genesis_routes(app, require_auth=_noop_auth)
    client = TestClient(app)

    response = client.get("/api/alpha-genesis/reports/full-flow")

    assert response.status_code == 200
    assert response.headers["cache-control"].startswith("no-store")
    body = response.json()
    assert body["decision"] == "candidate_zoo"
    assert "sk-live-secret" not in json.dumps(body)
