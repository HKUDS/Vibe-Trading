"""Offline contract tests for the paper-trade ledger reconciliation tool."""

from __future__ import annotations

import copy
import json

import pandas as pd
import pytest

CN_A_FEES = {
    "commission_rate": 0.00025,
    "commission_min": 5.0,
    "stamp_tax_sell": 0.0005,
    "transfer_fee": 0.00001,
}
HK_FEES = {
    "commission_rate": 0.0003,
    "commission_min": 3.0,
    "stamp_tax_rate": 0.001,
    "regulatory_levy_rate": 0.00003,
}
US_FEES = {
    "commission_per_share": 0.0049,
    "commission_min": 0.99,
    "sec_fee_rate": 0.0,
}
DAY = "2026-10-20"


def _tool():
    from src.tools.paper_trade_reconcile_tool import PaperTradeReconcileTool

    return PaperTradeReconcileTool()


def _document(**overrides):
    document = {
        "schema_version": "pt-v1.1",
        "tool": "paper_trade_step",
        "market": "cn_a",
        "effective_fee_model": dict(CN_A_FEES),
        "fills": [
            {
                "trade_date": DAY,
                "symbol": "600519.SH",
                "side": "buy",
                "qty": 100,
                "price": 10.0,
                "fee": 5.01,
                "reason": "",
            }
        ],
        "end_state": {
            "cash": 98994.99,
            "positions": [{"symbol": "600519.SH", "qty": 100, "avg_cost": 10.0}],
        },
        "nav_series": [
            {"date": DAY, "nav": 99994.99, "cash": 98994.99, "position_value": 1000.0}
        ],
    }
    document.update(overrides)
    return document


def _execute(document, account_state=None):
    return json.loads(
        _tool().execute(
            account_state=account_state or {"cash": 100000.0, "positions": []},
            result=document,
        )
    )


def test_valid_document_reconciles_without_issues() -> None:
    payload = _execute(_document())

    assert payload["status"] == "ok"
    assert payload["reconciled"] is True
    assert payload["issues"] == []
    assert payload["summary"] == {
        "fills_checked": 1,
        "nav_rows_checked": 1,
        "issue_count": 0,
    }
    assert payload["expected_end_state"]["cash"] == 98994.99
    assert payload["expected_end_state"]["positions"] == [
        {"symbol": "600519.SH", "qty": 100.0, "avg_cost": 10.0}
    ]
    assert any("position_value" in item for item in payload["not_verified"])


def test_future_additive_fields_do_not_weaken_ledger_checks() -> None:
    document = _document(schema_version="pt-v1.3")
    document["order_states"] = [{"order_id": "pt-0", "status": "held"}]
    document["canceled_orders"] = []

    payload = _execute(document)

    assert payload["reconciled"] is True
    assert payload["summary"]["fills_checked"] == 1


def test_reports_each_independent_mismatch_at_its_field() -> None:
    document = _document()
    document["fills"][0]["fee"] = 5.0
    document["end_state"]["cash"] = 1.0
    document["end_state"]["positions"][0]["avg_cost"] = 9.99
    document["nav_series"][0] = {
        "date": DAY,
        "nav": 1.0,
        "cash": 2.0,
        "position_value": 1000.0,
    }

    payload = _execute(document)
    issues = {issue["code"]: issue for issue in payload["issues"]}

    assert payload["reconciled"] is False
    assert issues["fee_mismatch"]["path"] == "fills[0].fee"
    assert issues["fee_mismatch"]["expected"] == 5.01
    assert issues["fee_mismatch"]["actual"] == 5.0
    assert issues["end_cash_mismatch"]["path"] == "end_state.cash"
    assert (
        issues["position_avg_cost_mismatch"]["path"]
        == "end_state.positions[600519.SH].avg_cost"
    )
    assert issues["nav_cash_mismatch"]["path"] == "nav_series[0].cash"
    assert issues["nav_identity_mismatch"]["path"] == "nav_series[0].nav"


def test_zero_fill_document_checks_end_state_and_nav_identity() -> None:
    document = _document(fills=[])
    document["end_state"] = {"cash": 100000.0, "positions": []}
    document["nav_series"] = [
        {"date": DAY, "nav": 100000.0, "cash": 100000.0, "position_value": 0.0}
    ]

    payload = _execute(document)

    assert payload["reconciled"] is True
    assert payload["summary"]["fills_checked"] == 0
    assert payload["summary"]["nav_rows_checked"] == 1


