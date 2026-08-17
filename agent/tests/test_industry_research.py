"""Tests for the industry research aggregation boundary."""

from __future__ import annotations

import json

from src.research.industry_research import (
    IndustryResearchService,
    IndustryResearchStore,
    ReportSearchClient,
    _INDUSTRIES,
    _normalize_report,
)


def test_report_search_is_optional_without_api_key(monkeypatch) -> None:
    monkeypatch.delenv("IWENCAI_API_KEY", raising=False)
    records, status = ReportSearchClient().search("人形机器人 行业 研报")
    assert records == []
    assert status == "unavailable"


def test_reports_merge_sources_by_url_and_keep_richer_fields(monkeypatch, tmp_path) -> None:
    service = IndustryResearchService(IndustryResearchStore(tmp_path / "research.db"))
    base = _normalize_report({
        "title": "人形机器人产业链跟踪",
        "orgSName": "基础机构",
        "publishDate": "2026-08-15",
        "url": "https://example.test/report/1",
        "code": "688001.SH",
    }, "humanoid-robot", "a-stock-data")
    enhanced = _normalize_report({
        "title": "人形机器人产业链跟踪",
        "institution": "增强机构",
        "publish_time": "2026-08-15",
        "url": "https://example.test/report/1",
        "summary": "研报摘要",
        "rating": "增持",
        "target_price": "12.5",
    }, "humanoid-robot", "report-search")
    assert base is not None and enhanced is not None
    monkeypatch.setattr(service, "_a_share_reports", lambda *args, **kwargs: ([base], "ok"))
    monkeypatch.setattr(service.report_search, "search", lambda *args, **kwargs: ([enhanced], "ok"))

    result = service.reports("humanoid-robot")

    assert len(result["items"]) == 1
    item = result["items"][0]
    assert item["summary"] == "研报摘要"
    assert item["rating"] == "增持"
    assert item["target_price"] == 12.5
    assert item["source"] in {"a-stock-data", "report-search"}
    assert set(item["sources"]) == {"a-stock-data", "report-search"}


def test_validation_fills_every_humanoid_section(tmp_path) -> None:
    service = IndustryResearchService(IndustryResearchStore(tmp_path / "research.db"))
    evidence = [{"evidence_id": "ev_1", "evidence_type": "reports", "source": "a-stock-data", "payload": {}}]
    payload = service._validate_payload({}, evidence, _INDUSTRIES["humanoid-robot"])

    expected = {section["id"] for section in _INDUSTRIES["humanoid-robot"]["sections"]} - {"overview", "reports"}
    assert {section["section_id"] for section in payload["sections"]} == expected
    assert payload["overview"]["conclusion"]["summary"] == "当前数据不足，无法形成可靠判断。"
    assert all(section["financial_judgment"]["summary"] == "当前数据不足，无法形成可靠判断。" for section in payload["sections"])


def test_sqlite_store_restores_analysis(tmp_path) -> None:
    store = IndustryResearchStore(tmp_path / "research.db")
    job_id = store.create_job("humanoid-robot", "test-model")
    payload = {"industry_id": "humanoid-robot", "overview": {"conclusion": "ok"}}
    store.save(job_id, "humanoid-robot", payload, [{"evidence_id": "ev_1", "evidence_type": "reports", "source": "a-stock-data", "payload": {"ok": True}}])
    store.update_job(job_id, "ready", 100, "done")

    restored = store.get_job(job_id)
    assert restored is not None
    assert restored["status"] == "ready"
    assert restored["analysis"] == payload
    assert json.loads(json.dumps(restored["analysis"], ensure_ascii=False)) == payload


def test_reports_are_cached_for_the_local_day(tmp_path) -> None:
    service = IndustryResearchService(IndustryResearchStore(tmp_path / "research.db"))
    base = _normalize_report({
        "title": "人形机器人行业日报",
        "publishDate": "2026-08-16",
        "url": "https://example.test/report/daily",
    }, "humanoid-robot", "a-stock-data")
    assert base is not None
    calls = {"base": 0, "search": 0}

    def fetch_base(*args, **kwargs):
        calls["base"] += 1
        return [base], "ok"

    def fetch_search(*args, **kwargs):
        calls["search"] += 1
        return [], "unavailable"

    service._a_share_reports = fetch_base
    service.report_search.search = fetch_search

    first = service.reports("humanoid-robot", days=90, limit=10)
    second = service.reports("humanoid-robot", days=90, limit=10)

    assert first["items"] and second["items"]
    assert calls == {"base": 1, "search": 1}
    cached = service.store.get_report_cache("humanoid-robot", 90)
    assert cached is not None
    assert cached["reports"][0]["title"] == "人形机器人行业日报"
    assert cached["refreshed_date"]


def test_industry_catalogue_is_persisted_and_restored(tmp_path) -> None:
    store = IndustryResearchStore(tmp_path / "research.db")
    store.save_industries([{
        "id": "sector-test-catalogue",
        "name": "测试行业",
        "description": "行业目录测试",
        "demand": "测试需求",
        "segments": ["环节A"],
        "upstream": ["上游A"],
        "sections": [{"id": "overview", "label": "总览"}],
        "market": {"board_code": "BKTEST"},
    }])

    restored = store.get_industries()

    assert restored[0]["id"] == "sector-test-catalogue"
    assert restored[0]["segments"] == ["环节A"]
    assert restored[0]["market"]["board_code"] == "BKTEST"
    assert store.get_industry_refresh_date()


def test_industry_search_understands_sector_language_without_exact_name(tmp_path) -> None:
    service = IndustryResearchService(IndustryResearchStore(tmp_path / "research.db"))
    service._ensure_live_industries = lambda: None

    result = service.list_industries("机器人产业链", limit=10)

    assert result["items"]
    assert result["items"][0]["id"] == "humanoid-robot"


def test_industry_search_creates_dynamic_query_template_without_hardcoded_catalogue(monkeypatch, tmp_path) -> None:
    from src.tools.iwencai_tool import IWenCaiSearchTool

    monkeypatch.setattr(
        IWenCaiSearchTool,
        "execute",
        lambda self, **kwargs: json.dumps({"ok": False, "error": "unavailable"}),
    )
    service = IndustryResearchService(IndustryResearchStore(tmp_path / "research.db"))
    service._ensure_live_industries = lambda: None
    service.report_search.search = lambda *args, **kwargs: ([], "unavailable")

    result = service.list_industries("农业", limit=10)

    assert result["search_mode"] == "semantic"
    assert result["items"]
    assert result["items"][0]["name"] == "农业"
    assert result["items"][0]["id"].startswith("sector-")
