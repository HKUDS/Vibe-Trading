"""Provider-neutral CSV/Parquet validation and transactional import."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from src.tw_quant.data.schemas import DatasetSchema, schema_for, table_columns
from src.tw_quant.db.connection import connect_database
from src.tw_quant.db.migrations import migrate
from src.tw_quant.market.symbols import SymbolParseError, parse_symbol


_TIMESTAMP_COLUMNS = {
    "listed_at", "delisted_at", "effective_at", "available_at", "ingested_at",
    "announced_at",
}
_DATE_COLUMNS = {"trade_date", "revenue_month"}
_NUMERIC_COLUMNS = {
    "open", "high", "low", "close", "volume", "turnover", "trades",
    "reference_price", "price_limit_up", "price_limit_down", "adjustment_factor",
    "revenue", "revenue_yoy", "revenue_mom",
}
_BOOLEAN_COLUMNS = {"is_suspended", "is_disposition", "is_full_delivery"}
_FILLABLE_COLUMNS = {"source", "source_dataset", "revision_id", "ingested_at"}


@dataclass(frozen=True)
class ValidationReport:
    dataset: str
    rows: int
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset": self.dataset,
            "rows": self.rows,
            "ok": self.ok,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class ImportResult:
    report: ValidationReport
    mode: str
    inserted_rows: int = 0

    def to_dict(self) -> dict[str, Any]:
        payload = self.report.to_dict()
        payload.update({"mode": self.mode, "inserted_rows": self.inserted_rows})
        return payload


def _sql_literal(path: Path) -> str:
    return "'" + str(path).replace("'", "''") + "'"


def read_input(path: str | Path) -> pd.DataFrame:
    """Read CSV or Parquet without heuristic column mapping."""
    input_path = Path(path).expanduser().resolve(strict=True)
    suffix = input_path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(input_path)
    if suffix in {".parquet", ".pq"}:
        import duckdb

        conn = duckdb.connect(database=":memory:")
        try:
            return conn.execute(f"SELECT * FROM read_parquet({_sql_literal(input_path)})").df()
        finally:
            conn.close()
    raise ValueError(f"unsupported import file type: {input_path.suffix!r}; use CSV or Parquet")


def _nonempty(value: Any) -> bool:
    return value is not None and str(value).strip() != "" and not pd.isna(value)


def _canonical_timestamp(value: Any, column: str) -> pd.Timestamp | None:
    if value is None or (isinstance(value, float) and math.isnan(value)) or pd.isna(value):
        return None
    parsed = pd.to_datetime(value, errors="coerce", utc=True)
    if pd.isna(parsed):
        raise ValueError(f"invalid timestamp in {column}: {value!r}")
    return pd.Timestamp(parsed)


def _canonical_date(value: Any, column: str) -> date:
    parsed = _canonical_timestamp(value, column)
    if parsed is None:
        raise ValueError(f"missing date in {column}")
    return parsed.date()


def _canonical_bool(value: Any, column: str) -> bool:
    if isinstance(value, bool):
        return value
    if value is None or pd.isna(value):
        raise ValueError(f"missing boolean in {column}")
    if isinstance(value, (int, float)) and value in {0, 1}:
        return bool(value)
    normalized = str(value).strip().lower()
    if normalized in {"true", "1"}:
        return True
    if normalized in {"false", "0"}:
        return False
    raise ValueError(f"invalid boolean in {column}: {value!r}")


def _canonical_json(value: Any) -> str | None:
    if value is None or (isinstance(value, float) and math.isnan(value)) or pd.isna(value):
        return None
    if isinstance(value, str):
        parsed = json.loads(value)
    else:
        parsed = value
    return json.dumps(parsed, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _normal_for_hash(value: Any) -> Any:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    if isinstance(value, pd.Timestamp):
        value = value.tz_convert("UTC") if value.tzinfo is not None else value.tz_localize("UTC")
        return value.isoformat()
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        return format(value, ".15g")
    return str(value)


def stable_row_hash(row: dict[str, Any]) -> str:
    """Hash canonical row content, excluding operational hash/time fields."""
    payload = {
        key: _normal_for_hash(value)
        for key, value in row.items()
        if key not in {"row_hash", "ingested_at"}
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _prepare_frame(
    frame: pd.DataFrame,
    schema: DatasetSchema,
    *,
    source: str,
    source_dataset: str,
    revision_id: str | None,
    ingested_at: str | None,
) -> tuple[pd.DataFrame | None, ValidationReport]:
    errors: list[str] = []
    if not isinstance(frame, pd.DataFrame):
        return None, ValidationReport(schema.name, 0, ("input is not a DataFrame",))

    columns = {str(column).strip() for column in frame.columns}
    frame = frame.rename(columns={column: str(column).strip() for column in frame.columns})
    missing = set(schema.required_columns) - columns
    missing -= _FILLABLE_COLUMNS
    unknown = columns - set(schema.columns)
    if missing:
        errors.append(f"missing required columns: {sorted(missing)}")
    if unknown:
        errors.append(f"unknown columns are not accepted: {sorted(unknown)}")
    if errors:
        return None, ValidationReport(schema.name, len(frame), tuple(errors))

    df = frame.copy()
    if "source" not in df:
        df["source"] = source
    if "source_dataset" not in df:
        df["source_dataset"] = source_dataset
    if "revision_id" not in df:
        if not revision_id:
            digest = hashlib.sha256(repr(sorted(df.columns)).encode("utf-8")).hexdigest()[:12]
            revision_id = f"import-{digest}"
        df["revision_id"] = revision_id
    if "ingested_at" in schema.columns and "ingested_at" not in df:
        df["ingested_at"] = ingested_at or datetime.now(timezone.utc).isoformat()

    for column in ("source", "source_dataset", "revision_id"):
        if column in df and not all(_nonempty(value) for value in df[column]):
            errors.append(f"{column} must not be empty")

    canonical_symbols: list[str] = []
    for value in df["symbol"]:
        try:
            canonical_symbols.append(parse_symbol(str(value)).canonical)
        except SymbolParseError as exc:
            errors.append(str(exc))
            canonical_symbols.append(str(value).strip().upper())
    df["symbol"] = canonical_symbols

    if schema.name == "security_master":
        for index, row in df.iterrows():
            try:
                parsed = parse_symbol(row["symbol"])
                if str(row["local_code"]).strip() != parsed.local_code:
                    errors.append(f"row {index}: local_code does not match symbol")
                if str(row["market"]).strip().upper() != parsed.market:
                    errors.append(f"row {index}: market does not match symbol")
            except SymbolParseError:
                pass

    for column in _TIMESTAMP_COLUMNS & set(df.columns):
        values: list[pd.Timestamp | None] = []
        for value in df[column]:
            try:
                values.append(_canonical_timestamp(value, column))
            except ValueError as exc:
                errors.append(str(exc))
                values.append(None)
        df[column] = values
        if column == "available_at" and any(value is None for value in values):
            errors.append("available_at must not be empty")

    for column in _DATE_COLUMNS & set(df.columns):
        values: list[date] = []
        for value in df[column]:
            try:
                values.append(_canonical_date(value, column))
            except ValueError as exc:
                errors.append(str(exc))
                values.append(date(1970, 1, 1))
        df[column] = values

    for column in _NUMERIC_COLUMNS & set(df.columns):
        converted = pd.to_numeric(df[column], errors="coerce")
        if converted.isna().any() or not converted.map(math.isfinite).all():
            errors.append(f"{column} contains missing or non-finite values")
        df[column] = converted.astype("float64")

    for column in _BOOLEAN_COLUMNS & set(df.columns):
        values: list[bool] = []
        for value in df[column]:
            try:
                values.append(_canonical_bool(value, column))
            except ValueError as exc:
                errors.append(str(exc))
                values.append(False)
        df[column] = values

    if "quality_flags" in df:
        values: list[str | None] = []
        for value in df["quality_flags"]:
            try:
                values.append(_canonical_json(value))
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                errors.append(f"quality_flags is not valid JSON: {exc}")
                values.append(None)
        df["quality_flags"] = values
    else:
        df["quality_flags"] = None

    if schema.name == "daily_price":
        invalid_ohlc = (
            (df["open"] <= 0) | (df["high"] <= 0) | (df["low"] <= 0) | (df["close"] <= 0)
            | (df["high"] < df[["open", "close", "high"]].max(axis=1))
            | (df["low"] > df[["open", "close", "low"]].min(axis=1))
            | (df["high"] < df["low"])
        )
        if invalid_ohlc.any():
            errors.append(f"{int(invalid_ohlc.sum())} daily_price row(s) violate OHLC invariants")
        for column in ("volume", "turnover", "trades"):
            if (df[column] < 0).any():
                errors.append(f"{column} must not be negative")
        if (df["adjustment_factor"] <= 0).any():
            errors.append("adjustment_factor must be positive")
    if schema.name == "monthly_revenue" and (df["revenue"] < 0).any():
        errors.append("revenue must not be negative")

    if df.duplicated(list(schema.business_key), keep=False).any():
        errors.append(f"duplicate business key/revision in {schema.name}")

    df["row_hash"] = [stable_row_hash(row.to_dict()) for _, row in df.iterrows()]
    df = df.reindex(columns=table_columns(schema.name))
    return df, ValidationReport(schema.name, len(df), tuple(dict.fromkeys(errors)))


def validate_dataset(
    frame: pd.DataFrame,
    dataset: str,
    *,
    source: str,
    source_dataset: str,
    revision_id: str | None = None,
    ingested_at: str | None = None,
) -> tuple[pd.DataFrame | None, ValidationReport]:
    """Validate and canonicalize a provider-neutral dataset."""
    schema = schema_for(dataset)
    return _prepare_frame(
        frame,
        schema,
        source=source,
        source_dataset=source_dataset,
        revision_id=revision_id,
        ingested_at=ingested_at,
    )


def import_dataset(
    input_path: str | Path,
    dataset: str,
    *,
    source: str,
    source_dataset: str,
    schema_version: int = 1,
    mode: str = "validate_only",
    db_path: str | Path | None = None,
    revision_id: str | None = None,
    ingested_at: str | None = None,
) -> ImportResult:
    """Validate or transactionally append one complete input batch."""
    if schema_version != 1:
        raise ValueError(f"unsupported Taiwan schema_version: {schema_version}")
    if mode not in {"validate_only", "append"}:
        raise ValueError("mode must be validate_only or append")
    frame = read_input(input_path)
    canonical, report = validate_dataset(
        frame,
        dataset,
        source=source,
        source_dataset=source_dataset,
        revision_id=revision_id,
        ingested_at=ingested_at,
    )
    if not report.ok or mode == "validate_only":
        return ImportResult(report=report, mode=mode, inserted_rows=0)
    if db_path is None:
        raise ValueError("db_path is required for append mode")

    migrate(db_path)
    conn = connect_database(db_path)
    try:
        conn.execute("BEGIN TRANSACTION")
        view_name = "tw_quant_import_batch"
        conn.register(view_name, canonical)
        columns = ", ".join(table_columns(dataset))
        conn.execute(f"INSERT INTO {dataset} ({columns}) SELECT {columns} FROM {view_name}")
        conn.unregister(view_name)
        conn.execute("COMMIT")
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        conn.close()
    return ImportResult(report=report, mode=mode, inserted_rows=len(canonical))
