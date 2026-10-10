"""portfolio_summary can read a stored snapshot by id."""

from __future__ import annotations

import json

from src.tools.portfolio_tool import PortfolioSummaryTool


def test_snapshot_id_reaches_the_service_and_an_unknown_id_fails_closed(monkeypatch):
    seen = []

    def fake_context(self, snapshot_id=None):
        seen.append(snapshot_id)
        return None if snapshot_id in {"gone", ""} else {"snapshot_id": snapshot_id or "latest-id"}

    monkeypatch.setattr("src.portfolio.service.PortfolioService.analysis_context", fake_context)
    tool = PortfolioSummaryTool()

    assert json.loads(tool.execute())["context"]["snapshot_id"] == "latest-id"
    assert json.loads(tool.execute(snapshot_id=" abc "))["context"]["snapshot_id"] == "abc"
    missing = json.loads(tool.execute(snapshot_id="gone"))
    blank = json.loads(tool.execute(snapshot_id="  "))

    assert seen == [None, "abc", "gone", ""]
    assert missing["status"] == "error"
    assert missing["error_code"] == "snapshot_not_found"
    assert blank["error_code"] == "snapshot_not_found"
    assert "snapshot_id" in PortfolioSummaryTool.parameters["properties"]
