"""Tier 2 Memory evaluation runner: FTS5, semantic links, compression, hierarchy.

Evaluates four Tier 2 capabilities against the shared benchmark corpus:
  1. FTS5 full-text search quality and latency vs O(n) token-scan
  2. Semantic link expansion recall improvement
  3. Compression information retention and search quality
  4. Hierarchical category routing search-space reduction

All evaluations reuse the same 200-entry corpus and 50-query dataset
used by the Tier 1 A/B benchmark runner.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

# Ensure agent source is importable
_AGENT_ROOT = Path(__file__).resolve().parents[4] / "agent"
if str(_AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENT_ROOT))

from src.memory.search_index import MemorySearchIndex
from src.memory.semantic_links import (
    SemanticLinker,
    _tokenize_for_bm25,
    compute_bm25_score,
    compute_idf,
)
from src.memory.compression import CompressionPipeline, _tokenize_for_tfidf
from src.memory.hierarchy import CATEGORIES, MemoryHierarchy

from .metrics import mean_reciprocal_rank, ndcg_at_k, precision_at_k
from .runner import (
    MemoryRecord,
    QueryRecord,
    load_corpus,
    load_queries,
    retrieve_top_k,
    tokenize,
    TOP_K,
)


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass
class FTS5Result:
    """Results from FTS5 search quality evaluation."""

    fts5_p5: float
    fts5_mrr: float
    fts5_ndcg5: float
    scan_p5: float
    scan_mrr: float
    scan_ndcg5: float
    fts5_avg_latency_ms: float
    scan_avg_latency_ms: float
    speedup_ratio: float


@dataclass
class LinksResult:
    """Results from semantic link expansion evaluation."""

    direct_p5: float
    expanded_p5: float
    link_hits: int  # extra ground-truth items found via links
    total_queries: int


@dataclass
class CompressionResult:
    """Results from compression information retention evaluation."""

    daily_avg_retention: float
    digest_avg_retention: float
    raw_p5: float
    daily_p5: float
    digest_p5: float
    daily_quality_retention: float  # daily_p5 / raw_p5
    digest_quality_retention: float  # digest_p5 / raw_p5


@dataclass
class HierarchyResult:
    """Results from hierarchical routing evaluation."""

    full_scan_count: int
    pruned_avg_count: float
    reduction_ratio: float  # 1 - pruned/full
    full_scan_p5: float
    pruned_p5: float


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------


def _mean(values: List[float]) -> float:
    """Compute arithmetic mean of a list (returns 0.0 for empty list)."""
    return sum(values) / len(values) if values else 0.0


# ---------------------------------------------------------------------------
# 1. FTS5 Search Quality Evaluation
# ---------------------------------------------------------------------------


def run_fts5_evaluation(
    corpus_data: List[Dict[str, Any]],
    queries_data: List[Dict[str, Any]],
    tmp_path: Path,
) -> FTS5Result:
    """Evaluate FTS5 search quality vs O(n) token-scan baseline.

    Indexes 200 memories into a temporary FTS5 database, then compares
    retrieval quality (P@5, MRR, NDCG@5) and latency against the
    sequential token-overlap scan.

    Args:
        corpus_data: Raw memory corpus JSON list.
        queries_data: Raw query dataset JSON list.
        tmp_path: Temporary directory for the SQLite database.

    Returns:
        FTS5Result with quality metrics and timing comparison.
    """
    db_path = tmp_path / "fts5_bench.db"
    index = MemorySearchIndex(db_path=db_path)

    # Index all memories
    entries_tuples: List[tuple] = []
    for entry in corpus_data:
        entry_id = entry["id"]
        title = entry.get("name", "")
        description = entry.get("description", "")
        keywords = " ".join(entry.get("keywords", []))
        body = entry.get("content", "")
        entries_tuples.append((entry_id, title, description, keywords, body))

    index.rebuild_all(entries_tuples)

    # Load corpus for baseline scan
    corpus, idf, avg_doc_len = load_corpus(corpus_data)
    queries = load_queries(queries_data)

    # Evaluate both methods
    fts5_p5_scores: List[float] = []
    fts5_mrr_scores: List[float] = []
    fts5_ndcg5_scores: List[float] = []
    scan_p5_scores: List[float] = []
    scan_mrr_scores: List[float] = []
    scan_ndcg5_scores: List[float] = []
    fts5_latencies: List[float] = []
    scan_latencies: List[float] = []

    for q in queries:
        gt = q.ground_truth_top5

        # FTS5 retrieval with timing
        t0 = time.perf_counter()
        fts5_matches = index.search(q.query, max_results=TOP_K)
        fts5_latencies.append((time.perf_counter() - t0) * 1000)
        fts5_ids = [m.entry_id for m in fts5_matches]

        fts5_p5_scores.append(precision_at_k(fts5_ids, gt, k=TOP_K))
        fts5_mrr_scores.append(mean_reciprocal_rank(fts5_ids, gt))
        fts5_ndcg5_scores.append(ndcg_at_k(fts5_ids, gt, k=TOP_K))

        # O(n) scan retrieval with timing (use treatment=True for BM25)
        query_tokens = tokenize(q.query)
        t0 = time.perf_counter()
        scan_ids = retrieve_top_k(
            query_tokens, corpus, treatment=True, idf=idf, avg_doc_len=avg_doc_len
        )
        scan_latencies.append((time.perf_counter() - t0) * 1000)

        scan_p5_scores.append(precision_at_k(scan_ids, gt, k=TOP_K))
        scan_mrr_scores.append(mean_reciprocal_rank(scan_ids, gt))
        scan_ndcg5_scores.append(ndcg_at_k(scan_ids, gt, k=TOP_K))

    index.close()

    fts5_avg = _mean(fts5_latencies)
    scan_avg = _mean(scan_latencies)
    speedup = scan_avg / fts5_avg if fts5_avg > 0 else 1.0

    return FTS5Result(
        fts5_p5=_mean(fts5_p5_scores),
        fts5_mrr=_mean(fts5_mrr_scores),
        fts5_ndcg5=_mean(fts5_ndcg5_scores),
        scan_p5=_mean(scan_p5_scores),
        scan_mrr=_mean(scan_mrr_scores),
        scan_ndcg5=_mean(scan_ndcg5_scores),
        fts5_avg_latency_ms=fts5_avg,
        scan_avg_latency_ms=scan_avg,
        speedup_ratio=speedup,
    )


# ---------------------------------------------------------------------------
# 2. Semantic Link Expansion Evaluation
# ---------------------------------------------------------------------------


def run_links_evaluation(
    corpus_data: List[Dict[str, Any]],
    queries_data: List[Dict[str, Any]],
    tmp_path: Path,
) -> LinksResult:
    """Evaluate semantic link expansion vs direct top-5 retrieval.

    Strategy:
      - Tokenize all 200 memories for BM25 link discovery
      - For each query: retrieve top-3 via token-scan, then expand
        via BM25 links to reach 5 results
      - Compare "direct top-5" vs "top-3 + 2-link-expanded" P@5

    Args:
        corpus_data: Raw memory corpus JSON list.
        queries_data: Raw query dataset JSON list.
        tmp_path: Temporary directory for linker sidecar files.

    Returns:
        LinksResult with direct vs expanded P@5 comparison.
    """
    corpus, idf, avg_doc_len = load_corpus(corpus_data)
    queries = load_queries(queries_data)

    # Tokenize all entries for BM25 link computation
    all_entries_tokens: List[Tuple[str, List[str]]] = []
    id_to_tokens: Dict[str, List[str]] = {}
    for entry in corpus_data:
        entry_id = entry["id"]
        text = " ".join([
            entry.get("name", ""),
            entry.get("description", ""),
            " ".join(entry.get("keywords", [])),
            entry.get("content", ""),
        ])
        tokens = _tokenize_for_bm25(text)
        all_entries_tokens.append((entry_id, tokens))
        id_to_tokens[entry_id] = tokens

    # Pre-compute BM25 links for all entries (top-5 per entry)
    linker = SemanticLinker(tmp_path / "memory")
    bm25_corpus = [tokens for _, tokens in all_entries_tokens]
    idf_links = compute_idf(bm25_corpus)
    avg_dl = _mean([float(len(t)) for t in bm25_corpus])

    # Build adjacency: entry_id -> [(linked_id, score), ...]
    adjacency: Dict[str, List[Tuple[str, float]]] = {}
    for entry_id, entry_tokens in all_entries_tokens:
        links = linker.discover_links(
            entry_title=entry_id,
            entry_tokens=entry_tokens,
            all_entries_data=all_entries_tokens,
            top_k=5,
        )
        adjacency[entry_id] = links

    direct_p5_scores: List[float] = []
    expanded_p5_scores: List[float] = []
    total_link_hits = 0

    for q in queries:
        gt = q.ground_truth_top5
        gt_set: Set[str] = set(gt)
        query_tokens = tokenize(q.query)

        # Direct top-5
        direct_ids = retrieve_top_k(
            query_tokens, corpus, treatment=True, idf=idf, avg_doc_len=avg_doc_len, k=TOP_K
        )
        direct_p5_scores.append(precision_at_k(direct_ids, gt, k=TOP_K))

        # Top-3 then expand via links
        top3_ids = retrieve_top_k(
            query_tokens, corpus, treatment=True, idf=idf, avg_doc_len=avg_doc_len, k=3
        )

        # Expand: collect linked entries from top-3, ranked by link score
        seen: Set[str] = set(top3_ids)
        candidates: List[Tuple[float, str]] = []
        for seed_id in top3_ids:
            for linked_id, score in adjacency.get(seed_id, []):
                if linked_id not in seen:
                    candidates.append((score, linked_id))
                    seen.add(linked_id)

        # Sort by link score descending, pick top 2
        candidates.sort(key=lambda x: -x[0])
        expanded_ids = list(top3_ids) + [cid for _, cid in candidates[:2]]

        expanded_p5_scores.append(precision_at_k(expanded_ids, gt, k=TOP_K))

        # Count extra ground-truth hits from link expansion
        direct_hits = set(direct_ids) & gt_set
        expanded_hits = set(expanded_ids) & gt_set
        extra_hits = expanded_hits - direct_hits
        total_link_hits += len(extra_hits)

    return LinksResult(
        direct_p5=_mean(direct_p5_scores),
        expanded_p5=_mean(expanded_p5_scores),
        link_hits=total_link_hits,
        total_queries=len(queries),
    )


# ---------------------------------------------------------------------------
# 3. Compression Information Retention Evaluation
# ---------------------------------------------------------------------------


def run_compression_evaluation(
    corpus_data: List[Dict[str, Any]],
    queries_data: List[Dict[str, Any]],
    tmp_path: Path,
) -> CompressionResult:
    """Evaluate compression information retention and search quality.

    Compresses all 200 memories through two stages:
      - Raw -> Daily (TF-IDF key-sentence extraction)
      - Daily -> Digest (keyword bullet summary)

    Measures:
      - Average Jaccard token retention at each level
      - P@5 on compressed corpora vs raw corpus

    Args:
        corpus_data: Raw memory corpus JSON list.
        queries_data: Raw query dataset JSON list.
        tmp_path: Temporary directory for compression pipeline.

    Returns:
        CompressionResult with retention and quality metrics.
    """
    pipeline = CompressionPipeline(tmp_path / "memory")
    queries = load_queries(queries_data)

    daily_retentions: List[float] = []
    digest_retentions: List[float] = []
    daily_corpus_data: List[Dict[str, Any]] = []
    digest_corpus_data: List[Dict[str, Any]] = []

    for entry in corpus_data:
        content = entry.get("content", "")
        keywords = tuple(entry.get("keywords", []))

        # Compress to daily
        daily_content = pipeline.compress_to_daily(content, keywords)
        daily_retention = pipeline.estimate_retention(content, daily_content)
        daily_retentions.append(daily_retention)

        # Compress to digest (from daily)
        digest_content = pipeline.compress_to_digest(daily_content, keywords)
        digest_retention = pipeline.estimate_retention(content, digest_content)
        digest_retentions.append(digest_retention)

        # Build modified corpus entries for retrieval evaluation
        daily_entry = dict(entry)
        daily_entry["content"] = daily_content
        daily_corpus_data.append(daily_entry)

        digest_entry = dict(entry)
        digest_entry["content"] = digest_content
        digest_corpus_data.append(digest_entry)

    # Load corpora for retrieval evaluation
    raw_corpus, raw_idf, raw_avg_dl = load_corpus(corpus_data)
    daily_corpus, daily_idf, daily_avg_dl = load_corpus(daily_corpus_data)
    digest_corpus, digest_idf, digest_avg_dl = load_corpus(digest_corpus_data)

    raw_p5_scores: List[float] = []
    daily_p5_scores: List[float] = []
    digest_p5_scores: List[float] = []

    for q in queries:
        gt = q.ground_truth_top5
        query_tokens = tokenize(q.query)

        # Raw retrieval
        raw_ids = retrieve_top_k(
            query_tokens, raw_corpus, treatment=True,
            idf=raw_idf, avg_doc_len=raw_avg_dl
        )
        raw_p5_scores.append(precision_at_k(raw_ids, gt, k=TOP_K))

        # Daily retrieval
        daily_ids = retrieve_top_k(
            query_tokens, daily_corpus, treatment=True,
            idf=daily_idf, avg_doc_len=daily_avg_dl
        )
        daily_p5_scores.append(precision_at_k(daily_ids, gt, k=TOP_K))

        # Digest retrieval
        digest_ids = retrieve_top_k(
            query_tokens, digest_corpus, treatment=True,
            idf=digest_idf, avg_doc_len=digest_avg_dl
        )
        digest_p5_scores.append(precision_at_k(digest_ids, gt, k=TOP_K))

    raw_p5 = _mean(raw_p5_scores)
    daily_p5 = _mean(daily_p5_scores)
    digest_p5 = _mean(digest_p5_scores)

    return CompressionResult(
        daily_avg_retention=_mean(daily_retentions),
        digest_avg_retention=_mean(digest_retentions),
        raw_p5=raw_p5,
        daily_p5=daily_p5,
        digest_p5=digest_p5,
        daily_quality_retention=daily_p5 / raw_p5 if raw_p5 > 0 else 1.0,
        digest_quality_retention=digest_p5 / raw_p5 if raw_p5 > 0 else 1.0,
    )


# ---------------------------------------------------------------------------
# 4. Hierarchical Routing Evaluation
# ---------------------------------------------------------------------------


def run_hierarchy_evaluation(
    corpus_data: List[Dict[str, Any]],
    queries_data: List[Dict[str, Any]],
    tmp_path: Path,
) -> HierarchyResult:
    """Evaluate hierarchical category routing vs full-scan retrieval.

    Simulates a hierarchical directory by grouping memories by `type` field:
      - Maps corpus types to CATEGORIES: strategy->project, market_analysis->reference,
        tool_usage->feedback, lesson->user
      - Builds hierarchy index
      - For each query: compares full-scan vs category-pruned retrieval

    Args:
        corpus_data: Raw memory corpus JSON list.
        queries_data: Raw query dataset JSON list.
        tmp_path: Temporary directory for hierarchy structure.

    Returns:
        HierarchyResult with search-space reduction and P@5 comparison.
    """
    # Map corpus types to hierarchy CATEGORIES
    type_to_category = {
        "strategy": "project",
        "market_analysis": "reference",
        "tool_usage": "feedback",
        "lesson": "user",
    }

    hierarchy_dir = tmp_path / "hierarchy_mem"
    hierarchy_dir.mkdir(parents=True, exist_ok=True)
    hierarchy = MemoryHierarchy(hierarchy_dir)

    # Create .md files in category subdirectories
    entries_for_index: List[Dict[str, Any]] = []
    id_to_category: Dict[str, str] = {}

    for entry in corpus_data:
        entry_id = entry["id"]
        mem_type = entry.get("type", "strategy")
        category = type_to_category.get(mem_type, "project")
        id_to_category[entry_id] = category

        # Write a minimal .md file for scanning
        cat_dir = hierarchy_dir / category
        cat_dir.mkdir(parents=True, exist_ok=True)
        md_path = cat_dir / f"{entry_id}.md"
        md_path.write_text(entry.get("name", entry_id), encoding="utf-8")

        entries_for_index.append({
            "memory_type": category,
            "keywords": entry.get("keywords", []),
        })

    # Build hierarchy index
    hierarchy.rebuild_index(entries_for_index)

    # Load corpus for retrieval
    corpus, idf, avg_doc_len = load_corpus(corpus_data)
    queries = load_queries(queries_data)

    # Map query categories to memory categories for pruning
    query_cat_to_mem_cats: Dict[str, List[str]] = {
        "strategy_recall": ["project"],
        "market_analysis": ["reference", "project"],
        "parameter_lookup": ["project", "feedback"],
        "temporal_preference": ["project", "reference"],
        "quality_preference": ["project", "reference"],
    }

    full_scan_count = len(corpus_data)
    pruned_counts: List[int] = []
    full_p5_scores: List[float] = []
    pruned_p5_scores: List[float] = []

    for q in queries:
        gt = q.ground_truth_top5
        query_tokens = tokenize(q.query)

        # Full scan retrieval
        full_ids = retrieve_top_k(
            query_tokens, corpus, treatment=True, idf=idf, avg_doc_len=avg_doc_len
        )
        full_p5_scores.append(precision_at_k(full_ids, gt, k=TOP_K))

        # Category-pruned retrieval: filter corpus to relevant categories
        target_cats = query_cat_to_mem_cats.get(q.category, list(CATEGORIES))
        pruned_corpus = [
            rec for rec in corpus
            if id_to_category.get(rec.id, "") in target_cats
        ]
        pruned_counts.append(len(pruned_corpus))

        pruned_ids = retrieve_top_k(
            query_tokens, pruned_corpus, treatment=True, idf=idf, avg_doc_len=avg_doc_len
        )
        pruned_p5_scores.append(precision_at_k(pruned_ids, gt, k=TOP_K))

    pruned_avg = _mean([float(c) for c in pruned_counts])
    reduction = 1.0 - (pruned_avg / full_scan_count) if full_scan_count > 0 else 0.0

    return HierarchyResult(
        full_scan_count=full_scan_count,
        pruned_avg_count=pruned_avg,
        reduction_ratio=reduction,
        full_scan_p5=_mean(full_p5_scores),
        pruned_p5=_mean(pruned_p5_scores),
    )
