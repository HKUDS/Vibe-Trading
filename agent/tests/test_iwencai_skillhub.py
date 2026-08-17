"""Tests for the server-side Iwencai SkillHub subprocess bridge."""

from __future__ import annotations

import json
import subprocess

from src import iwencai_skillhub


def test_report_skill_cli_is_called_and_normalized(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("IWENCAI_API_KEY", "test-key")
    monkeypatch.setenv("IWENCAI_SKILL_ROOT", str(tmp_path))
    skill_script = tmp_path / "report-search" / "scripts" / "report_search.py"
    skill_script.parent.mkdir(parents=True)
    skill_script.write_text("", encoding="utf-8")
    payload = {
        "status_code": 0,
        "data": [{
            "id": "r1",
            "title": "Test report",
            "url": "https://example.test/report",
            "publish_date": "2026-08-17 00:00:00",
            "extra": {"organization": "Test Securities", "rating": "Buy"},
        }],
    }
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0, json.dumps(payload).encode(), b"")

    monkeypatch.setattr(iwencai_skillhub.subprocess, "run", fake_run)

    result = iwencai_skillhub.search_stock_reports("600519.SH", limit=20)

    assert result[0]["title"] == "Test report"
    assert result[0]["orgSName"] == "Test Securities"
    assert result[0]["publishDate"] == "2026-08-17 00:00:00"
    assert any("600519" in arg for arg in calls[0][0])
    assert any("近一年研报" in arg for arg in calls[0][0])
    assert calls[0][1]["env"]["IWENCAI_API_KEY"] == "test-key"


def test_news_skill_cli_emulates_page_pagination(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("IWENCAI_API_KEY", "test-key")
    monkeypatch.setenv("IWENCAI_SKILL_ROOT", str(tmp_path))
    skill_script = tmp_path / "news-search" / "scripts" / "news_search.py"
    skill_script.parent.mkdir(parents=True)
    skill_script.write_text("", encoding="utf-8")
    payload = {
        "status_code": 0,
        "data": [
            {"id": f"n{i}", "title": f"News {i}", "publish_date": "2026-08-17", "url": f"https://example.test/{i}"}
            for i in range(4)
        ],
    }

    monkeypatch.setattr(
        iwencai_skillhub.subprocess,
        "run",
        lambda args, **kwargs: subprocess.CompletedProcess(args, 0, json.dumps(payload).encode(), b""),
    )

    result = iwencai_skillhub.search_stock_news("600519.SH", page=2, page_size=2)

    assert [item["title"] for item in result] == ["News 2", "News 3"]


def test_search_results_remove_provider_duplicates(monkeypatch) -> None:
    report_rows = [
        {"id": "r1_0", "uid": "r1", "title": "Same report", "publish_date": "2026-08-17", "url": "https://example.test/r1"},
        {"id": "r1_2", "uid": "r1", "title": "Same report", "publish_date": "2026-08-17", "url": "https://example.test/r1"},
        {"id": "r2", "uid": "r2", "title": "Another report", "publish_date": "2026-08-16", "url": "https://example.test/r2"},
    ]
    news_rows = [
        {"id": "n1", "title": "Same news", "publish_date": "2026-08-17", "url": "https://example.test/n1"},
        {"id": "n2", "title": "Same news", "publish_date": "2026-08-17", "url": "https://example.test/n2"},
        {"id": "n3", "title": "Another news", "publish_date": "2026-08-17", "url": "https://example.test/n3"},
    ]

    def fake_run_skill(skill, query, *, size):
        return {"status_code": 0, "data": report_rows if skill == "report-search" else news_rows}

    monkeypatch.setattr(iwencai_skillhub, "_run_skill", fake_run_skill)

    reports = iwencai_skillhub.search_stock_reports("600519.SH", limit=20)
    news = iwencai_skillhub.search_stock_news("600519.SH", page_size=20)

    assert [item["title"] for item in reports] == ["Same report", "Another report"]
    assert [item["title"] for item in news] == ["Same news", "Another news"]
