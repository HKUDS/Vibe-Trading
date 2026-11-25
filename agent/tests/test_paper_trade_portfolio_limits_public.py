"""Public cn_a limits resolution for portfolio mode (D6-② tool seam, TDD).

``run_paper_trade_step(mode="portfolio")`` must resolve the cn_a limits client
from the SAME shared ClickHouse connector probe the calendar/bars legs use
(``_default_cn_a_connector``), mirroring the single-market ``_resolve_clients``
semantics: cn_a gets ``ClickHouseLimitsClient(connector)`` when the probe
succeeds, hk/us stay None, and an unreachable connector degrades to the frozen
is_st=False heuristic — never a crash. Injected seams pass through untouched,
so no connector is built offline. Provenance stays engine-internal
(``MatchOutcome.limit_provenance``); the public document shape is unchanged.

Scenario reused from the internal threading suite: prior close 10.00 → target
close 10.80 (+8%) is inside the main-board ±10% heuristic band but outside the
ST ±5% table band [9.50, 10.50], so the terminal outcome discriminates which
band the engine used. Offline by construction: fake connector/loaders only.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pandas as pd
import pytest
from jsonschema import Draft202012Validator, FormatChecker

from src.tools.paper_trade import tool as tool_module
from src.tools.paper_trade.limits_cn_a import (
    PROV_LIMITS_HEURISTIC,
    PROV_LIMITS_TABLE,
    PROV_ST_ROW,
    ClickHouseLimitsClient,
)
from src.tools.paper_trade.portfolio.schema import load_portfolio_contract_schema
from src.tools.paper_trade.tool import run_paper_trade_step
from tests.test_paper_trade_portfolio_limits import (
    CN_SYMBOL,
    DAY,
    ST_DOWN_LIMIT,
    ST_UP_LIMIT,
    FakeCnALimitsClient,
    OpenCalendar,
    _cn_record,
    _loaders,
    _payload,
    _spy_engine,
)

GOLDEN_DIR = Path(__file__).parent / "fixtures" / "paper_trade" / "golden"


class FakeSTConnector:
    """Offline ClickHouse double: ST flag + ±5% table prices for the cn_a day.

    Answers the adapter's parameterised ``SELECT ... FROM <table> WHERE ...``
    lookups; every other symbol-day (and the ``SELECT 1`` probe) gets an empty
    or trivial frame. The query log is the consultation proof.
    """

    def __init__(self) -> None:
        self.queries: list[tuple[str, dict[str, str] | None]] = []

    def query(self, sql: str, params: dict[str, str] | None = None) -> pd.DataFrame:
        self.queries.append((sql, params))
        if sql.strip() == "SELECT 1":
            return pd.DataFrame({"1": [1]})
        table = sql.split(" FROM ", 1)[1].split(" ", 1)[0]
        if (
            params is None
            or params.get("param_ts_code") != CN_SYMBOL
            or params.get("param_trade_date") != DAY
        ):
            return pd.DataFrame()
        if table == "stk_st_daily":
            return pd.DataFrame([{"type": "ST", "type_name": "ST"}])
        if table == "stk_limit":
            return pd.DataFrame([{"up_limit": ST_UP_LIMIT, "down_limit": ST_DOWN_LIMIT}])
        return pd.DataFrame()

    def limit_tables(self) -> set[str]:
        return {
            sql.split(" FROM ", 1)[1].split(" ", 1)[0]
            for sql, _ in self.queries
            if " FROM " in sql
        }


def _run_public(**seams: Any) -> str:
    return run_paper_trade_step(
        _payload(),
        loader=_loaders(),
        ch_client=None,
        calendar_client=OpenCalendar(),
        **seams,
    )


def _assert_document_shape(text: str, document: dict[str, Any], tokens: tuple[str, ...]) -> None:
    """No provenance token surfaces; frozen top-level keys; result schema valid."""
    raw = text.encode("utf-8")
    for token in tokens:
        assert token.encode("utf-8") not in raw
    assert b"limits:stk_limit" not in raw
    frozen_keys = set(json.loads((GOLDEN_DIR / "portfolio_explicit_cn_hk_us.json").read_bytes()))
    assert set(document) == frozen_keys
    schema = load_portfolio_contract_schema("result")
    assert list(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(document)
    ) == []


def test_public_st_connector_gives_five_percent_table_first_band(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given a reachable shared connector serving ST + ±5% table rows.
    connector = FakeSTConnector()
    monkeypatch.setattr(tool_module, "_default_cn_a_connector", lambda: connector)
    records = _spy_engine(monkeypatch)

    # When the PUBLIC portfolio entry runs with the default limits seam.
    text = _run_public()
    document = json.loads(text)

    # Then the connector was consulted for every limits table of the cn_a day.
    assert connector.limit_tables() == {
        "stk_limit", "stk_st_daily", "stk_suspend", "stk_limit_list_d"
    }
    assert all(
        params is not None
        and params["param_trade_date"] == DAY
        and params["param_ts_code"] == CN_SYMBOL
        for sql, params in connector.queries
        if " FROM " in sql
    )

    # Then only cn_a received a ClickHouseLimitsClient; hk/us stay None.
    by_market = {record["market"]: record["limits_client"] for record in records}
    assert isinstance(by_market["cn_a"], ClickHouseLimitsClient)
    assert by_market["hk"] is None
    assert by_market["us"] is None

    # Then the ST ±5% TABLE band (10.00 × 1.05 = 10.50, not 11.00) rejected
    # the +8% close, and the tokens were recorded engine-internally.
    cn = _cn_record(records)["outcome"]
    assert cn.fills == ()
    assert [(row.symbol, row.reason_code) for row in cn.rejected_orders] == [
        (CN_SYMBOL, "limit_up")
    ]
    assert f"up limit {ST_UP_LIMIT:.2f}" in cn.rejected_orders[0].detail
    assert f"{CN_SYMBOL}@{DAY}:{PROV_LIMITS_TABLE}" in cn.limit_provenance
    assert f"{CN_SYMBOL}@{DAY}:{PROV_ST_ROW}" in cn.limit_provenance

    # Then the document reports an ordinary incomplete rejection row.
    assert document["complete"] is False
    assert [
        (row["plan_order_id"], row["bucket_id"], row["reason_code"])
        for row in document["rejected_orders"]
    ] == [("cn-buy-1", "cn", "limit_up")]
    assert [fill["bucket_id"] for fill in document["fills"]] == ["hk", "us"]
    _assert_document_shape(text, document, cn.limit_provenance)


def test_public_no_connector_keeps_heuristic_and_document_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given the upstream offline default: the connector probe degrades to None.
    monkeypatch.setattr(tool_module, "_default_cn_a_connector", lambda: None)
    records = _spy_engine(monkeypatch)

    # When the public entry runs with the default limits seam.
    text = _run_public()
    document = json.loads(text)

    # Then every market received limits_client=None and the frozen is_st=False
    # heuristic filled the +8% close inside ±10% (an ST band would reject).
    assert all(record["limits_client"] is None for record in records)
    cn = _cn_record(records)["outcome"]
    assert f"{CN_SYMBOL}@{DAY}:{PROV_LIMITS_HEURISTIC}" in cn.limit_provenance
    assert not any("stk_limit" in token or "st:" in token for token in cn.limit_provenance)
    assert [(fill.symbol, fill.qty) for fill in cn.fills] == [(CN_SYMBOL, 100.0)]
    assert document["complete"] is True

    # Then an explicit None injection (no probe at all) is byte-identical, and
    # the document stays Decimal-canonical with no token surfaced.
    assert _run_public(limits_client=None) == text
    for fill in document["fills"]:
        assert isinstance(fill["price"], str)
        assert isinstance(fill["fee"], str)
    _assert_document_shape(text, document, cn.limit_provenance)


def test_public_injected_limits_client_passes_through_without_a_connector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given an injected limits client (the single-market-style test seam).
    fake = FakeCnALimitsClient(
        st=[{"type": "ST", "type_name": "ST"}],
        stk_limit=[{"up_limit": ST_UP_LIMIT, "down_limit": ST_DOWN_LIMIT}],
    )

    def _never() -> Any:
        raise AssertionError("offline injection must not build a connector")

    monkeypatch.setattr(tool_module, "_default_cn_a_connector", _never)
    records = _spy_engine(monkeypatch)

    # When the public entry runs with every seam injected.
    document = json.loads(_run_public(limits_client=fake))

    # Then the injected client passes through to cn_a only, is consulted, and
    # narrows the band to ±5% — no connector was ever built.
    assert {record["market"]: record["limits_client"] for record in records} == {
        "cn_a": fake, "hk": None, "us": None
    }
    assert fake.calls
    assert document["complete"] is False
    assert [
        (row["plan_order_id"], row["reason_code"]) for row in document["rejected_orders"]
    ] == [("cn-buy-1", "limit_up")]


def test_public_unreachable_connector_degrades_to_the_heuristic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given a connector module whose SELECT 1 probe raises (unreachable CH).
    attempts: list[int] = []

    class _UnreachableConnector:
        def __init__(self) -> None:
            attempts.append(1)

        def query(self, sql: str, params: dict[str, str] | None = None) -> pd.DataFrame:
            raise ConnectionError("clickhouse unreachable")

    fake_module = ModuleType("src.clickhouse_connector")
    fake_module.ClickHouseConnector = _UnreachableConnector
    monkeypatch.setitem(sys.modules, "src.clickhouse_connector", fake_module)
    records = _spy_engine(monkeypatch)

    # When the public entry runs the REAL shared probe (lazy import).
    text = _run_public()
    document = json.loads(text)

    # Then the probe ran once, degraded to None, and the step completed on the
    # frozen heuristic — no crash, no table/ST token, document shape intact.
    assert attempts == [1]
    assert all(record["limits_client"] is None for record in records)
    cn = _cn_record(records)["outcome"]
    assert f"{CN_SYMBOL}@{DAY}:{PROV_LIMITS_HEURISTIC}" in cn.limit_provenance
    assert document["complete"] is True
    assert [(fill.symbol, fill.qty) for fill in cn.fills] == [(CN_SYMBOL, 100.0)]
    _assert_document_shape(text, document, cn.limit_provenance)
