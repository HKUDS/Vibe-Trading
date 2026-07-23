"""Tests for CompressionPipeline: three-level memory compression (Tier 2)."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from src.memory.compression import (
    DAILY_THRESHOLD_DAYS,
    DIGEST_THRESHOLD_DAYS,
    LEVEL_DAILY,
    LEVEL_DIGEST,
    LEVEL_RAW,
    CompressionPipeline,
    compute_tfidf,
    _tokenize_for_tfidf,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SECONDS_PER_DAY = 86400


def _make_entry_file(path: Path, content: str = "Sample content body") -> Path:
    """Write a dummy memory file for archival tests."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


# Long content with many sentences for compression testing
_LONG_CONTENT = (
    "The Bitcoin market showed strong bullish signals today. "
    "Trading volume increased by 50 percent compared to last week. "
    "Technical indicators suggest a breakout above resistance levels. "
    "Moving averages are converging for a potential golden cross. "
    "Institutional investors have been accumulating positions. "
    "The RSI remains in neutral territory around 55 percent. "
    "On-chain metrics show increased whale activity and exchange outflows. "
    "Market sentiment shifted from fear to greed in 24 hours. "
    "Derivatives funding rates indicate leveraged long positioning. "
    "Price action formed a cup-and-handle pattern on the daily chart. "
    "Support levels held firm during the recent correction phase. "
    "Resistance at 50000 remains the key level to watch closely."
)


# ---------------------------------------------------------------------------
# Tests: should_compress
# ---------------------------------------------------------------------------


class TestShouldCompress:
    def test_should_compress_raw_after_7_days(self, tmp_path: Path) -> None:
        """Raw entry accessed >7 days ago returns 'daily'."""
        pipeline = CompressionPipeline(tmp_path)
        now = time.time()
        last_accessed = now - (DAILY_THRESHOLD_DAYS + 1) * _SECONDS_PER_DAY
        result = pipeline.should_compress(LEVEL_RAW, last_accessed, now=now)
        assert result == LEVEL_DAILY

    def test_should_compress_daily_after_30_days(self, tmp_path: Path) -> None:
        """Daily entry accessed >30 days ago returns 'digest'."""
        pipeline = CompressionPipeline(tmp_path)
        now = time.time()
        last_accessed = now - (DIGEST_THRESHOLD_DAYS + 1) * _SECONDS_PER_DAY
        result = pipeline.should_compress(LEVEL_DAILY, last_accessed, now=now)
        assert result == LEVEL_DIGEST

    def test_should_compress_none_if_recent(self, tmp_path: Path) -> None:
        """Recent entry (accessed yesterday) returns None."""
        pipeline = CompressionPipeline(tmp_path)
        now = time.time()
        last_accessed = now - 1 * _SECONDS_PER_DAY  # 1 day ago
        result = pipeline.should_compress(LEVEL_RAW, last_accessed, now=now)
        assert result is None

    def test_should_compress_none_if_already_digest(self, tmp_path: Path) -> None:
        """Already-digest entry returns None regardless of age."""
        pipeline = CompressionPipeline(tmp_path)
        now = time.time()
        last_accessed = now - 365 * _SECONDS_PER_DAY  # 1 year ago
        result = pipeline.should_compress(LEVEL_DIGEST, last_accessed, now=now)
        assert result is None


# ---------------------------------------------------------------------------
# Tests: compress_to_daily
# ---------------------------------------------------------------------------


class TestCompressToDaily:
    def test_compress_to_daily_reduces_size(self, tmp_path: Path) -> None:
        """Output shorter than input for long content."""
        pipeline = CompressionPipeline(tmp_path)
        compressed = pipeline.compress_to_daily(_LONG_CONTENT)
        assert len(compressed) < len(_LONG_CONTENT)

    def test_compress_to_daily_preserves_key_info(self, tmp_path: Path) -> None:
        """Keywords appear in output."""
        pipeline = CompressionPipeline(tmp_path)
        keywords = ("bitcoin", "trading")
        compressed = pipeline.compress_to_daily(_LONG_CONTENT, keywords=keywords)
        # Keywords header should be present
        lower = compressed.lower()
        assert "bitcoin" in lower
        assert "trading" in lower

    def test_compress_to_daily_short_content_passthrough(self, tmp_path: Path) -> None:
        """Short content passes through unchanged."""
        pipeline = CompressionPipeline(tmp_path)
        short = "Just a brief note."
        compressed = pipeline.compress_to_daily(short)
        assert short in compressed


