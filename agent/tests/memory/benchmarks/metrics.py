"""Retrieval quality metrics: P@K, MRR, NDCG@K.

All functions follow the convention:
  - `retrieved`: ordered list of memory IDs returned by the retrieval system
  - `expected`: list of relevant memory IDs (ground truth)
  - Higher is better for all metrics (range [0, 1])
"""

from __future__ import annotations

import math


def precision_at_k(retrieved: list[str], expected: list[str], k: int = 5) -> float:
    """P@K: fraction of top-K retrieved items that appear in ground truth.

    Args:
        retrieved: Ranked list of retrieved memory IDs.
        expected: Set of relevant memory IDs (ground truth).
        k: Cut-off rank.

    Returns:
        Precision value in [0, 1].
    """
    if k <= 0 or not expected:
        return 0.0
    top_k = retrieved[:k]
    relevant_set = set(expected)
    hits = sum(1 for item in top_k if item in relevant_set)
    return hits / k


def mean_reciprocal_rank(retrieved: list[str], expected: list[str]) -> float:
    """MRR: reciprocal of the rank of the first relevant result.

    Args:
        retrieved: Ranked list of retrieved memory IDs.
        expected: Set of relevant memory IDs (ground truth).

    Returns:
        Reciprocal rank in (0, 1] if a hit exists, else 0.0.
    """
    relevant_set = set(expected)
    for rank, item in enumerate(retrieved, start=1):
        if item in relevant_set:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(retrieved: list[str], expected: list[str], k: int = 5) -> float:
    """NDCG@K: Normalized Discounted Cumulative Gain at rank K.

    Uses binary relevance (1 if in ground truth, 0 otherwise).
    Position-aware: rewards relevant items appearing earlier.

    Args:
        retrieved: Ranked list of retrieved memory IDs.
        expected: Set of relevant memory IDs (ground truth).
        k: Cut-off rank.

    Returns:
        NDCG value in [0, 1].
    """
    if k <= 0 or not expected:
        return 0.0

    relevant_set = set(expected)

    # DCG for the actual retrieved ranking
    dcg = 0.0
    for i, item in enumerate(retrieved[:k]):
        if item in relevant_set:
            # Binary relevance: gain = 1
            dcg += 1.0 / math.log2(i + 2)  # i+2 because rank starts at 1

    # Ideal DCG: all relevant items at the top
    ideal_hits = min(len(relevant_set), k)
    idcg = sum(1.0 / math.log2(i + 2) for i in range(ideal_hits))

    if idcg == 0.0:
        return 0.0
    return dcg / idcg