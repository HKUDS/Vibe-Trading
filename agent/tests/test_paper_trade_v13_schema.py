"""T12 gate — pt-v1.3 wire contract: ``order_states`` + ratio-covered fingerprints.

Pins the additive pt-v1.3 surface before T13 implements it (this file is the
failing contract test only):

* a ``fill_model="volume_share"`` call produces a ``pt-v1.3`` success document
  carrying the per-order lifecycle rows (``order_states``) and a 64-hex
  ``engine_fingerprint``;
* a ``pt-v1.2`` document never carries ``order_states`` and still rejects the
  pt-v1.3-only ``canceled_after_volume_cap`` cancel token;
* changing ONLY ``order_volume_ratio`` changes both ``received_state_hash``
  (AM-4-1: every non-order parameter joins the coverage object) and
  ``engine_fingerprint`` (GAP-8), while two identical pt-v1.2 calls keep the
  frozen v1.2 hash and fingerprint;
* every ``order_states`` row carries exactly the seven contract fields, a
  pinned cn_a session-open ``add_time``, ``price == 0.0`` when unfilled, and
  ``filled < amount`` for a partially filled order.

Every engine outcome comes from a real synthetic cn_a 5m ``volume_share`` run
(the ``_intraday``/``_FakeLoader`` pattern used by the other 5m suites); this
file imports no other test module, adds no fixture and touches no network.
The two v1.3 JSON contract files are T14's, not this file's.
"""

from __future__ import annotations

import re
from dataclasses import replace

import pandas as pd
import pytest

from src.tools.paper_trade import engine, state_hash, wire
from src.tools.paper_trade.data import fetch_market_data
from src.tools.paper_trade.schema import (
    CANCELED_REASON_CODE,
    SCHEMA_VERSION_V1_2,
    SCHEMA_VERSION_V1_3,
    CanceledOrder,
    PaperTradeStepResult,
    parse_request,
)

_DAY = "2026-10-20"
_PREV = "2026-10-19"
_SYM = "600519.SH"

#: The cn_a session open every pt-v1.3 ``order_states`` row is stamped with.
_ADD_TIME = f"{_DAY}T09:30:00+08:00"

#: pt-v1.3-only residual-cancel token, stated literally so a missing
#: implementation fails on behavior rather than on an import.
_CANCELED_VOLUME_CAP = "canceled_after_volume_cap"

_ORDER_STATE_KEYS = {"order_id", "status", "add_time", "amount", "filled", "price", "side"}
_FINGERPRINT_RE = re.compile(r"[0-9a-f]{64}")

#: transfer_fee pinned to 0 so each 100-share fill is exactly the ¥5 minimum.
_FEE_MODEL = {
    "commission_rate": 0.00025,
    "commission_min": 5.0,
    "stamp_tax_sell": 0.0005,
    "transfer_fee": 0.0,
}

_LABELS = ("09:35", "09:40")

# (open, high, low, close, volume)
Bar = tuple[float, float, float, float, float]


# ── synthetic cn_a 5m session (no committed fixture, no network) ─────────────


def _intraday(day: str, bars: tuple[Bar, ...]) -> pd.DataFrame:
    """On-grid continuous 5m bars; labels are bar ENDS (09:30 is the auction)."""
    records = [
        {
            "bar_time": f"{day} {label}",
            "open": bar[0],
            "high": bar[1],
            "low": bar[2],
            "close": bar[3],
            "volume": bar[4],
        }
        for label, bar in zip(_LABELS[: len(bars)], bars, strict=True)
    ]
    frame = pd.DataFrame(records)
    frame["bar_time"] = pd.to_datetime(frame["bar_time"])
    return frame.set_index("bar_time")


def _daily() -> pd.DataFrame:
    rows = [(_PREV, 10.00), (_DAY, 10.20)]
    frame = pd.DataFrame(
        [
            {
                "trade_date": day,
                "open": close,
                "high": close,
                "low": close,
                "close": close,
                "volume": 1000.0,
            }
            for day, close in rows
        ]
    )
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    return frame.set_index("trade_date")


def _partial_session() -> pd.DataFrame:
    """Session volume 1_000 across two bars; the first live reference is 10.00.

    Under ``order_volume_ratio=0.1`` the 300-share market order caps at
    ``floor(1000 x 0.1 / 100) x 100 = 100`` shares; the 100-share buy limit at
    9.50 is below every bar low, so it never triggers and is canceled at the
    session end.  The run therefore yields one partially filled order and one
    unfilled order.
    """
    return _intraday(
        _DAY,
        (
            (10.00, 10.00, 10.00, 10.00, 600.0),
            (10.20, 10.20, 10.20, 10.20, 400.0),
        ),
    )


