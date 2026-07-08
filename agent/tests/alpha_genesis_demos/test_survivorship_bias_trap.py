from __future__ import annotations

from examples.alpha_genesis_demos.survivorship_bias_trap.runner import run_demo


def test_survivorship_bias_trap_caps_pit_contract_missing() -> None:
    result = run_demo(dry_run=True)

    assert result["snapshot_match"]
    assert result["decision"] == "research_only"
    assert result["hard_failures"] == ["PIT_CONTRACT_MISSING"]
