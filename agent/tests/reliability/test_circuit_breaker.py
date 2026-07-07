"""Tests for Phase 2 source-level circuit breaker."""

from __future__ import annotations

from pathlib import Path

from src.reliability.data.circuit_breaker import CircuitBreaker


def test_circuit_breaker_opens_after_three_failures(tmp_path: Path) -> None:
    breaker = CircuitBreaker(tmp_path / "breaker.sqlite", failure_threshold=3, open_seconds=60)

    for _ in range(3):
        breaker.record_failure("yahoo", RuntimeError("rate limited"))

    assert breaker.snapshot("yahoo").state == "OPEN"


def test_circuit_breaker_half_open_success_closes(tmp_path: Path) -> None:
    breaker = CircuitBreaker(tmp_path / "breaker.sqlite", failure_threshold=1, open_seconds=0)
    breaker.record_failure("stooq", RuntimeError("timeout"))

    assert breaker.before_request("stooq").state == "HALF_OPEN"
    breaker.record_success("stooq")

    assert breaker.snapshot("stooq").state == "CLOSED"


def test_circuit_breaker_skip_records_warning(tmp_path: Path) -> None:
    breaker = CircuitBreaker(tmp_path / "breaker.sqlite", failure_threshold=1, open_seconds=60)
    breaker.record_failure("finnhub", RuntimeError("quota"))

    decision = breaker.before_request("finnhub")

    assert decision.allowed is False
    assert decision.warning is not None
    assert decision.warning.code == "DATA_SOURCE_SKIPPED_BY_CIRCUIT"
