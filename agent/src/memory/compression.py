"""Three-level memory compression pipeline: Raw -> Daily -> Digest (Tier 2).

Uses TF-IDF sentence scoring to extract key information while maintaining
high retention. Original content is archived before compression.

Feature flag: VT_MEMORY_COMPRESSION (default off).
"""

from __future__ import annotations

import logging
import math
import os
import re
import shutil
import time
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# ─── Compression level constants ────────────────────────────────────────────

LEVEL_RAW = "raw"
LEVEL_DAILY = "daily"
LEVEL_DIGEST = "digest"

# Trigger thresholds (days since last access)
DAILY_THRESHOLD_DAYS = 7
DIGEST_THRESHOLD_DAYS = 30

# Compression targets
DAILY_TOP_K_SENTENCES = 5  # Keep top-5 sentences + first/last
DIGEST_MAX_TOKENS = 50  # Max tokens in digest
DIGEST_TOP_KEYWORDS = 15  # Top keywords for digest bullet list

# Seconds per day
_SECONDS_PER_DAY = 86400

# ─── Tokenization ───────────────────────────────────────────────────────────

_NON_LATIN_RANGES = (
    "\u4e00-\u9fff"  # CJK Unified Ideographs
    "\u3400-\u4dbf"  # CJK Extension A
    "\u0e00-\u0e7f"  # Thai
    "\u0620-\u064a"  # Arabic letters
    "\u05d0-\u05ea"  # Hebrew letters
    "\u0400-\u04ff"  # Cyrillic
)
_TOKEN_RE = re.compile(rf"[a-zA-Z0-9]{{3,}}|[{_NON_LATIN_RANGES}]")

# Sentence boundary regex: split on . ! ? and CJK sentence-end marks
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?。！？])\s+|\n+")


# ─── Public Functions ────────────────────────────────────────────────────────


def _tokenize_for_tfidf(text: str) -> List[str]:
    """Tokenize text for TF-IDF scoring.

    Uses same regex pattern as persistent.py: ASCII words >= 3 chars
    or individual non-Latin script characters.
    """
    return _TOKEN_RE.findall(text.lower())


def _split_sentences(text: str) -> List[str]:
    """Split text into sentences.

    Handles English period/question/exclamation and Chinese period
    boundaries. Filters empty results.
    """
    raw_parts = _SENTENCE_SPLIT_RE.split(text.strip())
    sentences = [s.strip() for s in raw_parts if s.strip()]
    return sentences


def compute_tfidf(documents: List[str]) -> Dict[str, float]:
    """Compute IDF scores across a corpus of documents (sentences).

    Args:
        documents: List of document texts (typically sentences).

    Returns:
        Dict mapping term -> IDF score. IDF = log(N / (1 + df(t))).
    """
    n = len(documents)
    if n == 0:
        return {}

    # Count document frequency for each term
    df: Counter = Counter()
    for doc in documents:
        unique_terms = set(_tokenize_for_tfidf(doc))
        for term in unique_terms:
            df[term] += 1

    # Compute IDF: log(N / (1 + df(term)))
    idf_scores: Dict[str, float] = {}
    for term, freq in df.items():
        idf_scores[term] = math.log(n / (1 + freq))

    return idf_scores


def _score_sentence(sentence: str, idf_scores: Dict[str, float]) -> float:
    """Score a sentence by normalized sum of IDF weights.

    Score = sum(idf(token) for token in sentence) / len(tokens).
    Returns 0.0 for empty sentences.
    """
    tokens = _tokenize_for_tfidf(sentence)
    if not tokens:
        return 0.0
    total = sum(idf_scores.get(t, 0.0) for t in tokens)
    return total / len(tokens)


def extract_key_sentences(
    content: str, idf_scores: Dict[str, float], top_k: int = DAILY_TOP_K_SENTENCES
) -> str:
    """Extract top-k sentences ranked by TF-IDF weight sum.

    Always includes first and last sentence for context framing.
    Returns joined text of selected sentences.
    """
    sentences = _split_sentences(content)
    if len(sentences) <= top_k + 2:
        # Already short enough, return as-is
        return content.strip()

    # Score all sentences
    scored: List[Tuple[int, float, str]] = []
    for idx, sent in enumerate(sentences):
        score = _score_sentence(sent, idf_scores)
        scored.append((idx, score, sent))

    # Always keep first and last
    first_idx = 0
    last_idx = len(sentences) - 1
    kept_indices: Set[int] = {first_idx, last_idx}

    # Pick top-k from middle sentences by score
    middle = [(idx, sc, s) for idx, sc, s in scored if idx not in kept_indices]
    middle.sort(key=lambda x: x[1], reverse=True)

    for idx, _sc, _s in middle[:top_k]:
        kept_indices.add(idx)

    # Reconstruct in original order
    selected = [sentences[i] for i in sorted(kept_indices)]
    return " ".join(selected)


# ─── CompressionPipeline ─────────────────────────────────────────────────────


