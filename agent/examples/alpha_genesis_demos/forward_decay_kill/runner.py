from __future__ import annotations

from pathlib import Path

from examples.alpha_genesis_demos.shared_fixtures.factory import run_forward_decay_demo


def run_demo(*, dry_run: bool = True) -> dict:
    return run_forward_decay_demo(
        Path(__file__).with_name("expected_output.json"),
        dry_run=dry_run,
    )
