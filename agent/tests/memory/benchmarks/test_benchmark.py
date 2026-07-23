"""Pytest integration for P@5 evaluation benchmark.

Tests validate that the Treatment mode (importance decay + quality scoring)
delivers measurable improvement over the Baseline mode (pure relevance).

This benchmark suite is NOT intended for CI. It requires corpus files
(``tmp/benchmark_corpus/``) that are not version-controlled. The suite
automatically skips when corpus files are absent.

Usage:
    python -m pytest agent/tests/memory/benchmarks/ -v
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from .runner import (
    ABResult,
    generate_report,
    load_corpus,
    load_queries,
    retrieve_top_k,
    run_ab_comparison,
    tokenize,
)
from .metrics import mean_reciprocal_rank, ndcg_at_k, precision_at_k

# Project root for report output
PROJECT_ROOT = Path(__file__).resolve().parents[4]
REPORT_PATH = PROJECT_ROOT / "bench_report.json"


# ---------------------------------------------------------------------------
# Shared result (computed once per session)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def ab_result(
    memories_corpus: list[dict[str, Any]], queries_dataset: list[dict[str, Any]]
) -> ABResult:
    """Run A/B comparison once and share across all tests."""
    return run_ab_comparison(memories_corpus, queries_dataset)


@pytest.fixture(scope="session")
def report(ab_result: ABResult) -> dict:
    """Generate and persist bench_report.json."""
    return generate_report(ab_result, output_path=REPORT_PATH)


# ---------------------------------------------------------------------------
# Gate tests
# ---------------------------------------------------------------------------


class TestP5Gate:
    """Quality gate: Treatment must outperform Baseline."""

    def test_p5_improvement(self, ab_result: ABResult, report: dict) -> None:
        """Verify Treatment P@5 improves over Baseline by >=10% relative."""
        if ab_result.baseline_p5 == 0:
            pytest.skip("Baseline P@5 is 0; relative improvement undefined")

        improvement = (
            (ab_result.treatment_p5 - ab_result.baseline_p5) / ab_result.baseline_p5
        )
        assert improvement >= 0.10, (
            f"P@5 improvement {improvement:.2%} < 10% threshold. "
            f"Baseline={ab_result.baseline_p5:.4f}, "
            f"Treatment={ab_result.treatment_p5:.4f}"
        )

    def test_mrr_no_regression(self, ab_result: ABResult) -> None:
        """Verify Treatment MRR does not regress vs Baseline."""
        assert ab_result.treatment_mrr >= ab_result.baseline_mrr * 0.95, (
            f"MRR regression: Treatment={ab_result.treatment_mrr:.4f} < "
            f"95% of Baseline={ab_result.baseline_mrr:.4f}"
        )

    def test_ndcg5_no_regression(self, ab_result: ABResult) -> None:
        """Verify Treatment NDCG@5 does not regress vs Baseline."""
        assert ab_result.treatment_ndcg5 >= ab_result.baseline_ndcg5 * 0.95, (
            f"NDCG@5 regression: Treatment={ab_result.treatment_ndcg5:.4f} < "
            f"95% of Baseline={ab_result.baseline_ndcg5:.4f}"
        )


# ---------------------------------------------------------------------------
# Difficulty-stratified tests
# ---------------------------------------------------------------------------


class TestDifficultyStratified:
    """Ensure treatment benefits hard queries without hurting easy ones."""

    def test_hard_queries_benefit(
        self,
        memories_corpus: list[dict[str, Any]],
        queries_dataset: list[dict[str, Any]],
    ) -> None:
        """Verify hard queries see improved P@5 under Treatment mode."""
        corpus, idf, avg_doc_len = load_corpus(memories_corpus)
        queries = load_queries(queries_dataset)
        hard_queries = [q for q in queries if q.difficulty == "hard"]

        if not hard_queries:
            pytest.skip("No hard queries in dataset")

        baseline_scores = []
        treatment_scores = []

        for q in hard_queries:
            qt = tokenize(q.query)
            b_results = retrieve_top_k(qt, corpus, treatment=False)
            t_results = retrieve_top_k(
                qt, corpus, treatment=True, idf=idf, avg_doc_len=avg_doc_len
            )
            baseline_scores.append(
                precision_at_k(b_results, q.ground_truth_top5, k=5)
            )
            treatment_scores.append(
                precision_at_k(t_results, q.ground_truth_top5, k=5)
            )

        baseline_mean = sum(baseline_scores) / len(baseline_scores)
        treatment_mean = sum(treatment_scores) / len(treatment_scores)

        # Hard queries should benefit from BM25 + importance weighting
        assert treatment_mean >= baseline_mean, (
            f"Hard queries did not benefit: "
            f"Treatment P@5={treatment_mean:.4f} < Baseline={baseline_mean:.4f}"
        )

    def test_no_regression_easy_queries(
        self,
        memories_corpus: list[dict[str, Any]],
        queries_dataset: list[dict[str, Any]],
    ) -> None:
        """Verify easy queries do not degrade under Treatment mode."""
        corpus, idf, avg_doc_len = load_corpus(memories_corpus)
        queries = load_queries(queries_dataset)
        easy_queries = [q for q in queries if q.difficulty == "easy"]

        if not easy_queries:
            pytest.skip("No easy queries in dataset")

        baseline_scores = []
        treatment_scores = []

        for q in easy_queries:
            qt = tokenize(q.query)
            b_results = retrieve_top_k(qt, corpus, treatment=False)
            t_results = retrieve_top_k(
                qt, corpus, treatment=True, idf=idf, avg_doc_len=avg_doc_len
            )
            baseline_scores.append(
                precision_at_k(b_results, q.ground_truth_top5, k=5)
            )
            treatment_scores.append(
                precision_at_k(t_results, q.ground_truth_top5, k=5)
            )

        baseline_mean = sum(baseline_scores) / len(baseline_scores)
        treatment_mean = sum(treatment_scores) / len(treatment_scores)

        # Allow at most 5% relative degradation on easy queries
        threshold = baseline_mean * 0.95
        assert treatment_mean >= threshold, (
            f"Easy queries regressed: "
            f"Treatment P@5={treatment_mean:.4f} < 95% of Baseline={baseline_mean:.4f}"
        )


# ---------------------------------------------------------------------------
# Report output verification
# ---------------------------------------------------------------------------


class TestReportOutput:
    """Verify bench_report.json structure and content."""

    def test_report_structure(self, report: dict) -> None:
        """Verify report contains all required fields."""
        assert "timestamp" in report
        assert "corpus_size" in report
        assert "query_count" in report
        assert "baseline" in report
        assert "treatment" in report
        assert "improvement" in report
        assert "by_difficulty" in report
        assert "gate_passed" in report

    def test_report_values_valid(self, report: dict) -> None:
        """Verify report metric values are in valid ranges."""
        for mode in ("baseline", "treatment"):
            assert 0 <= report[mode]["p_at_5"] <= 1.0
            assert 0 <= report[mode]["mrr"] <= 1.0
            assert 0 <= report[mode]["ndcg_at_5"] <= 1.0

    def test_report_corpus_size(self, report: dict) -> None:
        """Verify corpus size matches expected 200."""
        assert report["corpus_size"] == 200

    def test_report_query_count(self, report: dict) -> None:
        """Verify query count matches expected 50."""
        assert report["query_count"] == 50

    def test_report_file_written(self, report: dict) -> None:
        """Verify bench_report.json file exists on disk."""
        assert REPORT_PATH.exists(), f"Report not written to {REPORT_PATH}"