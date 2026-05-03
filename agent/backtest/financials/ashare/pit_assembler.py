"""Point-in-time assembler for A-share financial statement fields.

The first version is intentionally narrow and conservative:

* visibility starts on the first trading day strictly after ``ann_date``
* revisions with different ``ann_date`` values are kept as separate events
* exact announcement-cycle duplicates are canonicalized before projection
"""

from __future__ import annotations

from typing import Any, Mapping

import pandas as pd

from backtest.financials.contracts import (
    FinancialDataMap,
    FinancialQueryPlan,
    FinancialTableMap,
    ReportTypePriorities,
)


_DEFAULT_REPORT_TYPE_PRIORITY = {
    "1": 120,
    "2": 110,
    "3": 100,
    "4": 90,
    "5": 80,
    "6": 70,
    "7": 60,
    "8": 50,
    "9": 40,
    "10": 30,
    "11": 20,
    "12": 10,
}


def _to_timestamp_series(series: pd.Series | None) -> pd.Series:
    if series is None:
        return pd.Series(dtype="datetime64[ns]")
    return pd.to_datetime(series, errors="coerce")


def _normalize_priority_key(value: Any) -> str | None:
    if pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


def _normalize_priority_map(report_type_priority: Mapping[Any, int] | None) -> dict[str, int]:
    source = report_type_priority or _DEFAULT_REPORT_TYPE_PRIORITY
    normalized: dict[str, int] = {}
    for key, priority in source.items():
        normalized_key = _normalize_priority_key(key)
        if normalized_key is None:
            continue
        normalized[normalized_key] = priority
    return normalized


def _update_flag_priority(series: pd.Series | None) -> pd.Series:
    if series is None:
        return pd.Series(dtype="int64")
    return series.fillna("").astype(str).str.strip().eq("1").astype(int)


def _stable_row_signature(frame: pd.DataFrame) -> pd.Series:
    stable_columns = [column for column in frame.columns if not column.startswith("_")]
    if not stable_columns:
        return pd.Series(0, index=frame.index, dtype="uint64")
    return pd.util.hash_pandas_object(frame[stable_columns], index=False).astype("uint64")


def _validate_financial_table_schema(
    table_name: str,
    table_rows: pd.DataFrame,
    requested_fields: tuple[str, ...],
) -> None:
    columns = set(table_rows.columns)
    missing_key_columns = [column for column in ("ts_code", "end_date") if column not in columns]
    if "ann_date" not in columns and "f_ann_date" not in columns:
        missing_key_columns.append("ann_date|f_ann_date")

    missing_requested_fields = [field_name for field_name in requested_fields if field_name not in columns]
    if not missing_key_columns and not missing_requested_fields:
        return

    details: list[str] = []
    if missing_key_columns:
        details.append(f"missing key columns={missing_key_columns}")
    if missing_requested_fields:
        details.append(f"missing requested fields={missing_requested_fields}")
    raise ValueError(f"financial table '{table_name}' has invalid schema: {'; '.join(details)}")


def canonicalize_financial_rows(
    records: pd.DataFrame,
    *,
    report_type_priority: Mapping[Any, int] | None = None,
) -> pd.DataFrame:
    """Select a single canonical row for each announcement cycle.

    Canonical key:
    ``ts_code + end_date + visibility_ann_date``

    Rows with different ``ann_date`` values are preserved because they model
    different market-visible revisions over time.
    """
    if records is None or records.empty:
        return pd.DataFrame(columns=list(records.columns) if records is not None else None)

    frame = records.copy()
    frame["_ann_date_ts"] = _to_timestamp_series(frame.get("ann_date"))
    frame["_f_ann_date_ts"] = _to_timestamp_series(frame.get("f_ann_date"))
    frame["_end_date_ts"] = _to_timestamp_series(frame.get("end_date"))
    frame["_visibility_ann_date"] = frame["_ann_date_ts"].where(
        frame["_ann_date_ts"].notna(),
        frame["_f_ann_date_ts"],
    )
    frame = frame[frame["_visibility_ann_date"].notna()].copy()
    if frame.empty:
        return frame.drop(columns=[c for c in frame.columns if c.startswith("_")], errors="ignore")

    priority_map = _normalize_priority_map(report_type_priority)
    report_type_series = frame.get("report_type", pd.Series(index=frame.index, dtype=object))
    frame["_report_priority"] = report_type_series.map(_normalize_priority_key).map(priority_map).fillna(0)
    frame["_update_flag_priority"] = _update_flag_priority(frame.get("update_flag"))
    frame["_row_signature"] = _stable_row_signature(frame)

    sort_columns = [
        "ts_code",
        "_end_date_ts",
        "_visibility_ann_date",
        "_report_priority",
        "_update_flag_priority",
        "_f_ann_date_ts",
        "_row_signature",
    ]
    frame = frame.sort_values(sort_columns, kind="mergesort")
    deduped = frame.drop_duplicates(
        subset=["ts_code", "_end_date_ts", "_visibility_ann_date"],
        keep="last",
    )
    deduped = deduped.sort_values(
        [
            "ts_code",
            "_visibility_ann_date",
            "_end_date_ts",
            "_report_priority",
            "_update_flag_priority",
            "_row_signature",
        ],
        kind="mergesort",
    )
    return deduped.drop(columns=[c for c in deduped.columns if c.startswith("_")], errors="ignore")


