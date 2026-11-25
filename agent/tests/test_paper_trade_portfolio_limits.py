"""Internal cn_a limits-client threading through the portfolio execution chain.

``run_portfolio_step(limits_clients=...)`` must reach the legacy engine's
existing table-first limits mechanism for cn_a buckets only (hk/us never look
up cn_a limits, mirroring the tool-level ``_resolve_clients`` semantics). An
ST table row narrows the main-board band to ±5%; the provenance tokens stay
engine-internal at ``MatchOutcome.limit_provenance`` and never surface in the
portfolio document. Without a client the frozen board heuristic (is_st=False)
is unchanged. Observation seam: a wrapper around ``engine.run_day_loop`` (the
same monkeypatch seam the step/execution suites use) records the injected
client and the returned outcome per market.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from jsonschema import Draft202012Validator, FormatChecker

from src.tools.paper_trade import engine
from src.tools.paper_trade.limits_cn_a import (
    PROV_LIMITS_HEURISTIC,
    PROV_LIMITS_TABLE,
    PROV_ST_ROW,
)
from src.tools.paper_trade.portfolio import run_portfolio_step
from src.tools.paper_trade.portfolio.schema import load_portfolio_contract_schema
from tests.paper_trade_portfolio_fixture import valid_portfolio_payload

TRADE_DATE = date(2026, 11, 13)
DAY = TRADE_DATE.isoformat()
PRIOR = date(2026, 11, 12).isoformat()
CN_SYMBOL = "600519.SH"
GOLDEN_DIR = Path(__file__).parent / "fixtures" / "paper_trade" / "golden"

# Prior close 10.00 → target close 10.80 (+8%): inside the main-board ±10%
# heuristic band [9.00, 11.00] but outside the ST ±5% band [9.50, 10.50],
# so the terminal outcome itself discriminates which band the engine used.
CN_PRIOR_CLOSE = 10.0
CN_TARGET_CLOSE = 10.8
ST_UP_LIMIT = 10.5
ST_DOWN_LIMIT = 9.5


class FakeLoader:
    """Offline loader double; the step must never reach a network provider."""

    def __init__(self, frames: dict[str, pd.DataFrame], name: str) -> None:
        self.name = name
        self.frames = frames

    def is_available(self) -> bool:
        return True

    def fetch(self, codes, start_date, end_date, *, interval="1D", fields=None):
        return {code: self.frames[code] for code in codes if code in self.frames}


class OpenCalendar:
    def get_trade_calendar(self, start_date: str, end_date: str) -> pd.DataFrame:
        rows = [
            {
                "exchange": "SSE",
                "cal_date": day.strftime("%Y-%m-%d"),
                "is_open": 1,
                "pretrade_date": "",
            }
            for day in pd.date_range(start_date, end_date)
        ]
        return pd.DataFrame(
            rows,
            columns=["exchange", "cal_date", "is_open", "pretrade_date"],
        )


class FakeCnALimitsClient:
    """Canned per-table rows with a call spy (table-first consultation proof)."""

    def __init__(
        self,
        *,
        st: list[dict] | None = None,
        stk_limit: list[dict] | None = None,
    ) -> None:
        self._st = st or []
        self._stk_limit = stk_limit or []
        self.calls: list[tuple[str, str, str]] = []

    def _frame(self, table: str, trade_date: str, ts_code: str, rows: list[dict]) -> pd.DataFrame:
        self.calls.append((table, trade_date, ts_code))
        return pd.DataFrame(rows)

    def get_stk_limit(self, trade_date: str, ts_code: str) -> pd.DataFrame:
        return self._frame("stk_limit", trade_date, ts_code, self._stk_limit)

    def get_stk_st_daily(self, trade_date: str, ts_code: str) -> pd.DataFrame:
        return self._frame("stk_st_daily", trade_date, ts_code, self._st)

    def get_stk_suspend(self, trade_date: str, ts_code: str) -> pd.DataFrame:
        return self._frame("stk_suspend", trade_date, ts_code, [])

    def get_stk_limit_list(self, trade_date: str, ts_code: str) -> pd.DataFrame:
        return self._frame("stk_limit_list_d", trade_date, ts_code, [])


def _frame(prior: float, target: float) -> pd.DataFrame:
    records = [
        {"trade_date": day, "open": close, "high": close, "low": close,
         "close": close, "volume": 1000.0}
        for day, close in ((PRIOR, prior), (DAY, target))
    ]
    frame = pd.DataFrame(records)
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    return frame.set_index("trade_date")[["open", "high", "low", "close", "volume"]]


def _loaders() -> dict[str, Any]:
    return {
        "cn_a": FakeLoader({CN_SYMBOL: _frame(CN_PRIOR_CLOSE, CN_TARGET_CLOSE)}, "cn-fixture"),
        "hk": FakeLoader({"00700.HK": _frame(410.0, 417.8)}, "hk-fixture"),
        "us": FakeLoader({"AAPL.US": _frame(340.0, 343.46)}, "us-fixture"),
    }


def _payload() -> dict[str, Any]:
    payload = json.loads(json.dumps(valid_portfolio_payload()))
    payload["fx_conversions"] = []
    payload["portfolio_state"]["buckets"][0]["cash"] = "200000.00"
    payload["portfolio_state"]["buckets"][0]["positions"][0]["avg_cost"] = "10.00"
    payload["orders"] = [
        {"order_id": "cn-buy-1", "bucket_id": "cn", "symbol": CN_SYMBOL,
         "currency": "CNY", "side": "buy", "qty": 100},
        {"order_id": "hk-buy-1", "bucket_id": "hk", "symbol": "00700.HK",
         "currency": "HKD", "side": "buy", "qty": 100},
        {"order_id": "us-buy-1", "bucket_id": "us", "symbol": "AAPL.US",
         "currency": "USD", "side": "buy", "qty": 10},
    ]
    return payload


def _run(payload: dict[str, Any], **kwargs: Any):
    return run_portfolio_step(
        payload,
        loaders=_loaders(),
        calendar_client=OpenCalendar(),
        **kwargs,
    )


def _spy_engine(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Wrap engine.run_day_loop, recording the injected client and outcome."""
    real_run = engine.run_day_loop
    records: list[dict[str, Any]] = []

    def recording(*args, **kwargs):
        outcome = real_run(*args, **kwargs)
        records.append(
            {
                "market": kwargs["market"],
                "limits_client": kwargs["limits_client"],
                "outcome": outcome,
            }
        )
        return outcome

    monkeypatch.setattr(engine, "run_day_loop", recording)
    return records


