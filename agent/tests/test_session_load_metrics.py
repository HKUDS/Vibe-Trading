"""``SessionService._load_metrics`` must not discard the whole row over one
non-numeric field (e.g. a benchmark ticker column written into metrics.csv).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.session.service import SessionService


def _write_metrics_csv(run_dir: Path, header: str, row: str) -> None:
    artifacts = run_dir / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "metrics.csv").write_text(f"{header}\n{row}\n", encoding="utf-8")


def test_non_numeric_field_is_skipped_not_fatal(tmp_path: Path) -> None:
    """A stray string column (e.g. benchmark_ticker) must not blank out real metrics."""
    _write_metrics_csv(
        tmp_path,
        "total_return,sharpe,benchmark_ticker",
        "0.15,1.2,SPY",
    )

    metrics = SessionService._load_metrics(tmp_path)

    assert metrics == {"total_return": 0.15, "sharpe": 1.2}


def test_all_numeric_row_is_unaffected(tmp_path: Path) -> None:
    _write_metrics_csv(tmp_path, "total_return,sharpe", "0.15,1.2")

    metrics = SessionService._load_metrics(tmp_path)

    assert metrics == {"total_return": 0.15, "sharpe": 1.2}


def test_missing_metrics_file_returns_none(tmp_path: Path) -> None:
    assert SessionService._load_metrics(tmp_path) is None


def test_row_with_only_non_numeric_fields_returns_none(tmp_path: Path) -> None:
    _write_metrics_csv(tmp_path, "benchmark_ticker", "SPY")

    assert SessionService._load_metrics(tmp_path) is None


def test_empty_field_values_are_skipped(tmp_path: Path) -> None:
    _write_metrics_csv(tmp_path, "total_return,sharpe", "0.15,")

    metrics = SessionService._load_metrics(tmp_path)

    assert metrics == {"total_return": 0.15}


@pytest.mark.parametrize("contents", [b"", b"total_return,sharpe\n", b"total_return\n\xff\n"])
def test_empty_or_unreadable_csv_returns_none(tmp_path: Path, contents: bytes) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "metrics.csv").write_bytes(contents)

    assert SessionService._load_metrics(tmp_path) is None


def test_extra_csv_cells_do_not_discard_named_numeric_metrics(tmp_path: Path) -> None:
    _write_metrics_csv(tmp_path, "total_return,benchmark_ticker", "0,SPY,extra")

    assert SessionService._load_metrics(tmp_path) == {"total_return": 0.0}
