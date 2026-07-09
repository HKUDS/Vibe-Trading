from __future__ import annotations

import json
from pathlib import Path

from cli.alpha_genesis import main, render_report_file
from src.alpha_foundry.reports.builder import build_alpha_genesis_report


def test_cli_handles_corrupt_report_without_stack_or_absolute_path_leak(
    tmp_path: Path,
    capsys,
) -> None:  # noqa: ANN001
    report_path = tmp_path / "bad-report.json"
    report_path.write_text("{not-json", encoding="utf-8")

    code = main([str(report_path)])
    captured = capsys.readouterr()

    assert code == 1
    assert "invalid Alpha Genesis report" in captured.err
    assert "Traceback" not in captured.err
    assert str(report_path) not in captured.err


def test_cli_rejects_non_object_report_without_stack_trace(
    tmp_path: Path,
    capsys,
) -> None:  # noqa: ANN001
    report_path = tmp_path / "array-report.json"
    report_path.write_text("[]", encoding="utf-8")

    code = main([str(report_path)])
    captured = capsys.readouterr()

    assert code == 1
    assert "invalid Alpha Genesis report" in captured.err
    assert "Traceback" not in captured.err


def test_cli_rejects_incomplete_report_without_stack_trace(
    tmp_path: Path,
    capsys,
) -> None:  # noqa: ANN001
    report_path = tmp_path / "incomplete-report.json"
    report_path.write_text('{"schema_version":"alpha_genesis_report.v1"}', encoding="utf-8")

    code = main([str(report_path)])
    captured = capsys.readouterr()

    assert code == 1
    assert "invalid Alpha Genesis report" in captured.err
    assert "Traceback" not in captured.err
    assert str(report_path) not in captured.err


def test_cli_export_redacts_secret_like_report_metadata(tmp_path: Path) -> None:
    report = build_alpha_genesis_report(
        report_id="cli-redaction",
        candidate_id="candidate",
        source_config={"token": "secret-token", "api_key": "sk-secret"},
    )
    report_path = tmp_path / "report.json"
    report_path.write_text(report.to_json(), encoding="utf-8")

    rendered = render_report_file(report_path)

    assert "secret-token" not in rendered
    assert "sk-secret" not in rendered
    assert json.loads(rendered)["metadata"]["source_config"]["token"] == "[redacted]"
