from __future__ import annotations

from examples.alpha_genesis_demos.forward_decay_kill.runner import run_demo


def test_forward_decay_kill_uses_append_only_observations() -> None:
    result = run_demo(dry_run=True)

    assert result["snapshot_match"]
    assert result["forward_status"] == "killed"
    assert result["observation_count"] == 3
    assert result["previous_hash_chained"]
