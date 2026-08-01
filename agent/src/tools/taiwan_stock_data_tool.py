"""Read-only Taiwan stock data tool backed by a published SQLite snapshot."""

from __future__ import annotations

import json
import math
import re
import sqlite3
from contextlib import closing
from datetime import date
from itertools import zip_longest
from pathlib import Path
from typing import Any

from src.agent.tools import BaseTool
from src.config.accessor import get_env_config

DEFAULT_DB_PATH = "/data/tw-stock/latest.db"


def _configured_db_path() -> str:
    """Return the configured snapshot path, or the container default.

    Returns:
        ``VIBE_TW_STOCK_DB`` when set, otherwise :data:`DEFAULT_DB_PATH`.
    """
    return get_env_config().data.vibe_tw_stock_db.strip() or DEFAULT_DB_PATH
STOCK_ID_PATTERN = re.compile(r"^\d{4}$")
MAX_QUERY_STOCKS = 50
MAX_RESULT_ROWS = 200

# src/agent/loop.py truncates every tool result at TOOL_RESULT_LIMIT = 10_000
# characters. A blind cut mid-string yields invalid JSON, and because rows are
# ordered oldest first it deletes the newest bars. Stay under that limit with
# headroom for the envelope so the agent always receives parseable JSON.
RESPONSE_CHAR_BUDGET = 9_500

# Tables and columns every query in this module reads. Validated when the
# snapshot is opened so a stale or unrelated SQLite file fails loudly with a
# named cause instead of mid-query.
REQUIRED_SCHEMA: dict[str, tuple[str, ...]] = {
    "stock_master": (
        "stock_id",
        "stock_name",
        "market",
        "industry",
        "enable",
    ),
    "daily_price": (
        "date",
        "stock_id",
        "open",
        "max",
        "min",
        "close",
        "Trading_Volume",
        "Trading_money",
        "Trading_turnover",
        "spread",
    ),
    "stock_feature": (
        "date",
        "stock_id",
        "ma5",
        "ma20",
        "ma60",
        "ema12",
        "ema26",
        "macd",
        "macd_signal",
        "macd_hist",
        "rsi14",
    ),
    "analysis_universe": (
        "stock_id",
        "stock_name",
        "market",
        "industry",
        "active",
        "reason",
        "price_rows",
        "last_price_date",
        "last_feature_date",
        "trading_day_lag",
        "latest_close",
    ),
}

# Per-action name of the column that dates a row, newest-first trimming order.
ROW_DATE_KEYS = ("date", "price_date", "last_price_date")

TRUNCATION_HINT = (
    "Response trimmed to fit the agent tool-result budget; the oldest rows "
    "were dropped. Narrow start_date/end_date, lower limit, or query fewer "
    "stock_ids to receive the full range."
)


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _json_safe(item)
            for key, item in value.items()
        }

    if isinstance(value, list):
        return [_json_safe(item) for item in value]

    if isinstance(value, float) and not math.isfinite(value):
        return None

    return value


def _dump(payload: dict[str, Any]) -> str:
    """Serialize an already JSON-safe response envelope.

    Args:
        payload: Envelope whose values passed through ``_json_safe``.

    Returns:
        Pretty-printed JSON text.
    """
    return json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        allow_nan=False,
    )