@pytest.mark.parametrize("residual", [0, 1, 100])
def test_liquidated_position_cannot_reappear_in_end_state(residual) -> None:
    initial = {
        "cash": 100.0,
        "positions": [
            {"symbol": "AAPL", "qty": 1, "avg_cost": 10.0},
        ],
    }
    document = _document(
        market="us",
        effective_fee_model=US_FEES,
        fills=[
            {
                "trade_date": DAY,
                "symbol": "AAPL",
                "side": "sell",
                "qty": 1,
                "price": 10.0,
                "fee": 0.99,
            }
        ],
        end_state={
            "cash": 109.01,
            "positions": (
                [{"symbol": "AAPL", "qty": residual, "avg_cost": 10.0}]
                if residual
                else []
            ),
        },
        nav_series=[
            {"date": DAY, "cash": 109.01, "position_value": 0.0, "nav": 109.01}
        ],
    )
    payload = _execute(document, initial)
    assert payload["reconciled"] is (residual == 0)
    assert payload["expected_end_state"]["positions"] == []
    if residual:
        assert {
            "code": "position_qty_mismatch",
            "path": "end_state.positions[AAPL].qty",
            "expected": 0.0,
            "actual": residual,
        } in payload["issues"]


def test_zero_initial_position_does_not_authorize_new_holdings() -> None:
    initial = {
        "cash": 100000.0,
        "positions": [
            {"symbol": "AAPL", "qty": 0, "avg_cost": 10.0},
        ],
    }
    document = _document(
        market="us",
        effective_fee_model=US_FEES,
        fills=[],
        end_state={
            "cash": 100000.0,
            "positions": [
                {"symbol": "AAPL", "qty": 1, "avg_cost": 10.0},
            ],
        },
        nav_series=[],
    )
    payload = _execute(document, initial)
    assert payload["reconciled"] is False
    assert "position_qty_mismatch" in {i["code"] for i in payload["issues"]}


@pytest.mark.parametrize(
    "sell_qty, expected_code",
    [(150, "t_plus_1_violation"), (250, "insufficient_position")],
)
def test_cn_a_sell_replay_distinguishes_t_plus_one_from_oversell(
    sell_qty: int, expected_code: str
) -> None:
    document = _document()
    document["fills"].append(
        {
            "trade_date": DAY,
            "symbol": "600519.SH",
            "side": "sell",
            "qty": sell_qty,
            "price": 10.0,
            "fee": 5.0,
            "reason": "",
        }
    )
    document["end_state"] = {"cash": 0.0, "positions": []}
    document["nav_series"] = []

    payload = _execute(
        document,
        {
            "cash": 100000.0,
            "positions": [{"symbol": "600519.SH", "qty": 100, "avg_cost": 9.0}],
        },
    )
    codes = {issue["code"] for issue in payload["issues"]}

    assert expected_code in codes
    assert "end_cash_mismatch" in codes


@pytest.mark.parametrize(
    "market, fees, initial_cash, expected_cash",
    [
        ("hk", HK_FEES, 10000.0, 7994.94),
        ("us", US_FEES, 10000.0, 9799.01),
    ],
)
def test_hk_and_us_fee_schedules_are_replayed_independently(
    market: str, fees: dict[str, float], initial_cash: float, expected_cash: float
) -> None:
    document = _document(
        market=market,
        effective_fee_model=fees,
        end_state={"cash": expected_cash, "positions": []},
        nav_series=[],
    )
    document["fills"][0].update(
        {
            "symbol": "0700.HK" if market == "hk" else "AAPL",
            "qty": 100 if market == "hk" else 10,
            "price": 20.0,
            "fee": 5.06 if market == "hk" else 0.99,
        }
    )
    document["end_state"]["positions"] = [
        {
            "symbol": "0700.HK" if market == "hk" else "AAPL",
            "qty": 100 if market == "hk" else 10,
            "avg_cost": 20.0,
        }
    ]

    payload = _execute(document, {"cash": initial_cash, "positions": []})

    assert payload["reconciled"] is True
    assert payload["expected_end_state"]["cash"] == expected_cash
    assert payload["expected_end_state"]["positions"][0]["qty"] == (
        100.0 if market == "hk" else 10.0
    )


