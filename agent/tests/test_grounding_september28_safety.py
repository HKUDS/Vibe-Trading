"""Safety boundaries while combining symbol, ref and locale fixes."""

from pathlib import Path

import pytest

from src.agent.grounding import GroundingLedger
from src.agent.grounding.figures import _numbers, _writes_decimal_commas, parse_figures_block


@pytest.mark.parametrize("prefix", ["0,", "0,1", "Values 0, 1"])
def test_ambiguous_zero_list_does_not_change_other_figures(prefix):
    text = prefix + "; observed price 5.165."
    assert not _writes_decimal_commas(text)
    assert _numbers(text)[-1].digits == "5.165"


@pytest.mark.parametrize(("written", "accepted"), [("0.82", False), ("0.825", True)])
def test_rounding_does_not_widen_the_existing_evidence_policy(tmp_path: Path, written, accepted):
    import json

    ledger = GroundingLedger(run_dir=tmp_path, user_message="Report the ratio")
    ledger.ingest_tool_result(
        tool_name="technical_indicators",
        arguments={},
        result=json.dumps({"ratio": 0.8246699017713774}),
        call_id="c1",
        success=True,
    )
    content = f"Ratio {written}.\n```figures\n0.8246699017713774 | observed | ratio | c1\n```"
    assert ledger.validate_final_answer(content).valid is accepted


def test_internal_pipe_in_ref_stays_exact():
    block = parse_figures_block("```figures\n| 1.57% | observed | risk | x1::data.var_95|scope |\n```")
    assert block.declarations[0].ref == "x1::data.var_95|scope"


def _two_symbol_metrics(tmp_path):
    import json

    ledger = GroundingLedger(run_dir=tmp_path, user_message="Report AAPL.US and MSFT.US metrics")
    for symbol, call_id, value in [("AAPL.US", "a", 0.0157), ("MSFT.US", "b", 0.0399)]:
        ledger.ingest_tool_result(
            tool_name="factor_analysis",
            arguments={"symbol": symbol},
            result=json.dumps({"status": "ok", "symbol": symbol, "var_95": value, "es_95": value + 0.01}),
            call_id=call_id,
            success=True,
        )
    return ledger


def test_field_ref_candidates_and_values_never_borrow_other_symbol(tmp_path):
    ledger = _two_symbol_metrics(tmp_path)
    assert ledger._tool_field_ref_candidates("factor_analysis::var_95", "AAPL.US") == ["a::var_95"]
    assert ledger._referenced("b::var_95", "AAPL.US", None) == ([], [])
    assert 0.0399 not in ledger._metric_pool("AAPL.US")


def test_candidate_corrections_are_scoped_to_claim_symbol(tmp_path):
    ledger = _two_symbol_metrics(tmp_path)
    result = ledger.validate_final_answer("AAPL.US risk 1.57%.")
    issue = next(issue for issue in result.issues if issue.get("reason") == "tail_risk_needs_field_ref")
    assert issue["field_ref_candidates"] == ["a::es_95", "a::var_95"]


def test_unframed_ref_ending_in_pipe_is_not_truncated():
    block = parse_figures_block("```figures\n1.57% | observed | risk | x1::data.risk|\n```")
    assert block.declarations[0].ref == "x1::data.risk|"


def test_pipe_field_requires_exact_call_when_values_disagree(tmp_path):
    import json

    ledger = GroundingLedger(run_dir=tmp_path, user_message="Report metrics")
    for call_id, value in [("a", 1.57), ("b", 3.99)]:
        ledger.ingest_tool_result(
            tool_name="technical_indicators",
            arguments={},
            result=json.dumps({"ratio|window": value}),
            call_id=call_id,
            success=True,
        )

    def check(ref):
        return ledger.validate_final_answer(f"Ratio 1.57.\n```figures\n1.57 | observed | ratio | {ref}\n```")

    assert check("a::ratio|window").valid
    assert not check("b::ratio|window").valid
    assert not check("ratio|window").valid


def test_multisymbol_call_does_not_attribute_unlabelled_analysis_to_one_symbol(tmp_path):
    from dataclasses import replace

    ledger = _two_symbol_metrics(tmp_path)
    # A mixed call has two explicit record identities but no per-metric identity.
    ledger._evidence.append(replace(ledger._evidence[-1], call_id="a"))
    assert not any(entry["call_id"] == "a" for entry in ledger._analysis_entries("AAPL.US"))
    # A truly symbol-less aggregate remains available.
    ledger._analysis_metrics.append({"call_id": "aggregate", "field": "var_95", "value": 0.055})
    assert any(entry["call_id"] == "aggregate" for entry in ledger._analysis_entries("AAPL.US"))