def _schema_problems(
    connection: sqlite3.Connection,
) -> list[str]:
    """List the ways a snapshot fails the schema this tool queries.

    Args:
        connection: Open SQLite connection to a candidate snapshot.

    Returns:
        Human-readable problem descriptions, empty when the snapshot matches
        ``REQUIRED_SCHEMA``. Identifiers are compared case-insensitively
        because SQLite resolves column names that way.

    Raises:
        sqlite3.DatabaseError: If the file is not a SQLite database at all.
    """
    present_tables = {
        str(row[0]).lower()
        for row in connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type IN ('table', 'view')
            """
        )
    }

    problems: list[str] = []

    for table, columns in REQUIRED_SCHEMA.items():
        if table.lower() not in present_tables:
            problems.append(f"missing table {table!r}")
            continue

        present_columns = {
            str(row[1]).lower()
            for row in connection.execute(
                f'PRAGMA table_info("{table}")'
            )
        }

        missing = [
            column
            for column in columns
            if column.lower() not in present_columns
        ]

        if missing:
            problems.append(
                f"table {table!r} is missing columns "
                f"{', '.join(repr(column) for column in missing)}"
            )

    return problems


def _row_date(row: dict[str, Any]) -> str:
    """Return the date that positions a row in time.

    Args:
        row: One result record.

    Returns:
        The row's date string, or an empty string when it carries none, which
        sorts it oldest and therefore drops it first.
    """
    for key in ROW_DATE_KEYS:
        value = row.get(key)

        if value:
            return str(value)

    return ""


def _retention_order(
    records: list[dict[str, Any]],
) -> list[int]:
    """Rank record indices newest-first, round-robin across stocks.

    Trimming drops from the tail of this ranking, so every requested stock
    keeps its newest bar before any stock keeps a second one. That guarantees
    the newest date survives and no single stock eats the whole budget.

    Args:
        records: Result rows in display order.

    Returns:
        Record indices ordered by retention priority, highest priority first.
    """
    groups: dict[str, list[int]] = {}

    for index, record in enumerate(records):
        groups.setdefault(
            str(record.get("stock_id", "")),
            [],
        ).append(index)

    for indices in groups.values():
        indices.sort(
            key=lambda index: _row_date(records[index]),
            reverse=True,
        )

    ordered = sorted(groups.items())
    ordered.sort(
        key=lambda item: _row_date(records[item[1][0]]),
        reverse=True,
    )

    return [
        index
        for tier in zip_longest(
            *(indices for _, indices in ordered)
        )
        for index in tier
        if index is not None
    ]


class TaiwanStockDataTool(BaseTool):
    """Query the local published Taiwan stock database."""

    name = "get_taiwan_stock_data"
    description = (
        "Query the local read-only Taiwan stock snapshot for TWSE and TPEx "
        "stocks. Use this before generic internet market-data tools when the "
        "user asks about Taiwan four-digit stock IDs. Supports database status, "
        "stock lookup, latest price and technical indicators, historical bars, "
        "and the active analysis universe. Indicator rows carry their own "
        "feature_date next to price_date, flagged by stale_features when they "
        "disagree. Responses are size-capped: when truncated is true the "
        "oldest rows were dropped, so narrow the date range or stock list. "
        "This tool never places orders."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "status",
                    "lookup",
                    "latest",
                    "history",
                    "universe",
                ],
                "description": (
                    "status: snapshot summary; "
                    "lookup: stock identity and eligibility; "
                    "latest: latest price and indicators; "
                    "history: historical daily bars and indicators; "
                    "universe: list analysis-universe stocks."
                ),
            },
            "stock_ids": {
                "type": "array",
                "items": {
                    "type": "string",
                    "pattern": "^[0-9]{4}$",
                },
                "maxItems": MAX_QUERY_STOCKS,
                "description": (
                    'Taiwan four-digit stock IDs, for example ["2330", "2317"]. '
                    "Required for lookup, latest, and history."
                ),
            },
            "start_date": {
                "type": "string",
                "description": (
                    "Optional history start date in YYYY-MM-DD format."
                ),
            },
            "end_date": {
                "type": "string",
                "description": (
                    "Optional history end date in YYYY-MM-DD format."
                ),
            },
            "market": {
                "type": "string",
                "enum": ["twse", "tpex"],
                "description": (
                    "Optional market filter for universe queries."
                ),
            },
            "industry": {
                "type": "string",
                "description": (
                    "Optional partial industry-name filter for universe queries."
                ),
            },
            "active_only": {
                "type": "boolean",
                "default": True,
                "description": (
                    "For universe queries, return only active analysis stocks."
                ),
            },
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": MAX_RESULT_ROWS,
                "default": 60,
                "description": (
                    "Maximum universe rows, or maximum history rows per stock."
                ),
            },
        },
        "required": ["action"],
    }
    repeatable = True
    is_readonly = True

    def __init__(
        self,
        db_path: str | Path | None = None,
    ) -> None:
        """Bind the tool to a published snapshot file.

        Args:
            db_path: Snapshot path. Defaults to ``VIBE_TW_STOCK_DB``, then to
                ``DEFAULT_DB_PATH``.
        """
        configured = str(db_path) if db_path is not None else _configured_db_path()
        self.db_path = Path(configured).expanduser()

    @classmethod
    def check_available(cls) -> bool:
        """Report whether a usable snapshot is configured.

        Returns:
            True only when the configured path holds a SQLite database that
            carries every table and column this tool queries. Registering on a
            merely-present file would defer the failure to a user query.
        """
        path = Path(_configured_db_path()).expanduser()

        if not path.is_file():
            return False

        try:
            with closing(
                sqlite3.connect(
                    f"file:{path.resolve()}?mode=ro&immutable=1",
                    uri=True,
                )
            ) as connection:
                return not _schema_problems(connection)
        except sqlite3.Error:
            return False

    def _connect(self) -> sqlite3.Connection:
        """Open the snapshot read-only and enforce its schema contract.

        Returns:
            Read-only connection with rows addressable by column name.

        Raises:
            FileNotFoundError: If the configured path is not a file.
            ValueError: If the file is not a SQLite database, or does not carry
                the tables and columns this tool queries. The message names
                every missing piece.
        """
        path = self.db_path.resolve()

        if not path.is_file():
            raise FileNotFoundError(
                f"Taiwan stock snapshot not found: {path}. Point "
                "VIBE_TW_STOCK_DB at a published snapshot file."
            )

        connection = sqlite3.connect(
            f"file:{path}?mode=ro&immutable=1",
            uri=True,
        )
        connection.row_factory = sqlite3.Row

        try:
            problems = _schema_problems(connection)
        except sqlite3.DatabaseError as error:
            connection.close()
            raise ValueError(
                f"Taiwan stock snapshot {path} is not a readable SQLite "
                f"database: {error}"
            ) from error

        if problems:
            connection.close()
            raise ValueError(
                f"Taiwan stock snapshot {path} does not match the required "
                f"schema: {'; '.join(problems)}. Point VIBE_TW_STOCK_DB at a "
                "snapshot published by the Taiwan stock pipeline."
            )

        return connection

    @staticmethod
    def _normalize_stock_ids(
        stock_ids: Any,
        *,
        required: bool,
    ) -> list[str]:
        """Validate and de-duplicate the requested Taiwan stock IDs.

        Args:
            stock_ids: Raw request value, expected to be a list of four-digit
                ID strings.
            required: Whether the action cannot run without at least one ID.

        Returns:
            De-duplicated IDs in request order.

        Raises:
            ValueError: If the value is not a list, holds a non four-digit ID,
                is empty while required, or exceeds ``MAX_QUERY_STOCKS``.
        """
        if stock_ids is None:
            if required:
                raise ValueError(
                    "stock_ids is required for this action"
                )
            return []

        if not isinstance(stock_ids, list):
            raise ValueError("stock_ids must be an array")

        normalized: list[str] = []

        for raw_stock_id in stock_ids:
            stock_id = str(raw_stock_id).strip()

            if not STOCK_ID_PATTERN.fullmatch(stock_id):
                raise ValueError(
                    f"Invalid Taiwan stock ID: {stock_id!r}"
                )

            if stock_id not in normalized:
                normalized.append(stock_id)

        if required and not normalized:
            raise ValueError(
                "stock_ids must contain at least one stock ID"
            )

        if len(normalized) > MAX_QUERY_STOCKS:
            raise ValueError(
                f"At most {MAX_QUERY_STOCKS} stock IDs are allowed"
            )

        return normalized

    @staticmethod
    def _validate_date(
        value: Any,
        field_name: str,
    ) -> str | None:
        """Normalize an optional ISO date bound.

        Args:
            value: Raw request value.
            field_name: Field name used in the error message.

        Returns:
            The date as ``YYYY-MM-DD``, or None when unset.

        Raises:
            ValueError: If the value is not an ISO calendar date.
        """
        if value in (None, ""):
            return None

        text = str(value).strip()

        try:
            parsed = date.fromisoformat(text)
        except ValueError as error:
            raise ValueError(
                f"{field_name} must use YYYY-MM-DD format"
            ) from error

        return parsed.isoformat()

    @staticmethod
    def _validate_limit(value: Any) -> int:
        """Coerce the row limit into the supported range.

        Args:
            value: Raw request value.

        Returns:
            The limit as an integer.

        Raises:
            ValueError: If it is not an integer in 1..``MAX_RESULT_ROWS``.
        """
        try:
            limit = int(value)
        except (TypeError, ValueError) as error:
            raise ValueError("limit must be an integer") from error

        if not 1 <= limit <= MAX_RESULT_ROWS:
            raise ValueError(
                f"limit must be between 1 and {MAX_RESULT_ROWS}"
            )

        return limit

    @staticmethod
    def _rows(
        cursor: sqlite3.Cursor,
    ) -> list[dict[str, Any]]:
        """Materialize a cursor as plain dictionaries.

        Args:
            cursor: Cursor over ``sqlite3.Row`` rows.

        Returns:
            One dictionary per row, keyed by column name.
        """
        return [dict(row) for row in cursor.fetchall()]

    @staticmethod
    def _flag_stale_features(
        records: list[dict[str, Any]],
    ) -> None:
        """Mark rows whose indicators predate their price bar.

        The newest price row and the newest feature row are selected
        independently, so they can land on different dates. Reporting one date
        for both would mis-attribute the indicators.

        Args:
            records: Rows carrying ``price_date`` and ``feature_date``, mutated
                in place to gain a ``stale_features`` flag.
        """
        for record in records:
            price_date = record.get("price_date")
            feature_date = record.get("feature_date")

            record["stale_features"] = bool(
                price_date
                and feature_date
                and price_date != feature_date
            )

    def _status(
        self,
        connection: sqlite3.Connection,
    ) -> dict[str, Any]:
        """Summarize snapshot coverage and integrity.

        Args:
            connection: Open snapshot connection.

        Returns:
            Row counts, the latest market date, universe reason distribution
            and the SQLite integrity verdict.
        """
        counts = {
            "stock_master_rows": connection.execute(
                "SELECT COUNT(*) FROM stock_master"
            ).fetchone()[0],
            "daily_price_rows": connection.execute(
                "SELECT COUNT(*) FROM daily_price"
            ).fetchone()[0],
            "daily_price_stocks": connection.execute(
                """
                SELECT COUNT(DISTINCT stock_id)
                FROM daily_price
                """
            ).fetchone()[0],
            "stock_feature_rows": connection.execute(
                "SELECT COUNT(*) FROM stock_feature"
            ).fetchone()[0],
            "stock_feature_stocks": connection.execute(
                """
                SELECT COUNT(DISTINCT stock_id)
                FROM stock_feature
                """
            ).fetchone()[0],
            "active_analysis_stocks": connection.execute(
                """
                SELECT COUNT(*)
                FROM analysis_universe
                WHERE active = 1
                """
            ).fetchone()[0],
        }

        reason_distribution = {
            str(row["reason"]): int(row["count"])
            for row in connection.execute(
                """
                SELECT reason, COUNT(*) AS count
                FROM analysis_universe
                GROUP BY reason
                ORDER BY count DESC, reason
                """
            )
        }

        return {
            "latest_market_date": connection.execute(
                "SELECT MAX(date) FROM daily_price"
            ).fetchone()[0],
            "integrity": connection.execute(
                "PRAGMA integrity_check"
            ).fetchone()[0],
            "journal_mode": connection.execute(
                "PRAGMA journal_mode"
            ).fetchone()[0],
            **counts,
            "reason_distribution": reason_distribution,
        }

    def _lookup(
        self,
        connection: sqlite3.Connection,
        stock_ids: list[str],
    ) -> dict[str, Any]:
        """Resolve stock identity and analysis eligibility.

        Args:
            connection: Open snapshot connection.
            stock_ids: Validated Taiwan stock IDs.

        Returns:
            Master and universe metadata per stock, plus the IDs absent from
            the snapshot.
        """
        placeholders = ",".join("?" for _ in stock_ids)

        records = self._rows(
            connection.execute(
                f"""
                SELECT
                    sm.stock_id,
                    sm.stock_name,
                    sm.market,
                    sm.industry,
                    sm.enable,
                    au.active,
                    au.reason,
                    au.price_rows,
                    au.last_price_date,
                    au.last_feature_date,
                    au.trading_day_lag,
                    au.latest_close
                FROM stock_master sm
                LEFT JOIN analysis_universe au
                  ON au.stock_id = sm.stock_id
                WHERE sm.stock_id IN ({placeholders})
                ORDER BY sm.stock_id
                """,
                stock_ids,
            )
        )

        found = {
            str(record["stock_id"])
            for record in records
        }

        return {
            "records": records,
            "not_found": [
                stock_id
                for stock_id in stock_ids
                if stock_id not in found
            ],
        }

    def _latest(
        self,
        connection: sqlite3.Connection,
        stock_ids: list[str],
    ) -> dict[str, Any]:
        """Return the newest price bar and newest indicator row per stock.

        Args:
            connection: Open snapshot connection.
            stock_ids: Validated Taiwan stock IDs.

        Returns:
            One record per stock carrying ``price_date``, ``feature_date`` and
            ``stale_features``, plus the IDs absent from the snapshot.
        """
        placeholders = ",".join("?" for _ in stock_ids)

        parameters = [
            *stock_ids,
            *stock_ids,
            *stock_ids,
        ]

        records = self._rows(
            connection.execute(
                f"""
                WITH latest_price AS (
                    SELECT stock_id, MAX(date) AS latest_date
                    FROM daily_price
                    WHERE stock_id IN ({placeholders})
                    GROUP BY stock_id
                ),
                latest_feature AS (
                    SELECT stock_id, MAX(date) AS latest_date
                    FROM stock_feature
                    WHERE stock_id IN ({placeholders})
                    GROUP BY stock_id
                )
                SELECT
                    sm.stock_id,
                    sm.stock_name,
                    sm.market,
                    sm.industry,
                    au.active,
                    au.reason,
                    dp.date AS price_date,
                    dp.open,
                    dp.max AS high,
                    dp.min AS low,
                    dp.close,
                    dp.Trading_Volume AS volume,
                    dp.Trading_money AS trading_money,
                    dp.Trading_turnover AS turnover,
                    dp.spread,
                    sf.date AS feature_date,
                    sf.ma5,
                    sf.ma20,
                    sf.ma60,
                    sf.ema12,
                    sf.ema26,
                    sf.macd,
                    sf.macd_signal,
                    sf.macd_hist,
                    sf.rsi14
                FROM stock_master sm
                LEFT JOIN analysis_universe au
                  ON au.stock_id = sm.stock_id
                LEFT JOIN latest_price lp
                  ON lp.stock_id = sm.stock_id
                LEFT JOIN daily_price dp
                  ON dp.stock_id = lp.stock_id
                 AND dp.date = lp.latest_date
                LEFT JOIN latest_feature lf
                  ON lf.stock_id = sm.stock_id
                LEFT JOIN stock_feature sf
                  ON sf.stock_id = lf.stock_id
                 AND sf.date = lf.latest_date
                WHERE sm.stock_id IN ({placeholders})
                ORDER BY sm.stock_id
                """,
                parameters,
            )
        )

        self._flag_stale_features(records)

        found = {
            str(record["stock_id"])
            for record in records
        }

        return {
            "records": records,
            "not_found": [
                stock_id
                for stock_id in stock_ids
                if stock_id not in found
            ],
        }

    def _history(
        self,
        connection: sqlite3.Connection,
        stock_ids: list[str],
        start_date: str | None,
        end_date: str | None,
        limit: int,
    ) -> dict[str, Any]:
        """Return the newest daily bars per stock, oldest first.

        Indicators join on the bar's own date, so no separate feature date is
        needed here.

        Args:
            connection: Open snapshot connection.
            stock_ids: Validated Taiwan stock IDs.
            start_date: Inclusive lower date bound, or None.
            end_date: Inclusive upper date bound, or None.
            limit: Maximum bars retained per stock.

        Returns:
            Bars ordered by stock then ascending date, the per-stock limit, and
            the IDs with no rows in range.
        """
        placeholders = ",".join("?" for _ in stock_ids)

        conditions = [
            f"dp.stock_id IN ({placeholders})"
        ]
        parameters: list[Any] = [*stock_ids]

        if start_date:
            conditions.append("dp.date >= ?")
            parameters.append(start_date)

        if end_date:
            conditions.append("dp.date <= ?")
            parameters.append(end_date)

        parameters.append(limit)

        records = self._rows(
            connection.execute(
                f"""
                WITH ranked AS (
                    SELECT
                        dp.stock_id,
                        dp.date,
                        dp.open,
                        dp.max AS high,
                        dp.min AS low,
                        dp.close,
                        dp.Trading_Volume AS volume,
                        dp.Trading_money AS trading_money,
                        dp.Trading_turnover AS turnover,
                        dp.spread,
                        sf.ma5,
                        sf.ma20,
                        sf.ma60,
                        sf.ema12,
                        sf.ema26,
                        sf.macd,
                        sf.macd_signal,
                        sf.macd_hist,
                        sf.rsi14,
                        ROW_NUMBER() OVER (
                            PARTITION BY dp.stock_id
                            ORDER BY dp.date DESC
                        ) AS row_number
                    FROM daily_price dp
                    LEFT JOIN stock_feature sf
                      ON sf.stock_id = dp.stock_id
                     AND sf.date = dp.date
                    WHERE {" AND ".join(conditions)}
                )
                SELECT
                    stock_id,
                    date,
                    open,
                    high,
                    low,
                    close,
                    volume,
                    trading_money,
                    turnover,
                    spread,
                    ma5,
                    ma20,
                    ma60,
                    ema12,
                    ema26,
                    macd,
                    macd_signal,
                    macd_hist,
                    rsi14
                FROM ranked
                WHERE row_number <= ?
                ORDER BY stock_id, date
                """,
                parameters,
            )
        )

        returned_ids = {
            str(record["stock_id"])
            for record in records
        }

        return {
            "records": records,
            "limit_per_stock": limit,
            "not_found_or_no_rows": [
                stock_id
                for stock_id in stock_ids
                if stock_id not in returned_ids
            ],
        }

    def _universe(
        self,
        connection: sqlite3.Connection,
        *,
        active_only: bool,
        market: str | None,
        industry: str | None,
        limit: int,
    ) -> dict[str, Any]:
        """List analysis-universe stocks with their latest indicators.

        Args:
            connection: Open snapshot connection.
            active_only: Restrict to stocks flagged active.
            market: Optional ``twse``/``tpex`` filter.
            industry: Optional partial industry-name filter.
            limit: Maximum rows returned.

        Returns:
            Universe records carrying ``price_date``, ``feature_date`` and
            ``stale_features``, plus the filters applied.

        Raises:
            ValueError: If ``market`` is neither ``twse`` nor ``tpex``.
        """
        conditions: list[str] = []
        parameters: list[Any] = []

        if active_only:
            conditions.append("au.active = 1")

        if market:
            market = market.strip().lower()

            if market not in {"twse", "tpex"}:
                raise ValueError(
                    "market must be twse or tpex"
                )

            conditions.append("au.market = ?")
            parameters.append(market)

        if industry:
            conditions.append("au.industry LIKE ?")
            parameters.append(f"%{industry.strip()}%")

        where_clause = (
            f"WHERE {' AND '.join(conditions)}"
            if conditions
            else ""
        )

        parameters.append(limit)

        records = self._rows(
            connection.execute(
                f"""
                SELECT
                    au.stock_id,
                    au.stock_name,
                    au.market,
                    au.industry,
                    au.active,
                    au.reason,
                    au.price_rows,
                    au.last_price_date AS price_date,
                    au.trading_day_lag,
                    au.latest_close,
                    sf.date AS feature_date,
                    sf.ma5,
                    sf.ma20,
                    sf.ma60,
                    sf.macd,
                    sf.macd_signal,
                    sf.macd_hist,
                    sf.rsi14
                FROM analysis_universe au
                LEFT JOIN stock_feature sf
                  ON sf.stock_id = au.stock_id
                 AND sf.date = au.last_feature_date
                {where_clause}
                ORDER BY
                    au.active DESC,
                    au.market,
                    au.stock_id
                LIMIT ?
                """,
                parameters,
            )
        )

        self._flag_stale_features(records)

        return {
            "records": records,
            "active_only": active_only,
            "market": market,
            "industry": industry,
        }

    @staticmethod
    def _serialize(payload: dict[str, Any]) -> str:
        """Serialize the envelope inside the agent's tool-result budget.

        Bulk actions can serialize to hundreds of thousands of characters,
        while the agent loop hard-truncates every result at 10,000 characters.
        A blind cut breaks JSON parsing and, since rows are ordered oldest
        first, throws away the newest bars. So oldest rows are dropped here —
        newest bar of each stock first, round-robin — until the envelope fits,
        and the response states that it happened.

        Args:
            payload: Response envelope whose ``data`` may hold a ``records``
                list.

        Returns:
            JSON text within ``RESPONSE_CHAR_BUDGET`` characters, carrying
            ``total_rows``, ``returned_rows`` and ``truncated`` whenever the
            action returns rows.
        """
        payload = _json_safe(payload)
        data = payload["data"]
        records = data.get("records")

        if not isinstance(records, list):
            return _dump(payload)

        total_rows = len(records)
        data["total_rows"] = total_rows
        data["returned_rows"] = total_rows
        data["truncated"] = False

        rendered = _dump(payload)

        if len(rendered) <= RESPONSE_CHAR_BUDGET:
            return rendered

        data["truncated"] = True
        data["hint"] = TRUNCATION_HINT

        order = _retention_order(records)

        def attempt(keep: int) -> str:
            retained = set(order[:keep])
            data["records"] = [
                record
                for index, record in enumerate(records)
                if index in retained
            ]
            data["returned_rows"] = keep
            return _dump(payload)

        # An empty record set always fits, so binary-search the largest count
        # that still does. The full set is already known not to fit.
        best_keep = 0
        low, high = 1, total_rows - 1

        while low <= high:
            middle = (low + high) // 2

            if len(attempt(middle)) <= RESPONSE_CHAR_BUDGET:
                best_keep = middle
                low = middle + 1
            else:
                high = middle - 1

        return attempt(best_keep)

    def execute(self, **kwargs: Any) -> str:
        """Run one read-only snapshot query.

        Args:
            **kwargs: ``action`` plus that action's parameters — ``stock_ids``,
                ``start_date``, ``end_date``, ``market``, ``industry``,
                ``active_only``, ``limit``.

        Returns:
            JSON envelope within ``RESPONSE_CHAR_BUDGET`` characters.

        Raises:
            FileNotFoundError: If the configured snapshot is missing.
            ValueError: If the action or a parameter is invalid, or the
                snapshot does not match the required schema.
        """
        action = str(
            kwargs.get("action", "")
        ).strip().lower()

        if action not in {
            "status",
            "lookup",
            "latest",
            "history",
            "universe",
        }:
            raise ValueError(
                "action must be status, lookup, latest, history, or universe"
            )

        requires_stock_ids = action in {
            "lookup",
            "latest",
            "history",
        }

        stock_ids = self._normalize_stock_ids(
            kwargs.get("stock_ids"),
            required=requires_stock_ids,
        )

        start_date = self._validate_date(
            kwargs.get("start_date"),
            "start_date",
        )
        end_date = self._validate_date(
            kwargs.get("end_date"),
            "end_date",
        )

        if (
            start_date
            and end_date
            and start_date > end_date
        ):
            raise ValueError(
                "start_date must not be after end_date"
            )

        limit = self._validate_limit(
            kwargs.get("limit", 60)
        )

        with closing(self._connect()) as connection:
            if action == "status":
                data = self._status(connection)

            elif action == "lookup":
                data = self._lookup(
                    connection,
                    stock_ids,
                )

            elif action == "latest":
                data = self._latest(
                    connection,
                    stock_ids,
                )

            elif action == "history":
                data = self._history(
                    connection,
                    stock_ids,
                    start_date,
                    end_date,
                    limit,
                )

            else:
                data = self._universe(
                    connection,
                    active_only=bool(
                        kwargs.get(
                            "active_only",
                            True,
                        )
                    ),
                    market=kwargs.get("market"),
                    industry=kwargs.get("industry"),
                    limit=limit,
                )

        return self._serialize(
            {
                "status": "success",
                "tool": self.name,
                "action": action,
                "snapshot": self.db_path.name,
                "data": data,
            }
        )
