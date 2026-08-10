"""Regression: increment_daily_count must be atomic under concurrency.

The original read-modify-write was not guarded by a lock. Two concurrent
orders could both read the same count (e.g. 5), both increment to 6, and
both write 6 — losing one increment. The fix uses ``fcntl.flock`` on a
sibling lock file so only one writer at a time enters the critical
section.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

import src.live.paths as paths
from src.live.daily_count import increment_daily_count, read_daily_count


@pytest.fixture
def live_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(paths, "get_runtime_root", lambda: tmp_path)
    return tmp_path


def test_increment_returns_increasing_count(live_runtime: Path) -> None:
    assert increment_daily_count("robinhood") == 1
    assert increment_daily_count("robinhood") == 2
    assert increment_daily_count("robinhood") == 3


def test_read_returns_current_count(live_runtime: Path) -> None:
    increment_daily_count("robinhood")
    increment_daily_count("robinhood")
    assert read_daily_count("robinhood") == 2


def test_read_returns_zero_for_new_broker(live_runtime: Path) -> None:
    assert read_daily_count("alpaca") == 0


def test_concurrent_increments_no_lost_updates(live_runtime: Path) -> None:
    """N threads each increment once; the final count must be exactly N.

    Without the flock, some increments are lost (two threads read the same
    value, both write count+1). With the lock, every increment is serialized
    and the final count is exactly the number of increments.
    """
    n_threads = 20
    barrier = threading.Barrier(n_threads)

    def _worker() -> None:
        barrier.wait()  # release all threads simultaneously
        increment_daily_count("robinhood")

    threads = [threading.Thread(target=_worker) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    final = read_daily_count("robinhood")
    assert final == n_threads, f"expected {n_threads}, got {final} — lost increments"


def test_concurrent_increments_different_browsers_dont_interfere(live_runtime: Path) -> None:
    """Increments for different brokers must not interfere."""
    increment_daily_count("robinhood")
    increment_daily_count("alpaca")
    increment_daily_count("robinhood")
    assert read_daily_count("robinhood") == 2
    assert read_daily_count("alpaca") == 1
