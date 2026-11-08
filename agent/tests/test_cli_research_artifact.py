"""CLI integration for versioned research artifacts."""

from __future__ import annotations

import argparse
import json

from src.research_artifacts.cli_handlers import add_subparser, dispatch


def _parser():
    parser = argparse.ArgumentParser()
    add_subparser(parser.add_subparsers(dest="command"))
    return parser


def _run(parser, capsys, *args):
    code = dispatch(parser.parse_args(list(args)))
    output = capsys.readouterr()
    return code, output.out, output.err


def test_cli_save_search_show_and_revision_round_trip(tmp_path, capsys):
    parser = _parser()
    db = str(tmp_path / "research.db")
    base = [
        "research-artifact",
        "--path",
        db,
        "save",
        "--subject",
        "NVDA fundamental review",
        "--content",
        "Original conclusion.",
        "--data-as-of",
        "2026-10-20",
        "--evidence",
        '[{"source_uri":"https://example.com/filing"}]',
        "--goal-id",
        "goal-a",
    ]
    code, out, _ = _run(parser, capsys, *base)
    first = json.loads(out)
    assert code == 0 and first["created"] is True

    code, out, _ = _run(parser, capsys, *base)
    assert code == 0 and json.loads(out)["created"] is False

    artifact_id = first["revision"]["artifact_id"]
    code, out, _ = _run(
        parser,
        capsys,
        "research-artifact",
        "--path",
        db,
        "save",
        "--artifact-id",
        artifact_id,
        "--content",
        "Updated conclusion.",
        "--data-as-of",
        "2026-10-27",
    )
    revised = json.loads(out)
    assert code == 0 and revised["revision"]["previous_revision_id"] == first["revision"]["revision_id"]

    code, out, _ = _run(
        parser,
        capsys,
        "research-artifact",
        "--path",
        db,
        "search",
        "--query",
        "Updated conclusion",
    )
    searched = json.loads(out)
    assert code == 0 and searched["count"] == 1

    code, out, _ = _run(parser, capsys, "research-artifact", "--path", db, "show", artifact_id)
    detail = json.loads(out)
    assert code == 0 and len(detail["revisions"]) == 2

    code, out, _ = _run(
        parser,
        capsys,
        "research-artifact",
        "--path",
        db,
        "revision",
        first["revision"]["revision_id"],
    )
    assert code == 0 and json.loads(out)["revision"]["content"] == "Original conclusion."

    code, out, _ = _run(
        parser,
        capsys,
        "research-artifact",
        "--path",
        db,
        "export",
        artifact_id,
        "--format",
        "json",
    )
    exported = json.loads(out)
    assert code == 0
    assert exported["filename"] == f"{artifact_id}.json"
    document = json.loads(exported["content"])
    assert document["revision_count"] == 2
    assert document["revisions"][0]["content"] == "Original conclusion."

    code, repeated, _ = _run(
        parser,
        capsys,
        "research-artifact",
        "--path",
        db,
        "export",
        artifact_id,
        "--format",
        "json",
    )
    assert code == 0 and repeated == out

    code, markdown, _ = _run(
        parser,
        capsys,
        "research-artifact",
        "--path",
        db,
        "export",
        artifact_id,
        "--format",
        "markdown",
    )
    assert code == 0
    assert "Updated conclusion." in markdown


def test_cli_compares_two_revisions(tmp_path, capsys):
    parser = _parser()
    db = str(tmp_path / "research.db")
    base = [
        "research-artifact",
        "--path",
        db,
        "save",
        "--subject",
        "NVDA fundamental review",
        "--content",
        "Original conclusion.",
        "--data-as-of",
        "2026-10-20",
    ]
    code, out, _ = _run(parser, capsys, *base)
    first = json.loads(out)["revision"]
    assert code == 0
    code, out, _ = _run(
        parser,
        capsys,
        "research-artifact",
        "--path",
        db,
        "save",
        "--artifact-id",
        first["artifact_id"],
        "--content",
        "Updated conclusion.",
        "--data-as-of",
        "2026-11-03",
    )
    revised = json.loads(out)["revision"]
    assert code == 0

    code, out, err = _run(
        parser,
        capsys,
        "research-artifact",
        "--path",
        db,
        "compare",
        first["artifact_id"],
        first["revision_id"],
        revised["revision_id"],
    )

    assert code == 0, err
    comparison = json.loads(out)["comparison"]
    assert comparison["from"]["revision_id"] == first["revision_id"]
    assert comparison["to"]["revision_id"] == revised["revision_id"]
    assert comparison["content"]["changed"] is True
    assert comparison["metadata"]["data_as_of"]["to"] == "2026-11-03"


def test_cli_reports_missing_artifact(tmp_path, capsys):
    parser = _parser()
    code, _, err = _run(
        parser,
        capsys,
        "research-artifact",
        "--path",
        str(tmp_path / "research.db"),
        "show",
        "ra_missing",
    )

    assert code == 1
    assert "not found" in err
