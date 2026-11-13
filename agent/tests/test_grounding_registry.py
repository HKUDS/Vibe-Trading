"""The declared grounding-check registry (#1622)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.test_grounding_figures_contract import HDR, HDR_ROW, _block, _ledger
from tests.test_grounding_role_hardening import MARKET_A, MARKET_C, _ledger as _multi_ledger

from evals.grounding.ledger import GroundingLedger
from evals.grounding.registry import GROUNDING_CHECKS, GroundingCheck, GroundingRegistry


def test_registry_rejects_duplicate_names() -> None:
    registry = GroundingRegistry()
    check = GroundingCheck(name="dup", code="some_code", description="d", predicate=lambda ledger, content: [])
    registry.register(check)
    with pytest.raises(ValueError, match="duplicate grounding check"):
        registry.register(check)


def test_registry_walk_order_and_describe_are_stable() -> None:
    registry = GroundingRegistry()
    for name in ("b-check", "a-check"):
        registry.register(GroundingCheck(name=name, code=f"{name}_code", description="d", predicate=lambda ledger, content: []))
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


def test_fired_checks_name_the_previously_inline_undeclared_rule(tmp_path: Path) -> None:
    ledger = _ledger_with_locked_listed_identity(tmp_path)
    result = ledger.validate_final_answer("GLD 现价 999.99 美元，建议买入。")
    assert result.issues
    assert _recorded_validations(tmp_path)[-1]["fired_checks"] == ["undeclared-figure"]


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
        "figure-symbol", "undeclared-figure", "figure-price-column",
        "figure-count", "figure-observed", "figure-derived", "figure-proposed", "figure-cited",
        "canonical-symbol-surfaced", "data-source-surfaced", "quote-currency-surfaced",
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


# One positive/negative answer pair for every catalog entry. Numeric fixtures
# use only the sparse two-bar ledger: dense frames can accidentally anchor bugs.

PAIRS = {
    "listed-identity-relabelled-private": ("listed", "GLD is a listed fund.", "GLD is a private company."),
    "identity-not-locked": ("identity", "GLD is a listed fund.", "机器人ETF 可以买入。"),
    "figures-block-malformed": ("market", HDR, HDR + "\n```figures\nbad row\n```"),
    "unsourced-symbol-figures": ("market", HDR, HDR + " 000858.SZ costs 15.20 CNY."),
    "figure-symbol": ("multi", "510300.SH akshare CNY close 3.912." + _block("3.912 | observed | 510300.SH close | c3"),
                      "159516.SZ akshare CNY close 3.912." + _block("3.912 | observed | 510300.SH close | c3")),
    "undeclared-figure": ("market", HDR + _block(HDR_ROW), HDR + " Value 0.777." + _block(HDR_ROW)),
    "figure-price-column": ("market", HDR + "\n| Close |\n|---|\n|0.666|" + _block(HDR_ROW),
                            HDR + "\n| Close |\n|---|\n|0.666|" + _block("0.666 | proposed | entry")),
    "figure-count": ("market", HDR + " Count 3.0." + _block(HDR_ROW, "3.0 | count | names"),
                     HDR + " Count 3.0 CNY." + _block(HDR_ROW, "3.0 | count | names")),
    "figure-observed": ("market", HDR + _block(HDR_ROW), HDR + " Price 0.777." + _block(HDR_ROW, "0.777 | observed | close | c1")),
    "figure-derived": ("market", HDR + " Result 0.099." + _block(HDR_ROW, "0.099 | derived | 0.666 - 0.567 | c1"),
                       HDR + " Result 0.123." + _block(HDR_ROW, "0.123 | derived | 0.666 - 0.567 | c1")),
    "figure-proposed": ("market", HDR + " Entry 0.950." + _block(HDR_ROW, "0.950 | proposed | entry"),
                        HDR + " Entry 9.950." + _block(HDR_ROW, "9.950 | proposed | entry")),
    "figure-cited": ("market", HDR + " Study score 1.8." + _block(HDR_ROW, "1.8 | cited | Study"),
                     HDR + " Score 1.8." + _block(HDR_ROW, "1.8 | cited | Study")),
    "canonical-symbol-surfaced": ("market", HDR, "akshare CNY close 0.666."),
    "data-source-surfaced": ("market", HDR, "159516.SZ CNY close 0.666."),
    "quote-currency-surfaced": ("market", HDR, "159516.SZ akshare close 0.666."),
}


def test_every_declared_check_has_a_fixture_pair():
    assert set(PAIRS) == {row["name"] for row in GROUNDING_CHECKS.describe()}
    assert {row["severity"] for row in GROUNDING_CHECKS.describe()} == {"block"}


@pytest.mark.parametrize("name", PAIRS)
def test_declared_check_fixture_pair(tmp_path, name):
    kind, good, bad = PAIRS[name]
    for failing, answer in [(False, good), (True, bad)]:
        path = tmp_path / str(failing)
        if kind == "identity" and failing:
            ledger = _ledger_with_invalidated_identity(path)
        elif kind in {"identity", "listed"}:
            ledger = _ledger_with_locked_listed_identity(path)
        elif kind == "multi":
            ledger = _multi_ledger(path, MARKET_A, MARKET_C)
        else:
            ledger = _ledger(path)
        verdict = ledger.validate_final_answer(answer)
        recorded = _recorded_validations(path)[-1]
        assert (name in recorded["fired_checks"]) is failing, recorded
        if not failing:
            assert verdict.valid, verdict.issues
        assert all(row["severity"] == "block" for row in recorded["check_findings"])


def test_shared_issue_codes_do_not_implicate_other_roles(tmp_path):
    ledger = _ledger(tmp_path)
    ledger.validate_final_answer(PAIRS["figure-derived"][2])
    assert _recorded_validations(tmp_path)[-1]["fired_checks"] == ["figure-derived"]
    ledger.validate_final_answer(HDR)
    assert _recorded_validations(tmp_path)[-1]["check_findings"] == []


def test_warning_and_log_findings_are_audited_without_blocking():
    from types import SimpleNamespace
    ledger = SimpleNamespace(_active_check_findings=[])
    registry = GroundingRegistry()
    for severity in ("warn", "log", "block"):
        registry.register(GroundingCheck(name=severity, code="fixture", description="d", severity=severity,
                                        predicate=lambda ledger, content: [{"code": "fixture"}]))
    assert registry.run_phase("manual", ledger, "answer") == [{"code": "fixture"}]
    assert [row["severity"] for row in ledger._active_check_findings] == ["warn", "log", "block"]
