"""Tushare fundamental data provider with point-in-time safeguards."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

import pandas as pd

TUSHARE_TOKEN_PLACEHOLDERS = {"", "your-tushare-token"}


class DataProviderError(Exception):
    """Base error for fundamental provider failures."""


class UnknownTableError(DataProviderError):
    """Raised when a requested fundamental table is not supported."""


class SchemaValidationError(DataProviderError):
    """Raised when provider output is missing required columns."""


class SubdailyPitError(ValueError):
    """Raised when fundamentals are requested for an intraday price frame.

    A caller-fixable contract error, not a provider failure — engines let it
    through verbatim instead of rewording it as an enrichment failure.
    """


@dataclass(frozen=True)
class ColumnSchema:
    """Machine-readable column metadata for a provider table."""

    name: str
    dtype: str
    required: bool = False


@dataclass(frozen=True)
class TableSchema:
    """Machine-readable metadata for a Tushare fundamental table."""

    name: str
    api_name: str
    point_in_time_column: str
    columns: tuple[ColumnSchema, ...]

    @property
    def required_columns(self) -> tuple[str, ...]:
        return tuple(column.name for column in self.columns if column.required)


_SCHEMAS: dict[str, TableSchema] = {
    "balancesheet": TableSchema(
        name="balancesheet",
        api_name="balancesheet",
        point_in_time_column="f_ann_date",
        columns=(
            ColumnSchema("ts_code", "str", required=True),
            ColumnSchema("ann_date", "date", required=True),
            ColumnSchema("f_ann_date", "date", required=False),
            ColumnSchema("end_date", "date", required=True),
            ColumnSchema("total_assets", "float"),
            ColumnSchema("total_liab", "float"),
            ColumnSchema("total_hldr_eqy_exc_min_int", "float"),
        ),
    ),
    "cashflow": TableSchema(
        name="cashflow",
        api_name="cashflow",
        point_in_time_column="f_ann_date",
        columns=(
            ColumnSchema("ts_code", "str", required=True),
            ColumnSchema("ann_date", "date", required=True),
            ColumnSchema("f_ann_date", "date", required=False),
            ColumnSchema("end_date", "date", required=True),
            ColumnSchema("net_profit", "float"),
            ColumnSchema("n_cashflow_act", "float"),
            ColumnSchema("c_cash_equ_end_period", "float"),
        ),
    ),
    "fina_indicator": TableSchema(
        name="fina_indicator",
        api_name="fina_indicator",
        point_in_time_column="ann_date",
        columns=(
            ColumnSchema("ts_code", "str", required=True),
            ColumnSchema("ann_date", "date", required=True),
            ColumnSchema("end_date", "date", required=True),
            ColumnSchema("eps", "float"),
            ColumnSchema("grossprofit_margin", "float"),
            ColumnSchema("netprofit_margin", "float"),
            ColumnSchema("roe", "float"),
            ColumnSchema("debt_to_assets", "float"),
        ),
    ),
    "income": TableSchema(
        name="income",
        api_name="income",
        point_in_time_column="f_ann_date",
        columns=(
            ColumnSchema("ts_code", "str", required=True),
            ColumnSchema("ann_date", "date", required=True),
            ColumnSchema("f_ann_date", "date", required=False),
            ColumnSchema("end_date", "date", required=True),
            ColumnSchema("total_revenue", "float"),
            ColumnSchema("revenue", "float"),
            ColumnSchema("operate_profit", "float"),
            ColumnSchema("n_income", "float"),
        ),
    ),
}


class TushareFundamentalProvider:
    """Small DataProvider contract for Tushare financial statement tables."""

    def __init__(self, api: Any | None = None) -> None:
        if api is None:
            import tushare as ts

            from src.config.accessor import get_env_config

            token = get_env_config().data.tushare_token.strip()
            if token in TUSHARE_TOKEN_PLACEHOLDERS:
                token = ""
            api = ts.pro_api(token)
        self.api = api

    def list_tables(self) -> list[str]:
        """Return supported fundamental tables in stable order."""
        return sorted(_SCHEMAS)

    def describe_table(self, table: str) -> TableSchema:
        """Return schema metadata for a supported table."""
        try:
            return _SCHEMAS[table]
        except KeyError as exc:
            raise UnknownTableError(f"Unsupported Tushare fundamental table: {table}") from exc

    def query_fundamentals(
        self,
        table: str,
        codes: Iterable[str],
        *,
        as_of: str | pd.Timestamp,
        periods: Iterable[str] | None = None,
        fields: Iterable[str] | None = None,
    ) -> pd.DataFrame:
        """Query a fundamental table and filter out rows unpublished by ``as_of``.

        After the PIT cut, rows are deduplicated so that each ``(ts_code,
        end_date)`` pair keeps only the entry with the latest effective pit
        date (``f_ann_date`` when present and non-null, falling back to
        ``ann_date``).  Ties on the same pit date preserve the last row in
        input order, which matches the natural Tushare ordering where
        restatements appear after originals.
        """
        result = self._query_pit_cut(table, codes, as_of=as_of, periods=periods, fields=fields)
        if result.empty:
            return result

        schema = self.describe_table(table)
        pit_column = schema.point_in_time_column
        if pit_column not in result.columns or result[pit_column].isna().all():
            pit_column = "ann_date"

        pit_values = result[pit_column]
        if pit_column != "ann_date" and "ann_date" in result.columns:
            pit_values = pit_values.where(pit_values.notna(), result["ann_date"])
        result = result.copy()
        result["_eff_pit_date"] = pit_values.map(_parse_tushare_date)

        # Keep the row with the latest effective pit date per (ts_code, end_date).
        # stable sort + keep='last' means that within ties the last row in
        # input order wins, which is what we want for restatements appended
        # after the original.
        result = result.sort_values("_eff_pit_date", kind="stable")
        result = result.drop_duplicates(subset=["ts_code", "end_date"], keep="last")
        result = result.drop(columns=["_eff_pit_date"])

        output_columns = self._output_columns(schema, result, fields)
        result = result.loc[:, output_columns].sort_values(["ts_code", "end_date"]).reset_index(drop=True)
        return result

    def _query_pit_cut(
        self,
        table: str,
        codes: Iterable[str],
        *,
        as_of: str | pd.Timestamp,
        periods: Iterable[str] | None = None,
        fields: Iterable[str] | None = None,
    ) -> pd.DataFrame:
        """Return all rows visible by ``as_of`` without deduplication.

        This is the raw PIT cut used internally by
        :func:`enrich_price_frames_with_fundamentals` so that per-trading-day
        visibility can be evaluated before deduplication is applied.
        """
        schema = self.describe_table(table)
        requested_periods = set(periods or [])
        frames: list[pd.DataFrame] = []

        api_method = getattr(self.api, schema.api_name, None)
        if api_method is None:
            raise DataProviderError(f"Tushare API object has no method: {schema.api_name}")

        for code in codes:
            from src.data_gateway.reads import managed_reader

            frame = managed_reader(api_method)(ts_code=code, period=None)
            if frame is not None and not frame.empty:
                frames.append(frame.copy())

        if not frames:
            return self._empty_frame(schema, fields)

        result = pd.concat(frames, ignore_index=True)
        self._validate_schema(schema, result)

        if requested_periods:
            result = result[result["end_date"].astype(str).isin(requested_periods)]

        pit_column = schema.point_in_time_column
        if pit_column not in result.columns or result[pit_column].isna().all():
            pit_column = "ann_date"
        as_of_date = _parse_tushare_date(as_of)
        pit_values = result[pit_column]
        if pit_column != "ann_date" and "ann_date" in result.columns:
            pit_values = pit_values.where(pit_values.notna(), result["ann_date"])
        pit_dates = pit_values.map(_parse_tushare_date)
        result = result[pit_dates <= as_of_date]

        output_columns = self._output_columns(schema, result, fields)
        result = result.loc[:, output_columns].reset_index(drop=True)
        return result

    def _validate_schema(self, schema: TableSchema, frame: pd.DataFrame) -> None:
        missing = [column for column in schema.required_columns if column not in frame.columns]
        if missing:
            raise SchemaValidationError(f"{schema.name} missing required columns: {', '.join(missing)}")

    def _output_columns(
        self,
        schema: TableSchema,
        frame: pd.DataFrame,
        fields: Iterable[str] | None,
    ) -> list[str]:
        identity = ["ts_code", "end_date", "ann_date"]
        if schema.point_in_time_column in frame.columns and schema.point_in_time_column not in identity:
            identity.append(schema.point_in_time_column)
        wanted = identity + list(fields or [])
        return [column for column in dict.fromkeys(wanted) if column in frame.columns]

    def _empty_frame(self, schema: TableSchema, fields: Iterable[str] | None) -> pd.DataFrame:
        columns = self._output_columns(schema, pd.DataFrame(columns=[c.name for c in schema.columns]), fields)
        return pd.DataFrame(columns=columns)


def _parse_tushare_date(value: str | pd.Timestamp) -> pd.Timestamp:
    """Parse Tushare YYYYMMDD strings and common timestamp/date strings."""
    if isinstance(value, pd.Timestamp):
        return value.normalize()
    text = str(value)
    if len(text) == 8 and text.isdigit():
        return pd.to_datetime(text, format="%Y%m%d")
    return pd.to_datetime(text).normalize()


SUBDAILY_POLICIES = ("reject", "next_day")


def _is_subdaily_index(index: pd.Index) -> bool:
    """Report whether a price frame's index carries intraday bars.

    A frame is sub-daily when any timestamp has a time-of-day component, or
    when one calendar day holds more than one bar. Either alone is enough:
    a 1h frame that happens to start at midnight still repeats the day.

    Args:
        index: A price frame's index.

    Returns:
        ``True`` when the frame is finer than one bar per day.
    """
    if isinstance(index, pd.DatetimeIndex):
        stamps = index
    elif pd.api.types.is_object_dtype(index) or pd.api.types.is_string_dtype(index):
        try:
            stamps = pd.DatetimeIndex(pd.to_datetime(index))
        except (TypeError, ValueError):
            # Not a clock at all. The merge below already fails on such an
            # index exactly as it did before this guard existed; do not
            # convert that into a sub-daily rejection with a date-parse
            # message pinned to it.
            return False
    else:
        # A numeric index is not a clock either: ``pd.to_datetime`` reads it
        # as nanoseconds since the epoch, which puts every row at a distinct
        # sub-second time and reports every frame as sub-daily.
        return False
    if len(stamps) == 0:
        return False
    if (stamps != stamps.normalize()).any():
        return True
    return bool(stamps.normalize().duplicated().any())


def enrich_price_frames_with_fundamentals(
    data_map: dict[str, pd.DataFrame],
    provider: TushareFundamentalProvider,
    fields_by_table: dict[str, Iterable[str]],
    *,
    as_of: str | pd.Timestamp,
    periods: Iterable[str] | None = None,
    subdaily: str = "reject",
) -> dict[str, pd.DataFrame]:
    """Attach PIT-safe fundamental snapshots to daily price frames.

    Sub-daily frames (``subdaily``): Tushare's ``ann_date`` / ``f_ann_date``
    is a date with no time of day, and CN filings typically land after the
    close, so a day-granular visibility rule applied to intraday bars makes
    a filing visible from the first bar of its own announcement day — a real
    lookahead below 1D. Daily runs are unaffected because a signal on day D
    fills at D+1's open at the earliest. ``"reject"`` (the default) raises
    rather than enriching an intraday frame; ``"next_day"`` opts in to
    intraday enrichment with the conservative convention that a filing
    announced on D is visible from the first bar of D+1.

    Fundamental columns are prefixed with their table name, for example
    ``income_total_revenue`` and ``fina_indicator_roe``. Each row becomes
    visible only on or after its announcement/disclosure date.

    Restatement handling: when a later disclosure covers an *older* reporting
    period than the most-recently-seen period, the snapshot does **not**
    regress to that older period.  Specifically, the effective announcement
    timeline is built by scanning rows in ascending pit-date order and only
    accepting a row when its ``end_date`` is >= the ``end_date`` that is
    currently visible.  Same-period restatements (same ``end_date``, later
    pit date) do update the visible values.
    """
    if subdaily not in SUBDAILY_POLICIES:
        raise ValueError(
            f"subdaily must be one of {SUBDAILY_POLICIES}, got {subdaily!r}"
        )
    if not data_map or not fields_by_table:
        return data_map

    subdaily_codes = [
        code
        for code, frame in data_map.items()
        if not frame.empty and _is_subdaily_index(frame.index)
    ]
    if subdaily_codes and subdaily == "reject":
        raise SubdailyPitError(
            "fundamental_fields is PIT-safe for daily frames only; "
            f"{', '.join(sorted(subdaily_codes)[:5])} carry intraday bars, where an "
            "ann_date with no time of day would be visible from the first bar of "
            "its own announcement day. Run the backtest daily, or set "
            "fundamental_subdaily='next_day' to accept the conservative "
            "first-bar-of-the-next-day convention."
        )

    enriched = {code: frame.copy() for code, frame in data_map.items()}
    codes = list(enriched)

    for table, fields in fields_by_table.items():
        field_list = list(fields or [])
        # Use the raw PIT cut (no dedup) so that per-day visibility can be
        # evaluated correctly before same-period deduplication is applied.
        fundamentals = provider._query_pit_cut(
            table,
            codes,
            as_of=as_of,
            periods=periods,
            fields=field_list,
        )
        if fundamentals.empty:
            continue

        schema = provider.describe_table(table)
        pit_column = schema.point_in_time_column
        if pit_column not in fundamentals.columns or fundamentals[pit_column].isna().all():
            pit_column = "ann_date"

        for code, frame in enriched.items():
            rows = fundamentals[fundamentals["ts_code"] == code].copy()
            if rows.empty or frame.empty:
                continue

            pit_values = rows[pit_column]
            if pit_column != "ann_date" and "ann_date" in rows.columns:
                pit_values = pit_values.where(pit_values.notna(), rows["ann_date"])
            rows["_pit_date"] = pit_values.map(_parse_tushare_date)
            rows["_end_date_parsed"] = rows["end_date"].map(_parse_tushare_date)
            rows = rows.dropna(subset=["_pit_date", "_end_date_parsed"]).sort_values(
                ["_pit_date", "_end_date_parsed"], kind="stable"
            )
            if rows.empty:
                continue

            # Build effective timeline: scan in ascending pit-date order and
            # only include a row when its end_date >= the currently-visible
            # end_date.  This prevents an old-period restatement (announced
            # later) from regressing the snapshot to an earlier period.
            # Same-period restatements (same end_date, later pit_date) pass
            # the check and are appended as additional timeline entries;
            # merge_asof will then naturally surface the later restatement for
            # trade dates on or after its pit_date while keeping the original
            # visible for earlier dates.
            timeline_rows: list[pd.Series] = []
            current_end_date: pd.Timestamp | None = None
            for _, row in rows.iterrows():
                row_end_date: pd.Timestamp = row["_end_date_parsed"]
                if current_end_date is None or row_end_date >= current_end_date:
                    timeline_rows.append(row)
                    current_end_date = row_end_date
                # Rows where row_end_date < current_end_date are silently
                # dropped — they represent old-period restatements that must
                # not regress the visible snapshot.

            if not timeline_rows:
                continue

            timeline = pd.DataFrame(timeline_rows).drop(columns=["_end_date_parsed"])

            value_columns = [
                column
                for column in timeline.columns
                if column not in {"ts_code", "_pit_date"}
            ]
            right = timeline[["_pit_date", *value_columns]].rename(
                columns={column: f"{table}_{column}" for column in value_columns}
            )

            if code in subdaily_codes:
                # ``next_day``: an announcement dated D becomes visible one
                # calendar day later, i.e. from the first bar of D+1. The bar
                # index is normalized to midnight below, so shifting the pit
                # date by one day is exactly that boundary.
                right = right.copy()
                right["_pit_date"] = right["_pit_date"] + pd.Timedelta(days=1)

            left = frame.copy()
            original_index = left.index
            left["_trade_date"] = pd.to_datetime(left.index).normalize()
            left["_original_order"] = range(len(left))

            merged = pd.merge_asof(
                left.sort_values("_trade_date"),
                right.sort_values("_pit_date"),
                left_on="_trade_date",
                right_on="_pit_date",
                direction="backward",
            )
            merged = merged.sort_values("_original_order").drop(
                columns=["_trade_date", "_original_order", "_pit_date"]
            )
            merged.index = original_index
            enriched[code] = merged

    return enriched
