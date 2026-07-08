from __future__ import annotations

from src.alpha_foundry.reports.builder import build_alpha_genesis_report


def test_report_redacts_secret_like_values() -> None:
    report = build_alpha_genesis_report(
        report_id="report-secret",
        candidate_id="candidate-secret",
        source_config={
            "api_key": "sk-abc123",
            "token": "secret-token",
            "nested": {"broker_password": "pw"},
        },
    )

    payload = report.to_json()

    assert "sk-abc123" not in payload
    assert "secret-token" not in payload
    assert "pw" not in payload
    assert "[redacted]" in payload
