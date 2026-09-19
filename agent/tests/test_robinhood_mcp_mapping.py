"""Robinhood reply mapping (#1428 / #1442): the one place that reads the nested shape.

Fixtures come from ``tests/robinhood_mcp_helpers.py``, which reproduces the
shapes posted on #1428. Each rejection case is a way a reply could be read as
something it is not: a first page as the whole account, a null list as an empty
account, an omitted cost as zero.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.trading import service
from src.trading.connectors.robinhood import mcp
from tests import robinhood_mcp_helpers as rh

pytestmark = pytest.mark.unit


def test_portfolio_summary_reads_the_nested_data_object() -> None:
    summary = mcp.portfolio_summary(rh.portfolio(total_value="1234.50", cash="200.00", buying_power="180.25"))

    assert summary == {
        "portfolio_value": "1234.50",
        "cash": "200.00",
        "buying_power": "180.25",
        "currency": "USD",
        "non_equity_values": {field: "0.00" for field in mcp.NON_EQUITY_VALUE_FIELDS},
    }


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"total_value": None}, "total_value is missing"),
        ({"total_value": "n/a"}, "total_value is not a number"),
        ({"total_value": "NaN"}, "total_value is not finite"),
        ({"currency": ""}, "currency is missing"),
    ],
)
def test_portfolio_summary_refuses_a_missing_or_unreadable_total(override: dict, message: str) -> None:
    envelope = rh.portfolio()
    envelope["structured_content"]["data"].update(override)

    with pytest.raises(mcp.RobinhoodShapeError, match=message):
        mcp.portfolio_summary(envelope)


def test_an_omitted_non_equity_value_is_unknown_not_zero() -> None:
    envelope = rh.portfolio()
    del envelope["structured_content"]["data"]["crypto_value"]

    assert mcp.portfolio_summary(envelope)["non_equity_values"]["crypto_value"] is None


def test_position_rows_map_symbol_quantity_and_cost() -> None:
    rows = mcp.position_rows(
        rh.positions(
            [
                rh.position("aapl", "10.5", average_buy_price="150.25"),
                rh.position("MSFT", "2", average_buy_price=None),
            ]
        )
    )

    assert rows == [
        {"symbol": "AAPL", "quantity": "10.5", "average_cost": "150.25", "broker_type": "unobserved"},
        {"symbol": "MSFT", "quantity": "2", "average_cost": None, "broker_type": "unobserved"},
    ]


def test_an_empty_position_list_is_a_complete_empty_account() -> None:
    assert mcp.position_rows(rh.positions([])) == []
    assert mcp.position_rows(rh.positions([], next_page="")) == []


@pytest.mark.parametrize(
    ("envelope", "message"),
    [
        (rh.positions(None), "no positions list"),
        (rh.positions([None]), r"positions\[0\] is not an object"),
        (rh.positions([rh.position("AAPL", "1")], next_page="cursor-2"), "more than one page"),
        (rh.envelope("get_equity_positions", {"positions": [], "total": "3"}), "unmapped data keys: total"),
        (rh.positions([{**rh.position("AAPL", "1"), "symbol": ""}]), "has no symbol"),
        (rh.positions([{**rh.position("AAPL", "1"), "quantity": "lots"}]), "quantity is not a number"),
        ({"status": "ok", "structured_content": {"guide": "no data"}}, "no data object"),
        ({"status": "error", "error": "token expired"}, "token expired"),
    ],
)
def test_position_rows_refuse_what_is_not_a_whole_account(envelope: dict, message: str) -> None:
    with pytest.raises(mcp.RobinhoodShapeError, match=message):
        mcp.position_rows(envelope)


def test_account_choices_keep_only_what_a_picker_shows() -> None:
    choices = mcp.account_choices(
        rh.accounts(
            [
                rh.account("5QR12345", nickname="Main", is_default=True),
                rh.account("5QR99887", agentic_allowed=False),
                {**rh.account("5QR55555"), "permanently_deactivated": True},
            ]
        )
    )

    assert choices == [
        {
            "account_ref": "5QR12345",
            "label": "Main ····2345",
            "is_default": True,
            "agentic_allowed": True,
            "deactivated": False,
        },
        {
            "account_ref": "5QR99887",
            "label": "individual ····9887",
            "is_default": False,
            "agentic_allowed": False,
            "deactivated": False,
        },
        {
            "account_ref": "5QR55555",
            "label": "individual ····5555",
            "is_default": False,
            "agentic_allowed": True,
            "deactivated": True,
        },
    ]


def test_account_choices_refuse_an_account_without_a_number() -> None:
    with pytest.raises(mcp.RobinhoodShapeError, match="has no account_number"):
        mcp.account_choices(rh.accounts([{**rh.account("5QR1"), "account_number": None}]))


def test_normalize_result_adds_the_view_and_keeps_the_raw_reply() -> None:
    envelope = rh.positions([rh.position("AAPL", "1")])

    normalized = mcp.normalize_result("positions", envelope)

    assert normalized["positions"][0]["symbol"] == "AAPL"
    assert normalized["structured_content"] is envelope["structured_content"]
    assert "mapping_error" not in normalized
    assert "positions" not in envelope  # the caller's reply is not mutated


def test_normalize_result_marks_an_unmappable_reply_instead_of_failing_the_read() -> None:
    normalized = mcp.normalize_result("positions", rh.positions([rh.position("AAPL", "1")], next_page="p2"))

    assert normalized["status"] == "ok"
    assert "positions" not in normalized
    assert "more than one page" in normalized["mapping_error"]


def test_normalize_result_leaves_error_envelopes_and_other_operations_alone() -> None:
    error = {"status": "error", "error": "boom"}
    quote = {"status": "ok", "data": {"anything": 1}}

    assert mcp.normalize_result("positions", error) is error
    assert mcp.normalize_result("quote", quote) is quote


def test_account_scoped_operations_send_account_number_and_accounts_sends_nothing() -> None:
    assert mcp.remote_arguments("positions", {"account": "5QR1"}) == {"account_number": "5QR1"}
    assert mcp.remote_arguments("account", {"account_number": "5QR1"}) == {"account_number": "5QR1"}
    assert mcp.remote_arguments("orders", {}) == {}
    assert mcp.remote_arguments("accounts", {"account": "5QR1"}) == {}


def test_trading_service_lists_accounts_through_get_accounts(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict]] = []
    server = SimpleNamespace(
        url="https://agent.robinhood.com/mcp/trading",
        enabled_tools=["get_accounts"],
        auth=SimpleNamespace(cache_dir="/tmp/vibe-token"),
    )

    class _Adapter:
        def __init__(self, server_name, server_config, **kwargs):  # noqa: ANN001
            assert kwargs == {"interactive_oauth": False}

        def call_tool(self, remote_name, arguments):  # noqa: ANN001
            calls.append((remote_name, dict(arguments)))
            return rh.accounts([rh.account("5QR12345", nickname="Main")])

    monkeypatch.setattr(
        "src.config.loader.load_agent_config", lambda: SimpleNamespace(mcp_servers={"robinhood": server})
    )
    monkeypatch.setattr("src.live.registry.has_cached_oauth_token", lambda *_: True)
    monkeypatch.setattr("src.tools.mcp.MCPServerAdapter", _Adapter)

    result = service.get_accounts("robinhood-live-mcp-readonly", interactive_oauth=False)

    assert calls == [("get_accounts", {})]
    assert result["accounts"][0]["account_ref"] == "5QR12345"
    assert result["profile_id"] == "robinhood-live-mcp-readonly"


def test_accounts_are_unsupported_off_remote_mcp() -> None:
    result = service.get_accounts("ibkr-paper-local")

    assert result["status"] == "error"
    assert "accounts.read" in result["error"]


def test_the_trading_profile_stays_first_for_the_broker_on_ramp() -> None:
    assert service.connector_profile_id_for_broker("robinhood") == "robinhood-live-mcp"
    assert service.live_runner_profile_for_broker("robinhood").id == "robinhood-live-mcp"
    assert service.runner_requires_account("robinhood") is True
    assert service.runner_requires_account("ibkr") is False
