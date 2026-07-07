"""Run the deterministic overfit best-trial trap demo."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

AGENT_ROOT = Path(__file__).resolve().parents[3]
if str(AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_ROOT))

from examples.irr_agl_demos.common import (  # noqa: E402
    BUILDER_NAME,
    VERIFIER_NAME,
    build_card_evidence,
    json_main,
    prepare_demo_context,
    record_trial_events,
    write_demo_summary,
)
from examples.irr_agl_demos.overfit_best_trial_trap import fixture  # noqa: E402


def run_demo(*, output_dir: Path | str | None = None, dry_run: bool = False) -> dict[str, Any]:
    """Run the demo and return a compact, JSON-safe summary."""
    del dry_run
    context = prepare_demo_context(output_dir, "overfit_best_trial_trap")
    ledger = fixture.trial_ledger()
    trial_event_refs = record_trial_events(context, fixture.RUN_ID, ledger["events"])
    built = build_card_evidence(
        context,
        research_card=fixture.research_card(),
        protocol=fixture.protocol(),
        scorecard=fixture.scorecard(),
        trial_ledger=ledger,
    )
    artifacts = built.artifacts
    result = {
        "demo": "overfit_best_trial_trap",
        "builder": BUILDER_NAME,
        "verifier": VERIFIER_NAME,
        "run_id": fixture.RUN_ID,
        "trial_ledger": ledger,
        "selected_trial": fixture.selected_trial(),
        "claim_set": artifacts.claim_set.model_dump(mode="json"),
        "methodology_facts": artifacts.methodology_facts.model_dump(mode="json"),
        "scorecard": artifacts.scorecard.model_dump(mode="json"),
        "research_card": artifacts.research_card,
        "evidence_closure_report": built.report.model_dump(mode="json"),
        "artifact_refs": {
            "trial_events": trial_event_refs,
            "claim_set": artifacts.claim_set_artifact_id,
            "methodology_facts": artifacts.methodology_fact_artifact_id,
            "scorecard": artifacts.scorecard_artifact_id,
            "research_card": artifacts.research_card_artifact_id,
        },
    }
    write_demo_summary(context, result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Use isolated local demo stores only.")
    parser.add_argument("--output-dir", type=Path, default=None, help="Directory for local demo evidence.")
    args = parser.parse_args(argv)
    json_main(run_demo(output_dir=args.output_dir, dry_run=args.dry_run))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