def test_duplicate_and_zero_end_position_rows_are_not_silently_merged() -> None:
    document = _document()
    document["end_state"]["positions"] = [
        {"symbol": "600519.SH", "qty": 100, "avg_cost": 10.0},
        {"symbol": "600519.SH", "qty": 0, "avg_cost": 10.0},
    ]

    payload = _execute(document)
    codes = {issue["code"] for issue in payload["issues"]}

    assert "duplicate_end_position" in codes
    assert "zero_end_position" in codes


def test_nonfinite_fill_is_contained_in_a_stable_error_envelope() -> None:
    document = _document()
    document["fills"][0]["price"] = float("inf")

    payload = _execute(document)

    assert payload["status"] == "error"
    assert payload["tool"] == "paper_trade_reconcile"
    assert "finite" in payload["error"]


def test_error_result_is_not_misreported_as_a_success_document() -> None:
    payload = _execute({"status": "error", "code": "INVALID_REQUEST"})

    assert payload["status"] == "error"
    assert "successful paper_trade_step" in payload["error"]


def test_tool_is_auto_discovered_as_readonly() -> None:
    from src.tools import build_registry

    tool = build_registry().get("paper_trade_reconcile")

    assert tool is not None
    assert tool.is_readonly is True


def test_mcp_wrapper_delegates_the_same_document() -> None:
    import mcp_server

    payload = json.loads(
        mcp_server.paper_trade_reconcile(
            account_state={"cash": 100000.0, "positions": []},
            result=_document(),
        )
    )

    assert payload["status"] == "ok"
    assert payload["reconciled"] is True


def test_reconciliation_is_byte_deterministic_for_unrelated_field_order() -> None:
    first = _document()
    second = copy.deepcopy(first)
    second["zzz_future_extension"] = {"b": 1, "a": 2}

    left = _tool().execute(
        account_state={"cash": 100000.0, "positions": []}, result=first
    )
    right = _tool().execute(
        account_state={"cash": 100000.0, "positions": []}, result=second
    )

    assert left == right


class _Loader:
    name = "tencent"

    def __init__(self, frame):
        self.frame = frame

    def is_available(self):
        return True

    def fetch(self, codes, start_date, end_date, *, interval="1D", fields=None):
        return {code: self.frame for code in codes if code == "600519.SH"}


class _Ch:
    def __init__(self, frame):
        self.frame = frame

    def get_bars(self, ts_code, start_date, end_date):
        return self.frame


class _Calendar:
    def get_trade_calendar(self, start_date, end_date):
        return pd.DataFrame(
            [
                {
                    "exchange": "SSE",
                    "cal_date": DAY,
                    "is_open": 1,
                    "pretrade_date": "2026-10-19",
                }
            ]
        )


def _price_frame(days):
    frame = pd.DataFrame(
        [
            {
                "trade_date": day,
                "open": 10.0,
                "high": 10.0,
                "low": 10.0,
                "close": 10.0,
                "volume": 1000,
            }
            for day in days
        ]
    )
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    return frame.set_index("trade_date")


@pytest.mark.parametrize("side", ["buy", "sell"])
def test_real_step_output_reconciles_end_to_end_offline(side) -> None:
    from src.tools.paper_trade.tool import run_paper_trade_step

    account_state = {"cash": 100000.0, "positions": []}
    if side == "sell":
        account_state["positions"] = [
            {"symbol": "600519.SH", "qty": 100, "avg_cost": 9.0}
        ]
    result = json.loads(
        run_paper_trade_step(
            {
                "account_id": "pa_reconcile",
                "market": "cn_a",
                "account_state": account_state,
                "orders": [{"symbol": "600519.SH", "side": side, "qty": 100}],
                "from_date": DAY,
                "to_date": DAY,
                "fee_model": dict(CN_A_FEES),
            },
            loader=_Loader(_price_frame([DAY])),
            ch_client=_Ch(_price_frame(["2026-10-19"])),
            calendar_client=_Calendar(),
            limits_client=None,
        )
    )

    payload = _execute(result, account_state)

    assert payload["reconciled"] is True
    assert payload["issues"] == []
    assert payload["expected_end_state"] == result["end_state"]
    if side == "sell":
        result["end_state"]["positions"] = copy.deepcopy(account_state["positions"])
        mutated = _execute(result, account_state)
        assert mutated["reconciled"] is False
        assert "position_qty_mismatch" in {issue["code"] for issue in mutated["issues"]}