# ---------------------------------------------------------------------------
# Tests: compress_to_digest
# ---------------------------------------------------------------------------


class TestCompressToDigest:
    def test_compress_to_digest_bullet_format(self, tmp_path: Path) -> None:
        """Output is bullet list format."""
        pipeline = CompressionPipeline(tmp_path)
        compressed = pipeline.compress_to_digest(_LONG_CONTENT)
        assert "Key concepts:" in compressed
        assert "  - " in compressed

    def test_compress_to_digest_with_keywords(self, tmp_path: Path) -> None:
        """Context header includes keywords."""
        pipeline = CompressionPipeline(tmp_path)
        keywords = ("crypto", "market")
        compressed = pipeline.compress_to_digest(_LONG_CONTENT, keywords=keywords)
        assert "Context:" in compressed
        assert "crypto" in compressed


# ---------------------------------------------------------------------------
# Tests: estimate_retention
# ---------------------------------------------------------------------------


class TestEstimateRetention:
    def test_estimate_retention_perfect(self, tmp_path: Path) -> None:
        """Same content returns ~1.0."""
        pipeline = CompressionPipeline(tmp_path)
        text = "Bitcoin trading strategy analysis report"
        score = pipeline.estimate_retention(text, text)
        assert abs(score - 1.0) < 0.01

    def test_estimate_retention_low(self, tmp_path: Path) -> None:
        """Very different content returns low score."""
        pipeline = CompressionPipeline(tmp_path)
        original = "Bitcoin cryptocurrency blockchain technology analysis"
        compressed = "cooking recipe pasta garlic olive tomato"
        score = pipeline.estimate_retention(original, compressed)
        assert score < 0.2

    def test_estimate_retention_empty_both(self, tmp_path: Path) -> None:
        """Both empty returns 1.0."""
        pipeline = CompressionPipeline(tmp_path)
        assert pipeline.estimate_retention("", "") == 1.0


# ---------------------------------------------------------------------------
# Tests: apply_compression
# ---------------------------------------------------------------------------


class TestApplyCompression:
    def test_apply_compression_archives_original(self, tmp_path: Path) -> None:
        """Original backed up to archive/ directory."""
        pipeline = CompressionPipeline(tmp_path)
        entry_path = _make_entry_file(tmp_path / "note.md", content=_LONG_CONTENT)

        result = pipeline.apply_compression(
            entry_path, _LONG_CONTENT, ("bitcoin",), LEVEL_DAILY
        )
        assert result is not None
        # Archive should exist
        archive_path = tmp_path / "archive" / "note.md"
        assert archive_path.exists()
        # Archived content should be the original
        assert archive_path.read_text(encoding="utf-8") == _LONG_CONTENT

    def test_apply_compression_daily_output(self, tmp_path: Path) -> None:
        """apply_compression with daily target returns compressed string."""
        pipeline = CompressionPipeline(tmp_path)
        entry_path = _make_entry_file(tmp_path / "note2.md", content=_LONG_CONTENT)

        result = pipeline.apply_compression(
            entry_path, _LONG_CONTENT, ("market",), LEVEL_DAILY
        )
        assert result is not None
        assert len(result) < len(_LONG_CONTENT)


# ---------------------------------------------------------------------------
# Tests: compute_tfidf
# ---------------------------------------------------------------------------


class TestComputeTfidf:
    def test_compute_tfidf(self) -> None:
        """Basic IDF computation correctness."""
        documents = [
            "Bitcoin trading strategy",
            "Ethereum trading protocol",
            "Cooking recipe guide",
        ]
        idf = compute_tfidf(documents)
        # "trading" appears in 2/3 docs, "cooking" in 1/3
        assert "trading" in idf
        assert "cooking" in idf
        # Rare term should have higher IDF
        assert idf["cooking"] > idf["trading"]

    def test_compute_tfidf_empty(self) -> None:
        """Empty documents returns empty dict."""
        assert compute_tfidf([]) == {}

    def test_compute_tfidf_single_doc(self) -> None:
        """Single document gives zero IDF for all terms."""
        idf = compute_tfidf(["Bitcoin trading analysis"])
        # With N=1 and df=1: log(1/(1+1)) = log(0.5) < 0
        # All terms appear in the only doc
        for score in idf.values():
            assert score <= 0.0