def assemble_pit_frame(
    trade_index: pd.DatetimeIndex,
    records: pd.DataFrame,
    *,
    fields: list[str] | tuple[str, ...],
    report_type_priority: Mapping[Any, int] | None = None,
) -> pd.DataFrame:
    """Project raw financial rows onto a daily trading index.

    For each field, value visibility begins on the first trading day strictly
    after the row's ``ann_date`` (or ``f_ann_date`` fallback).
    """
    normalized_index = pd.DatetimeIndex(pd.to_datetime(trade_index)).sort_values().unique()
    output = pd.DataFrame(index=normalized_index)
    if records is None or records.empty or not fields:
        for field_name in fields:
            output[field_name] = pd.Series(index=normalized_index, dtype=float)
        output.index.name = trade_index.name
        return output

    canonical = canonicalize_financial_rows(records, report_type_priority=report_type_priority)
    canonical["_ann_date_ts"] = _to_timestamp_series(canonical.get("ann_date"))
    canonical["_f_ann_date_ts"] = _to_timestamp_series(canonical.get("f_ann_date"))
    canonical["_visibility_ann_date"] = canonical["_ann_date_ts"].where(
        canonical["_ann_date_ts"].notna(),
        canonical["_f_ann_date_ts"],
    )
    canonical["_effective_pos"] = normalized_index.searchsorted(
        canonical["_visibility_ann_date"],
        side="right",
    )
    canonical = canonical[canonical["_effective_pos"] < len(normalized_index)].copy()

    for field_name in fields:
        field_series = pd.Series(index=normalized_index, dtype=float)
        if field_name not in canonical.columns:
            output[field_name] = field_series
            continue

        field_rows = canonical[canonical[field_name].notna()].copy()
        field_rows = field_rows.sort_values(
            ["_effective_pos", "_visibility_ann_date", "end_date"],
            kind="mergesort",
        )
        starts = field_rows["_effective_pos"].tolist()
        values = field_rows[field_name].tolist()
        for idx, start in enumerate(starts):
            end = starts[idx + 1] if idx + 1 < len(starts) else len(normalized_index)
            field_series.iloc[start:end] = values[idx]
        output[field_name] = field_series

    output.index.name = trade_index.name
    return output


def enrich_data_map_with_financials(
    data_map: FinancialDataMap,
    raw_tables: FinancialTableMap,
    query_plan: FinancialQueryPlan,
    *,
    report_type_priorities: ReportTypePriorities | None = None,
) -> dict[str, pd.DataFrame]:
    """Attach PIT financial columns to each symbol's price DataFrame."""
    report_type_priorities = report_type_priorities or {}
    enriched: dict[str, pd.DataFrame] = {}

    for code, frame in data_map.items():
        enriched_frame = frame.copy()
        for table_name, requested_fields in query_plan.requested_fields.items():
            table_rows = raw_tables.get(table_name)
            if table_rows is None or table_rows.empty:
                continue
            _validate_financial_table_schema(table_name, table_rows, requested_fields)
            code_rows = table_rows[table_rows["ts_code"] == code].copy()
            if code_rows.empty:
                continue
            pit = assemble_pit_frame(
                enriched_frame.index,
                code_rows,
                fields=list(requested_fields),
                report_type_priority=report_type_priorities.get(table_name),
            )
            for field_name in requested_fields:
                enriched_frame[field_name] = pit[field_name].reindex(enriched_frame.index)
        enriched[code] = enriched_frame

    return enriched