class _FakeChClient:
    def get_bars(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        return pd.DataFrame()


class _FakeLoader:
    name = "tencent"

    def __init__(self, five: dict[str, pd.DataFrame]) -> None:
        self._daily = {_SYM: _daily()}
        self._five = five
        self.calls: list[tuple[tuple[str, ...], str, str, str]] = []

    def is_available(self) -> bool:
        return True

    def fetch(self, codes, start_date, end_date, *, interval="1D", fields=None):
        self.calls.append((tuple(codes), start_date, end_date, interval))
        source = self._five if interval == "5m" else self._daily
        return {code: source[code] for code in codes if code in source}


class _FakeCalendarClient:
    def __init__(self, open_days: frozenset[str]) -> None:
        self._open = open_days

    def get_trade_calendar(self, start_date: str, end_date: str) -> pd.DataFrame:
        rows = [
            {
                "exchange": "SSE",
                "cal_date": day.strftime("%Y-%m-%d"),
                "is_open": int(day.strftime("%Y-%m-%d") in self._open),
                "pretrade_date": "",
            }
            for day in pd.date_range(start_date, end_date)
        ]
        return pd.DataFrame(rows, columns=["exchange", "cal_date", "is_open", "pretrade_date"])


# ── harness ──────────────────────────────────────────────────────────────────


def _orders() -> list[dict]:
    return [
        {"symbol": _SYM, "side": "buy", "qty": 300},
        {"symbol": _SYM, "side": "buy", "qty": 100, "limit": 9.50},
    ]


def _payload(**overrides) -> dict:
    payload = {
        "account_id": "pa_v13_01",
        "market": "cn_a",
        "account_state": {"cash": 100000.0, "positions": []},
        "orders": _orders(),
        "from_date": _DAY,
        "to_date": _DAY,
        "fee_model": dict(_FEE_MODEL),
        "interval": "5m",
    }
    payload.update(overrides)
    return payload


def _run(**overrides) -> tuple[dict, object, engine.MatchOutcome]:
    """Parse a real request and match it against the synthetic 5m session."""
    payload = _payload(**overrides)
    request = parse_request(payload)
    market_data = fetch_market_data(
        "cn_a",
        [_SYM],
        _DAY,
        _DAY,
        loader=_FakeLoader({_SYM: _partial_session()}),
        ch_client=_FakeChClient(),
        interval="5m",
    )
    outcome = engine.match_orders(
        request,
        market_data=market_data,
        calendar_client=_FakeCalendarClient(frozenset({_DAY})),
    )
    assert outcome.error is None, f"unexpected engine error: {outcome.error!r}"
    return payload, request, outcome


def _assemble(payload: dict, request, outcome: engine.MatchOutcome) -> PaperTradeStepResult:
    return wire.assemble_result(request, outcome, raw_account_state=payload["account_state"])


def _v13_document(ratio: float = 0.1) -> tuple[dict, PaperTradeStepResult]:
    payload, request, outcome = _run(fill_model="volume_share", order_volume_ratio=ratio)
    result = _assemble(payload, request, outcome)
    return wire.build_success_payload(result), result


def _v13_order_rows() -> tuple[list[dict], tuple]:
    document, result = _v13_document()
    return document["order_states"], result.order_states


# ── v1.3 success document: order_states + a 64-hex fingerprint ──────────────


def test_v13_success_document_carries_order_states_and_a_64_hex_fingerprint() -> None:
    document, _ = _v13_document()

    assert document.get("schema_version") == SCHEMA_VERSION_V1_3 == "pt-v1.3", (
        "a volume_share call must resolve to a pt-v1.3 success document; got "
        f"schema_version={document.get('schema_version')!r}"
    )
    assert "order_states" in document, (
        "a pt-v1.3 success document must expose the per-order lifecycle rows; "
        f"the current tree ships keys {sorted(document)!r}"
    )
    rows = document["order_states"]
    assert isinstance(rows, list) and rows, (
        f"order_states must be a non-empty array for a matched order; got {rows!r}"
    )
    fingerprint = document.get("engine_fingerprint")
    assert isinstance(fingerprint, str) and _FINGERPRINT_RE.fullmatch(fingerprint), (
        "a pt-v1.3 document requires a 64-character lowercase hex "
        f"engine_fingerprint (D3); got {fingerprint!r}"
    )


def test_v13_document_fails_closed_without_a_64_hex_fingerprint() -> None:
    _, request, outcome = _run(fill_model="volume_share", order_volume_ratio=0.1)
    result = _assemble(_payload(fill_model="volume_share", order_volume_ratio=0.1), request, outcome)

    for broken in ("", "d" * 63, "D" * 64):
        with pytest.raises(ValueError, match="engine_fingerprint"):
            wire.build_success_payload(replace(result, engine_fingerprint=broken))


# ── v1.2 documents must stay untouched by the v1.3 additions ────────────────


def test_v12_document_never_carries_order_states() -> None:
    # interval="5m" alone selects pt-v1.2; the outcome still has lifecycle
    # rows, so their absence from the wire must be the version gate, not an
    # empty engine result.
    payload, request, outcome = _run()
    assert outcome.order_states, "the 5m engine must expose per-order states"
    result = _assemble(payload, request, outcome)
    assert result.schema_version == SCHEMA_VERSION_V1_2
    document = wire.build_success_payload(result)

    assert "order_states" not in document, (
        "order_states is a pt-v1.3 additive key; a pt-v1.2 document must not "
        f"carry it; got keys {sorted(document)!r}"
    )


def test_v12_document_rejects_the_volume_cap_cancel_reason() -> None:
    payload, request, outcome = _run()
    result = _assemble(payload, request, outcome)
    assert result.schema_version == SCHEMA_VERSION_V1_2
    poisoned = replace(
        result,
        canceled_orders=(
            CanceledOrder(
                trade_date=_DAY,
                symbol=_SYM,
                side="buy",
                qty=200.0,
                reason_code=_CANCELED_VOLUME_CAP,
                detail="volume cap reached; residual 200 canceled",
            ),
        ),
    )

    with pytest.raises(ValueError) as excinfo:
        wire.build_success_payload(poisoned)
    message = str(excinfo.value)
    assert "canceled reason_code" in message, (
        "a pt-v1.2 document accepting canceled_after_volume_cap must fail on "
        f"the frozen cancel token; got {message!r}"
    )
    assert _CANCELED_VOLUME_CAP in message, (
        f"the rejection must name the offending reason_code; got {message!r}"
    )


# ── the ratio is a covered parameter: hash + fingerprint must change ────────


def test_v13_received_state_hash_covers_the_order_volume_ratio() -> None:
    payload_a, request_a, outcome_a = _run(fill_model="volume_share", order_volume_ratio=0.1)
    payload_b, request_b, outcome_b = _run(fill_model="volume_share", order_volume_ratio=0.2)
    assert payload_a["orders"] == payload_b["orders"], "only the ratio may differ"

    hash_a = wire.received_state_hash_from_payload(payload_a)
    hash_b = wire.received_state_hash_from_payload(payload_b)
    assert hash_a is not None and hash_b is not None
    assert hash_a != hash_b, (
        "AM-4-1: every non-order parameter joins the coverage object, so a "
        "pt-v1.3 order_volume_ratio change must change received_state_hash; the "
        f"current tree hashes both ratios to {hash_a!r}"
    )

    result_a = _assemble(payload_a, request_a, outcome_a)
    result_b = _assemble(payload_b, request_b, outcome_b)
    assert result_a.received_state_hash != result_b.received_state_hash, (
        "the success document's received_state_hash must distinguish "
        f"order_volume_ratio=0.1 from 0.2; both are {result_a.received_state_hash!r}"
    )


def test_v13_engine_fingerprint_covers_the_order_volume_ratio() -> None:
    payload_a, request_a, outcome_a = _run(fill_model="volume_share", order_volume_ratio=0.1)
    payload_b, request_b, outcome_b = _run(fill_model="volume_share", order_volume_ratio=0.2)
    assert payload_a["orders"] == payload_b["orders"], "only the ratio may differ"

    fingerprint_a = _assemble(payload_a, request_a, outcome_a).engine_fingerprint
    fingerprint_b = _assemble(payload_b, request_b, outcome_b).engine_fingerprint
    assert _FINGERPRINT_RE.fullmatch(fingerprint_a), fingerprint_a
    assert _FINGERPRINT_RE.fullmatch(fingerprint_b), fingerprint_b
    assert fingerprint_a != fingerprint_b, (
        "GAP-8: two different volume policies must not share one engine "
        "fingerprint; order_volume_ratio=0.1 and 0.2 both fingerprint as "
        f"{fingerprint_a!r}"
    )


# ── v1.2 byte-compatibility: identical calls keep the frozen values ─────────


def test_v12_hash_and_fingerprint_are_unchanged_across_identical_calls() -> None:
    payload_a, request_a, outcome_a = _run()
    payload_b, request_b, outcome_b = _run()
    result_a = _assemble(payload_a, request_a, outcome_a)
    result_b = _assemble(payload_b, request_b, outcome_b)

    assert result_a.schema_version == SCHEMA_VERSION_V1_2
    assert result_a.received_state_hash == result_b.received_state_hash, (
        "two identical pt-v1.2 calls must not drift the received_state_hash"
    )
    assert result_a.engine_fingerprint == result_b.engine_fingerprint, (
        "two identical pt-v1.2 calls must not drift the engine_fingerprint"
    )
    assert result_a.engine_fingerprint == outcome_a.engine_fingerprint, (
        "a pt-v1.2 document must echo the engine-computed fingerprint"
    )

    # The v1.2 coverage object is the frozen AM-4-1 set plus the non-default
    # interval — adding ratio coverage for v1.3 must not touch this formula.
    manual = state_hash.state_hash(
        {
            "account_id": "pa_v13_01",
            "market": "cn_a",
            "account_state": payload_a["account_state"],
            "fee_model": state_hash.effective_fee_model("cn_a", dict(_FEE_MODEL)),
            "from_date": _DAY,
            "to_date": _DAY,
            "interval": "5m",
        }
    )
    assert result_a.received_state_hash == manual, (
        "a pt-v1.2 call must keep hashing exactly the frozen coverage object; "
        f"got {result_a.received_state_hash!r}, expected {manual!r}"
    )
    assert wire.received_state_hash_from_payload(payload_a) == manual, (
        "the pt-v1.2 error-path hash must use the same frozen coverage object"
    )


# ── order_states row shape (exactly seven fields) ───────────────────────────


def test_order_states_rows_have_exactly_the_seven_contract_fields() -> None:
    rows, states = _v13_order_rows()

    assert len(rows) == len(states) == 2, (
        f"the harness submits two orders, so the wire must expose two rows; got {rows!r}"
    )
    for row in rows:
        assert set(row) == _ORDER_STATE_KEYS, (
            "each pt-v1.3 order_states row must carry exactly "
            f"{sorted(_ORDER_STATE_KEYS)}; got {sorted(row)!r}"
        )
    assert [row["order_id"] for row in rows] == [state.order_id for state in states], (
        "order_states must preserve submission order and reuse the engine ids; "
        f"wire={[row['order_id'] for row in rows]!r}, "
        f"engine={[state.order_id for state in states]!r}"
    )
    assert [row["side"] for row in rows] == ["buy", "buy"]


def test_order_states_add_time_is_the_cn_a_session_open() -> None:
    rows, _ = _v13_order_rows()

    assert [row["add_time"] for row in rows] == [_ADD_TIME, _ADD_TIME], (
        "every pt-v1.3 order_states row must be stamped with the cn_a session "
        f"open {_ADD_TIME!r}; got {[row['add_time'] for row in rows]!r}"
    )
    assert all(re.fullmatch(r"\d{4}-\d{2}-\d{2}T09:30:00\+08:00", row["add_time"]) for row in rows)


def test_unfilled_order_state_reports_a_zero_price() -> None:
    rows, _ = _v13_order_rows()

    unfilled = [row for row in rows if row["filled"] == 0]
    assert len(unfilled) == 1, f"the limit buy never triggers, so one row is unfilled; got {rows!r}"
    row = unfilled[0]
    assert row["amount"] == 100.0, row
    assert row["price"] == 0.0, (
        "an unfilled order has no fill price, so order_states.price must be 0.0; "
        f"got {row['price']!r}"
    )


def test_partially_filled_order_state_reports_filled_below_amount() -> None:
    rows, _ = _v13_order_rows()

    partial = [row for row in rows if 0 < row["filled"] < row["amount"]]
    assert len(partial) == 1, (
        "the market order fills 100 of its 300 shares, so exactly one row must "
        f"report 0 < filled < amount; got {rows!r}"
    )
    row = partial[0]
    assert (row["amount"], row["filled"], row["price"]) == (300.0, 100.0, 10.00), (
        "the partial row must report the requested amount, the executed filled "
        f"quantity and the fill price; got {row!r}"
    )


# ── canceled_after_volume_cap is a pt-v1.3-only token ───────────────────────


def test_volume_cap_cancel_reason_is_accepted_only_by_a_v13_document() -> None:
    payload, request, outcome = _run(fill_model="volume_share", order_volume_ratio=0.1)
    assert [
        (cancel.qty, cancel.reason_code) for cancel in outcome.canceled_orders
    ] == [
        (200.0, _CANCELED_VOLUME_CAP),
        (100.0, CANCELED_REASON_CODE),
    ], "the run must emit the volume-cap residual cancel plus the day-end cancel"

    result = _assemble(payload, request, outcome)
    document = wire.build_success_payload(result)
    reasons = [row["reason_code"] for row in document["canceled_orders"]]

    assert _CANCELED_VOLUME_CAP in reasons, (
        "a pt-v1.3 document must serialize the volume-cap residual cancel; got "
        f"{reasons!r}"
    )
    assert _CANCELED_VOLUME_CAP != CANCELED_REASON_CODE, (
        "the volume-cap token must stay distinct from the frozen day-end token"
    )
