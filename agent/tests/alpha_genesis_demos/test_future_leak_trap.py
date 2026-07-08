from __future__ import annotations

from examples.alpha_genesis_demos.future_leak_trap.runner import run_demo


def test_future_leak_trap_rejects_lookahead() -> None:
    result = run_demo(dry_run=True)

    assert result["snapshot_match"]
    assert result["decision"] == "reject"
    assert result["hard_failures"] == ["LOOKAHEAD_DETECTED"]
