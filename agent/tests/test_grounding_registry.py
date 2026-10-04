"""The declared grounding-check registry (#1622)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.agent.grounding.ledger import GroundingLedger
from src.agent.grounding.registry import GROUNDING_CHECKS, GroundingCheck, GroundingRegistry


def test_registry_rejects_duplicate_names() -> None:
    registry = GroundingRegistry()
    check = GroundingCheck(name="dup", code="some_code", description="d", predicate=lambda ledger, content: [])
    registry.register(check)
    with pytest.raises(ValueError, match="duplicate grounding check"):
        registry.register(check)


def test_registry_walk_order_and_describe_are_stable() -> None:
    registry = GroundingRegistry()
    for name in ("b-check", "a-check"):
        registry.register(GroundingCheck(name=name, code=f"{name}_code", description="d", predicate=lambda l, c: []))
    assert [c.name for c, _ in registry.walk(None, "")] == ["b-check", "a-check"]
    assert [d["name"] for d in registry.describe()] == ["b-check", "a-check"]


def _ledger_with_locked_listed_identity(tmp_path: Path) -> GroundingLedger:
    ledger = GroundingLedger(run_dir=tmp_path, user_message="分析 GLD 并给出买入价")
    ledger.ingest_tool_result(
        tool_name="search_symbol",
        arguments={"query": "GLD"},
        result=json.dumps(
            {
                "ok": True,
                "source": "symbol_search",
                "data": {
                    "query": "GLD",
                    "count": 1,
                    "sources": {"yahoo": "ok"},
                    "candidates": [
                        {
                            "symbol": "GLD",
                            "market": "us",
                            "type": "listed_security",
                            "exchange": "ARCX",
                            "source": "yahoo",
                        }
                    ],
                },
            }
        ),
        call_id="resolve",
        success=True,
    )
    assert ledger.identity_status == "locked"
    return ledger


def test_migrated_check_fires_identically_through_the_gate(tmp_path: Path) -> None:
    """Golden pass for the first migrated check: same issue through both paths."""
    ledger = _ledger_with_locked_listed_identity(tmp_path)

    bad = ledger.validate_final_answer("GLD 仍是一家私人公司，建议观望。")
    assert "listed_identity_relabelled_private" in [str(issue.get("code")) for issue in bad.issues]

    direct = GROUNDING_CHECKS.run("listed-identity-relabelled-private", ledger, "GLD 仍是一家私人公司，建议观望。")
    assert [issue["code"] for issue in direct] == ["listed_identity_relabelled_private"]

    good = ledger.validate_final_answer("GLD 是上市 ETF，维持观察。")
    assert "listed_identity_relabelled_private" not in [str(issue.get("code")) for issue in good.issues]
    assert GROUNDING_CHECKS.run("listed-identity-relabelled-private", ledger, "GLD 是上市 ETF，维持观察。") == []


def test_migrated_check_is_silent_with_nothing_locked(tmp_path: Path) -> None:
    ledger = GroundingLedger(run_dir=tmp_path, user_message="随便聊聊")
    assert GROUNDING_CHECKS.run("listed-identity-relabelled-private", ledger, "这是一家私人公司。") == []


def test_names_for_codes_maps_back_in_registration_order() -> None:
    predicate = lambda ledger, content: []  # noqa: E731
    registry = GroundingRegistry()
    registry.register(GroundingCheck(name="b-check", code="shared_code", description="d", predicate=predicate))
    registry.register(GroundingCheck(name="a-check", code="other_code", description="d", predicate=predicate))
    registry.register(GroundingCheck(name="c-check", code="shared_code", description="d", predicate=predicate))
    assert registry.names_for_codes({"shared_code"}) == ["b-check", "c-check"]
    assert registry.names_for_codes({"shared_code", "other_code"}) == ["b-check", "a-check", "c-check"]
    assert registry.names_for_codes({"never_emitted"}) == []


def _recorded_validations(tmp_path: Path) -> list[dict[str, object]]:
    artifact = json.loads(
        (tmp_path / "artifacts" / "grounding_evidence.json").read_text(encoding="utf-8")
    )
    return artifact["validations"]


def test_fired_checks_name_the_declared_check_that_fired(tmp_path: Path) -> None:
    ledger = _ledger_with_locked_listed_identity(tmp_path)
    ledger.validate_final_answer("GLD 仍是一家私人公司，建议观望。")
    assert _recorded_validations(tmp_path)[-1]["fired_checks"] == ["listed-identity-relabelled-private"]


def test_fired_checks_stay_empty_when_only_inline_rules_fire(tmp_path: Path) -> None:
    ledger = _ledger_with_locked_listed_identity(tmp_path)
    result = ledger.validate_final_answer("GLD 现价 999.99 美元，建议买入。")
    assert result.issues
    assert _recorded_validations(tmp_path)[-1]["fired_checks"] == []


def test_fired_checks_empty_for_a_clean_answer(tmp_path: Path) -> None:
    ledger = _ledger_with_locked_listed_identity(tmp_path)
    ledger.validate_final_answer("GLD 是上市 ETF，维持观察。")
    assert _recorded_validations(tmp_path)[-1]["fired_checks"] == []


def _ledger_with_invalidated_identity(tmp_path: Path) -> GroundingLedger:
    """A failed resolution leaves identity invalidated (#1622 identity slice)."""
    ledger = GroundingLedger(run_dir=tmp_path, user_message="分析机器人ETF并给出买入价")
    ledger.ingest_tool_result(
        tool_name="search_symbol",
        arguments={"query": "机器人ETF"},
        result=json.dumps({"ok": False, "error": "timeout"}),
        call_id="resolve",
        success=False,
    )
    return ledger


def test_declared_checks_cover_identity_and_figure_slices_in_order() -> None:
    assert [d["name"] for d in GROUNDING_CHECKS.describe()] == [
        "listed-identity-relabelled-private",
        "identity-not-locked",
        "figures-block-malformed",
        "unsourced-symbol-figures",
    ]


def test_identity_not_locked_fires_identically_through_the_gate(tmp_path: Path) -> None:
    ledger = _ledger_with_invalidated_identity(tmp_path)
    answer = "机器人ETF 可以买入。"
    result = ledger.validate_final_answer(answer)
    assert "identity_not_locked" in [str(issue.get("code")) for issue in result.issues]
    direct = GROUNDING_CHECKS.run("identity-not-locked", ledger, answer)
    assert [issue["code"] for issue in direct] == ["identity_not_locked"]


def test_identity_not_locked_is_silent_once_locked(tmp_path: Path) -> None:
    ledger = _ledger_with_locked_listed_identity(tmp_path)
    assert GROUNDING_CHECKS.run("identity-not-locked", ledger, "GLD 是上市 ETF。") == []


def test_figures_block_malformed_fires_identically_through_the_gate(tmp_path: Path) -> None:
    ledger = GroundingLedger(run_dir=tmp_path, user_message="随便聊聊")
    answer = "一些文字\n\n```figures\n0.95 is my entry\n```"
    result = ledger.validate_final_answer(answer)
    assert "figures_block_malformed" in [str(issue.get("code")) for issue in result.issues]
    # The walk just stashed this answer's figure state on the ledger, which is
    # what a direct registry run reads.
    direct = GROUNDING_CHECKS.run("figures-block-malformed", ledger, answer)
    assert [issue["code"] for issue in direct] == ["figures_block_malformed"]


def test_unsourced_symbol_figures_fires_identically_through_the_gate(tmp_path: Path) -> None:
    ledger = _ledger_with_locked_listed_identity(tmp_path)
    answer = "GLD 维持观察。000858.SZ 现价 15.20 元，可以买入。"
    result = ledger.validate_final_answer(answer)
    assert "unsourced_symbol_figures" in [str(issue.get("code")) for issue in result.issues]
    direct = GROUNDING_CHECKS.run("unsourced-symbol-figures", ledger, answer)
    assert [issue["code"] for issue in direct] == ["unsourced_symbol_figures"]


def test_unsourced_symbol_figures_ignores_session_symbols(tmp_path: Path) -> None:
    ledger = _ledger_with_locked_listed_identity(tmp_path)
    answer = "GLD 现价 999.99 美元，建议买入。"
    ledger.validate_final_answer(answer)
    assert GROUNDING_CHECKS.run("unsourced-symbol-figures", ledger, answer) == []


def test_fired_checks_name_the_identity_and_figure_slices(tmp_path: Path) -> None:
    ledger = _ledger_with_invalidated_identity(tmp_path)
    ledger.validate_final_answer("机器人ETF 可以买入。")
    assert _recorded_validations(tmp_path)[-1]["fired_checks"] == ["identity-not-locked"]

    figure_ledger = GroundingLedger(run_dir=tmp_path / "figs", user_message="随便聊聊")
    figure_ledger.validate_final_answer("一些文字\n\n```figures\n0.95 is my entry\n```")
    artifact = json.loads(
        (tmp_path / "figs" / "artifacts" / "grounding_evidence.json").read_text(encoding="utf-8")
    )
    assert artifact["validations"][-1]["fired_checks"] == ["figures-block-malformed"]
