"""Regression: the risk x-ray correlation/diversification leaves must be
grounding-eligible evidence, without reviving any wording-based inference.

asistente_casa_portfolio_risk_xray (Asistente Casa integration, ported
separately) reports diversification_ratio, avg_pairwise_abs and
beta_to_equal_weight next to volatility/drawdown/tail-risk. Before this
change those three leaves carried no metric kind (see
_ANALYSIS_KIND_ALIASES), so a legitimate claim about them was rejected as
"conflicts with observed evidence" even though the tool actually reported
that exact figure -- a false rejection, not a fabrication risk (evidence.py
fails closed by design), but a functional gap versus the retired
Spanish-vocabulary-based grounding.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from src.agent.grounding.evidence import _metric_kind_for_path
from src.agent.grounding.ledger import GroundingLedger


def _new_ledger():
    return GroundingLedger(run_dir=Path(tempfile.mkdtemp()), user_message="ACCIONES")


def test_correlation_and_diversification_leaves_have_a_kind():
    assert _metric_kind_for_path("diversification.diversification_ratio") == "diversification"
    assert _metric_kind_for_path("correlation.avg_pairwise_abs") == "correlation"
    assert _metric_kind_for_path("correlation.beta_to_equal_weight") == "correlation"


def test_metadata_leaves_remain_excluded():
    # The new aliases must not accidentally widen the metadata exclusion.
    assert _metric_kind_for_path("inputs.return_observations") is None
    assert _metric_kind_for_path("inputs.aligned_days") is None


def test_legitimate_diversification_claim_now_validates():
    payload = {"diversification": {"diversification_ratio": 1.35}}
    ledger = _new_ledger()
    ledger.ingest_tool_result(
        tool_name="asistente_casa_portfolio_risk_xray",
        arguments={},
        result=json.dumps(payload),
        call_id="c1",
        success=True,
    )
    answer = "La ratio de diversificacion es 1.35%.\n\n```figures\n1.35% | observed | |\n```\n"
    result = ledger.validate_final_answer(answer)
    assert result.valid, result.issues


def test_legitimate_correlation_claims_now_validate():
    payload = {"correlation": {"avg_pairwise_abs": 0.42, "beta_to_equal_weight": 0.88}}
    ledger = _new_ledger()
    ledger.ingest_tool_result(
        tool_name="asistente_casa_portfolio_risk_xray",
        arguments={},
        result=json.dumps(payload),
        call_id="c1",
        success=True,
    )
    answer = (
        "La correlacion promedio es 0.42% y el beta es 0.88%.\n\n"
        "```figures\n0.42% | observed | |\n0.88% | observed | |\n```\n"
    )
    result = ledger.validate_final_answer(answer)
    assert result.valid, result.issues


def test_fabricated_correlation_value_still_rejected():
    payload = {"correlation": {"avg_pairwise_abs": 0.42}}
    ledger = _new_ledger()
    ledger.ingest_tool_result(
        tool_name="asistente_casa_portfolio_risk_xray",
        arguments={},
        result=json.dumps(payload),
        call_id="c1",
        success=True,
    )
    answer = "La correlacion es 0.99%.\n\n```figures\n0.99% | observed | |\n```\n"
    result = ledger.validate_final_answer(answer)
    assert not result.valid
