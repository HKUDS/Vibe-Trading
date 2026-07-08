from __future__ import annotations

from examples.alpha_genesis_demos.high_turnover_cost_trap.runner import run_demo


def test_high_turnover_cost_trap_rejects_cost_blowup() -> None:
    result = run_demo(dry_run=True)

    assert result["snapshot_match"]
    assert result["decision"] == "reject"
    assert result["hard_failures"] == ["COST_EXCEEDS_ALPHA"]
