"""Case validation and safe artifact loading."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.harness.artifacts import ArtifactBundle
from evals.harness.schema import HarnessCase


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"schema_version": 2}, "schema_version"),
        ({"data_snapshot": "../private.json"}, "fixture tree"),
        ({"expect": {"execution": {"allowed": "success"}}}, "allowed"),
        ({"expect": {"budget": {"max_llm_calls": True}}}, "max_llm_calls"),
        (
            {"expect": {"risk": {"forbidden_successful_tools": [1]}}},
            "forbidden_successful_tools",
        ),
    ],
)
def test_invalid_case_contract_is_rejected(change: dict, message: str) -> None:
    base = {
        "schema_version": 1,
        "case_id": "case",
        "scenario": "scenario",
        "prompt": "prompt",
        "history": [],
        "data_snapshot": None,
        "expect": {"execution": {"allowed": ["success"]}},
    }
    base.update(change)
    with pytest.raises(ValueError, match=message):
        HarnessCase.from_dict(base)


def test_trace_loader_uses_only_latest_session_turn(artifact_dir: Path) -> None:
    path = artifact_dir / "trace.jsonl"
    current = path.read_text(encoding="utf-8")
    prior = [
        {"type": "start", "iter": 1, "prompt": "old"},
        {"type": "message", "iter": 1, "role": "user", "content": "old"},
        {"type": "end", "iter": 1, "iterations": 1, "status": "failed"},
    ]
    path.write_text(
        "".join(json.dumps(record) + "\n" for record in prior) + current,
        encoding="utf-8",
    )

    bundle = ArtifactBundle.load(artifact_dir)

    assert bundle.errors == {}
    assert bundle.trace[0]["type"] == "start"
    assert bundle.trace[0]["prompt"] != "old"
    assert [record["status"] for record in bundle.trace if record["type"] == "end"] == [
        "success"
    ]


def test_malformed_trace_is_reported_instead_of_silently_skipped(
    artifact_dir: Path,
) -> None:
    (artifact_dir / "trace.jsonl").write_text(
        '{"type":"start"}\n{bad json\n', encoding="utf-8"
    )

    bundle = ArtifactBundle.load(artifact_dir)

    assert bundle.trace == ()
    assert "trace.jsonl:2" in bundle.errors["trace"]


def test_trace_sidecar_cannot_escape_trace_directory(artifact_dir: Path) -> None:
    secret = artifact_dir.parent / "private.txt"
    secret.write_text("secret", encoding="utf-8")
    (artifact_dir / "trace.jsonl").write_text(
        json.dumps(
            {"type": "message", "role": "user", "content_path": "../private.txt"}
        )
        + "\n",
        encoding="utf-8",
    )

    bundle = ArtifactBundle.load(artifact_dir)

    assert bundle.trace == ()
    assert "escaped" in bundle.errors["trace"]
    assert "secret" not in bundle.errors["trace"]


def test_known_artifact_symlink_cannot_escape_run_directory(artifact_dir: Path) -> None:
    outside = artifact_dir.parent / "outside.json"
    outside.write_text(json.dumps({"prompt": "private"}), encoding="utf-8")
    (artifact_dir / "req.json").unlink()
    (artifact_dir / "req.json").symlink_to(outside)

    bundle = ArtifactBundle.load(artifact_dir)

    assert bundle.req is None
    assert "escaped" in bundle.errors["req"]
    assert '"prompt"' not in bundle.errors["req"]
