"""Shared fixtures for route tests under ``tests/api``."""

from __future__ import annotations

from typing import Callable, List

import pytest

from src.api import runs_routes


@pytest.fixture
def offloaded(monkeypatch: pytest.MonkeyPatch) -> List[Callable[..., object]]:
    """Record callables the runs routes hand to ``run_in_threadpool``."""
    calls: List[Callable[..., object]] = []

    async def fake_run_in_threadpool(func, *args, **kwargs):
        calls.append(func)
        return func(*args, **kwargs)

    monkeypatch.setattr(runs_routes, "run_in_threadpool", fake_run_in_threadpool)
    return calls
