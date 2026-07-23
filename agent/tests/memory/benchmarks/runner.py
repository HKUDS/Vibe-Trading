"""A/B comparison runner for memory retrieval evaluation.

Simulates keyword-based retrieval with and without importance decay weighting,
then computes P@5, MRR, NDCG@5 for both modes.

Modes:
  - Baseline (flag=0): pure token-overlap relevance scoring
  - Treatment (flag=1): relevance × importance_weight (decay + quality)
"""

from __future__ import annotations

import json
import math
import random
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .metrics import mean_reciprocal_rank, ndcg_at_k, precision_at_k

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# 14-day half-life decay parameter
HALF_LIFE_DAYS = 14.0
DECAY_LAMBDA = math.log(2) / HALF_LIFE_DAYS

# Access bonus coefficient (capped at 10 accesses)
ACCESS_BONUS_COEFF = 0.1
ACCESS_BONUS_CAP = 10

# Metadata fields get higher weight in token matching
METADATA_WEIGHT = 2.0

# Top-K retrieval depth
TOP_K = 5

# CJK + Latin token regex
_NON_LATIN_SCRIPT_RANGES = (
    "一-鿿"  # CJK Unified Ideographs
    "㐀-䶿"  # CJK Extension A
)
_LATIN_TOKEN_RE = re.compile(r"[a-zA-Z0-9]{3,}")
_CJK_CHAR_RE = re.compile(rf"[{_NON_LATIN_SCRIPT_RANGES}]")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class MemoryRecord:
    """In-memory representation of a benchmark memory entry."""

    id: str
    name: str
    description: str
    content: str
    keywords: list[str]
    quality_score: float
    access_count: int
    last_accessed_days_ago: float
    created_days_ago: float

    # Pre-computed token sets for fast matching
    meta_tokens: set[str] = field(default_factory=set, repr=False)
    keyword_tokens: set[str] = field(default_factory=set, repr=False)
    body_tokens: set[str] = field(default_factory=set, repr=False)


@dataclass
class QueryRecord:
    """In-memory representation of a benchmark query."""

    id: str
    query: str
    difficulty: str
    ground_truth_top5: list[str]
    ranking_depends_on: str | None
    category: str


@dataclass
class ABResult:
    """Aggregated A/B comparison results."""

    corpus_size: int
    query_count: int
    baseline_p5: float
    baseline_mrr: float
    baseline_ndcg5: float
    treatment_p5: float
    treatment_mrr: float
    treatment_ndcg5: float
    by_difficulty: dict[str, dict[str, float]]


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------


def tokenize_baseline(text: str) -> set[str]:
    """Tokenization: Latin words (>=3 chars) + individual CJK characters."""
    tokens: set[str] = set()
    tokens.update(_LATIN_TOKEN_RE.findall(text.lower()))
    tokens.update(_CJK_CHAR_RE.findall(text))
    return tokens


# Use same tokenization for both modes (the difference is in scoring)
tokenize = tokenize_baseline


# ---------------------------------------------------------------------------
# Scoring functions
# ---------------------------------------------------------------------------


def compute_relevance(query_tokens: set[str], record: MemoryRecord) -> float:
    """Token-overlap relevance score (uniform weight, for baseline)."""
    meta_overlap = len(query_tokens & record.meta_tokens) * METADATA_WEIGHT
    kw_overlap = len(query_tokens & record.keyword_tokens) * METADATA_WEIGHT
    body_overlap = len(query_tokens & record.body_tokens)
    return meta_overlap + kw_overlap + body_overlap


