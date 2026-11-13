"""Context-aware identity resolution without rewriting the user request."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from evals.grounding import GroundingLedger
from src.agent.resolution_context import ResolutionContext


def _resolver_payload(query: str, candidates: list[dict[str, Any]]) -> str:
    return json.dumps(
        {
            "ok": True,
            "source": "symbol_search",
            "data": {
                "query": query,
                "candidates": candidates,
                "sources": {"eastmoney": "ok", "yahoo": "ok"},
            },
        },
        ensure_ascii=False,
    )


def _hengrui_candidates() -> list[dict[str, Any]]:
    return [
        {
            "symbol": "600276.SH",
            "name": "恒瑞医药",
            "market": "cn",
            "source": "eastmoney",
        },
        {
            "symbol": "01276.HK",
            "name": "恒瑞医药",
            "market": "hk",
            "source": "eastmoney",
        },
    ]


def _ingest(
    ledger: GroundingLedger,
    query: str,
    candidates: list[dict[str, Any]],
    call_id: str = "resolve",
) -> None:
    ledger.ingest_tool_result(
        tool_name="search_symbol",
        arguments={"query": query},
        result=_resolver_payload(query, candidates),
        call_id=call_id,
        success=True,
    )


def test_explicit_a_share_context_locks_the_a_share_candidate(tmp_path: Path) -> None:
    message = "请分析A股恒瑞医药的最新财务情况"
    ledger = GroundingLedger(run_dir=tmp_path, user_message=message)

    _ingest(ledger, "恒瑞医药", _hengrui_candidates())

    assert ledger.resolution_context.raw_user_message == message
    assert ledger.authorized_symbols == {"600276.SH"}
    record = ledger.identity_summary()["records"][0]
    assert record["status"] == "locked"
    assert record["resolution_constraints"] == [
        {
            "dimension": "market",
            "value": "cn",
            "source_message_id": "current_user_message",
            "source_span": [3, 5],
            "explicit": True,
        }
    ]
    assert message not in json.dumps(record, ensure_ascii=False)
    artifact = (tmp_path / "artifacts" / "grounding_evidence.json").read_text()
    assert message not in artifact


def test_explicit_a_h_comparison_keeps_both_candidates(tmp_path: Path) -> None:
    ledger = GroundingLedger(
        run_dir=tmp_path,
        user_message="比较恒瑞医药 A/H 两地上市表现",
    )

    _ingest(ledger, "恒瑞医药", _hengrui_candidates())

    assert ledger.identity_status == "ambiguous"
    assert ledger.authorized_symbols == set()
    constraints = ledger.identity_summary()["records"][0]["resolution_constraints"]
    assert {item["value"] for item in constraints} == {"cn", "hk"}


def test_no_explicit_market_remains_fail_closed(tmp_path: Path) -> None:
    ledger = GroundingLedger(run_dir=tmp_path, user_message="分析恒瑞医药")

    _ingest(ledger, "恒瑞医药", _hengrui_candidates())

    assert ledger.identity_status == "ambiguous"
    assert ledger.authorized_symbols == set()


def test_explicit_us_market_in_english_locks_the_us_candidate(tmp_path: Path) -> None:
    ledger = GroundingLedger(
        run_dir=tmp_path,
        user_message="Analyze the US stock ABC",
    )
    candidates = [
        {"symbol": "ABC.US", "name": "ABC", "market": "us", "source": "yahoo"},
        {
            "symbol": "00123.HK",
            "name": "ABC",
            "market": "hk",
            "source": "eastmoney",
        },
    ]

    _ingest(ledger, "ABC", candidates)

    assert ledger.authorized_symbols == {"ABC.US"}


def test_negated_market_is_not_used_as_positive_authorization(tmp_path: Path) -> None:
    ledger = GroundingLedger(
        run_dir=tmp_path,
        user_message="不要看港股恒瑞医药",
    )

    _ingest(ledger, "恒瑞医药", _hengrui_candidates())

    assert ledger.identity_status == "ambiguous"
    assert ledger.authorized_symbols == set()


def test_constraint_mismatch_stays_fail_closed(tmp_path: Path) -> None:
    ledger = GroundingLedger(run_dir=tmp_path, user_message="只看A股恒瑞医药")

    _ingest(ledger, "恒瑞医药", [_hengrui_candidates()[1]])

    assert ledger.identity_status == "ambiguous"
    assert ledger.authorized_symbols == set()


def test_one_ambiguous_entity_does_not_retract_another_lock(tmp_path: Path) -> None:
    ledger = GroundingLedger(
        run_dir=tmp_path,
        user_message="A股恒瑞医药；比较 ABC A/H",
    )
    abc_candidates = [
        {"symbol": "600123.SH", "name": "ABC", "market": "cn", "source": "eastmoney"},
        {"symbol": "00123.HK", "name": "ABC", "market": "hk", "source": "eastmoney"},
    ]

    _ingest(ledger, "恒瑞医药", _hengrui_candidates(), "hengrui")
    _ingest(ledger, "ABC", abc_candidates, "abc")

    assert ledger.authorized_symbols == {"600276.SH"}
    assert (
        ledger.authorize_tool_call(
            "get_market_data",
            {"codes": ["600276.SH"]},
            batch_authorized_symbols=ledger.authorized_symbols,
            batch_identity_status=ledger.identity_status,
            call_id="prices",
        ).allowed
        is True
    )


def test_market_constraints_stay_attached_to_their_named_clause(tmp_path: Path) -> None:
    ledger = GroundingLedger(
        run_dir=tmp_path,
        user_message="我的持仓包括A股恒瑞医药，港股腾讯",
    )
    tencent_candidates = [
        {
            "symbol": "00700.HK",
            "name": "腾讯",
            "market": "hk",
            "source": "eastmoney",
        },
        {
            "symbol": "TCEHY.US",
            "name": "腾讯",
            "market": "us",
            "source": "yahoo",
        },
    ]

    _ingest(ledger, "恒瑞医药", _hengrui_candidates(), "hengrui")
    _ingest(ledger, "腾讯", tencent_candidates, "tencent")

    assert ledger.authorized_symbols == {"600276.SH", "00700.HK"}


def test_current_follow_up_constraint_applies_to_prior_subjects(tmp_path: Path) -> None:
    ledger = GroundingLedger(
        run_dir=tmp_path,
        user_message="都只看 A 股",
        history=[
            {"role": "user", "content": "比较恒瑞医药和药明康德"},
            {"role": "assistant", "content": "你希望看哪个市场？"},
        ],
    )
    wuxi_candidates = [
        {
            "symbol": "603259.SH",
            "name": "药明康德",
            "market": "cn",
            "source": "eastmoney",
        },
        {
            "symbol": "02359.HK",
            "name": "药明康德",
            "market": "hk",
            "source": "eastmoney",
        },
    ]

    _ingest(ledger, "恒瑞医药", _hengrui_candidates(), "hengrui")
    _ingest(ledger, "药明康德", wuxi_candidates, "wuxi")

    assert ledger.authorized_symbols == {"600276.SH", "603259.SH"}


def test_named_constraint_overrides_current_global_constraint(tmp_path: Path) -> None:
    ledger = GroundingLedger(
        run_dir=tmp_path,
        user_message="都只看A股，腾讯看港股",
    )
    candidates = [
        {"symbol": "00700.HK", "name": "腾讯", "market": "hk", "source": "eastmoney"},
        {"symbol": "TCEHY.US", "name": "腾讯", "market": "us", "source": "yahoo"},
    ]

    _ingest(ledger, "腾讯", candidates)

    assert ledger.authorized_symbols == {"00700.HK"}


def test_stale_global_history_does_not_authorize_a_new_turn(tmp_path: Path) -> None:
    ledger = GroundingLedger(
        run_dir=tmp_path,
        user_message="分析恒瑞医药",
        history=[{"role": "user", "content": "都只看港股"}],
    )

    _ingest(ledger, "恒瑞医药", _hengrui_candidates())

    assert ledger.identity_status == "ambiguous"
    assert ledger.authorized_symbols == set()


def test_named_history_constraint_can_follow_its_subject(tmp_path: Path) -> None:
    ledger = GroundingLedger(
        run_dir=tmp_path,
        user_message="继续分析",
        history=[{"role": "user", "content": "只看A股恒瑞医药"}],
    )

    _ingest(ledger, "恒瑞医药", _hengrui_candidates())

    assert ledger.authorized_symbols == {"600276.SH"}


def test_latest_named_history_constraint_wins(tmp_path: Path) -> None:
    ledger = GroundingLedger(
        run_dir=tmp_path,
        user_message="继续分析恒瑞医药",
        history=[
            {"role": "user", "content": "只看港股恒瑞医药"},
            {"role": "assistant", "content": "好的"},
            {"role": "user", "content": "改为A股恒瑞医药"},
        ],
    )

    _ingest(ledger, "恒瑞医药", _hengrui_candidates())

    assert ledger.authorized_symbols == {"600276.SH"}


def test_current_reset_discards_history_constraints(tmp_path: Path) -> None:
    ledger = GroundingLedger(
        run_dir=tmp_path,
        user_message="忽略之前的市场限制，分析恒瑞医药",
        history=[{"role": "user", "content": "只看港股恒瑞医药"}],
    )

    _ingest(ledger, "恒瑞医药", _hengrui_candidates())

    assert ledger.identity_status == "ambiguous"
    assert ledger.authorized_symbols == set()


def test_feature_flag_can_restore_previous_resolution_behavior(tmp_path: Path) -> None:
    ledger = GroundingLedger(
        run_dir=tmp_path,
        user_message="只看A股恒瑞医药",
        contextual_identity_constraints=False,
    )

    _ingest(ledger, "恒瑞医药", _hengrui_candidates())

    assert ledger.identity_status == "ambiguous"
    assert ledger.authorized_symbols == set()


@pytest.mark.parametrize(
    "message",
    ["分析NVDA股票", "分析 NVDA 股票", "比较NVDA和HOOD的表现", "compare NVDA/HOOD performance"],
)
def test_a_ticker_ending_in_a_is_not_a_market_constraint(tmp_path: Path, message: str) -> None:
    assert ResolutionContext.from_messages(message).constraints == ()
    ledger = GroundingLedger(run_dir=tmp_path, user_message=message)
    _ingest(ledger, "NVDA", [{"symbol": "NVDA.US", "name": "NVIDIA", "market": "us", "source": "yahoo"}])
    assert ledger.authorized_symbols == {"NVDA.US"}


@pytest.mark.parametrize(
    "message, expected",
    [
        ("请分析A股恒瑞医药", {"cn"}),
        ("看 A 股", {"cn"}),
        ("比较恒瑞医药 A/H 两地上市表现", {"cn", "hk"}),
        ("恒瑞医药A股/H股", {"cn", "hk"}),
        ("比较AH股溢价", {"cn", "hk"}),
    ],
)
def test_written_market_words_still_constrain(message: str, expected: set[str]) -> None:
    assert {c.value for c in ResolutionContext.from_messages(message).constraints} == expected
