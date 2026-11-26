"""Each financial task has a passing fixture and a deliberately wrong answer."""

import argparse
import json
from pathlib import Path

import pytest

from evals.harness.runner import load_case
from evals.harness.suite import case_paths, replay_run, replay_suite
from evals.harness.measurements import validate_measurements

RESEARCH_CASES = [key for key in case_paths() if key.startswith("research.")]


def _write(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def make_bundle(root, case):
    (root / "artifacts").mkdir(parents=True)
    _write(root / "req.json", {"prompt": case.prompt})
    _write(root / "state.json", {"status": "success"})
    _write(
        root / "llm_usage.json",
        {
            "totals": {"calls": 1, "input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            "per_iteration": [{"iter": 1, "input_tokens": 10, "output_tokens": 5, "total_tokens": 15}],
        },
    )
    records = [
        {"type": "start", "iter": 1, "prompt": case.prompt, "ts": 100.0},
        {"type": "message", "iter": 1, "role": "user", "content": case.prompt},
        {"type": "end", "iter": 1, "iterations": 1, "status": "success", "ts": 102.0},
    ]
    (root / "trace.jsonl").write_text("".join(json.dumps(row) + "\n" for row in records))
    from src.governance.manifest import build_run_manifest

    manifest = build_run_manifest(
        run_id="synthetic-verifier-fixture",
        timestamp="2026-11-07T00:00:00Z",
        system_prompt="synthetic verifier fixture",
        tool_names=[],
        package_versions={"fixture": "1"},
    )
    (root / "run_manifest.json").write_text(manifest.to_json())
    values = {}
    for entry in case.expect["measurements"]:
        target = values
        parts = entry["field"].split(".")
        for part in parts[:-1]:
            target = target.setdefault(part, {})
        target[parts[-1]] = entry.get("expected", 1)
    _write(root / "artifacts/task_result.json", values)
    return values


def _wrong_measurement(root, case, values):
    entry = case.expect["measurements"][0]
    target = values
    parts = entry["field"].split(".")
    for part in parts[:-1]:
        target = target[part]
    expected = entry.get("expected", 1)
    target[parts[-1]] = (
        not expected if type(expected) is bool else expected + 100 if type(expected) in (int, float) else "WRONG"
    )
    _write(root / "artifacts/task_result.json", values)


@pytest.mark.parametrize("identifier", RESEARCH_CASES)
def test_each_task_passes_then_rejects_incorrect_measurement(identifier, tmp_path, monkeypatch):
    # Any attempt to introduce network/model work into the offline verifier fails.
    import socket

    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: pytest.fail("offline replay tried network"))
    case = load_case(case_paths()[identifier])
    values = make_bundle(tmp_path, case)
    result = replay_run(tmp_path, [identifier])
    assert result["evaluation_status"] == "passed", result
    _wrong_measurement(tmp_path, case, values)
    assert replay_run(tmp_path, [identifier])["evaluation_status"] == "failed"


def test_missing_measurement_and_latency_are_not_a_pass(tmp_path):
    case = load_case(case_paths()[RESEARCH_CASES[0]])
    make_bundle(tmp_path, case)
    (tmp_path / "artifacts/task_result.json").unlink()
    result = replay_run(tmp_path, [case.case_id])
    assert result["evaluation_status"] == "not_evaluable"
    verdicts = result["reports"][0]["verdicts"]
    assert any(v["status"] == "NOT_EVALUABLE" and v["code"].startswith("financial.") for v in verdicts)


def test_prompt_is_not_rewritten_to_match_case_and_bindings_keep_distinct_runs(tmp_path):
    selected = [load_case(case_paths()[key]) for key in RESEARCH_CASES[:2]]
    bindings = []
    for i, case in enumerate(selected):
        root = tmp_path / str(i)
        make_bundle(root, case)
        bindings.append({"case_id": case.case_id, "run_dir": str(root)})
    assert replay_suite(bindings)["passed"]
    _write(Path(bindings[0]["run_dir"]) / "req.json", {"prompt": "changed request"})
    assert not replay_suite(bindings)["passed"]


@pytest.mark.parametrize(
    "outcomes, expected_status, expected_exit",
    [
        pytest.param(("passed", "passed"), "passed", 0, id="all-pass"),
        pytest.param(("not_evaluable",), "not_evaluable", 2, id="no-evidence"),
        pytest.param(("passed", "not_evaluable"), "not_evaluable", 2, id="partial-coverage"),
        pytest.param(("not_evaluable", "failed"), "failed", 1, id="actual-failure"),
        pytest.param(("failed", "invalid_artifact"), "invalid_artifact", 1, id="invalid-artifact"),
    ],
)
def test_batch_replay_reports_status_and_exit_code(tmp_path, capsys, outcomes, expected_status, expected_exit):
    from src.research_lab.cli import add_subparser, dispatch

    bindings = []
    for index, outcome in enumerate(outcomes):
        case = load_case(case_paths()[RESEARCH_CASES[index]])
        root = tmp_path / f"run-{index}"
        values = make_bundle(root, case)
        artifact = root / "artifacts/task_result.json"
        if outcome == "not_evaluable":
            artifact.unlink()
        elif outcome == "failed":
            _wrong_measurement(root, case, values)
        elif outcome == "invalid_artifact":
            artifact.write_text("{", encoding="utf-8")
        bindings.append({"case_id": case.case_id, "run_dir": str(root)})

    binding_file = tmp_path / "bindings.json"
    _write(binding_file, bindings)
    parser = argparse.ArgumentParser()
    add_subparser(parser.add_subparsers(dest="command"))
    args = parser.parse_args(["research-lab", "replay", "--bindings", str(binding_file), "--json"])
    exit_code = dispatch(args)
    report = json.loads(capsys.readouterr().out)

    assert [result["evaluation_status"] for result in report["results"]] == list(outcomes)
    assert exit_code == expected_exit
    assert report["evaluation_status"] == expected_status
    assert report["passed"] is (expected_exit == 0)
    assert report["case_count"] == len(outcomes)


@pytest.mark.parametrize(
    "entry",
    [
        {"artifact": "../escape.json", "field": "x", "operator": "finite"},
        {"artifact": "x.json", "field": "x", "operator": "approx", "expected": True},
        {"artifact": "x.json", "field": "x", "operator": "approx", "expected": float("nan")},
    ],
)
def test_invalid_numeric_contracts_fail_before_replay(entry):
    with pytest.raises(ValueError):
        validate_measurements([entry])


@pytest.mark.parametrize(
    ("bindings", "expected_fragment"),
    [
        ({}, "JSON array"),
        ({"case_id": "x", "run_dir": "/tmp/run"}, "JSON array"),
        ("not-a-list", "JSON array"),
        (123, "JSON array"),
        ([], "1 to 100"),
        ([{"case_id": "x", "run_dir": "/tmp/run"}] * 101, "1 to 100"),
        ([None], "binding[0]"),
        ([{"case_id": "x", "run_dir": "/tmp/run"}, None], "binding[1]"),
        ([{"case_id": "x"}], "binding[0].run_dir"),
        ([{"run_dir": "/tmp/run"}], "binding[0].case_id"),
        ([{"case_id": "", "run_dir": "/tmp/run"}], "binding[0].case_id"),
        ([{"case_id": 123, "run_dir": "/tmp/run"}], "binding[0].case_id"),
        ([{"case_id": "x", "run_dir": "   "}], "binding[0].run_dir"),
        ([{"case_id": "x", "run_dir": 123}], "binding[0].run_dir"),
        ([{"case_id": "x", "run_dir": "/tmp/run", "trace_dir": 123}], "binding[0].trace_dir"),
        ([{"case_id": "x", "run_dir": "/tmp/run", "trace_dir": ""}], "binding[0].trace_dir"),
    ],
)
def test_replay_suite_rejects_malformed_bindings(bindings, expected_fragment):
    with pytest.raises(ValueError, match=expected_fragment.replace("[", r"\[").replace("]", r"\]")):
        replay_suite(bindings)


def test_replay_suite_validates_all_bindings_before_running(monkeypatch):
    called = False

    def _fail_if_called(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("replay_run should not be invoked for invalid bindings")

    monkeypatch.setattr("evals.harness.suite.replay_run", _fail_if_called)
    with pytest.raises(ValueError, match=r"binding\[1\]\.run_dir"):
        replay_suite([{"case_id": "x", "run_dir": "/tmp/run"}, {"case_id": "y"}])
    assert not called
