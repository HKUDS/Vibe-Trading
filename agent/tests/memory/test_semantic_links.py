"""Tests for SemanticLinker: BM25-based memory linking (Tier 2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.memory.semantic_links import (
    SemanticLinker,
    _tokenize_for_bm25,
    compute_bm25_score,
    compute_idf,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tokens(text: str) -> list[str]:
    """Tokenize text using the module tokenizer."""
    return _tokenize_for_bm25(text)


# ---------------------------------------------------------------------------
# Tests: discover_links
# ---------------------------------------------------------------------------


class TestDiscoverLinks:
    def test_discover_links_finds_similar(self, tmp_path: Path) -> None:
        """Entries with overlapping content get linked."""
        linker = SemanticLinker(tmp_path)
        source_tokens = _make_tokens("bitcoin trading strategy analysis")
        all_entries = [
            ("source.md", _make_tokens("bitcoin trading strategy analysis")),
            ("related.md", _make_tokens("bitcoin trading strategy backtest")),
            ("unrelated.md", _make_tokens("weather forecast temperature rain")),
        ]
        links = linker.discover_links("source.md", source_tokens, all_entries)
        # related.md should be linked (overlapping tokens)
        targets = [t for t, _ in links]
        assert "related.md" in targets

    def test_discover_links_threshold(self, tmp_path: Path) -> None:
        """Low-similarity entries excluded (score < 0.3)."""
        linker = SemanticLinker(tmp_path)
        source_tokens = _make_tokens("quantum computing algorithm optimization")
        all_entries = [
            ("source.md", _make_tokens("quantum computing algorithm optimization")),
            ("different.md", _make_tokens("cooking recipe pasta tomato garlic olive")),
        ]
        links = linker.discover_links("source.md", source_tokens, all_entries)
        # "different.md" has zero overlap, should be excluded
        targets = [t for t, _ in links]
        assert "different.md" not in targets

    def test_discover_links_max_cap(self, tmp_path: Path) -> None:
        """Hard cap at 10 outgoing links."""
        linker = SemanticLinker(tmp_path)
        source_tokens = _make_tokens("common shared term repeated many times")
        # Create 15 entries all sharing some terms
        all_entries = [("source.md", source_tokens)]
        for i in range(15):
            all_entries.append(
                (f"entry_{i}.md", _make_tokens(f"common shared term variant {i} extra words here"))
            )
        links = linker.discover_links("source.md", source_tokens, all_entries, top_k=15)
        assert len(links) <= 10

    def test_discover_links_empty_tokens(self, tmp_path: Path) -> None:
        """Empty tokens returns empty list."""
        linker = SemanticLinker(tmp_path)
        links = linker.discover_links("source.md", [], [("other.md", ["abc"])])
        assert links == []


# ---------------------------------------------------------------------------
# Tests: save/load relations
# ---------------------------------------------------------------------------


class TestRelationsPersistence:
    def test_save_and_load_relations(self, tmp_path: Path) -> None:
        """Roundtrip write/read .relations.json."""
        linker = SemanticLinker(tmp_path)
        entry_path = tmp_path / "test_entry.md"
        entry_path.write_text("content", encoding="utf-8")

        links = [("related_a.md", 0.85), ("related_b.md", 0.42)]
        linker.save_relations(entry_path, links)

        loaded = linker.load_relations(entry_path)
        assert len(loaded) == 2
        assert loaded[0][0] == "related_a.md"
        assert abs(loaded[0][1] - 0.85) < 0.001
        assert loaded[1][0] == "related_b.md"
        assert abs(loaded[1][1] - 0.42) < 0.001

    def test_load_relations_missing_file(self, tmp_path: Path) -> None:
        """Returns empty list gracefully when no .relations.json."""
        linker = SemanticLinker(tmp_path)
        entry_path = tmp_path / "nonexistent.md"
        loaded = linker.load_relations(entry_path)
        assert loaded == []

    def test_remove_relations(self, tmp_path: Path) -> None:
        """Deletes the .relations.json file."""
        linker = SemanticLinker(tmp_path)
        entry_path = tmp_path / "to_remove.md"
        entry_path.write_text("content", encoding="utf-8")

        # Save then remove
        linker.save_relations(entry_path, [("target.md", 0.5)])
        rel_path = linker.get_relation_path(entry_path)
        assert rel_path.exists()

        linker.remove_relations(entry_path)
        assert not rel_path.exists()

    def test_remove_relations_missing_file_no_error(self, tmp_path: Path) -> None:
        """remove_relations gracefully handles missing file."""
        linker = SemanticLinker(tmp_path)
        entry_path = tmp_path / "no_rels.md"
        # Should not raise
        linker.remove_relations(entry_path)


# ---------------------------------------------------------------------------
# Tests: resolve_wikilinks
# ---------------------------------------------------------------------------


class TestResolveWikilinks:
    def test_resolve_wikilinks(self, tmp_path: Path) -> None:
        """Parses [[6-char-hex]] references from body text."""
        linker = SemanticLinker(tmp_path)
        body = "See [[a1b2c3]] and also [[ff00ee]] for details."
        result = linker.resolve_wikilinks(body)
        assert result == ["a1b2c3", "ff00ee"]

    def test_resolve_wikilinks_no_matches(self, tmp_path: Path) -> None:
        """Body without wikilinks returns empty."""
        linker = SemanticLinker(tmp_path)
        body = "This is plain text with no links at all."
        result = linker.resolve_wikilinks(body)
        assert result == []

    def test_resolve_wikilinks_dedup(self, tmp_path: Path) -> None:
        """Duplicate wikilinks appear only once."""
        linker = SemanticLinker(tmp_path)
        body = "First [[abc123]], then [[abc123]] again."
        result = linker.resolve_wikilinks(body)
        assert result == ["abc123"]

    def test_resolve_wikilinks_empty_body(self, tmp_path: Path) -> None:
        """Empty body returns empty list."""
        linker = SemanticLinker(tmp_path)
        assert linker.resolve_wikilinks("") == []

    def test_resolve_wikilinks_invalid_format(self, tmp_path: Path) -> None:
        """Non-hex or wrong length are not matched."""
        linker = SemanticLinker(tmp_path)
        body = "[[GGGGGG]] [[abc]] [[1234567]]"
        result = linker.resolve_wikilinks(body)
        assert result == []


# ---------------------------------------------------------------------------
# Tests: IDF computation
# ---------------------------------------------------------------------------


class TestComputeIdf:
    def test_basic_idf(self) -> None:
        """IDF scores are higher for rare terms."""
        corpus = [
            ["trading", "bitcoin", "strategy"],
            ["trading", "ethereum", "defi"],
            ["cooking", "recipe", "pasta"],
        ]
        idf = compute_idf(corpus)
        # "trading" appears in 2/3 docs → lower IDF
        # "cooking" appears in 1/3 docs → higher IDF
        assert idf["cooking"] > idf["trading"]

    def test_empty_corpus(self) -> None:
        """Empty corpus returns empty dict."""
        assert compute_idf([]) == {}


class TestBm25Score:
    def test_identical_returns_positive(self) -> None:
        """Identical query and doc tokens give positive score."""
        tokens = ["bitcoin", "trading", "strategy"]
        idf = compute_idf([tokens, ["other", "words", "here"]])
        score = compute_bm25_score(tokens, tokens, idf, avg_dl=3.0)
        assert score > 0.0

    def test_no_overlap_returns_zero(self) -> None:
        """No term overlap gives zero score."""
        query = ["bitcoin", "trading"]
        doc = ["cooking", "recipe"]
        idf = compute_idf([query, doc])
        score = compute_bm25_score(query, doc, idf, avg_dl=2.0)
        assert score == 0.0
