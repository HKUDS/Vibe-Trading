from __future__ import annotations

import json

import pytest

from src.alpha_foundry.cases.ashare_liquidity_reversal import (
    TestSetAccessError,
    run_case_with_fixture,
)


def test_case_generates_controls_and_candidates(tmp_path) -> None:
    result = run_case_with_fixture(artifact_root=tmp_path)

    assert result.n_candidates >= 8
    assert "future_control" in result.control_ids
    assert "duplicate_control" in result.control_ids
    assert result.ledger.verify_hash_chain()
    assert len(result.ledger.query()) == result.n_candidates


def test_case_does_not_open_test_during_search() -> None:
    with pytest.raises(TestSetAccessError):
        run_case_with_fixture(force_test_access_in_search=True)


def test_case_outputs_required_artifacts(tmp_path) -> None:
    result = run_case_with_fixture(artifact_root=tmp_path)

    study_path = tmp_path / "alpha_genesis_case_study.json"
    report_path = tmp_path / "alpha_genesis_comparison_report.md"
    index_path = tmp_path / "candidate_pool.jsonl"

    assert study_path.exists()
    assert report_path.exists()
    assert index_path.exists()
    study = json.loads(study_path.read_text(encoding="utf-8"))
    assert study["n_candidates"] == result.n_candidates
    assert "not production-ready" in report_path.read_text(encoding="utf-8")