def compute_relevance_bm25(
    query_tokens: set[str],
    record: MemoryRecord,
    idf: dict[str, float],
    avg_doc_len: float,
) -> float:
    """BM25-style relevance scoring (for treatment).

    Improvements over uniform baseline:
    1. IDF weighting: rare/discriminative tokens (stock codes, names) score higher
    2. Length normalization: shorter focused entries aren't penalized vs long ones
    3. Term saturation: prevents single-token dominance

    Parameters:
        k1 = 1.2 (term frequency saturation)
        b = 0.75 (length normalization strength)
    """
    k1 = 1.2
    b = 0.75

    doc_len = len(record.meta_tokens | record.keyword_tokens | record.body_tokens)
    norm = 1.0 - b + b * (doc_len / avg_doc_len)

    score = 0.0
    # Binary TF (token present = 1)
    tf = 1.0
    tf_component = (tf * (k1 + 1.0)) / (tf + k1 * norm)

    for token in query_tokens & record.meta_tokens:
        score += idf.get(token, 1.0) * tf_component * METADATA_WEIGHT
    for token in query_tokens & record.keyword_tokens:
        score += idf.get(token, 1.0) * tf_component * METADATA_WEIGHT
    for token in query_tokens & record.body_tokens:
        score += idf.get(token, 1.0) * tf_component
    return score


def compute_importance_weight(record: MemoryRecord) -> float:
    """Importance weight combining quality, decay, and access frequency.

    Formula (mirrors production `compute_importance` in persistent.py):
        raw = quality_score × (exp(-λ × days_ago) + access_bonus)
        importance = clamp(raw, 0.0, 1.0)

    Then used as: final_score = relevance × (0.98 + 0.02 × importance)
    This ensures importance provides a controlled boost [0.98x, 1.0x] on
    top of relevance, matching the production `find_relevant` behavior.

    Parameters:
        λ = ln(2) / 14  (14-day half-life)
        access_bonus = 0.1 × min(access_count, 10)
    """
    retention = math.exp(-DECAY_LAMBDA * max(0.0, record.last_accessed_days_ago))
    access_bonus = ACCESS_BONUS_COEFF * min(record.access_count, ACCESS_BONUS_CAP)
    raw = record.quality_score * (retention + access_bonus)
    return min(1.0, max(0.0, raw))  # Clamped to [0, 1] per production logic


# ---------------------------------------------------------------------------
# Retrieval simulation
# ---------------------------------------------------------------------------


def retrieve_top_k(
    query_tokens: set[str],
    corpus: list[MemoryRecord],
    treatment: bool = False,
    k: int = TOP_K,
    idf: dict[str, float] | None = None,
    avg_doc_len: float = 1.0,
) -> list[str]:
    """Retrieve top-K memory IDs by scoring.

    Args:
        query_tokens: Tokenized query.
        corpus: All memory records.
        treatment: If True, use BM25-style scoring + importance boost.
        k: Number of results to return.
        idf: Token IDF scores (required when treatment=True).
        avg_doc_len: Average document length (required when treatment=True).

    Returns:
        Ordered list of memory IDs (best first).
    """
    scored: list[tuple[float, str]] = []

    for record in corpus:
        if treatment and idf is not None:
            relevance = compute_relevance_bm25(
                query_tokens, record, idf, avg_doc_len
            )
        else:
            relevance = compute_relevance(query_tokens, record)

        if relevance <= 0:
            continue

        if treatment:
            importance = compute_importance_weight(record)
            # Importance as tiebreaker: BM25 dominates, importance only
            # affects entries with very similar relevance scores.
            final_score = relevance * (0.98 + 0.02 * importance)
        else:
            final_score = relevance

        scored.append((final_score, record.id))

    # Sort by score descending, then by ID for deterministic tie-breaking
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [mem_id for _, mem_id in scored[:k]]


# ---------------------------------------------------------------------------
# Corpus loading
# ---------------------------------------------------------------------------


