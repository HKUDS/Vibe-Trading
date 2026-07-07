"""Tests for Phase 2 data audit schemas and validators."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from src.reliability.data.contracts import (
    DataAccessContract,
    DataAuditReport,
    DataSetContract,
    StructuredWarning,
)
from src.reliability.data.validators import validate_data_map


def test_data_audit_report_has_stable_warning_error_codes() -> None:
    report = DataAuditReport(
        audit_id="audit_test",
        schema_version="1.0.0",
        dataset_contract=DataSetContract(
            dataset_id="prices",
            asset_class="us_equity",
            frequency="1D",
            calendar="XNYS",
            fields=["open", "close"],
            timezone="UTC",
        ),
        access_contract=DataAccessContract(
            source="auto",
            selected_source="yahoo",
            request_params_hash="a" * 64,
            fallback_chain=["yahoo", "stooq"],
            fetched_at=datetime.now(timezone.utc),
            explicit_local=False,
        ),
        row_count=10,
        symbol_count=1,
        field_coverage={"close": 1.0},
        quality_warnings=[
            StructuredWarning(
                code="DATA_FIELD_COVERAGE_LOW",
                severity="warning",
                message="close coverage below threshold",
            )
        ],
        all_sources_open=False,
    )

    dumped = report.model_dump(mode="json")

    assert dumped["quality_warnings"][0]["code"] == "DATA_FIELD_COVERAGE_LOW"
    assert dumped["all_sources_open"] is False
    assert dumped["schema_version"] == "1.0.0"


def test_validator_samples_large_dataframe() -> None:
    rows = 50_000
    frame = pd.DataFrame(
        {
            "open": range(rows),
            "high": range(rows),
            "low": range(rows),
            "close": range(rows),
            "volume": range(rows),
        },
        index=pd.date_range("2026-01-01", periods=rows, freq="min"),
    )

    result = validate_data_map({"AAPL.US": frame}, max_sample_rows=1000)

    assert result.row_count == rows
    assert result.symbol_count == 1
    assert result.content_sample_hash is not None
    assert result.inspected_rows <= 1000
    assert any(warning.code == "DATA_VALIDATOR_SAMPLED" for warning in result.quality_warnings)


def test_validator_hashes_nan_samples_without_throwing() -> None:
    frame = pd.DataFrame(
        {
            "open": [1.0],
            "high": [float("nan")],
            "low": [0.9],
            "close": [1.1],
            "volume": [100],
        },
        index=pd.date_range("2026-01-01", periods=1, freq="D"),
    )

    result = validate_data_map({"AAPL.US": frame})

    assert result.content_sample_hash is not None
    assert result.per_symbol_hashes["AAPL.US"]
    assert result.field_coverage["high"] == 0.0
