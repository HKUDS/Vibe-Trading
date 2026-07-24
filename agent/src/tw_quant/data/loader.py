"""Snapshot-only Taiwan loader with an existing Vibe-Trading adapter."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pandas as pd

from backtest.loaders.registry import register
from src.tw_quant.config import snapshot_root as default_snapshot_root
from src.tw_quant.data.verifier import verify_snapshot
from src.tw_quant.market.symbols import SymbolParseError, parse_symbol


class SnapshotLoadError(RuntimeError):
    """Raised when a Taiwan snapshot cannot satisfy a load request."""


class SnapshotRequiredError(SnapshotLoadError):
    """Raised when a request does not identify an immutable snapshot."""


def _sql_literal(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


@register
class TaiwanSnapshotLoader:
    """Read daily Taiwan data only from a verified immutable snapshot."""

    name = "tw_snapshot"
    markets = {"taiwan_equity"}
    requires_auth = False

    def __init__(self, snapshot_id: str | None = None, snapshot_root: str | Path | None = None) -> None:
        self.snapshot_id = snapshot_id or os.getenv("TW_QUANT_SNAPSHOT_ID", "").strip() or None
        self.snapshot_root = Path(snapshot_root or os.getenv("TW_QUANT_SNAPSHOT_ROOT", "") or default_snapshot_root())
        self._provenance: dict[str, Any] = {}

    @property
    def provenance(self) -> dict[str, Any]:
        return dict(self._provenance)

    def is_available(self) -> bool:
        """Return True only when an explicit snapshot can be verified."""
        if not self.snapshot_id:
            return False
        try:
            report = verify_snapshot(self.snapshot_id, self.snapshot_root)
        except Exception:
            return False
        return report.ok

    def load(
        self,
        symbols: list[str],
        start: str,
        end: str,
        fields: list[str] | None = None,
        snapshot_id: str | None = None,
        adjustment_mode: str = "raw",
        *,
        market_hint: str | None = None,
    ) -> dict[str, pd.DataFrame]:
        """Load daily bars from one verified snapshot, with no fallback."""
        selected_snapshot = snapshot_id or self.snapshot_id
        if not selected_snapshot:
            raise SnapshotRequiredError("snapshot_id is required for Taiwan snapshot loads")
        if adjustment_mode not in {"raw", "none"}:
            raise SnapshotLoadError(
                f"unsupported adjustment_mode {adjustment_mode!r}; Phase 01 supports raw only"
            )
        try:
            start_date = pd.Timestamp(start).date()
            end_date = pd.Timestamp(end).date()
        except Exception as exc:
            raise SnapshotLoadError(f"invalid Taiwan load date range: {start!r}, {end!r}") from exc
        if start_date > end_date:
            raise SnapshotLoadError(f"start date {start!r} is after end date {end!r}")

        canonical: list[str] = []
        for symbol in symbols:
            try:
                canonical.append(parse_symbol(symbol, market_hint=market_hint).canonical)
            except SymbolParseError as exc:
                raise SnapshotLoadError(str(exc)) from exc
        if not canonical:
            return {}

        report = verify_snapshot(selected_snapshot, self.snapshot_root)
        if not report.ok:
            raise SnapshotLoadError(
                f"snapshot verification failed for {selected_snapshot}: " + "; ".join(report.errors)
            )
        table = next((entry for entry in report.tables if entry.get("dataset") == "daily_price"), None)
        if table is None:
            raise SnapshotLoadError("verified snapshot does not contain daily_price")
        data_path = (self.snapshot_root / selected_snapshot / table["path"]).resolve(strict=True)

        allowed_fields = {
            "open", "high", "low", "close", "volume", "turnover", "trades",
            "reference_price", "price_limit_up", "price_limit_down", "is_suspended",
            "is_disposition", "is_full_delivery", "adjustment_factor", "effective_at",
            "available_at", "ingested_at", "source", "source_dataset", "revision_id",
            "quality_flags", "row_hash",
        }
        selected_fields = list(fields or (
            "open", "high", "low", "close", "volume", "turnover", "trades",
            "reference_price", "price_limit_up", "price_limit_down", "is_suspended",
            "is_disposition", "is_full_delivery", "adjustment_factor", "effective_at",
            "available_at", "ingested_at", "source", "source_dataset", "revision_id",
            "quality_flags", "row_hash",
        ))
        unknown = set(selected_fields) - allowed_fields
        if unknown:
            raise SnapshotLoadError(f"daily_price fields are unavailable: {sorted(unknown)}")
        if not selected_fields:
            raise SnapshotLoadError("at least one daily_price field is required")

        import duckdb

        placeholders = ", ".join("?" for _ in canonical)
        select_fields = ", ".join(["symbol", "trade_date", *selected_fields])
        sql = (
            f"SELECT {select_fields} FROM read_parquet({_sql_literal(data_path)}) "
            f"WHERE symbol IN ({placeholders}) "
            f"AND trade_date >= DATE {_sql_literal(start_date.isoformat())} "
            f"AND trade_date <= DATE {_sql_literal(end_date.isoformat())} "
            "ORDER BY symbol, trade_date"
        )
        conn = duckdb.connect(database=":memory:")
        try:
            frame = conn.execute(sql, canonical).df()
        finally:
            conn.close()

        result: dict[str, pd.DataFrame] = {}
        if frame.empty:
            raise SnapshotLoadError(
                f"symbols are absent from snapshot or have no rows in requested date range "
                f"for {canonical}: "
                f"{start_date}..{end_date}"
            )
        frame["trade_date"] = pd.to_datetime(frame["trade_date"], utc=True).dt.tz_convert(None)
        for symbol, group in frame.groupby("symbol", sort=False):
            output = group.drop(columns=["symbol"]).set_index("trade_date").sort_index()
            result[str(symbol)] = output
        missing = [symbol for symbol in canonical if symbol not in result]
        if missing:
            raise SnapshotLoadError(f"symbols are absent from snapshot/date range: {missing}")
        self.snapshot_id = selected_snapshot
        self._provenance = {
            "snapshot_id": selected_snapshot,
            "table": "daily_price",
            "table_sha256": table["sha256"],
            "source_datasets": table.get("source_datasets", []),
            "revision_ids": table.get("revision_ids", []),
            "rule_profile": "TW_EQUITY_PHASE01_PLACEHOLDER",
        }
        return result

    def fetch(
        self,
        codes: list[str],
        start_date: str,
        end_date: str,
        *,
        interval: str = "1D",
        fields: list[str] | None = None,
    ) -> dict[str, pd.DataFrame]:
        """Adapt ``load`` to Vibe-Trading's canonical loader contract."""
        if interval != "1D":
            raise SnapshotLoadError(
                f"Taiwan snapshot loader supports daily bars only in Phase 01, got {interval!r}"
            )
        return self.load(codes, start_date, end_date, fields=fields)
