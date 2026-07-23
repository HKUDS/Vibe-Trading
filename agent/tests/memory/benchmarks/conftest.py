"""Shared fixtures for memory benchmark tests.

Corpus files live outside version control (``tmp/benchmark_corpus/``).
When they are absent the entire benchmark suite is skipped so CI stays green.
The benchmark suite is designed to run locally after modifying the memory layer,
not as part of the automated CI pipeline.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

# Project root (Vibe-Trading/)
PROJECT_ROOT = Path(__file__).resolve().parents[4]
CORPUS_DIR = PROJECT_ROOT / "tmp" / "benchmark_corpus"


def _require_corpus() -> None:
    """Skip the benchmark suite when corpus files are missing."""
    memories = CORPUS_DIR / "memories_with_lifecycle.json"
    queries = CORPUS_DIR / "queries.json"
    if not memories.exists() or not queries.exists():
        pytest.skip(
            "Benchmark corpus files not found — run locally with corpus data "
            "or regenerate via pipeline (see BENCHMARK_GUIDE.md §6).",
            allow_module_level=True,
        )


# Fail-fast at collection time so the whole module is skipped when corpus
# files are absent, rather than failing on every individual test.
_require_corpus()


@pytest.fixture(scope="session")
def memories_corpus() -> list[dict[str, Any]]:
    """Load the 200-entry memory corpus with lifecycle metadata."""
    path = CORPUS_DIR / "memories_with_lifecycle.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def queries_dataset() -> list[dict[str, Any]]:
    """Load the 50-query evaluation dataset with ground-truth top-5."""
    path = CORPUS_DIR / "queries.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)