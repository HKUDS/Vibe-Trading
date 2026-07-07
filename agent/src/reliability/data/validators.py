"""Bounded DataFrame validators for data audit reports."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

import pandas as pd
from pydantic import BaseModel, Field

from src.reliability.data.contracts import StructuredWarning


class DataValidationResult(BaseModel):
    """Bounded validation summary for a data map."""

    row_count: int
    symbol_count: int
    field_coverage: dict[str, float]
    content_sample_hash: str | None = None
    per_symbol_hashes: dict[str, str] = Field(default_factory=dict)
    quality_warnings: list[StructuredWarning] = Field(default_factory=list)
    inspected_rows: int = 0


def validate_data_map(
    data_map: dict[str, pd.DataFrame],
    *,
    max_sample_rows: int = 10_000,
    per_symbol_hash_limit: int = 20,
) -> DataValidationResult:
    """Validate a loader return map using bounded sampling."""
    row_count = 0
    sampled_rows = 0
    field_non_null: dict[str, int] = {}
    field_seen_rows: dict[str, int] = {}
    sample_parts: list[dict[str, Any]] = []
    per_symbol_hashes: dict[str, str] = {}
    warnings: list[StructuredWarning] = []

    remaining = max(0, int(max_sample_rows))
    for symbol, frame in data_map.items():
        if not isinstance(frame, pd.DataFrame):
            warnings.append(
                StructuredWarning(
                    code="DATA_NON_DATAFRAME_RESULT",
                    severity="warning",
                    message="loader returned a non-DataFrame value",
                    metadata={"symbol": symbol, "type": type(frame).__name__},
                )
            )
            continue
        row_count += len(frame)
        sample = _sample_frame(frame, remaining)
        remaining = max(0, remaining - len(sample))
        sampled_rows += len(sample)
        if len(frame) > len(sample):
            warnings.append(
                StructuredWarning(
                    code="DATA_VALIDATOR_SAMPLED",
                    severity="info",
                    message="large DataFrame sampled for audit validation",
                    metadata={"symbol": symbol, "rows": len(frame), "sampled_rows": len(sample)},
                )
            )
        for column in frame.columns:
            series = sample[column] if column in sample.columns else pd.Series(dtype="object")
            field_non_null[column] = field_non_null.get(column, 0) + int(series.notna().sum())
            field_seen_rows[column] = field_seen_rows.get(column, 0) + len(sample)
        sample_parts.append(_frame_sample_payload(symbol, sample))
        if len(per_symbol_hashes) < per_symbol_hash_limit:
            per_symbol_hashes[symbol] = _hash_payload(_frame_sample_payload(symbol, sample))

    field_coverage = {
        field: (field_non_null.get(field, 0) / seen if seen else 0.0)
        for field, seen in field_seen_rows.items()
    }
    content_sample_hash = _hash_payload(sample_parts) if sample_parts else None
    return DataValidationResult(
        row_count=row_count,
        symbol_count=len(data_map),
        field_coverage=field_coverage,
        content_sample_hash=content_sample_hash,
        per_symbol_hashes=per_symbol_hashes,
        quality_warnings=warnings,
        inspected_rows=sampled_rows,
    )


def _sample_frame(frame: pd.DataFrame, max_rows: int) -> pd.DataFrame:
    if max_rows <= 0:
        return frame.iloc[0:0]
    if len(frame) <= max_rows:
        return frame
    if max_rows == 1:
        return frame.iloc[[0]]
    step = max(1, len(frame) // max_rows)
    sample = frame.iloc[::step].head(max_rows)
    return sample


def _frame_sample_payload(symbol: str, frame: pd.DataFrame) -> dict[str, Any]:
    reset = frame.reset_index()
    records = reset.head(len(frame)).to_dict(orient="records")
    return {
        "symbol": symbol,
        "columns": [str(column) for column in frame.columns],
        "rows": [_json_safe_record(record) for record in records],
    }


def _json_safe_record(record: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in record.items():
        safe[str(key)] = _json_safe_value(value)
    return safe


def _json_safe_value(value: Any) -> Any:
    if hasattr(value, "item"):
        value = value.item()
    if value is None:
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _hash_payload(payload: Any) -> str:
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False, default=str, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()