def _cn_record(records: list[dict[str, Any]]) -> dict[str, Any]:
    return next(record for record in records if record["market"] == "cn_a")


def _canonical(document) -> bytes:
    return json.dumps(
        document.model_dump(mode="json", by_alias=True, exclude_none=True),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _st_client() -> FakeCnALimitsClient:
    return FakeCnALimitsClient(
        st=[{"type": "ST", "type_name": "ST"}],
        stk_limit=[{"up_limit": ST_UP_LIMIT, "down_limit": ST_DOWN_LIMIT}],
    )


def test_st_table_client_gives_five_percent_band_and_engine_internal_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given an ST symbol whose +8% close is inside ±10% but outside ±5%.
    fake = _st_client()
    records = _spy_engine(monkeypatch)

    # When the step threads the cn_a limits client into the legacy engine.
    step = _run(_payload(), limits_clients={"cn_a": fake})
    document = step.document

    # Then the fake client was consulted table-first for the cn_a symbol-day.
    assert fake.calls, "the injected limits client was never consulted"
    assert {table for table, _, _ in fake.calls} == {
        "stk_limit", "stk_st_daily", "stk_suspend", "stk_limit_list_d"
    }
    assert all((day, symbol) == (DAY, CN_SYMBOL) for _, day, symbol in fake.calls)

    # Then only the cn_a bucket received the client; hk/us stay None.
    by_market = {record["market"]: record["limits_client"] for record in records}
    assert by_market == {"cn_a": fake, "hk": None, "us": None}

    # Then the ST ±5% table band (not main-board ±10%) rejected the buy:
    # 10.00 × 1.05 = 10.50, and the engine detail names that exact band.
    cn = _cn_record(records)["outcome"]
    assert cn.fills == ()
    assert [(row.symbol, row.reason_code) for row in cn.rejected_orders] == [
        (CN_SYMBOL, "limit_up")
    ]
    assert f"up limit {ST_UP_LIMIT:.2f}" in cn.rejected_orders[0].detail

    # Then the table/ST provenance tokens are recorded engine-internally.
    assert f"{CN_SYMBOL}@{DAY}:{PROV_LIMITS_TABLE}" in cn.limit_provenance
    assert f"{CN_SYMBOL}@{DAY}:{PROV_ST_ROW}" in cn.limit_provenance

    # Then the document reports the rejection as an ordinary incomplete row.
    assert document.complete is False
    assert [
        (row.plan_order_id, row.bucket_id, row.reason_code)
        for row in document.rejected_orders
    ] == [("cn-buy-1", "cn", "limit_up")]
    assert [fill.bucket_id for fill in document.fills] == ["hk", "us"]

    # Then the document shape is unchanged: no token surfaces, the top-level
    # keys equal the frozen golden's, and the result contract still validates.
    raw = _canonical(document)
    for token in cn.limit_provenance:
        assert token.encode("utf-8") not in raw
    assert b"limits:stk_limit" not in raw
    frozen_keys = set(json.loads((GOLDEN_DIR / "portfolio_explicit_cn_hk_us.json").read_bytes()))
    assert set(json.loads(raw)) == frozen_keys
    schema = load_portfolio_contract_schema("result")
    assert list(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(
            json.loads(raw)
        )
    ) == []


def test_st_flag_without_table_rows_narrows_the_heuristic_to_five_percent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given an ST table row but no stk_limit row (heuristic fallback path).
    fake = FakeCnALimitsClient(st=[{"type": "ST", "type_name": "ST"}])
    records = _spy_engine(monkeypatch)

    # When the step runs with the client.
    document = _run(_payload(), limits_clients={"cn_a": fake}).document

    # Then the ST flag narrows the heuristic band to ±5% (the frozen engine
    # heuristic alone cannot detect ST), rejecting the +8% close.
    cn = _cn_record(records)["outcome"]
    assert [(row.symbol, row.reason_code) for row in cn.rejected_orders] == [
        (CN_SYMBOL, "limit_up")
    ]
    assert f"up limit {ST_UP_LIMIT:.2f}" in cn.rejected_orders[0].detail
    assert f"{CN_SYMBOL}@{DAY}:{PROV_LIMITS_HEURISTIC}" in cn.limit_provenance
    assert f"{CN_SYMBOL}@{DAY}:{PROV_ST_ROW}" in cn.limit_provenance
    assert f"{CN_SYMBOL}@{DAY}:{PROV_LIMITS_TABLE}" not in cn.limit_provenance
    assert document.complete is False


def test_no_client_keeps_the_frozen_board_heuristic_and_document_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given the default no-client path (limits_clients omitted).
    records = _spy_engine(monkeypatch)

    # When the step runs twice.
    step = _run(_payload())
    repeated = _run(_payload())
    document = step.document

    # Then every market received limits_client=None and the cn_a band came
    # from the frozen is_st=False heuristic: the +8% close fills inside ±10%.
    assert all(record["limits_client"] is None for record in records)
    cn = _cn_record(records)["outcome"]
    assert f"{CN_SYMBOL}@{DAY}:{PROV_LIMITS_HEURISTIC}" in cn.limit_provenance
    assert not any("stk_limit" in token or "st:" in token for token in cn.limit_provenance)
    assert [(fill.symbol, fill.qty) for fill in cn.fills] == [(CN_SYMBOL, 100.0)]
    assert document.complete is True

    # Then the document stays Decimal-canonical and byte-deterministic.
    raw = _canonical(document)
    assert raw == _canonical(repeated.document)
    dumped = json.loads(raw)
    for fill in dumped["fills"]:
        assert isinstance(fill["price"], str)
        assert isinstance(fill["fee"], str)
    for bucket in dumped["end_portfolio"]["buckets"]:
        assert isinstance(bucket["cash"], str)


def test_hk_us_mapping_entries_never_receive_a_limits_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given a mapping that (incorrectly) carries hk/us entries too.
    fake = _st_client()
    records = _spy_engine(monkeypatch)

    # When the step runs.
    _run(_payload(), limits_clients={"cn_a": fake, "hk": fake, "us": fake})

    # Then cn_a-only semantics hold: hk/us never look up cn_a limits.
    by_market = {record["market"]: record["limits_client"] for record in records}
    assert by_market == {"cn_a": fake, "hk": None, "us": None}
    assert all(symbol == CN_SYMBOL for _, _, symbol in fake.calls)
