from __future__ import annotations

from examples.alpha_genesis_demos.duplicate_public_alpha_trap.runner import run_demo


def test_duplicate_public_alpha_trap_rejects_duplicate() -> None:
    result = run_demo(dry_run=True)

    assert result["snapshot_match"]
    assert result["decision"] == "reject"
    assert result["hard_failures"] == ["DUPLICATE_ALPHA"]
