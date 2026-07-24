"""Canonical Phase 01 table schemas and DuckDB definitions."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DatasetSchema:
    name: str
    required_columns: tuple[str, ...]
    optional_columns: tuple[str, ...] = ()
    business_key: tuple[str, ...] = ()
    event_column: str | None = None

    @property
    def columns(self) -> tuple[str, ...]:
        return self.required_columns + self.optional_columns


DATASET_SCHEMAS: dict[str, DatasetSchema] = {
    "security_master": DatasetSchema(
        name="security_master",
        required_columns=(
            "symbol", "local_code", "market", "security_type", "name",
            "listed_at", "delisted_at", "industry_code", "effective_at",
            "available_at", "source", "source_dataset", "revision_id",
        ),
        optional_columns=("quality_flags", "row_hash"),
        business_key=("symbol", "effective_at", "revision_id"),
        event_column="effective_at",
    ),
    "daily_price": DatasetSchema(
        name="daily_price",
        required_columns=(
            "symbol", "trade_date", "open", "high", "low", "close",
            "volume", "turnover", "trades", "reference_price",
            "price_limit_up", "price_limit_down", "is_suspended",
            "is_disposition", "is_full_delivery", "adjustment_factor",
            "effective_at", "available_at", "ingested_at", "source",
            "source_dataset", "revision_id",
        ),
        optional_columns=("quality_flags", "row_hash"),
        business_key=("symbol", "trade_date", "revision_id"),
        event_column="trade_date",
    ),
    "monthly_revenue": DatasetSchema(
        name="monthly_revenue",
        required_columns=(
            "symbol", "revenue_month", "revenue", "revenue_yoy", "revenue_mom",
            "announced_at", "effective_at", "available_at", "ingested_at",
            "source", "source_dataset", "revision_id",
        ),
        optional_columns=("quality_flags", "row_hash"),
        business_key=("symbol", "revenue_month", "revision_id"),
        event_column="revenue_month",
    ),
}


TABLE_DDL: dict[str, str] = {
    "security_master": """
        CREATE TABLE IF NOT EXISTS security_master (
            symbol VARCHAR NOT NULL,
            local_code VARCHAR NOT NULL,
            market VARCHAR NOT NULL,
            security_type VARCHAR NOT NULL,
            name VARCHAR NOT NULL,
            listed_at TIMESTAMPTZ,
            delisted_at TIMESTAMPTZ,
            industry_code VARCHAR NOT NULL,
            effective_at TIMESTAMPTZ NOT NULL,
            available_at TIMESTAMPTZ NOT NULL,
            source VARCHAR NOT NULL,
            source_dataset VARCHAR NOT NULL,
            revision_id VARCHAR NOT NULL,
            quality_flags VARCHAR,
            row_hash VARCHAR NOT NULL,
            UNIQUE(symbol, effective_at, revision_id)
        )
    """,
    "daily_price": """
        CREATE TABLE IF NOT EXISTS daily_price (
            symbol VARCHAR NOT NULL,
            trade_date DATE NOT NULL,
            open DOUBLE NOT NULL,
            high DOUBLE NOT NULL,
            low DOUBLE NOT NULL,
            close DOUBLE NOT NULL,
            volume DOUBLE NOT NULL,
            turnover DOUBLE NOT NULL,
            trades DOUBLE NOT NULL,
            reference_price DOUBLE NOT NULL,
            price_limit_up DOUBLE NOT NULL,
            price_limit_down DOUBLE NOT NULL,
            is_suspended BOOLEAN NOT NULL,
            is_disposition BOOLEAN NOT NULL,
            is_full_delivery BOOLEAN NOT NULL,
            adjustment_factor DOUBLE NOT NULL,
            effective_at TIMESTAMPTZ NOT NULL,
            available_at TIMESTAMPTZ NOT NULL,
            ingested_at TIMESTAMPTZ NOT NULL,
            source VARCHAR NOT NULL,
            source_dataset VARCHAR NOT NULL,
            revision_id VARCHAR NOT NULL,
            quality_flags VARCHAR,
            row_hash VARCHAR NOT NULL,
            UNIQUE(symbol, trade_date, revision_id)
        )
    """,
    "monthly_revenue": """
        CREATE TABLE IF NOT EXISTS monthly_revenue (
            symbol VARCHAR NOT NULL,
            revenue_month DATE NOT NULL,
            revenue DOUBLE NOT NULL,
            revenue_yoy DOUBLE NOT NULL,
            revenue_mom DOUBLE NOT NULL,
            announced_at TIMESTAMPTZ,
            effective_at TIMESTAMPTZ NOT NULL,
            available_at TIMESTAMPTZ NOT NULL,
            ingested_at TIMESTAMPTZ NOT NULL,
            source VARCHAR NOT NULL,
            source_dataset VARCHAR NOT NULL,
            revision_id VARCHAR NOT NULL,
            quality_flags VARCHAR,
            row_hash VARCHAR NOT NULL,
            UNIQUE(symbol, revenue_month, revision_id)
        )
    """,
}


def schema_for(dataset: str) -> DatasetSchema:
    try:
        return DATASET_SCHEMAS[dataset]
    except KeyError as exc:
        raise ValueError(f"unsupported Taiwan dataset: {dataset!r}") from exc


def table_columns(dataset: str) -> tuple[str, ...]:
    """Return the physical column order used by DuckDB and Parquet."""
    return schema_for(dataset).columns

