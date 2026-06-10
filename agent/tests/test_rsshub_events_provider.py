"""Unit tests for the RSSHub event/sentiment provider (no network)."""

from __future__ import annotations

import pandas as pd
import pytest

from backtest.loaders.rsshub_events import (
    EVENT_COLUMNS,
    FeedSpec,
    RSSHubEventProvider,
    UnknownFeedError,
    default_lexicon_scorer,
)

_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <title>Company beats earnings</title>
    <description>Q4 revenue surges on strong demand</description>
    <pubDate>Mon, 15 Jan 2024 09:00:00 +0000</pubDate>
  </item>
  <item>
    <title>Regulator opens probe</title>
    <description>probe into accounting, shares plunge</description>
    <pubDate>Tue, 16 Jan 2024 18:30:00 +0000</pubDate>
  </item>
</channel></rss>"""

# A billion-laughs payload: must be neutralised by defusedxml, never expanded.
_HOSTILE = """<?xml version="1.0"?>
<!DOCTYPE lolz [
  <!ENTITY lol "lol">
  <!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
  <!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">
]>
<rss version="2.0"><channel><item><title>&lol3;</title>
<pubDate>Mon, 15 Jan 2024 09:00:00 +0000</pubDate></item></channel></rss>"""


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text

    def raise_for_status(self) -> None:
        return None


class _FakeClient:
    """Minimal httpx.Client stand-in returning a fixed payload."""

    def __init__(self, payload: str) -> None:
        self.payload = payload
        self.calls: list[str] = []

    def get(self, url: str, timeout: float | None = None) -> _FakeResponse:
        self.calls.append(url)
        return _FakeResponse(self.payload)


def _provider(payload: str = _RSS) -> RSSHubEventProvider:
    return RSSHubEventProvider(
        "https://rsshub.local",
        feeds=[FeedSpec("news", "/stock/news/{code}", "sentiment")],
        client=_FakeClient(payload),
    )


def test_is_available_true_with_base_url() -> None:
    assert _provider().is_available() is True


@pytest.mark.parametrize("base", ["", "https://rsshub.example.com", "   "])
def test_is_available_false_without_real_base_url(base: str) -> None:
    assert RSSHubEventProvider(base, client=_FakeClient(_RSS)).is_available() is False


def test_query_events_schema_and_scoring() -> None:
    frame = _provider().query_events(["AAA"], as_of="2024-01-31")
    assert list(frame.columns) == list(EVENT_COLUMNS)
    assert set(frame["ts_code"]) == {"AAA"}
    assert (frame["event_type"] == "sentiment").all()

    by_summary = {row.summary: row.score for row in frame.itertuples()}
    bullish = next(s for t, s in by_summary.items() if "revenue" in t)
    bearish = next(s for t, s in by_summary.items() if "probe" in t)
    assert bullish > 0
    assert bearish < 0


def test_after_close_publication_rolls_to_next_day() -> None:
    frame = _provider().query_events(["AAA"], as_of="2024-01-31")
    dates = dict(zip(frame["summary"], frame["knowable_date"]))
    intraday = next(v for k, v in dates.items() if "revenue" in k)  # 09:00 -> same day
    after_close = next(v for k, v in dates.items() if "probe" in k)  # 18:30 -> next day
    assert intraday == pd.Timestamp("2024-01-15")
    assert after_close == pd.Timestamp("2024-01-17")


def test_point_in_time_filter_excludes_future_items() -> None:
    frame = _provider().query_events(["AAA"], as_of="2024-01-15")
    assert (frame["knowable_date"] <= pd.Timestamp("2024-01-15")).all()
    assert len(frame) == 1  # only the 09:00 item is knowable by the 15th


def test_duplicate_items_are_deduplicated() -> None:
    items = _RSS.split("<channel>")[1].split("</channel>")[0]
    doubled = f'<?xml version="1.0"?><rss version="2.0"><channel>{items}{items}</channel></rss>'
    frame = _provider(doubled).query_events(["AAA"], as_of="2024-01-31")
    assert len(frame) == 2  # 4 items in, 2 unique out
    assert frame.duplicated(subset=["ts_code", "knowable_date", "event_type", "summary"]).sum() == 0


def test_hostile_xml_is_neutralised() -> None:
    frame = _provider(_HOSTILE).query_events(["AAA"], as_of="2024-01-31")
    assert frame.empty


def test_unknown_feed_raises() -> None:
    with pytest.raises(UnknownFeedError):
        _provider().query_events(["AAA"], as_of="2024-01-31", feeds=["does_not_exist"])


def test_custom_scorer_override() -> None:
    frame = _provider().query_events(["AAA"], as_of="2024-01-31", scorer=lambda t, s: 0.5)
    assert (frame["score"] == 0.5).all()


def test_default_lexicon_scorer_bounds() -> None:
    assert default_lexicon_scorer("", "") == 0.0
    assert default_lexicon_scorer("neutral filler text", "") == 0.0
    assert -1.0 <= default_lexicon_scorer("loss plunge fraud", "") <= 0.0
    assert 0.0 <= default_lexicon_scorer("beat surge record", "") <= 1.0
