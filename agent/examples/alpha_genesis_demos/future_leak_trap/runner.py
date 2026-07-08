from __future__ import annotations

from pathlib import Path

from examples.alpha_genesis_demos.future_leak_trap.fixture import DEMO_ID
from examples.alpha_genesis_demos.shared_fixtures.factory import run_quality_demo


def run_demo(*, dry_run: bool = True) -> dict:
    return run_quality_demo(
        DEMO_ID,
        Path(__file__).with_name("expected_output.json"),
        dry_run=dry_run,
    )
