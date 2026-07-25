"""Read-only Taiwan stock data tool backed by a published SQLite snapshot."""

from __future__ import annotations

import json
import math
import os
import re
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any

from src.agent.tools import BaseTool

DEFAULT_DB_PATH = "/data/tw-stock/latest.db"
STOCK_ID_PATTERN = re.compile(r"^\d{4}$")
MAX_QUERY_STOCKS = 50
MAX_RESULT_ROWS = 200


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


class TaiwanStockDataTool(BaseTool):
    """Query the local published Taiwan stock database."""

    name = "get_taiwan_stock_data"
    description = (
        "Query the local read-only Taiwan stock snapshot for TWSE and TPEx "
        "stocks. Use this before generic internet market-data tools when the "
        "user asks about Taiwan four-digit stock IDs. Supports database status, "
        "stock lookup, latest price and technical indicators, historical bars, "
        "and the active analysis universe. This tool never places orders."
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
        configured = (
            str(db_path)
            if db_path is not None
            else os.getenv(
                "VIBE_TW_STOCK_DB",
                DEFAULT_DB_PATH,
            )
        )
        self.db_path = Path(configured).expanduser()

    @classmethod
    def check_available(cls) -> bool:
        path = Path(
            os.getenv(
                "VIBE_TW_STOCK_DB",
                DEFAULT_DB_PATH,
            )
        ).expanduser()

        return path.is_file()

    def _connect(self) -> sqlite3.Connection:
        path = self.db_path.resolve()

        if not path.is_file():
            raise FileNotFoundError(
                f"Taiwan stock snapshot not found: {path}"
            )

        connection = sqlite3.connect(
            f"file:{path}?mode=ro&immutable=1",
            uri=True,
        )
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _normalize_stock_ids(
        stock_ids: Any,
        *,
        required: bool,
    ) -> list[str]:
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
        return [dict(row) for row in cursor.fetchall()]

    def _status(
        self,
        connection: sqlite3.Connection,
    ) -> dict[str, Any]:
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
                    au.last_price_date,
                    au.trading_day_lag,
                    au.latest_close,
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

        return {
            "records": records,
            "returned": len(records),
            "active_only": active_only,
            "market": market,
            "industry": industry,
        }

    def execute(self, **kwargs: Any) -> str:
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

        with self._connect() as connection:
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

        payload = {
            "status": "success",
            "tool": self.name,
            "action": action,
            "snapshot": self.db_path.name,
            "data": data,
        }

        return json.dumps(
            _json_safe(payload),
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        )
