from __future__ import annotations

from examples.alpha_genesis_demos.orthogonal_liquidity_reversal_candidate.runner import run_demo


def test_orthogonal_liquidity_reversal_candidate_is_narrow_candidate() -> None:
    result = run_demo(dry_run=True)

    assert result["snapshot_match"]
    assert result["decision"] in {"candidate_zoo", "paper_candidate"}
    assert result["hard_failures"] == []
    assert result["synergy_metrics"]["delta_ir"] > 0
    assert result["decision"] != "production_ready"
