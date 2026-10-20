"""cn_a price-limit / ST / suspension lookups (pt-v1.1 §4, VD-11).

Table-first, heuristic-fallback, provenance-recorded:

* **Tables (truth)** — ClickHouse ``ashare`` DDL snapshots:
  ``stk_limit`` (up_limit/down_limit prices per trade_date+ts_code),
  ``stk_st_daily`` (ST flag rows), ``stk_suspend`` (suspension rows),
  ``stk_limit_list_d`` (auxiliary: which side the symbol locked, ``limit``
  column ``U``/``D``/``Z``; the engine — Step 3 — decides consumption).
* **Heuristic (fallback)** — when ``stk_limit`` lacks the day, the band is
  derived from the board ratio via ``backtest.engines.china_a._price_limit``
  (REUSED BY IMPORT, never modified — VD-2) applied to the previous close,
  with the ST ±5% ratio taken from ``stk_st_daily`` (the engine heuristic
  has a known ST detection gap; the paper path closes it with the table).
* **Provenance** — every lookup records which path served each facet, so
  the tool output can state table vs heuristic per symbol-day inside
  ``data_provenance`` (VD-11).  An unknown band is never fabricated: with
  no table row and no previous close, limits stay ``None`` and the engine
  fails closed (Step 3 decision).

Money discipline (VD-9): heuristic bands quantize to 0.01 with Decimal
ROUND_HALF_UP — Python's builtin rounding function is banned on money paths
(banker's rounding: 2.675 to 2dp yields 2.67, not 2.68).

Determinism: table rows are part of the input snapshot; no clock, no
environment, no network in this module.  Clients are injectable — tests
use fakes, never live ClickHouse.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Protocol

# VD-2: reuse the engine primitive by import; agent/backtest/ is never modified.
from backtest.engines.china_a import _price_limit

if TYPE_CHECKING:
    import pandas as pd

__all__ = [
    "CnALimitStatus",
    "CnALimitsClient",
    "ClickHouseLimitsClient",
    "get_limit_status",
    "heuristic_limit_prices",
]

# FROZEN provenance tokens (G1: RM written approval 2026-10-19, pt-v1.1) —
# they flow into the wire ``data_provenance`` object (AM-9/VD-11 extension
# surface, FINALIZED at G1 per the contract JSON ``limit_provenance``
# $comment).  Any token change = major schema bump with RM written
# confirmation (REQUIREMENTS §9).
PROV_LIMITS_TABLE = "limits:stk_limit"
PROV_LIMITS_HEURISTIC = "limits:heuristic"
PROV_LIMITS_UNAVAILABLE = "limits:unavailable"
PROV_ST_ROW = "st:stk_st_daily"
PROV_ST_NO_ROW = "st:stk_st_daily-no-row"
PROV_SUSPEND_ROW = "suspend:stk_suspend"
PROV_SUSPEND_NO_ROW = "suspend:stk_suspend-no-row"
PROV_LIMIT_LIST_ROW = "limit_list:stk_limit_list_d"

#: ST price-limit ratio (REQUIREMENTS §4: ST ±5%).  The board heuristic in
#: china_a.py cannot detect ST from the code alone; the table can.
_ST_LIMIT_RATIO = Decimal("0.05")

_TICK = Decimal("0.01")


class CnALimitsClient(Protocol):
    """Narrow injectable lookup surface (one method per CH table).

    :class:`ClickHouseLimitsClient` adapts a ``ClickHouseConnector``; tests
    inject fakes returning recorded DataFrames.  All ``trade_date``
    parameters are ``YYYY-MM-DD`` strings.
    """

    def get_stk_limit(self, trade_date: str, ts_code: str) -> "pd.DataFrame":
        """Rows with columns ``up_limit``, ``down_limit`` (empty = no data)."""
        ...

    def get_stk_st_daily(self, trade_date: str, ts_code: str) -> "pd.DataFrame":
        """Rows with columns ``type``, ``type_name`` (any row = ST that day)."""
        ...

    def get_stk_suspend(self, trade_date: str, ts_code: str) -> "pd.DataFrame":
        """Rows with columns ``suspend_type``, ``suspend_timing``."""
        ...

    def get_stk_limit_list(self, trade_date: str, ts_code: str) -> "pd.DataFrame":
        """Rows with the ``limit`` column (``U``/``D``/``Z``), auxiliary."""
        ...


@dataclass(frozen=True, slots=True)
class CnALimitStatus:
    """Per symbol-day limit/ST/suspension status with path provenance."""

    ts_code: str
    trade_date: str
    up_limit: float | None
    down_limit: float | None
    is_st: bool
    is_suspended: bool
    limit_list_flag: str | None
    provenance: tuple[str, ...]


def heuristic_limit_prices(ts_code: str, prev_close: float, is_st: bool) -> tuple[float, float]:
    """Derive (up_limit, down_limit) from the board ratio and previous close.

    Ratio source: ``china_a._price_limit`` (main board 10%, ChiNext/STAR
    20%, BSE 30%), overridden to 5% when the ST table says the symbol is
    ST that day.  Quantized to the 0.01 tick with ROUND_HALF_UP (VD-9).
    ``prev_close`` must be positive — non-positive prices are a data-layer
    sanity gate (plan R-V3), not something to derive bands from.
    """
    if prev_close <= 0:
        raise ValueError(f"prev_close must be positive to derive a heuristic band, got {prev_close!r}")
    ratio = _ST_LIMIT_RATIO if is_st else Decimal(str(_price_limit(ts_code)))
    base = Decimal(str(prev_close))
    up = (base * (Decimal(1) + ratio)).quantize(_TICK, rounding=ROUND_HALF_UP)
    down = (base * (Decimal(1) - ratio)).quantize(_TICK, rounding=ROUND_HALF_UP)
    return float(up), float(down)


def _records(frame: "pd.DataFrame") -> list[dict]:
    return list(frame.to_dict("records"))


def _is_suspended(records: list[dict]) -> bool:
    """Suspension verdict from ``stk_suspend`` rows.

    tushare-lineage semantics: ``suspend_type`` ``S`` = suspended,
    ``R`` = resumed.  A resumption row means the symbol trades again, so
    only non-``R`` rows count as suspended.  (Live column recheck is a
    Step 0 DD-5 item — ClickHouse is currently unreachable; the fake-client
    tests pin this interpretation.)
    """
    return any(str(record.get("suspend_type", "")).strip().upper() != "R" for record in records)


def get_limit_status(
    client: CnALimitsClient,
    ts_code: str,
    trade_date: str,
    prev_close: float | None = None,
) -> CnALimitStatus:
    """Look up one symbol-day: table-first, heuristic fallback, provenance.

    ``prev_close`` is only needed on the heuristic path (the ``stk_limit``
    table carries absolute prices).  When neither the table nor a previous
    close is available, ``up_limit``/``down_limit`` are ``None`` and the
    provenance says ``limits:unavailable`` — the caller must fail closed,
    never fabricate a band.
    """
    provenance: list[str] = []

    st_records = _records(client.get_stk_st_daily(trade_date, ts_code))
    is_st = bool(st_records)
    provenance.append(PROV_ST_ROW if is_st else PROV_ST_NO_ROW)

    suspend_records = _records(client.get_stk_suspend(trade_date, ts_code))
    is_suspended = _is_suspended(suspend_records)
    provenance.append(PROV_SUSPEND_ROW if suspend_records else PROV_SUSPEND_NO_ROW)

    limit_records = _records(client.get_stk_limit(trade_date, ts_code))
    up_limit: float | None
    down_limit: float | None
    if limit_records:
        up_limit = float(limit_records[0]["up_limit"])
        down_limit = float(limit_records[0]["down_limit"])
        provenance.append(PROV_LIMITS_TABLE)
    elif prev_close is not None:
        up_limit, down_limit = heuristic_limit_prices(ts_code, prev_close, is_st)
        provenance.append(PROV_LIMITS_HEURISTIC)
    else:
        up_limit = None
        down_limit = None
        provenance.append(PROV_LIMITS_UNAVAILABLE)

    limit_list_flag: str | None = None
    list_records = _records(client.get_stk_limit_list(trade_date, ts_code))
    if list_records:
        raw_flag = str(list_records[0].get("limit") or "").strip()
        limit_list_flag = raw_flag or None
        provenance.append(PROV_LIMIT_LIST_ROW)

    return CnALimitStatus(
        ts_code=ts_code,
        trade_date=trade_date,
        up_limit=up_limit,
        down_limit=down_limit,
        is_st=is_st,
        is_suspended=is_suspended,
        limit_list_flag=limit_list_flag,
        provenance=tuple(provenance),
    )


class _QueryConnector(Protocol):
    """The one ``ClickHouseConnector`` method the adapter needs."""

    def query(self, sql: str, params: dict[str, str] | None = None) -> "pd.DataFrame":
        ...


class ClickHouseLimitsClient:
    """Thin adapter over an INJECTED connector (VD-2: adapters live here).

    Never constructs ``ClickHouseConnector`` itself — credentials and
    connection stay the caller's decision (zero side effects at import and
    construction).  SQL follows the connector's established parameter style
    (``{name:Type}`` placeholders bound via ``param_<name>``) and names
    columns explicitly (no ``SELECT *`` — clickhouse_columns.py contract).
    """

    def __init__(self, connector: _QueryConnector) -> None:
        self._connector = connector

    def _lookup(self, table: str, columns: str, trade_date: str, ts_code: str) -> "pd.DataFrame":
        sql = (
            f"SELECT {columns} FROM {table} "
            "WHERE trade_date = {trade_date:String} AND ts_code = {ts_code:String}"
        )
        return self._connector.query(
            sql, params={"param_trade_date": trade_date, "param_ts_code": ts_code}
        )

    def get_stk_limit(self, trade_date: str, ts_code: str) -> "pd.DataFrame":
        return self._lookup("stk_limit", "up_limit, down_limit", trade_date, ts_code)

    def get_stk_st_daily(self, trade_date: str, ts_code: str) -> "pd.DataFrame":
        return self._lookup("stk_st_daily", "type, type_name", trade_date, ts_code)

    def get_stk_suspend(self, trade_date: str, ts_code: str) -> "pd.DataFrame":
        return self._lookup("stk_suspend", "suspend_type, suspend_timing", trade_date, ts_code)

    def get_stk_limit_list(self, trade_date: str, ts_code: str) -> "pd.DataFrame":
        # `limit` is a SQL keyword — backtick-quoted in ClickHouse.
        return self._lookup("stk_limit_list_d", "`limit`", trade_date, ts_code)
