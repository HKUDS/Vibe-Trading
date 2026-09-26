"""Regression coverage for figures refs containing provider call-id separators."""

from src.agent.grounding.figures import parse_figures_block


def test_figures_ref_keeps_pipe_inside_call_id() -> None:
    block = parse_figures_block(
        "```figures\n"
        "2.96% | observed | VaR 95% | call_alpha|fc_beta::data.tail_risk.var_95\n"
        "```"
    )

    assert block.malformed == ()
    assert len(block.declarations) == 1
    assert block.declarations[0].ref == "call_alpha|fc_beta::data.tail_risk.var_95"