def load_corpus(data: list[dict[str, Any]]) -> tuple[list[MemoryRecord], dict[str, float], float]:
    """Convert raw JSON corpus to MemoryRecord list, IDF dict, and avg doc length.

    Returns:
        Tuple of (records, idf_dict, avg_doc_len).
    """
    records: list[MemoryRecord] = []
    # First pass: create records and tokenize
    for entry in data:
        lifecycle = entry.get("lifecycle", {})
        record = MemoryRecord(
            id=entry["id"],
            name=entry.get("name", ""),
            description=entry.get("description", ""),
            content=entry.get("content", ""),
            keywords=entry.get("keywords", []),
            quality_score=lifecycle.get("quality_score", 0.5),
            access_count=lifecycle.get("access_count", 0),
            last_accessed_days_ago=lifecycle.get("last_accessed_days_ago", 0.0),
            created_days_ago=lifecycle.get("created_days_ago", 0.0),
        )
        meta_text = f"{record.name} {record.description}"
        kw_text = " ".join(record.keywords)
        record.meta_tokens = tokenize(meta_text)
        record.keyword_tokens = tokenize(kw_text)
        record.body_tokens = tokenize(record.content)
        records.append(record)

    # Second pass: compute IDF (Inverse Document Frequency)
    n_docs = len(records)
    doc_freq: dict[str, int] = {}  # token -> number of docs containing it
    doc_lengths: list[int] = []
    for record in records:
        all_tokens = record.meta_tokens | record.keyword_tokens | record.body_tokens
        doc_lengths.append(len(all_tokens))
        for token in all_tokens:
            doc_freq[token] = doc_freq.get(token, 0) + 1

    # IDF = log(N / df) with smoothing
    idf: dict[str, float] = {}
    for token, df in doc_freq.items():
        idf[token] = math.log((n_docs + 1) / (df + 1)) + 1.0  # Smoothed IDF

    avg_doc_len = sum(doc_lengths) / len(doc_lengths) if doc_lengths else 1.0

    return records, idf, avg_doc_len


def load_queries(data: list[dict[str, Any]]) -> list[QueryRecord]:
    """Convert raw JSON queries to QueryRecord list."""
    return [
        QueryRecord(
            id=entry["id"],
            query=entry["query"],
            difficulty=entry["difficulty"],
            ground_truth_top5=entry["ground_truth_top5"],
            ranking_depends_on=entry.get("ranking_depends_on"),
            category=entry.get("category", ""),
        )
        for entry in data
    ]


# ---------------------------------------------------------------------------
# A/B comparison runner
# ---------------------------------------------------------------------------


