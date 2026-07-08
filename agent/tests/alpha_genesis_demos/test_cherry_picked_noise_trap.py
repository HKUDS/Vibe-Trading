from __future__ import annotations

from examples.alpha_genesis_demos.cherry_picked_noise_trap.runner import run_demo


def test_cherry_picked_noise_trap_warns_multiple_testing_proxy() -> None:
    result = run_demo(dry_run=True)

    assert result["snapshot_match"]
    assert result["decision"] == "research_only"
    assert "HIGH_PBO_PROXY" in result["warnings"]
