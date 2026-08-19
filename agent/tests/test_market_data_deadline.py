"""Test the deadline mechanism in fetch_market_data.

Verifies that fetch_market_data respects the deadline_s parameter
and returns partial results instead of blocking indefinitely.
"""
from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

import pytest

from src.market_data import fetch_market_data


def test_deadline_exceeded_returns_partial() -> None:
    """When deadline is exceeded, return partial results."""
    call_count = 0

    def slow_fetch(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        time.sleep(2)  # Each call takes 2s
        raise TimeoutError("simulated timeout")

    class FakeLoader:
        def fetch(self, *args, **kwargs):
            return slow_fetch()

    def fake_resolver(source):
        if source == "slow":
            return FakeLoader
        raise Exception(f"no loader for {source}")

    def fake_chain(src):
        return ["slow", "slow", "slow", "slow", "slow"]

    # 5 sources × 2s = 10s normally, but deadline is 3s
    start = time.monotonic()
    result = fetch_market_data(
        codes=["0700.HK"],
        start_date="2024-01-01",
        end_date="2024-01-31",
        source="slow",
        loader_resolver=fake_resolver,
        fallback_chain_provider=fake_chain,
        max_fallback_attempts=5,
        deadline_s=3.0,
    )
    elapsed = time.monotonic() - start

    # Should complete in ~3-5s (deadline + one extra call), not 10s
    assert elapsed < 8.0, f"Took {elapsed:.1f}s, deadline was 3s"
    # Should have tried at least 1 source
    assert call_count >= 1


def test_no_deadline_retries_all_sources() -> None:
    """When deadline_s=None, retry all sources."""
    call_count = 0

    def fast_fetch(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        raise ValueError("simulated error")

    class FakeLoader:
        def fetch(self, *args, **kwargs):
            return fast_fetch()

    def fake_resolver(source):
        return FakeLoader

    def fake_chain(src):
        return ["a", "b", "c"]

    result = fetch_market_data(
        codes=["0700.HK"],
        start_date="2024-01-01",
        end_date="2024-01-31",
        source="a",
        loader_resolver=fake_resolver,
        fallback_chain_provider=fake_chain,
        max_fallback_attempts=3,
        deadline_s=None,
    )

    # Should have tried: a, b, c (the full chain)
    assert call_count == 3


def test_deadline_does_not_affect_fast_sources() -> None:
    """When sources are fast, deadline is not triggered."""
    call_count = 0

    class FastLoader:
        def fetch(self, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            import pandas as pd
            return {"0700.HK": pd.DataFrame({"close": [100.0]})}

    def fake_resolver(source):
        return FastLoader

    def fake_chain(src):
        return ["fast"]

    result = fetch_market_data(
        codes=["0700.HK"],
        start_date="2024-01-01",
        end_date="2024-01-31",
        source="fast",
        loader_resolver=fake_resolver,
        fallback_chain_provider=fake_chain,
        max_fallback_attempts=3,
        deadline_s=5.0,
    )

    assert "0700.HK" in result
    assert call_count == 1  # Succeeded first try


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
