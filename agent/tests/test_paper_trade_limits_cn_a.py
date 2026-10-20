"""Offline tests for cn_a price-limit / ST / suspension lookups (VD-11).

Table-first (fake CH client with recorded rows), heuristic fallback (the
imported china_a._price_limit board ratios + Decimal ROUND_HALF_UP), and
provenance recording.  Never the network, never live ClickHouse.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.tools.paper_trade.limits_cn_a import (
    PROV_LIMITS_HEURISTIC,
    PROV_LIMITS_TABLE,
    PROV_LIMITS_UNAVAILABLE,
    PROV_LIMIT_LIST_ROW,
    PROV_ST_NO_ROW,
    PROV_ST_ROW,
    PROV_SUSPEND_NO_ROW,
    PROV_SUSPEND_ROW,
    ClickHouseLimitsClient,
    get_limit_status,
    heuristic_limit_prices,
)

_TRADE_DATE = "2026-10-20"


class FakeLimitsClient:
    """Canned per-table rows; each getter returns the recorded DataFrame."""

    def __init__(
        self,
        *,
        stk_limit: list[dict] | None = None,
        st: list[dict] | None = None,
        suspend: list[dict] | None = None,
        limit_list: list[dict] | None = None,
    ) -> None:
        self._stk_limit = stk_limit or []
        self._st = st or []
        self._suspend = suspend or []
        self._limit_list = limit_list or []

    def get_stk_limit(self, trade_date: str, ts_code: str) -> pd.DataFrame:
        return pd.DataFrame(self._stk_limit)

    def get_stk_st_daily(self, trade_date: str, ts_code: str) -> pd.DataFrame:
        return pd.DataFrame(self._st)

    def get_stk_suspend(self, trade_date: str, ts_code: str) -> pd.DataFrame:
        return pd.DataFrame(self._suspend)

    def get_stk_limit_list(self, trade_date: str, ts_code: str) -> pd.DataFrame:
        return pd.DataFrame(self._limit_list)


# ── Table-first path ──


def test_table_hit_serves_absolute_prices() -> None:
    client = FakeLimitsClient(stk_limit=[{"up_limit": 11.0, "down_limit": 9.0}])
    status = get_limit_status(client, "600519.SH", _TRADE_DATE)
    assert status.up_limit == 11.0
    assert status.down_limit == 9.0
    assert PROV_LIMITS_TABLE in status.provenance
    assert PROV_LIMITS_HEURISTIC not in status.provenance


def test_table_wins_over_prev_close_heuristic() -> None:
    client = FakeLimitsClient(stk_limit=[{"up_limit": 11.0, "down_limit": 9.0}])
    status = get_limit_status(client, "600519.SH", _TRADE_DATE, prev_close=999.0)
    assert status.up_limit == 11.0
    assert PROV_LIMITS_TABLE in status.provenance


# ── Heuristic fallback path ──


@pytest.mark.parametrize(
    ("ts_code", "expected"),
    [
        ("600519.SH", (11.0, 9.0)),  # main board ±10%
        ("000001.SZ", (11.0, 9.0)),  # main board ±10%
        ("300001.SZ", (12.0, 8.0)),  # ChiNext ±20%
        ("688001.SH", (12.0, 8.0)),  # STAR ±20%
        ("830799.BJ", (13.0, 7.0)),  # BSE ±30%
    ],
)
def test_heuristic_board_ratios_match_the_engine_primitive(ts_code: str, expected: tuple[float, float]) -> None:
    client = FakeLimitsClient()
    status = get_limit_status(client, ts_code, _TRADE_DATE, prev_close=10.0)
    assert (status.up_limit, status.down_limit) == expected
    assert PROV_LIMITS_HEURISTIC in status.provenance


def test_st_from_table_overrides_heuristic_ratio_to_five_percent() -> None:
    # The engine heuristic cannot detect ST from the code alone (known gap);
    # the paper path closes it with stk_st_daily.
    client = FakeLimitsClient(st=[{"type": "ST", "type_name": "ST"}])
    status = get_limit_status(client, "600519.SH", _TRADE_DATE, prev_close=10.0)
    assert status.is_st is True
    assert (status.up_limit, status.down_limit) == (10.5, 9.5)
    assert PROV_ST_ROW in status.provenance


def test_heuristic_quantizes_half_up_not_banker() -> None:
    # VD-9 trap pin: 10.05 × 1.1 = 11.055 → HALF_UP → 11.06.
    # Builtin round(11.055, 2) gives 11.05 (float 11.0549999… + banker's).
    up, down = heuristic_limit_prices("600519.SH", 10.05, is_st=False)
    assert up == 11.06
    # 10.05 × 0.9 = 9.045 → HALF_UP → 9.05 (builtin round would give 9.04).
    assert down == 9.05


def test_heuristic_rejects_non_positive_prev_close() -> None:
    with pytest.raises(ValueError, match="prev_close must be positive"):
        heuristic_limit_prices("600519.SH", 0.0, is_st=False)
    with pytest.raises(ValueError, match="prev_close must be positive"):
        heuristic_limit_prices("600519.SH", -1.5, is_st=False)


def test_no_table_and_no_prev_close_never_fabricates_a_band() -> None:
    client = FakeLimitsClient()
    status = get_limit_status(client, "600519.SH", _TRADE_DATE)
    assert status.up_limit is None
    assert status.down_limit is None
    assert PROV_LIMITS_UNAVAILABLE in status.provenance


# ── ST / suspension facets ──


def test_no_st_row_reports_not_st_with_provenance() -> None:
    status = get_limit_status(FakeLimitsClient(), "600519.SH", _TRADE_DATE, prev_close=10.0)
    assert status.is_st is False
    assert PROV_ST_NO_ROW in status.provenance


def test_suspension_row_marks_suspended() -> None:
    client = FakeLimitsClient(suspend=[{"suspend_type": "S", "suspend_timing": ""}])
    status = get_limit_status(client, "600519.SH", _TRADE_DATE)
    assert status.is_suspended is True
    assert PROV_SUSPEND_ROW in status.provenance


def test_resumption_row_is_not_a_suspension() -> None:
    # tushare-lineage semantics: suspend_type R = resumed trading that day.
    client = FakeLimitsClient(suspend=[{"suspend_type": "R", "suspend_timing": ""}])
    status = get_limit_status(client, "600519.SH", _TRADE_DATE)
    assert status.is_suspended is False
    assert PROV_SUSPEND_ROW in status.provenance


def test_no_suspension_row_reports_not_suspended_with_provenance() -> None:
    status = get_limit_status(FakeLimitsClient(), "600519.SH", _TRADE_DATE, prev_close=10.0)
    assert status.is_suspended is False
    assert PROV_SUSPEND_NO_ROW in status.provenance


# ── Auxiliary stk_limit_list_d flag ──


def test_limit_list_flag_passes_through() -> None:
    client = FakeLimitsClient(limit_list=[{"limit": "U"}])
    status = get_limit_status(client, "600519.SH", _TRADE_DATE, prev_close=10.0)
    assert status.limit_list_flag == "U"
    assert PROV_LIMIT_LIST_ROW in status.provenance


def test_limit_list_absent_leaves_flag_none() -> None:
    status = get_limit_status(FakeLimitsClient(), "600519.SH", _TRADE_DATE, prev_close=10.0)
    assert status.limit_list_flag is None
    assert PROV_LIMIT_LIST_ROW not in status.provenance


# ── Determinism ──


def test_lookup_is_deterministic() -> None:
    client = FakeLimitsClient(
        stk_limit=[{"up_limit": 11.0, "down_limit": 9.0}],
        st=[{"type": "ST", "type_name": "ST"}],
    )
    first = get_limit_status(client, "600519.SH", _TRADE_DATE, prev_close=10.0)
    second = get_limit_status(client, "600519.SH", _TRADE_DATE, prev_close=10.0)
    assert first == second
    assert first.provenance == second.provenance


# ── ClickHouse adapter (SQL shape only — no live CH) ──


class FakeConnector:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str]]] = []

    def query(self, sql: str, params: dict[str, str] | None = None) -> pd.DataFrame:
        self.calls.append((sql, params or {}))
        return pd.DataFrame([])


def test_adapter_sql_names_tables_and_columns_explicitly() -> None:
    connector = FakeConnector()
    client = ClickHouseLimitsClient(connector)
    client.get_stk_limit(_TRADE_DATE, "600519.SH")
    client.get_stk_st_daily(_TRADE_DATE, "600519.SH")
    client.get_stk_suspend(_TRADE_DATE, "600519.SH")
    client.get_stk_limit_list(_TRADE_DATE, "600519.SH")

    assert len(connector.calls) == 4
    for sql, params in connector.calls:
        assert "SELECT *" not in sql  # clickhouse_columns.py contract
        assert params == {"param_trade_date": _TRADE_DATE, "param_ts_code": "600519.SH"}

    by_table = {sql.split("FROM ")[1].split(" ")[0]: sql for sql, _ in connector.calls}
    assert set(by_table) == {"stk_limit", "stk_st_daily", "stk_suspend", "stk_limit_list_d"}
    assert "up_limit, down_limit" in by_table["stk_limit"]
    assert "`limit`" in by_table["stk_limit_list_d"]  # SQL keyword, backtick-quoted