class CompressionPipeline:
    """Three-level compression pipeline for memory entries."""

    def __init__(self, memory_dir: Path) -> None:
        """Initialize with memory directory for archive storage."""
        self._memory_dir = memory_dir
        self._archive_dir = memory_dir / "archive"

    def should_compress(
        self, compression_level: str, last_accessed: float, now: float = 0.0
    ) -> Optional[str]:
        """Determine if an entry should be compressed and to what level.

        Args:
            compression_level: Current level ("raw", "daily", "digest").
            last_accessed: Epoch timestamp of last access.
            now: Current time (defaults to time.time()).

        Returns:
            Target compression level ("daily" or "digest") or None.
        """
        if now <= 0.0:
            now = time.time()

        days_since_access = (now - last_accessed) / _SECONDS_PER_DAY

        if compression_level == LEVEL_RAW and days_since_access > DAILY_THRESHOLD_DAYS:
            return LEVEL_DAILY
        if compression_level == LEVEL_DAILY and days_since_access > DIGEST_THRESHOLD_DAYS:
            return LEVEL_DIGEST

        # Already digest or not enough time elapsed
        return None

    def compress_to_daily(self, content: str, keywords: tuple = ()) -> str:
        """Compress raw content to daily level (~50% size).

        Strategy: TF-IDF key-sentence extraction.
        - Split into sentences
        - Score each sentence by sum of IDF weights
        - Keep top-5 + first sentence + last sentence
        - Prepend keywords as context header
        """
        sentences = _split_sentences(content)
        if not sentences:
            return content

        # Use sentences as document corpus for IDF calculation
        idf_scores = compute_tfidf(sentences)

        # Extract key sentences
        compressed = extract_key_sentences(content, idf_scores, DAILY_TOP_K_SENTENCES)

        # Prepend keywords as context header if available
        if keywords:
            header = "Keywords: " + ", ".join(keywords)
            compressed = header + "\n\n" + compressed

        return compressed

    def compress_to_digest(self, daily_content: str, keywords: tuple = ()) -> str:
        """Compress daily content to digest level (~10-20% of original).

        Strategy: Extract core concepts and keywords.
        - Extract top-N most important terms
        - Format as bullet-point summary
        """
        tokens = _tokenize_for_tfidf(daily_content)
        if not tokens:
            return daily_content

        # Count term frequencies in the content
        tf: Counter = Counter(tokens)

        # Use sentence-level IDF for importance weighting
        sentences = _split_sentences(daily_content)
        idf_scores = compute_tfidf(sentences) if sentences else {}

        # Score each unique term: tf * idf
        term_scores: List[Tuple[str, float]] = []
        for term, freq in tf.items():
            idf = idf_scores.get(term, 1.0)
            term_scores.append((term, freq * idf))

        # Sort by score descending, take top keywords
        term_scores.sort(key=lambda x: x[1], reverse=True)
        top_terms = [t for t, _s in term_scores[:DIGEST_TOP_KEYWORDS]]

        # Build bullet-point summary
        lines: List[str] = []
        if keywords:
            lines.append("Context: " + ", ".join(keywords))
        lines.append("Key concepts:")
        for term in top_terms:
            lines.append(f"  - {term}")

        return "\n".join(lines)

    def archive_original(self, entry_path: Path) -> Optional[Path]:
        """Backup original file to archive/ before compression.

        Returns archive path or None on failure. Creates archive/ dir
        on demand. Uses atomic copy (write tmp + rename) for safety.
        """
        if not entry_path.exists():
            logger.warning("Cannot archive non-existent file: %s", entry_path)
            return None

        try:
            self._archive_dir.mkdir(parents=True, exist_ok=True)
            archive_path = self._archive_dir / entry_path.name
            tmp_path = archive_path.with_suffix(archive_path.suffix + ".tmp")

            # Atomic copy: write to tmp then rename
            shutil.copy2(str(entry_path), str(tmp_path))
            os.replace(str(tmp_path), str(archive_path))

            logger.debug("Archived %s -> %s", entry_path.name, archive_path)
            return archive_path
        except OSError as exc:
            logger.error("Archive failed for %s: %s", entry_path, exc)
            # Clean up tmp file if it exists
            tmp_path = (self._archive_dir / entry_path.name).with_suffix(
                entry_path.suffix + ".tmp"
            )
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
            return None

    def apply_compression(
        self, entry_path: Path, content: str, keywords: tuple, target_level: str
    ) -> Optional[str]:
        """Execute compression: archive original, compute compressed content.

        Args:
            entry_path: Path to the memory .md file.
            content: Current body content.
            keywords: Entry keywords for context.
            target_level: "daily" or "digest".

        Returns:
            Compressed content string, or None on failure.
        """
        # Archive the original before modifying
        archive_result = self.archive_original(entry_path)
        if archive_result is None and entry_path.exists():
            # Archive failed but file exists - abort to avoid data loss
            logger.error(
                "Compression aborted: archive failed for %s", entry_path
            )
            return None

        try:
            if target_level == LEVEL_DAILY:
                compressed = self.compress_to_daily(content, keywords)
            elif target_level == LEVEL_DIGEST:
                compressed = self.compress_to_digest(content, keywords)
            else:
                logger.error("Unknown compression target: %s", target_level)
                return None

            retention = self.estimate_retention(content, compressed)
            logger.info(
                "Compressed %s to %s (retention=%.2f)",
                entry_path.name,
                target_level,
                retention,
            )
            return compressed
        except Exception as exc:
            logger.error("Compression failed for %s: %s", entry_path, exc)
            return None

    def estimate_retention(self, original: str, compressed: str) -> float:
        """Estimate information retention as Jaccard token overlap (0.0-1.0).

        Computes |intersection| / |union| of token sets between original
        and compressed text.
        """
        orig_tokens = set(_tokenize_for_tfidf(original))
        comp_tokens = set(_tokenize_for_tfidf(compressed))

        if not orig_tokens and not comp_tokens:
            return 1.0
        if not orig_tokens or not comp_tokens:
            return 0.0

        intersection = orig_tokens & comp_tokens
        union = orig_tokens | comp_tokens
        return len(intersection) / len(union)
