"""Regression tests for Tencent A-share bar endpoint selection."""

from __future__ import annotations

from src import a_share_data


class _Response:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self._payload


class _TextResponse:
    def __init__(self, text: str) -> None:
        self.text = text

    def raise_for_status(self) -> None:
        pass


def test_tencent_minute_bars_use_mkline_and_preserve_intraday_timestamp(monkeypatch) -> None:
    calls: list[dict] = []

    def fake_get(url, **kwargs):
        calls.append({"url": url, **kwargs})
        return _Response({
            "data": {
                "sh600519": {
                    "m1": [
                        ["202608141459", "1490", "1491", "1492", "1489", "100"],
                        ["202608170931", "1500", "1501", "1502", "1499", "120"],
                    ],
                },
            },
        })

    monkeypatch.setattr(a_share_data, "throttled_get", fake_get)

    rows = a_share_data.tencent_bars("600519.SH", "2026-08-17", "2026-08-18", period="1m")

    assert calls[0]["url"] == a_share_data._TENCENT_MINUTE_KLINE_URL
    assert calls[0]["params"] == {"param": "sh600519,m1,,320"}
    assert calls[0]["headers"]["Referer"] == "https://gu.qq.com/"
    assert rows == [{
        "trade_date": "2026-08-17 09:31",
        "open": 1500.0,
        "close": 1501.0,
        "high": 1502.0,
        "low": 1499.0,
        "volume": 120.0,
        "source": "tencent",
    }]


def test_tencent_daily_bars_keep_fqkline_endpoint(monkeypatch) -> None:
    calls: list[dict] = []

    def fake_get(url, **kwargs):
        calls.append({"url": url, **kwargs})
        return _Response({
            "data": {
                "sh600519": {
                    "day": [["2026-08-17", "1500", "1501", "1502", "1499", "120"]],
                },
            },
        })

    monkeypatch.setattr(a_share_data, "throttled_get", fake_get)

    rows = a_share_data.tencent_bars("600519.SH", "2026-08-17", "2026-08-18", period="1d")

    assert calls[0]["url"] == a_share_data._TENCENT_KLINE_URL
    assert calls[0]["params"]["param"] == "sh600519,day,2026-08-17,2026-08-18,500,qfq"
    assert rows[0]["trade_date"] == "2026-08-17"


def test_ths_historical_intraday_bars_parse_all_sessions(monkeypatch) -> None:
    calls: list[dict] = []

    def fake_get(url, **kwargs):
        calls.append({"url": url, **kwargs})
        return _TextResponse(
            'quotebridge_v6_line_hs_600519_30_last36000({"total":2,"data":{"hs_600519":{"data":"202608141430,1490,1492,1488,1491,100,0;202608171030,1491,1495,1490,1494,120,0;"}}});'
        )

    monkeypatch.setattr(a_share_data, "throttled_get", fake_get)

    rows = a_share_data.ths_bars("600519.SH", "2026-08-01", "2026-08-18", period="30m")

    assert calls[0]["url"].endswith("/hs_600519/30/last36000.js")
    assert [row["trade_date"] for row in rows] == ["2026-08-14 14:30", "2026-08-17 10:30"]
    assert rows[0]["high"] == 1492.0


def test_eastmoney_stock_news_falls_back_to_sina_stock_feed(monkeypatch) -> None:
    class Response:
        def __init__(self, *, text: str = "", payload: dict | None = None) -> None:
            self.text = text
            self._payload = payload

        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return self._payload or {}

    def fake_get(url, **kwargs):
        if url == a_share_data._EM_SEARCH_URL:
            return Response(text='{"result":{"passportWeb":{}}}')
        assert url == a_share_data._SINA_STOCK_NEWS_URL
        return Response(payload={
            "result": {"data": {"feed": {"list": [{
                "rich_text": "贵州茅台发布经营公告",
                "create_time": "2026-08-17 10:00:00",
                "docurl": "https://finance.sina.cn/news/1",
                "ext": '{"stocks":[{"market":"cn","symbol":"sh600519","key":"贵州茅台"}]}'
            }]}}}
        })

    monkeypatch.setattr(a_share_data, "throttled_get", fake_get)

    rows = a_share_data.eastmoney_stock_news("600519.SH", limit=1)

    assert rows == [{
        "title": "贵州茅台发布经营公告",
        "content": "贵州茅台发布经营公告",
        "time": "2026-08-17 10:00:00",
        "source": "新浪财经",
        "url": "https://finance.sina.cn/news/1",
    }]


def test_eastmoney_stock_news_requests_article_results(monkeypatch) -> None:
    calls: list[dict] = []

    class TextResponse:
        text = 'jQuery_news({"result":{"cmsArticleWebOld":[{"title":"<b>贵州茅台</b>","content":"news","date":"2026-08-17 10:00:00","mediaName":"Eastmoney","url":"https://example.test/news"}]}})'

        def raise_for_status(self) -> None:
            pass

    def fake_get(url, **kwargs):
        calls.append({"url": url, **kwargs})
        return TextResponse()

    monkeypatch.setattr(a_share_data, "throttled_get", fake_get)

    rows = a_share_data.eastmoney_stock_news("600519.SH", limit=1)

    assert calls[0]["params"]["cb"] == ""
    assert calls[0]["params"]["_"] == "0"
    assert rows[0]["title"] == "贵州茅台"


def test_eastmoney_reports_only_requests_and_returns_the_last_year(monkeypatch) -> None:
    calls: list[dict] = []

    class ReportResponse:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {
                "data": [
                    {"title": "Recent report", "publishDate": "2026-08-17 09:00:00"},
                    {"title": "Old report", "publishDate": "2025-08-16 09:00:00"},
                ],
                "TotalPage": 1,
            }

    def fake_get(url, **kwargs):
        calls.append({"url": url, **kwargs})
        return ReportResponse()

    monkeypatch.setattr(a_share_data, "throttled_get", fake_get)

    rows = a_share_data.eastmoney_reports("600519.SH", limit=20)

    assert [row["title"] for row in rows] == ["Recent report"]
    assert calls[0]["params"]["beginTime"] == "2025-08-17"
    assert calls[0]["params"]["endTime"] == "2026-08-17"
