"""Semantic linking between memory entries via BM25 similarity (Tier 2).

Automatically discovers and maintains relationships between memories using
term-frequency scoring. Links are stored as .relations.json sidecar files.

Feature flag: VT_MEMORY_LINKS (default off).
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Set, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# BM25 parameters
# ---------------------------------------------------------------------------
_BM25_K1 = 1.5
_BM25_B = 0.75

# ---------------------------------------------------------------------------
# Link thresholds
# ---------------------------------------------------------------------------
_MIN_SCORE_THRESHOLD = 0.3
_MAX_OUTGOING_LINKS = 10

# ---------------------------------------------------------------------------
# Wikilink regex: [[6-char-hex-id]]
# ---------------------------------------------------------------------------
_WIKILINK_RE = re.compile(r"\[\[([a-f0-9]{6})\]\]")

# ---------------------------------------------------------------------------
# Tokenization (mirrors persistent.py regex pattern)
# ---------------------------------------------------------------------------
_NON_LATIN_SCRIPT_RANGES = (
    "一-鿿"  # CJK Unified Ideographs
    "㐀-䶿"  # CJK Extension A
    "฀-๿"  # Thai
    "ؠ-ي"  # Arabic letters
    "א-ת"  # Hebrew letters
    "Ѐ-ӿ"  # Cyrillic
)
_TOKEN_RE = re.compile(rf"[a-zA-Z0-9]{{3,}}|[{_NON_LATIN_SCRIPT_RANGES}]")

# Relations file schema version
_RELATIONS_VERSION = 1


# ---------------------------------------------------------------------------
# Public helper functions
# ---------------------------------------------------------------------------


def _tokenize_for_bm25(text: str) -> List[str]:
    """Tokenize text for BM25 scoring.

    Uses the same regex pattern as persistent.py to ensure consistent token
    extraction across the memory subsystem. Returns a list (preserving
    duplicates for term-frequency calculation).
    """
    return _TOKEN_RE.findall(text.lower())


def compute_idf(corpus: List[List[str]]) -> Dict[str, float]:
    """Compute IDF scores from a token corpus.

    Formula: IDF(t) = log((N - n + 0.5) / (n + 0.5) + 1)
    where N = total document count, n = documents containing term t.

    Args:
        corpus: List of tokenized documents (each doc is a list of tokens).

    Returns:
        Dictionary mapping each term to its IDF score.
    """
    n_docs = len(corpus)
    if n_docs == 0:
        return {}

    # Count document frequency for each term
    doc_freq: Counter = Counter()
    for doc_tokens in corpus:
        unique_terms = set(doc_tokens)
        for term in unique_terms:
            doc_freq[term] += 1

    idf_scores: Dict[str, float] = {}
    for term, freq in doc_freq.items():
        # Standard BM25 IDF with +1 inside log to avoid negative values
        idf_scores[term] = math.log((n_docs - freq + 0.5) / (freq + 0.5) + 1)

    return idf_scores


def compute_bm25_score(
    query_tokens: List[str],
    doc_tokens: List[str],
    idf_scores: Dict[str, float],
    avg_dl: float,
) -> float:
    """Compute BM25 score for a single document against query tokens.

    Formula per term t:
        score += IDF(t) * (tf(t) * (k1 + 1)) / (tf(t) + k1 * (1 - b + b * dl / avgdl))

    Args:
        query_tokens: Tokenized query (the source entry).
        doc_tokens: Tokenized candidate document.
        idf_scores: Pre-computed IDF mapping.
        avg_dl: Average document length across corpus.

    Returns:
        BM25 relevance score (non-negative float).
    """
    if not doc_tokens or avg_dl <= 0:
        return 0.0

    dl = len(doc_tokens)
    tf_map: Counter = Counter(doc_tokens)

    score = 0.0
    # Deduplicate query tokens for scoring
    seen_terms: Set[str] = set()
    for term in query_tokens:
        if term in seen_terms:
            continue
        seen_terms.add(term)

        idf = idf_scores.get(term, 0.0)
        if idf <= 0:
            continue

        tf = tf_map.get(term, 0)
        if tf == 0:
            continue

        numerator = tf * (_BM25_K1 + 1)
        denominator = tf + _BM25_K1 * (1 - _BM25_B + _BM25_B * dl / avg_dl)
        score += idf * numerator / denominator

    return score


# ---------------------------------------------------------------------------
# SemanticLinker class
# ---------------------------------------------------------------------------


class SemanticLinker:
    """Manages BM25-based semantic links between memory entries.

    Responsible for discovering related memories via BM25 similarity scoring,
    persisting link data as .relations.json sidecar files, and resolving
    wikilink references embedded in memory body text.
    """

    def __init__(self, memory_dir: Path) -> None:
        """Initialize with the memory directory path.

        Args:
            memory_dir: Path to the directory containing memory .md files.
        """
        self._memory_dir = memory_dir

    @property
    def memory_dir(self) -> Path:
        """The memory directory this linker operates on."""
        return self._memory_dir

    def discover_links(
        self,
        entry_title: str,
        entry_tokens: List[str],
        all_entries_data: List[Tuple[str, List[str]]],
        top_k: int = 5,
    ) -> List[Tuple[str, float]]:
        """Find top-k most similar entries via BM25.

        Args:
            entry_title: Title of the source entry (used to exclude self).
            entry_tokens: Tokens of the source entry (the query).
            all_entries_data: List of (filename, tokens) for all entries.
            top_k: Maximum number of links to return.

        Returns:
            List of (target_filename, bm25_score) sorted by descending score,
            filtered by _MIN_SCORE_THRESHOLD and capped at _MAX_OUTGOING_LINKS.
        """
        if not entry_tokens or not all_entries_data:
            return []

        # Build corpus for IDF computation (exclude self)
        corpus: List[List[str]] = []
        filenames: List[str] = []
        for fname, tokens in all_entries_data:
            if fname == entry_title:
                continue
            corpus.append(tokens)
            filenames.append(fname)

        if not corpus:
            return []

        # Compute IDF and average document length
        idf_scores = compute_idf(corpus)
        total_tokens = sum(len(doc) for doc in corpus)
        avg_dl = total_tokens / len(corpus) if corpus else 1.0

        # Score each candidate
        scored: List[Tuple[str, float]] = []
        for idx, doc_tokens in enumerate(corpus):
            score = compute_bm25_score(entry_tokens, doc_tokens, idf_scores, avg_dl)
            if score >= _MIN_SCORE_THRESHOLD:
                scored.append((filenames[idx], score))

        # Sort descending by score
        scored.sort(key=lambda x: x[1], reverse=True)

        # Apply limits
        effective_k = min(top_k, _MAX_OUTGOING_LINKS)
        return scored[:effective_k]

    def save_relations(self, entry_path: Path, links: List[Tuple[str, float]]) -> None:
        """Write .relations.json sidecar file beside the memory file.

        Uses atomic write (write to temp file + rename) to ensure thread safety
        and prevent partial writes on crash.

        Args:
            entry_path: Path to the source memory file.
            links: List of (target_filename, score) tuples to persist.
        """
        rel_path = self.get_relation_path(entry_path)
        data = {
            "version": _RELATIONS_VERSION,
            "links": [
                {"target": target, "score": round(score, 4)}
                for target, score in links
            ],
            "updated_at": datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat(),
        }

        content = json.dumps(data, indent=2, ensure_ascii=False)

        # Atomic write: write to temp file in same directory, then rename
        dir_path = rel_path.parent
        dir_path.mkdir(parents=True, exist_ok=True)

        fd = None
        tmp_path = None
        try:
            fd, tmp_path = tempfile.mkstemp(
                suffix=".tmp", prefix=".relations_", dir=str(dir_path)
            )
            os.write(fd, content.encode("utf-8"))
            os.fsync(fd)
            os.close(fd)
            fd = None
            os.replace(tmp_path, str(rel_path))
            tmp_path = None
        except OSError:
            logger.exception("Failed to write relations file: %s", rel_path)
            if fd is not None:
                os.close(fd)
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    def load_relations(self, entry_path: Path) -> List[Tuple[str, float]]:
        """Read relations from .relations.json sidecar.

        Args:
            entry_path: Path to the source memory file.

        Returns:
            List of (target_filename, score) tuples. Returns [] if file
            not found or on parse error.
        """
        rel_path = self.get_relation_path(entry_path)
        if not rel_path.exists():
            return []

        try:
            raw = rel_path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (OSError, json.JSONDecodeError):
            logger.warning("Failed to read relations file: %s", rel_path)
            return []

        if not isinstance(data, dict) or data.get("version") != _RELATIONS_VERSION:
            logger.warning("Unsupported relations format: %s", rel_path)
            return []

        links_raw = data.get("links", [])
        if not isinstance(links_raw, list):
            return []

        result: List[Tuple[str, float]] = []
        for item in links_raw:
            if isinstance(item, dict) and "target" in item and "score" in item:
                try:
                    result.append((str(item["target"]), float(item["score"])))
                except (TypeError, ValueError):
                    continue

        return result

    def resolve_wikilinks(self, body: str) -> List[str]:
        """Parse [[6-char-hex-id]] references from body text.

        Wikilinks provide explicit cross-references between memories.
        Format: [[abcdef]] where abcdef is a 6-character hex identifier.

        Args:
            body: The memory body text to parse.

        Returns:
            List of unique hex IDs found, in order of first appearance.
        """
        if not body:
            return []

        seen: Set[str] = set()
        result: List[str] = []
        for match in _WIKILINK_RE.finditer(body):
            hex_id = match.group(1)
            if hex_id not in seen:
                seen.add(hex_id)
                result.append(hex_id)

        return result

    def get_relation_path(self, entry_path: Path) -> Path:
        """Return the .relations.json path for a given memory file.

        The sidecar file is placed in the same directory as the memory file,
        named as {stem}.relations.json.

        Args:
            entry_path: Path to the memory file.

        Returns:
            Path to the corresponding .relations.json file.
        """
        return entry_path.parent / f"{entry_path.stem}.relations.json"

    def remove_relations(self, entry_path: Path) -> None:
        """Delete the .relations.json sidecar if it exists.

        Args:
            entry_path: Path to the memory file whose relations to remove.
        """
        rel_path = self.get_relation_path(entry_path)
        if rel_path.exists():
            try:
                rel_path.unlink()
            except OSError:
                logger.warning("Failed to remove relations file: %s", rel_path)
