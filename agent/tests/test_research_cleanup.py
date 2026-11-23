"""Runtime separation and the real sign-transcription regression."""

import json
from pathlib import Path
import subprocess
import sys

import pytest

from evals.harness.artifacts import ArtifactBundle
from evals.harness.assertions import evaluate_assertions
from evals.harness.measurements import measurement_verdicts
from evals.harness.schema import HarnessCase, VerdictStatus
from src.agent.instrument_identity import IdentityLedger

FIXTURE = Path(__file__).parent / "fixtures/research_output/collar_sign.json"


def test_research_runtime_does_not_load_offline_numeric_checks():
    # A fresh interpreter catches transitive imports hidden by the test runner.
    code = """
import sys
from src.agent.loop import AgentLoop
from src.swarm.worker import run_worker
assert not any(n.startswith(('evals.grounding', 'src.agent.grounding')) for n in sys.modules)
"""
    code = f"import sys; sys.path.insert(0, {str(Path(__file__).resolve().parents[1])!r})\n" + code
    subprocess.run([sys.executable, "-c", code], check=True)


def test_identity_ledger_has_no_answer_processing_interface(tmp_path):
    ledger = IdentityLedger(run_dir=tmp_path, user_message="Review SPY.US")
    assert ledger.authorized_symbols == {"SPY.US"}
    assert not (tmp_path / "artifacts/grounding_evidence.json").exists()
    payload = json.loads((tmp_path / "artifacts/identity_evidence.json").read_text())
    assert set(payload) == {"schema_version", "identity"}
    assert not any(
        hasattr(ledger, name)
        for name in (
            "validate_final_answer",
            "redacted_release",
            "correction_prompt",
            "repair_provenance",
            "safe_fallback",
            "streamable_length",
        )
    )


def test_harness_reads_current_identity_without_claiming_numeric_validation(tmp_path):
    IdentityLedger(run_dir=tmp_path, user_message="Review SPY.US")
    case = HarnessCase.from_dict(
        {
            "schema_version": 1,
            "case_id": "identity.current",
            "scenario": "identity",
            "prompt": "Review SPY.US",
            "expect": {
                "identity": {"status": "locked", "authorized_symbols": ["SPY.US"]},
                "evidence": {"forbidden_issue_codes": ["numeric_claim_conflict"]},
            },
        }
    )
    verdicts = evaluate_assertions(case, ArtifactBundle.load(tmp_path))
    identity = [v for v in verdicts if v.code.startswith("identity.")]
    assert identity and all(v.status == VerdictStatus.PASS for v in identity)
    assert all("identity_evidence.json" in v.evidence_refs[0] for v in identity)
    assert not any(v.status == VerdictStatus.PASS for v in verdicts if v.code.startswith("evidence."))


@pytest.mark.parametrize(
    "fixture_name",
    [
        "collar_sign.json",
        "gpd_scale_as_mean.json",
        "collar_scenario_arithmetic.json",
        "collar_cap_comparison.json",
        "scenario_price_label.json",
    ],
)
@pytest.mark.parametrize("rounding_control", [False, True])
def test_real_report_errors_are_offline_findings_only(tmp_path, fixture_name, rounding_control):
    fixture = json.loads(FIXTURE.with_name(fixture_name).read_text())
    claim = dict(fixture["claim"])
    if rounding_control:
        for entry in fixture["measurements"]:
            claim[entry["field"]] = round(entry["expected"], 1)
    path = tmp_path / "claims.json"
    path.write_text(json.dumps(claim))
    before = path.read_bytes()
    case = HarnessCase.from_dict(
        {
            "schema_version": 1,
            "case_id": fixture["case_id"],
            "scenario": "model_report_quality",
            "prompt": "",
            "expect": {
                "measurements": [
                    {
                        "artifact": "claims.json",
                        "operator": "approx",
                        "absolute_tolerance": 0.05,
                        **entry,
                    }
                    for entry in fixture["measurements"]
                ],
            },
        }
    )
    verdicts = measurement_verdicts(case, ArtifactBundle.load(tmp_path))
    expected = VerdictStatus.PASS if rounding_control else VerdictStatus.FAIL
    assert all(verdict.status == expected for verdict in verdicts)
    assert path.read_bytes() == before