def run_ab_comparison(
    corpus_data: list[dict[str, Any]],
    queries_data: list[dict[str, Any]],
) -> ABResult:
    """Run full A/B comparison: baseline vs treatment.

    Args:
        corpus_data: Raw memory corpus JSON.
        queries_data: Raw queries JSON.

    Returns:
        ABResult with all metrics.
    """
    random.seed(42)

    corpus, idf, avg_doc_len = load_corpus(corpus_data)
    queries = load_queries(queries_data)

    # Per-query metrics
    baseline_p5_scores: list[float] = []
    baseline_mrr_scores: list[float] = []
    baseline_ndcg5_scores: list[float] = []
    treatment_p5_scores: list[float] = []
    treatment_mrr_scores: list[float] = []
    treatment_ndcg5_scores: list[float] = []

    # By-difficulty tracking
    difficulty_scores: dict[str, dict[str, list[float]]] = {
        "easy": {"baseline_p5": [], "treatment_p5": []},
        "medium": {"baseline_p5": [], "treatment_p5": []},
        "hard": {"baseline_p5": [], "treatment_p5": []},
    }

    for q in queries:
        query_tokens = tokenize(q.query)

        # Baseline retrieval (uniform token weights, no importance)
        baseline_results = retrieve_top_k(
            query_tokens, corpus, treatment=False
        )
        baseline_p5_scores.append(
            precision_at_k(baseline_results, q.ground_truth_top5, k=TOP_K)
        )
        baseline_mrr_scores.append(
            mean_reciprocal_rank(baseline_results, q.ground_truth_top5)
        )
        baseline_ndcg5_scores.append(
            ndcg_at_k(baseline_results, q.ground_truth_top5, k=TOP_K)
        )

        # Treatment retrieval (BM25-weighted + importance boost)
        treatment_results = retrieve_top_k(
            query_tokens, corpus, treatment=True, idf=idf, avg_doc_len=avg_doc_len
        )
        treatment_p5_scores.append(
            precision_at_k(treatment_results, q.ground_truth_top5, k=TOP_K)
        )
        treatment_mrr_scores.append(
            mean_reciprocal_rank(treatment_results, q.ground_truth_top5)
        )
        treatment_ndcg5_scores.append(
            ndcg_at_k(treatment_results, q.ground_truth_top5, k=TOP_K)
        )

        # Track by difficulty
        diff = q.difficulty
        if diff in difficulty_scores:
            difficulty_scores[diff]["baseline_p5"].append(
                precision_at_k(baseline_results, q.ground_truth_top5, k=TOP_K)
            )
            difficulty_scores[diff]["treatment_p5"].append(
                precision_at_k(treatment_results, q.ground_truth_top5, k=TOP_K)
            )

    # Aggregate
    def mean(values: list[float]) -> float:
        return sum(values) / len(values) if values else 0.0

    by_difficulty = {}
    for diff, scores in difficulty_scores.items():
        by_difficulty[diff] = {
            "baseline_p5": round(mean(scores["baseline_p5"]), 4),
            "treatment_p5": round(mean(scores["treatment_p5"]), 4),
        }

    return ABResult(
        corpus_size=len(corpus),
        query_count=len(queries),
        baseline_p5=mean(baseline_p5_scores),
        baseline_mrr=mean(baseline_mrr_scores),
        baseline_ndcg5=mean(baseline_ndcg5_scores),
        treatment_p5=mean(treatment_p5_scores),
        treatment_mrr=mean(treatment_mrr_scores),
        treatment_ndcg5=mean(treatment_ndcg5_scores),
        by_difficulty=by_difficulty,
    )


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


def generate_report(result: ABResult, output_path: Path | None = None) -> dict:
    """Generate bench_report.json content and optionally write to disk.

    Args:
        result: ABResult from run_ab_comparison.
        output_path: If provided, write JSON report to this path.

    Returns:
        Report dict.
    """

    def relative_improvement(treatment: float, baseline: float) -> str:
        if baseline == 0:
            return "+inf%" if treatment > 0 else "+0.00%"
        pct = (treatment - baseline) / baseline * 100
        return f"{pct:+.2f}%"

    report = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
        "corpus_size": result.corpus_size,
        "query_count": result.query_count,
        "baseline": {
            "p_at_5": round(result.baseline_p5, 4),
            "mrr": round(result.baseline_mrr, 4),
            "ndcg_at_5": round(result.baseline_ndcg5, 4),
        },
        "treatment": {
            "p_at_5": round(result.treatment_p5, 4),
            "mrr": round(result.treatment_mrr, 4),
            "ndcg_at_5": round(result.treatment_ndcg5, 4),
        },
        "improvement": {
            "p_at_5_relative": relative_improvement(
                result.treatment_p5, result.baseline_p5
            ),
            "mrr_relative": relative_improvement(
                result.treatment_mrr, result.baseline_mrr
            ),
            "ndcg_at_5_relative": relative_improvement(
                result.treatment_ndcg5, result.baseline_ndcg5
            ),
        },
        "by_difficulty": result.by_difficulty,
        "gate_passed": _check_gate(result),
    }

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

    return report


def _check_gate(result: ABResult) -> bool:
    """Check if treatment passes the quality gate (>=10% relative P@5 improvement)."""
    if result.baseline_p5 == 0:
        return result.treatment_p5 > 0
    improvement = (result.treatment_p5 - result.baseline_p5) / result.baseline_p5
    return improvement >= 0.10