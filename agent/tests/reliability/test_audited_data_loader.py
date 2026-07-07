"""Tests for Phase 2 audited data loader wrapper."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from src.reliability.data.circuit_breaker import CircuitBreaker
from src.reliability.data.errors import AllSourcesOpenError
from src.reliability.data.loader_wrapper import AuditedDataLoader
from src.reliability.data.source_manifest import SourceManifest
from backtest.runner import _attach_loader_audit_to_config


class FakeLoader:
    name = "yahoo"
    markets = {"us_equity"}
    requires_auth = False

    def __init__(self, data_map: dict[str, pd.DataFrame] | None = None) -> None:
        self.data_map = data_map or {}
        self.calls: list[tuple] = []

    def is_available(self) -> bool:
        return True

    def fetch(self, codes, start_date, end_date, interval="1D", fields=None):
        self.calls.append((codes, start_date, end_date, interval, fields))
        return self.data_map


class LoaderWithoutFields:
    name = "yahoo"

    def __init__(self, data_map: dict[str, pd.DataFrame] | None = None) -> None:
        self.data_map = data_map or {}
        self.calls: list[tuple] = []

    def is_available(self) -> bool:
        return True

    def fetch(self, codes, start_date, end_date, interval="1D"):
        self.calls.append((codes, start_date, end_date, interval))
        return self.data_map


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": [10.0, 11.0],
            "high": [11.0, 12.0],
            "low": [9.0, 10.0],
            "close": [10.5, 11.5],
            "volume": [1000, 1100],
        },
        index=pd.date_range("2026-01-01", periods=2, freq="D"),
    )


def test_audited_loader_preserves_fetch_return_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VIBE_TRADING_RELIABILITY_MODE", "observe")
    inner = FakeLoader({"AAPL.US": _frame()})
    loader = AuditedDataLoader(inner, source="yahoo")

    result = loader.fetch(["AAPL.US"], "2026-01-01", "2026-01-02", interval="1D")

    assert result is inner.data_map
    assert loader.last_audit_report is not None
    assert loader.last_audit_report.row_count == 2


def test_audited_loader_preserves_legacy_fetch_without_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VIBE_TRADING_RELIABILITY_MODE", "observe")
    inner = LoaderWithoutFields({"AAPL.US": _frame()})
    loader = AuditedDataLoader(inner, source="yahoo")

    result = loader.fetch(["AAPL.US"], "2026-01-01", "2026-01-02")

    assert result is inner.data_map
    assert inner.calls == [(["AAPL.US"], "2026-01-01", "2026-01-02", "1D")]
    assert loader.last_audit_report is not None


def test_reliability_mode_off_uses_original_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VIBE_TRADING_RELIABILITY_MODE", "off")
    inner = FakeLoader({"AAPL.US": _frame()})
    loader = AuditedDataLoader(inner, source="yahoo")

    result = loader.fetch(["AAPL.US"], "2026-01-01", "2026-01-02")

    assert result is inner.data_map
    assert loader.last_audit_report is None


def test_auto_source_records_fallback_manifest(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VIBE_TRADING_RELIABILITY_MODE", "observe")
    inner = FakeLoader({"AAPL.US": _frame()})
    manifest = SourceManifest(
        requested_source="auto",
        selected_source="yahoo",
        fallback_chain=["yahoo", "stooq"],
        attempted_sources=["tencent", "yahoo"],
        runtime_source="yahoo",
        cache_hit=False,
    )
    loader = AuditedDataLoader(inner, source="auto", source_manifest=manifest)

    loader.fetch(["AAPL.US"], "2026-01-01", "2026-01-02")

    assert loader.last_audit_report is not None
    access = loader.last_audit_report.access_contract
    assert access.source == "auto"
    assert access.selected_source == "yahoo"
    assert access.fallback_chain == ["yahoo", "stooq"]


def test_local_source_never_falls_back_to_network(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VIBE_TRADING_RELIABILITY_MODE", "observe")
    inner = FakeLoader({})
    inner.name = "local"
    loader = AuditedDataLoader(inner, source="local")

    loader.fetch(["local:AAPL.US"], "2026-01-01", "2026-01-02")

    assert loader.last_audit_report is not None
    assert loader.last_audit_report.access_contract.explicit_local is True
    assert loader.last_audit_report.access_contract.fallback_chain == ["local"]


def test_all_sources_open_raises_not_empty_frame(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VIBE_TRADING_RELIABILITY_MODE", "observe")
    breaker = CircuitBreaker(tmp_path / "breaker.sqlite", failure_threshold=1, open_seconds=60)
    breaker.record_failure("yahoo", RuntimeError("quota"))
    breaker.record_failure("stooq", RuntimeError("quota"))
    inner = FakeLoader({})
    loader = AuditedDataLoader(
        inner,
        source="auto",
        source_manifest=SourceManifest(
            requested_source="auto",
            selected_source="yahoo",
            fallback_chain=["yahoo", "stooq"],
            attempted_sources=[],
            runtime_source=None,
            cache_hit=False,
        ),
        circuit_breaker=breaker,
    )

    with pytest.raises(AllSourcesOpenError) as excinfo:
        loader.fetch(["AAPL.US"], "2026-01-01", "2026-01-02")

    assert excinfo.value.error_code == "DATA_ALL_SOURCES_OPEN"


def test_all_sources_open_records_hard_failure_code(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VIBE_TRADING_RELIABILITY_MODE", "observe")
    breaker = CircuitBreaker(tmp_path / "breaker.sqlite", failure_threshold=1, open_seconds=60)
    breaker.record_failure("yahoo", RuntimeError("quota"))
    inner = FakeLoader({})
    loader = AuditedDataLoader(
        inner,
        source="auto",
        source_manifest=SourceManifest(
            requested_source="auto",
            selected_source="yahoo",
            fallback_chain=["yahoo"],
            attempted_sources=[],
            runtime_source=None,
            cache_hit=False,
        ),
        circuit_breaker=breaker,
    )

    with pytest.raises(AllSourcesOpenError):
        loader.fetch(["AAPL.US"], "2026-01-01", "2026-01-02")

    assert loader.last_audit_report is not None
    assert loader.last_audit_report.all_sources_open is True
    assert any(w.code == "DATA_ALL_SOURCES_OPEN" for w in loader.last_audit_report.quality_warnings)


def test_available_at_after_as_of_records_future_data_violation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VIBE_TRADING_RELIABILITY_MODE", "observe")
    inner = FakeLoader({"AAPL.US": _frame()})
    loader = AuditedDataLoader(
        inner,
        source="yahoo",
        as_of=datetime(2026, 1, 1, tzinfo=timezone.utc),
        available_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        dataset_kind="ohlcv",
    )

    loader.fetch(["AAPL.US"], "2026-01-01", "2026-01-02")

    assert loader.last_audit_report is not None
    assert any(v.code == "PIT_FUTURE_DATA" for v in loader.last_audit_report.pit_violations)


def test_runner_config_collects_audit_refs_for_run_card(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VIBE_TRADING_RELIABILITY_MODE", "observe")
    monkeypatch.setenv("VIBE_TRADING_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    loader = AuditedDataLoader(FakeLoader({"AAPL.US": _frame()}), source="yahoo")
    loader.fetch(["AAPL.US"], "2026-01-01", "2026-01-02")
    config: dict[str, object] = {}

    _attach_loader_audit_to_config(config, loader)

    assert config["_data_audit_ids"] == [loader.last_audit_report.audit_id]
    refs = config["_irr_artifact_refs"]
    assert refs[0]["artifact_type"] == "data_audit"
