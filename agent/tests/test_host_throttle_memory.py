"""Regression: HostThrottle must not leak memory from stale bucket entries.

The ``_last`` dict grows one entry per unique host bucket and never
evicts stale entries. A batch job that queries many distinct hosts
(e.g. N tickers across N providers) accumulates dead entries without
bound. The fix adds a periodic sweep that drops buckets whose spacing
window (fire_at + min_interval) has fully elapsed.

The sweep must be interval-aware: a bucket that fired 0.1s ago with a
1.5s interval is still within its spacing window and must NOT be swept.
Sweeping it early would let the next request fire immediately with no
spacing, defeating the rate limiter.
"""

from __future__ import annotations

import time

from backtest.loaders._http import HostThrottle


def test_wait_records_bucket() -> None:
    throttle = HostThrottle()
    throttle.wait("eastmoney", min_interval=1.0)
    assert "eastmoney" in throttle._last


def test_wait_zero_interval_no_op() -> None:
    throttle = HostThrottle()
    throttle.wait("x", min_interval=0.0)
    # min_interval <= 0 returns early without recording.
    assert "x" not in throttle._last


def test_sweep_removes_stale_buckets() -> None:
    """Buckets whose spacing window has fully elapsed must be swept."""
    throttle = HostThrottle()
    # Use a tiny interval so the spacing window elapses quickly.
    throttle.wait("a", min_interval=0.01)
    throttle.wait("b", min_interval=0.01)
    assert len(throttle._last) == 2

    # Wait for the spacing window (fire_at + 0.01) to pass.
    time.sleep(0.02)

    now = time.monotonic()
    with throttle._lock:
        throttle._sweep_stale_locked(now)

    assert "a" not in throttle._last
    assert "b" not in throttle._last


def test_sweep_keeps_active_buckets() -> None:
    """Buckets with a future fire time must survive the sweep."""
    throttle = HostThrottle()
    # Manually set a future fire time to avoid the real sleep.
    with throttle._lock:
        throttle._last["a"] = (time.monotonic() + 100.0, 1.0)

    now = time.monotonic()
    with throttle._lock:
        throttle._sweep_stale_locked(now)
    assert "a" in throttle._last


def test_sweep_keeps_buckets_within_spacing_window() -> None:
    """A bucket that fired recently but is still within its spacing window
    must NOT be swept — sweeping it early would skip rate-limit spacing."""
    throttle = HostThrottle()
    # Bucket fired 0.01s ago with a 10s interval — still within spacing window.
    with throttle._lock:
        throttle._last["iwencai"] = (time.monotonic() - 0.01, 10.0)

    now = time.monotonic()
    with throttle._lock:
        throttle._sweep_stale_locked(now)

    assert "iwencai" in throttle._last


def test_periodic_sweep_on_wait() -> None:
    """wait() should trigger a sweep after the sweep interval."""
    throttle = HostThrottle()
    # Use a tiny interval so the bucket becomes stale quickly.
    throttle.wait("a", min_interval=0.01)

    # Simulate that the last sweep was long ago.
    throttle._last_sweep = time.monotonic() - 61.0

    time.sleep(0.02)

    # This wait should trigger a sweep, removing "a" (stale) and adding "b".
    throttle.wait("b", min_interval=1.0)

    assert "a" not in throttle._last
    assert "b" in throttle._last


def test_many_unique_buckets_do_not_grow_unboundedly() -> None:
    """After a sweep, stale buckets from earlier calls must be gone."""
    throttle = HostThrottle()
    # Simulate old last_sweep so the next wait triggers a sweep.
    throttle._last_sweep = time.monotonic() - 61.0

    # Add 100 buckets with past fire times and tiny intervals (stale).
    now = time.monotonic()
    for i in range(100):
        throttle._last[f"host-{i}"] = (now - 10.0, 0.01)

    assert len(throttle._last) == 100

    # This wait triggers a sweep that should remove all stale entries.
    throttle.wait("new-host", min_interval=1.0)

    assert len(throttle._last) == 1
    assert "new-host" in throttle._last


def test_deadline_rejects_local_wait_without_reserving_another_slot(monkeypatch):
    import pytest
    from backtest.loaders.acquisition import source_deadline, SourceAdmissionTimeout
    from backtest.loaders.base import acquisition_error_kind
    from backtest.loaders import _http

    monkeypatch.setattr(_http.time, "monotonic", lambda: 100.0)
    gate = _http.HostThrottle()
    gate._last["test"] = (101.0, 0.6)
    token = source_deadline.set(100.5)
    try:
        with pytest.raises(SourceAdmissionTimeout) as error:
            gate.wait("test", 0.6)
        assert acquisition_error_kind(error.value) == "source_busy"
        assert gate._last["test"] == (101.0, 0.6)
    finally:
        source_deadline.reset(token)


def test_http_socket_timeout_uses_remaining_acquisition_budget(monkeypatch):
    from types import SimpleNamespace
    from backtest.loaders import _http
    from backtest.loaders.acquisition import source_deadline

    calls = []
    monkeypatch.setattr(_http, "_THROTTLE", SimpleNamespace(wait=lambda *args: None))
    monkeypatch.setattr(_http, "_session_for", lambda key: SimpleNamespace(get=lambda *args, **kwargs: calls.append(kwargs)))
    monkeypatch.setattr(_http.time, "monotonic", lambda: 100.0)
    token = source_deadline.set(100.5)
    try:
        _http.throttled_get("https://example.test", host_key="test", min_interval=0.6, timeout=15)
        assert 0.44 < calls[0]["timeout"] < 0.46
    finally:
        source_deadline.reset(token)
