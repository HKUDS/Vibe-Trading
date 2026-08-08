"""Tests for prediction_market_tool: validation, normalization, batch isolation.

All HTTP is mocked — no test ever reaches a live Polymarket endpoint. The tool
imports ``throttled_get_json`` from :mod:`backtest.loaders._http` into its own
namespace, so we monkeypatch that name on the ``prediction_market_tool`` module.

Fixture payloads mirror shapes captured from the live endpoints, including the
awkward parts: gamma serializes ``outcomes`` / ``outcomePrices`` /
``clobTokenIds`` as JSON strings, CLOB book sides arrive worst-price-first, and
``umaResolutionStatus`` is absent (not false) on markets with no oracle record.

The settlement suite below is anchored on live observations recorded in the
module docstring: a closed market carries no outcome information at all
(``outcomePrices == ["0", "0"]`` on 2020-era markets), an *open* market can
trade above the 0.99 floor, and a genuinely resolved market can pay
``["0.5", "0.5"]``. Those three are why ``closed`` and ``resolved`` are
separate fields.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

import pytest

from src.tools import prediction_market_tool
from src.tools.prediction_market_tool import PredictionMarketTool


def _open_market() -> Dict[str, Any]:
    """An unsettled binary market as gamma serializes it."""
    return {
        "id": "2774056",
        "question": "Strait of Hormuz traffic returns to normal by August 31?",
        "slug": "strait-of-hormuz-traffic-returns-to-normal-by-august-31",
        "conditionId": "0x60c2c085ee8c16bc8f2419739a94971d4c9d00f637ead10fc0f540afa1be64e8",
        "outcomes": '["Yes", "No"]',
        "outcomePrices": '["0.135", "0.865"]',
        "clobTokenIds": '["10542637382636993559560386066341160494159913021117602084303677886792771111733", '
        '"90869494087977018607792751230236923002303032923064138180950209430688758061828"]',
        "bestBid": 0.13,
        "bestAsk": 0.14,
        "lastTradePrice": 0.14,
        "spread": 0.01,
        "oneDayPriceChange": 0.015,
        "endDate": "2026-08-31T00:00:00Z",
        "closed": False,
        "active": True,
        "archived": False,
        # Live shape: present but null while no answer has reached the oracle.
        "umaResolutionStatus": None,
        # Populated on OPEN markets too — the resolver contract address, not
        # evidence that anything was resolved.
        "resolvedBy": "0x65070BE91477460D8A7AeEb94ef92fe056C2f2A7",
        "volumeNum": 6306835.903025,
        "liquidityNum": 627255.8635,
    }


def _closed_unresolved_market() -> Dict[str, Any]:
    """A pre-oracle closed market: trading over, outcome recorded nowhere.

    Mirrors gamma market 12 (``will-joe-biden-get-coronavirus-before-the-
    election``), closed since 2020 with ``outcomePrices == ["0", "0"]``.
    """
    return {
        "id": "12",
        "question": "Will Joe Biden get coronavirus before the election?",
        "conditionId": "0xe3b423df",
        "outcomes": '["Yes", "No"]',
        "outcomePrices": '["0", "0"]',
        "clobTokenIds": '["281824040059679406524954632285378409010556497262481904628549144165", '
        '"470448457534500220474364299688086011308111641315715496825417038661"]',
        "endDate": "2020-11-04T00:00:00Z",
        "closedTime": "2020-11-02 16:31:01+00",
        "closed": True,
        "active": True,
        "archived": False,
        "umaResolutionStatus": None,
    }


def _price_pinned_closed_market() -> Dict[str, Any]:
    """A closed market with a pinned price but no oracle record.

    Mirrors gamma market 239826: closed 2021, ``["0.0000004…", "0.9999995…"]``,
    ``umaResolutionStatus`` null. The price implies "No"; nothing states it.
    """
    return {
        "id": "239826",
        "question": "NBA: Will the Mavericks beat the Grizzlies by more than 5.5 points?",
        "conditionId": "0x064d33e3",
        "outcomes": '["Yes", "No"]',
        "outcomePrices": '["0.0000004113679809846114", "0.9999995886320190153885"]',
        "clobTokenIds": '["281824040059679406524954632285378409010556497262481904628549144165", '
        '"470448457534500220474364299688086011308111641315715496825417038661"]',
        "endDate": "2021-12-04T00:00:00Z",
        "closedTime": "2021-12-05 20:37:01+00",
        "closed": True,
        "active": True,
        "archived": False,
        "umaResolutionStatus": None,
    }


def _oracle_resolved_market() -> Dict[str, Any]:
    """A market the oracle finalized, with the payout price pinned on "No"."""
    market = _price_pinned_closed_market()
    market["id"] = "254572"
    market["umaResolutionStatus"] = "resolved"
    market["outcomePrices"] = '["0", "1"]'
    return market


def _event(markets: List[Dict[str, Any]]) -> Dict[str, Any]:
    """A gamma event wrapping the supplied markets."""
    return {
        "id": "660108",
        "title": "Strait of Hormuz traffic returns to normal by...?",
        "slug": "strait-of-hormuz-traffic-returns-to-normal-by-august-31-20260702154212320",
        "ticker": "strait-of-hormuz",
        "startDate": "2026-07-02T15:42:12Z",
        "endDate": "2026-08-31T00:00:00Z",
        "resolutionSource": "",
        "closed": False,
        "active": True,
        "archived": False,
        "volume": 6306835.9,
        "volume24hr": 12345.6,
        "liquidity": 627255.86,
        "markets": markets,
    }


class _Router:
    """Records calls and returns a canned payload per URL substring."""

    def __init__(self, routes: Dict[str, Any]) -> None:
        self.routes = routes
        self.calls: List[Dict[str, Any]] = []

    def __call__(self, url: str, **kwargs: Any) -> Any:
        self.calls.append({"url": url, "params": kwargs.get("params"),
                           "host_key": kwargs.get("host_key")})
        for fragment, payload in self.routes.items():
            if fragment in url:
                if isinstance(payload, Exception):
                    raise payload
                if callable(payload):
                    return payload(url, kwargs.get("params") or {})
                return payload
        raise AssertionError(f"unrouted URL in test: {url}")


def _install(monkeypatch, routes: Dict[str, Any]) -> _Router:
    """Patch the tool's HTTP entry point with a routing stub."""
    router = _Router(routes)
    monkeypatch.setattr(prediction_market_tool, "throttled_get_json", router)
    return router


def _run(**kwargs: Any) -> Dict[str, Any]:
    """Execute the tool and decode its JSON return value."""
    return json.loads(PredictionMarketTool().execute(**kwargs))


def _market(monkeypatch, raw: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
    """Normalize one gamma market through the tool and return the record."""
    _install(monkeypatch, {"/markets/": raw})
    return _run(mode="market", ids=[raw.get("id") or "1"], **kwargs)["data"]["markets"][0]


# ---------------------------------------------------------------------------
# Metadata / red line
# ---------------------------------------------------------------------------


class TestMetadata:
    """Tool identity and the read-only guarantee."""

    def test_identity(self):
        assert PredictionMarketTool.name == "prediction_market"
        assert PredictionMarketTool.check_available() is True
        assert PredictionMarketTool().is_readonly is True
        assert PredictionMarketTool.repeatable is True

    def test_schema_declares_all_modes(self):
        schema = PredictionMarketTool().to_openai_schema()
        props = schema["function"]["parameters"]["properties"]
        assert props["mode"]["enum"] == ["search", "event", "market", "history"]
        assert schema["function"]["parameters"]["required"] == ["mode"]

    def test_search_status_filter_is_named_for_trading_not_settlement(self):
        """The catalogue filter cannot select on settlement, so it says so."""
        props = PredictionMarketTool().to_openai_schema()["function"]["parameters"]["properties"]
        assert props["status"]["enum"] == ["open", "closed", "any"]
        assert "resolved" not in props["status"]["enum"]

    def test_description_separates_closed_from_resolved(self):
        text = PredictionMarketTool.description
        assert "CLOSED AND RESOLVED ARE DIFFERENT" in text
        for state in ("unresolved", "pending", "resolved"):
            assert state in text

    def test_module_exposes_no_trading_surface(self):
        """Read-only red line: only GET helpers, no order/trade entry points."""
        source = open(prediction_market_tool.__file__, encoding="utf-8").read()
        for banned in ("place_order", "cancel_order", "requests.post", "session.post",
                       "throttled_post", "private_key", "api_secret"):
            assert banned not in source
        for url_name in ("_GAMMA_SEARCH_URL", "_GAMMA_EVENTS_URL", "_GAMMA_MARKETS_URL",
                         "_CLOB_BOOK_URL", "_CLOB_MARKETS_URL", "_CLOB_HISTORY_URL"):
            url = getattr(prediction_market_tool, url_name)
            assert url.startswith("https://")
            assert "order" not in url


# ---------------------------------------------------------------------------
# Parameter validation
# ---------------------------------------------------------------------------


class TestValidation:
    """Bad input produces the error envelope and never touches the network."""

    @pytest.mark.parametrize(
        "kwargs, fragment",
        [
            ({}, "mode must be one of"),
            ({"mode": "trade"}, "mode must be one of"),
            ({"mode": "search"}, "requires a non-empty 'query'"),
            ({"mode": "search", "query": "  "}, "requires a non-empty 'query'"),
            ({"mode": "search", "query": "fed", "status": "dead"}, "status must be one of"),
            ({"mode": "search", "query": "fed", "limit": 0}, "limit must be"),
            ({"mode": "search", "query": "fed", "limit": "many"}, "limit must be"),
            ({"mode": "search", "query": "fed", "limit": 1.5}, "limit must be"),
            ({"mode": "search", "query": "fed", "limit": True}, "limit must be"),
            ({"mode": "event"}, "requires a non-empty 'ids'"),
            ({"mode": "market", "ids": []}, "requires a non-empty 'ids'"),
            ({"mode": "market", "ids": ["1", ""]}, "must be a non-empty string"),
            ({"mode": "market", "ids": ["1"], "depth": -1}, "depth must be"),
            ({"mode": "history", "ids": ["1"], "interval": "5s"}, "interval must be one of"),
            ({"mode": "history", "ids": ["1"], "max_points": 0}, "max_points must be"),
            ({"mode": "history", "ids": ["1"], "outcome": " "}, "outcome must be"),
        ],
    )
    def test_rejected(self, monkeypatch, kwargs, fragment):
        def explode(*_a, **_k):
            raise AssertionError("validation must reject before any HTTP call")

        monkeypatch.setattr(prediction_market_tool, "throttled_get_json", explode)
        out = _run(**kwargs)
        assert out["ok"] is False
        assert fragment in out["error"]

    def test_limit_is_clamped_not_rejected(self, monkeypatch):
        router = _install(monkeypatch, {"public-search": {"events": [], "pagination": {}}})
        assert _run(mode="search", query="fed", limit=10_000)["ok"] is True
        assert router.calls[0]["params"]["limit_per_type"] == 25

    def test_numeric_strings_are_accepted_not_rejected(self, monkeypatch):
        """LLM tool calls routinely send "10" for an integer field."""
        router = _install(monkeypatch, {"public-search": {"events": [], "pagination": {}}})
        assert _run(mode="search", query="fed", limit="5")["ok"] is True
        assert router.calls[0]["params"]["limit_per_type"] == 5

    def test_integral_floats_are_accepted(self, monkeypatch):
        _install(monkeypatch, {"/markets/": _open_market(), "/book": {"bids": []}})
        out = _run(mode="market", ids=["2774056"], depth=2.0)
        assert out["ok"] is True
        assert out["data"]["depth"] == 2

    def test_string_depth_and_max_points_are_accepted(self, monkeypatch):
        _install(monkeypatch, {"prices-history": {"history": [
            {"t": 1783209607, "p": 0.5}, {"t": 1783296004, "p": 0.6}]}})
        out = _run(mode="history", ids=["9" * 50], max_points=" 1 ")
        assert out["data"]["series"][0]["count"] == 1

    def test_ids_are_capped(self, monkeypatch):
        _install(monkeypatch, {"/markets/": _open_market()})
        out = _run(mode="market", ids=[str(i) for i in range(50)])
        assert len(out["data"]["markets"]) == 10

    def test_dropped_ids_are_disclosed_not_silent(self, monkeypatch):
        """A truncated id list must say so, or the caller assumes full coverage."""
        _install(monkeypatch, {"/markets/": _open_market(), "/events": _event([])})
        assert _run(mode="market", ids=[str(i) for i in range(50)])["data"]["ids_dropped"] == 40
        assert _run(mode="event", ids=[str(i) for i in range(12)])["data"]["ids_dropped"] == 2
        # Within the cap there is nothing to disclose.
        assert "ids_dropped" not in _run(mode="market", ids=["1"])["data"]


# ---------------------------------------------------------------------------
# Settlement vocabulary — the contract shared by every record type
# ---------------------------------------------------------------------------


class TestSettlementVocabulary:
    """`closed` and `resolved` are two different claims, in two fields."""

    def test_closed_without_evidence_is_not_called_resolved(self, monkeypatch):
        """The live 2020 case: closed for years, outcome recorded nowhere."""
        market = _market(monkeypatch, _closed_unresolved_market())
        assert market["status"] == "closed"
        assert market["trading_closed"] is True
        assert market["resolution"]["state"] == "pending"
        assert market["resolution"]["winning_outcome"] is None
        assert "no resolution record" in market["resolution"]["state_basis"]
        assert "implied_winning_outcome" not in market["resolution"]

    def test_oracle_final_status_resolves_and_names_the_winner(self, monkeypatch):
        market = _market(monkeypatch, _oracle_resolved_market())
        assert market["status"] == "resolved"
        assert market["resolution"]["state"] == "resolved"
        assert market["resolution"]["state_basis"].startswith("uma_resolution_status=resolved")
        assert market["resolution"]["winning_outcome"] == "No"
        assert market["resolution"]["winning_outcome_basis"].startswith("settled_outcome_price")

    @pytest.mark.parametrize("uma", ["settled", "RESOLVED", " settled "])
    def test_every_final_oracle_spelling_resolves(self, monkeypatch, uma):
        raw = _oracle_resolved_market()
        raw["umaResolutionStatus"] = uma
        assert _market(monkeypatch, raw)["resolution"]["state"] == "resolved"

    def test_proposed_oracle_answer_is_pending_not_resolved(self, monkeypatch):
        """"proposed" means an answer was submitted and can still be disputed."""
        raw = _oracle_resolved_market()
        raw["umaResolutionStatus"] = "proposed"
        market = _market(monkeypatch, raw)

        assert market["status"] == "closed"
        assert market["resolution"]["state"] == "pending"
        assert "not final" in market["resolution"]["state_basis"]
        assert market["resolution"]["winning_outcome"] is None

    def test_proposed_on_a_still_trading_market_is_pending(self, monkeypatch):
        raw = _open_market()
        raw["umaResolutionStatus"] = "proposed"
        market = _market(monkeypatch, raw)
        assert market["resolution"]["state"] == "pending"
        assert market["status"] == "open"

    def test_resolved_with_split_payout_reports_no_winner_not_no_resolution(self, monkeypatch):
        """Live case: uma "resolved" with prices ["0.5", "0.5"] — a void/tie.

        A price-only rule calls this unresolved; the oracle says otherwise.
        """
        raw = _oracle_resolved_market()
        raw["outcomes"] = '["Over", "Under"]'
        raw["outcomePrices"] = '["0.5", "0.5"]'
        market = _market(monkeypatch, raw)

        assert market["resolution"]["state"] == "resolved"
        assert market["resolution"]["winning_outcome"] is None
        assert "void or split" in market["resolution"]["winning_outcome_basis"]

    def test_pinned_price_alone_is_an_inference_never_a_resolution(self, monkeypatch):
        market = _market(monkeypatch, _price_pinned_closed_market())

        assert market["status"] == "closed"
        assert market["resolution"]["state"] == "pending"
        assert market["resolution"]["winning_outcome"] is None
        assert market["resolution"]["implied_winning_outcome"] == "No"
        assert market["resolution"]["implied_winning_outcome_basis"].startswith("INFERENCE ONLY")

    def test_open_market_trading_above_the_floor_is_not_settled(self, monkeypatch):
        """115 of 400 sampled OPEN markets priced >= 0.99. A price is not a payout."""
        raw = _open_market()
        raw["outcomePrices"] = '["0.995", "0.005"]'
        market = _market(monkeypatch, raw)

        assert market["status"] == "open"
        assert market["resolution"]["state"] == "unresolved"
        assert market["resolution"]["winning_outcome"] is None
        assert "implied_winning_outcome" not in market["resolution"]

    def test_resolved_by_address_is_not_settlement_evidence(self, monkeypatch):
        """`resolvedBy` is populated on open markets; it names a contract."""
        raw = _open_market()
        assert raw["resolvedBy"]
        assert _market(monkeypatch, raw)["resolution"]["state"] == "unresolved"

    def test_archived_label_does_not_hide_a_resolution(self, monkeypatch):
        raw = _oracle_resolved_market()
        raw["archived"] = True
        market = _market(monkeypatch, raw)

        assert market["status"] == "archived"
        assert market["trading_closed"] is True
        assert market["resolution"]["state"] == "resolved"
        assert market["resolution"]["winning_outcome"] == "No"

    def test_unsettled_archived_market_is_not_called_resolved(self, monkeypatch):
        raw = _closed_unresolved_market()
        raw["archived"] = True
        market = _market(monkeypatch, raw)
        assert market["status"] == "archived"
        assert market["resolution"]["state"] == "pending"

    def test_vocabulary_defines_every_status_the_tool_can_emit(self, monkeypatch):
        _install(monkeypatch, {"/markets/": _open_market()})
        vocabulary = _run(mode="market", ids=["2774056"])["vocabulary"]

        assert set(vocabulary["status"]) == set(prediction_market_tool._STATUSES)
        assert set(vocabulary["resolution.state"]) == {"unresolved", "pending", "resolved"}
        assert "NOT" in vocabulary["resolution.state"]["pending"]
        assert "resolution.state" in vocabulary["status"]["closed"]


# ---------------------------------------------------------------------------
# Settlement vocabulary — event and market must agree
# ---------------------------------------------------------------------------


class TestEventSettlementAgreesWithMarkets:
    """An event has no prices and no oracle field, so it may not assert one."""

    def test_closed_event_alone_is_not_resolved(self, monkeypatch):
        """The bug this suite exists for: `closed` used to mean `resolved`."""
        raw = _event([_closed_unresolved_market()])
        raw["closed"] = True
        _install(monkeypatch, {"/events": raw})
        event = _run(mode="event", ids=["660108"])["data"]["events"][0]

        assert event["status"] == "closed"
        assert event["trading_closed"] is True
        assert event["resolution"]["state"] == "pending"
        assert event["resolution"]["markets_resolved"] == 0
        assert event["resolution"]["markets_total"] == 1

    def test_closed_event_with_no_markets_is_pending(self, monkeypatch):
        raw = _event([])
        raw["closed"] = True
        _install(monkeypatch, {"/events": raw})
        event = _run(mode="event", ids=["660108"])["data"]["events"][0]

        assert event["status"] == "closed"
        assert event["resolution"]["state"] == "pending"
        assert "no markets to check" in event["resolution"]["state_basis"]

    def test_event_resolves_only_when_all_its_markets_do(self, monkeypatch):
        raw = _event([_oracle_resolved_market(), _closed_unresolved_market()])
        raw["closed"] = True
        _install(monkeypatch, {"/events": raw})
        event = _run(mode="event", ids=["660108"])["data"]["events"][0]

        assert event["status"] == "closed"
        assert event["resolution"]["state"] == "pending"
        assert event["resolution"]["markets_resolved"] == 1
        assert event["resolution"]["markets_total"] == 2

    def test_fully_resolved_event_is_resolved(self, monkeypatch):
        raw = _event([_oracle_resolved_market(), _oracle_resolved_market()])
        raw["closed"] = True
        _install(monkeypatch, {"/events": raw})
        event = _run(mode="event", ids=["660108"])["data"]["events"][0]

        assert event["status"] == "resolved"
        assert event["resolution"]["state"] == "resolved"
        assert event["resolution"]["markets_resolved"] == 2

    def test_open_event_is_unresolved(self, monkeypatch):
        _install(monkeypatch, {"/events": _event([_open_market()])})
        event = _run(mode="event", ids=["660108"])["data"]["events"][0]

        assert event["status"] == "open"
        assert event["trading_closed"] is False
        assert event["resolution"]["state"] == "unresolved"

    def test_event_and_market_use_the_same_words(self, monkeypatch):
        """Both record types must answer "is this settled?" identically."""
        raw = _event([_oracle_resolved_market()])
        raw["closed"] = True
        _install(monkeypatch, {"/events": raw})
        event = _run(mode="event", ids=["660108"])["data"]["events"][0]

        assert event["status"] == event["markets"][0]["status"] == "resolved"
        assert event["resolution"]["state"] == event["markets"][0]["resolution"]["state"]
        assert event["trading_closed"] == event["markets"][0]["trading_closed"] is True

    def test_capped_market_list_cannot_resolve_the_event(self, monkeypatch):
        """The cap must not resurrect the bug: 30 resolved of 32 is not resolved.

        ``_MAX_MARKETS_PER_EVENT`` truncates the payload. Counting the resolved
        markets against the truncated list called a 32-market event ``resolved``
        on the strength of its first 30 — the same "close enough" inference the
        rest of this suite removes, reintroduced by a display cap.
        """
        markets = [_oracle_resolved_market() for _ in range(30)]
        markets += [_closed_unresolved_market(), _closed_unresolved_market()]
        raw = _event(markets)
        raw["closed"] = True
        _install(monkeypatch, {"/events": raw})
        event = _run(mode="event", ids=["660108"])["data"]["events"][0]

        assert event["status"] == "closed"
        assert event["resolution"]["state"] == "pending"
        assert event["resolution"]["markets_total"] == 32
        assert event["resolution"]["markets_inspected"] == 30
        assert "not inspected" in event["resolution"]["state_basis"]

    def test_uncapped_fully_resolved_event_still_resolves(self, monkeypatch):
        """The cap guard must not block the legitimate resolved verdict."""
        raw = _event([_oracle_resolved_market() for _ in range(30)])
        raw["closed"] = True
        _install(monkeypatch, {"/events": raw})
        event = _run(mode="event", ids=["660108"])["data"]["events"][0]

        assert event["resolution"]["state"] == "resolved"
        assert event["resolution"]["markets_total"] == 30
        assert event["resolution"]["markets_inspected"] == 30

    def test_search_results_carry_resolution_without_expanding_markets(self, monkeypatch):
        """Search stays condensed but must not lose the settlement judgement."""
        raw = _event([_oracle_resolved_market()])
        raw["closed"] = True
        _install(monkeypatch, {"public-search": {"events": [raw], "pagination": {}}})
        event = _run(mode="search", query="hormuz", status="closed")["data"]["events"][0]

        assert "markets" not in event
        assert event["market_count"] == 1
        assert event["status"] == "resolved"
        assert event["resolution"]["markets_resolved"] == 1


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------


class TestSearch:
    """Keyword search shape, status mapping and pagination passthrough."""

    def test_success_envelope(self, monkeypatch):
        payload = {
            "events": [_event([_open_market()])],
            "pagination": {"hasMore": True, "totalResults": 25},
        }
        router = _install(monkeypatch, {"public-search": payload})
        out = _run(mode="search", query="  hormuz  ", limit=5)

        assert out["ok"] is True
        assert out["source"] == "polymarket"
        assert out["mode"] == "search"
        assert out["data"]["query"] == "hormuz"
        assert out["data"]["total_results"] == 25
        assert out["data"]["has_more"] is True

        event = out["data"]["events"][0]
        assert event["event_id"] == "660108"
        assert event["status"] == "open"
        assert event["trading_closed"] is False
        assert event["end_date"] == "2026-08-31T00:00:00Z"
        # Search results stay condensed: counted, not expanded.
        assert event["market_count"] == 1
        assert "markets" not in event

        assert router.calls[0]["host_key"] == "polymarket_gamma"
        assert router.calls[0]["params"]["q"] == "hormuz"
        assert router.calls[0]["params"]["events_status"] == "active"

    @pytest.mark.parametrize(
        "status, expected",
        [("open", "active"), ("closed", "resolved"), ("resolved", "resolved"), ("any", None)],
    )
    def test_status_maps_to_server_filter(self, monkeypatch, status, expected):
        """'resolved' stays accepted as a legacy alias for 'closed'."""
        router = _install(monkeypatch, {"public-search": {"events": [], "pagination": {}}})
        out = _run(mode="search", query="fed", status=status)
        assert router.calls[0]["params"].get("events_status") == expected
        assert out["data"]["status_filter"] in ("open", "closed", "any")

    def test_closed_filter_discloses_it_cannot_select_on_settlement(self, monkeypatch):
        _install(monkeypatch, {"public-search": {"events": [], "pagination": {}}})
        basis = _run(mode="search", query="fed", status="closed")["data"]["status_filter_basis"]
        assert "closed == true" in basis
        assert "does NOT filter on settlement" in basis

    def test_network_failure_becomes_error_envelope(self, monkeypatch):
        _install(monkeypatch, {"public-search": RuntimeError("boom")})
        out = _run(mode="search", query="fed")
        assert out["ok"] is False
        assert "boom" in out["error"]

    def test_unexpected_shape_is_tolerated(self, monkeypatch):
        _install(monkeypatch, {"public-search": ["not", "a", "dict"]})
        out = _run(mode="search", query="fed")
        assert out["ok"] is True
        assert out["data"]["events"] == []


# ---------------------------------------------------------------------------
# event
# ---------------------------------------------------------------------------


class TestEvent:
    """Event lookup by id and by slug, plus per-id batch isolation."""

    def test_numeric_id_uses_path_lookup(self, monkeypatch):
        router = _install(monkeypatch, {"/events": _event([_open_market()])})
        out = _run(mode="event", ids=["660108"])

        assert router.calls[0]["url"].endswith("/events/660108")
        assert router.calls[0]["params"] is None
        event = out["data"]["events"][0]
        assert event["market_count"] == 1
        assert event["markets"][0]["market_id"] == "2774056"

    def test_slug_uses_query_lookup(self, monkeypatch):
        router = _install(monkeypatch, {"/events": [_event([_open_market()])]})
        out = _run(mode="event", ids=["strait-of-hormuz-x"])

        assert router.calls[0]["url"].endswith("/events")
        assert router.calls[0]["params"] == {"slug": "strait-of-hormuz-x"}
        assert out["data"]["events"][0]["event_id"] == "660108"

    def test_empty_slug_result_is_reported_not_raised(self, monkeypatch):
        _install(monkeypatch, {"/events": []})
        out = _run(mode="event", ids=["nope"])
        assert out["ok"] is True
        assert "no event matches this slug" in out["data"]["events"][0]["error"]

    def test_one_failing_id_does_not_abort_the_batch(self, monkeypatch):
        def route(url: str, _params: Dict[str, Any]) -> Any:
            if url.endswith("/events/404"):
                raise RuntimeError("404 not found")
            return _event([_open_market()])

        _install(monkeypatch, {"/events": route})
        out = _run(mode="event", ids=["404", "660108"])

        events = out["data"]["events"]
        assert out["ok"] is True
        assert events[0] == {"id": "404", "error": "404 not found"}
        assert events[1]["event_id"] == "660108"

    def test_nested_markets_are_capped(self, monkeypatch):
        _install(monkeypatch, {"/events": _event([_open_market()] * 40)})
        out = _run(mode="event", ids=["660108"])
        event = out["data"]["events"][0]
        assert event["market_count"] == 40
        assert len(event["markets"]) == 30


# ---------------------------------------------------------------------------
# market — probability conversion, status, book
# ---------------------------------------------------------------------------


class TestMarket:
    """Quote normalization: probabilities, settlement status, order book."""

    def test_prices_become_labelled_probabilities(self, monkeypatch):
        _install(monkeypatch, {"/markets/": _open_market()})
        out = _run(mode="market", ids=["2774056"])
        market = out["data"]["markets"][0]

        yes, no = market["outcomes"]
        assert yes["outcome"] == "Yes"
        assert yes["implied_probability"] == 0.135
        assert yes["implied_probability_pct"] == 13.5
        assert yes["price_usd"] == 0.135
        assert no["implied_probability_pct"] == 86.5
        # JSON-string clobTokenIds are decoded into real ids.
        assert yes["clob_token_id"].isdigit()

        assert market["status"] == "open"
        assert market["trading_closed"] is False
        assert market["end_date"] == "2026-08-31T00:00:00Z"
        assert market["best_bid"] == 0.13
        assert market["best_ask"] == 0.14
        assert market["spread"] == 0.01
        assert market["volume_usd"] == pytest.approx(6306835.903025)

    def test_units_are_declared_on_every_envelope(self, monkeypatch):
        _install(monkeypatch, {"/markets/": _open_market()})
        units = _run(mode="market", ids=["2774056"])["units"]
        assert "0-1" in units["implied_probability"]
        assert "NOT" in units["implied_probability"]
        assert units["price_usd"].startswith("USD")

    def test_closed_time_is_surfaced(self, monkeypatch):
        market = _market(monkeypatch, _price_pinned_closed_market())
        assert market["closed_time"] == "2021-12-05 20:37:01+00"

    def test_default_depth_makes_no_book_requests(self, monkeypatch):
        router = _install(monkeypatch, {"/markets/": _open_market()})
        _run(mode="market", ids=["2774056"])
        assert all("/book" not in c["url"] for c in router.calls)
        assert len(router.calls) == 1

    def test_depth_returns_touch_first_ladder(self, monkeypatch):
        book = {
            "asset_id": "1",
            "tick_size": "0.01",
            "min_order_size": "5",
            # Live ordering: bids ascending, asks descending — touch at the tail.
            "bids": [{"price": "0.01", "size": "1287065.04"},
                     {"price": "0.12", "size": "500"},
                     {"price": "0.13", "size": "100"}],
            "asks": [{"price": "0.99", "size": "23774.73"},
                     {"price": "0.15", "size": "300"},
                     {"price": "0.14", "size": "200"}],
        }
        router = _install(monkeypatch, {"/markets/": _open_market(), "/book": book})
        market = _run(mode="market", ids=["2774056"], depth=2)["data"]["markets"][0]

        bids = market["outcomes"][0]["book"]["bids"]
        asks = market["outcomes"][0]["book"]["asks"]
        assert [b["implied_probability"] for b in bids] == [0.13, 0.12]
        assert [a["implied_probability"] for a in asks] == [0.14, 0.15]
        assert bids[0]["size"] == 100.0
        assert market["outcomes"][0]["book"]["tick_size"] == 0.01
        assert all(c["host_key"] == "polymarket_clob"
                   for c in router.calls if "/book" in c["url"])

    def test_book_failure_is_contained_to_the_outcome(self, monkeypatch):
        _install(monkeypatch, {"/markets/": _open_market(), "/book": RuntimeError("book down")})
        market = _run(mode="market", ids=["2774056"], depth=3)["data"]["markets"][0]

        assert market["status"] == "open"
        assert market["outcomes"][0]["implied_probability"] == 0.135
        assert market["outcomes"][0]["book"]["error"] == "book down"

    def test_condition_id_routes_to_clob(self, monkeypatch):
        clob = {
            "condition_id": "0xabc",
            "question": "Will X happen?",
            "market_slug": "will-x-happen",
            "end_date_iso": "2026-12-31T00:00:00Z",
            "closed": False,
            "active": True,
            "archived": False,
            "tokens": [
                {"token_id": "111", "outcome": "Yes", "price": 0.42, "winner": False},
                {"token_id": "222", "outcome": "No", "price": 0.58, "winner": False},
            ],
        }
        router = _install(monkeypatch, {"clob.polymarket.com/markets/": clob})
        market = _run(mode="market", ids=["0xabc"])["data"]["markets"][0]

        assert router.calls[0]["host_key"] == "polymarket_clob"
        assert market["condition_id"] == "0xabc"
        assert market["outcomes"][0]["implied_probability_pct"] == 42.0
        assert market["outcomes"][1]["clob_token_id"] == "222"
        # CLOB exposes no gamma numeric id. Echoing the slug as `market_id`
        # would hand back an id gamma's /markets/<id> rejects (HTTP 422).
        assert market["market_id"] is None
        assert market["slug"] == "will-x-happen"
        assert market["resolution"]["state"] == "unresolved"

    def test_clob_winner_flag_is_the_strongest_evidence(self, monkeypatch):
        """The venue's own settlement flag, taken over price and oracle status."""
        clob = {
            "condition_id": "0xaf1b563a",
            "question": "Credible FDV above $X one day after launch?",
            "market_slug": "credible-fdv-above",
            "closed": True,
            "active": True,
            "archived": False,
            "tokens": [
                {"token_id": "462371", "outcome": "Yes", "price": 1, "winner": True},
                {"token_id": "867301", "outcome": "No", "price": 0, "winner": False},
            ],
        }
        _install(monkeypatch, {"clob.polymarket.com/markets/": clob})
        market = _run(mode="market", ids=["0xaf1b563a"])["data"]["markets"][0]

        assert market["status"] == "resolved"
        assert market["resolution"]["state"] == "resolved"
        assert market["resolution"]["state_basis"].startswith("clob_winner_flag")
        assert market["resolution"]["winning_outcome"] == "Yes"
        assert market["outcomes"][0]["is_winner"] is True
        assert market["outcomes"][1]["is_winner"] is False

    def test_clob_winner_flag_outranks_the_closed_flag(self, monkeypatch):
        """A winner can be flagged while `closed` is still false; trust the flag."""
        clob = {
            "condition_id": "0xdef",
            "market_slug": "x",
            "closed": False,
            "active": False,
            "archived": False,
            "tokens": [
                {"token_id": "1", "outcome": "Yes", "price": 1, "winner": True},
                {"token_id": "2", "outcome": "No", "price": 0, "winner": False},
            ],
        }
        _install(monkeypatch, {"clob.polymarket.com/markets/": clob})
        market = _run(mode="market", ids=["0xdef"])["data"]["markets"][0]

        assert market["trading_closed"] is False
        assert market["resolution"]["state"] == "resolved"
        assert market["status"] == "resolved"

    def test_two_flagged_winners_are_not_trusted(self, monkeypatch):
        """A payload claiming two winners is incoherent; fall back, don't guess."""
        clob = {
            "condition_id": "0xbad",
            "market_slug": "x",
            "closed": True,
            "active": True,
            "archived": False,
            "tokens": [
                {"token_id": "1", "outcome": "Yes", "price": 0.5, "winner": True},
                {"token_id": "2", "outcome": "No", "price": 0.5, "winner": True},
            ],
        }
        _install(monkeypatch, {"clob.polymarket.com/markets/": clob})
        market = _run(mode="market", ids=["0xbad"])["data"]["markets"][0]

        assert market["resolution"]["state"] == "pending"
        assert market["resolution"]["winning_outcome"] is None

    def test_failing_market_does_not_abort_batch(self, monkeypatch):
        def route(url: str, _params: Dict[str, Any]) -> Any:
            if url.endswith("/999"):
                raise RuntimeError("id not found")
            return _open_market()

        _install(monkeypatch, {"/markets/": route})
        markets = _run(mode="market", ids=["999", "2774056"])["data"]["markets"]
        assert markets[0] == {"id": "999", "error": "id not found"}
        assert markets[1]["market_id"] == "2774056"


# ---------------------------------------------------------------------------
# history
# ---------------------------------------------------------------------------


class TestHistory:
    """Probability series: token resolution, interval grammar, caps."""

    _HISTORY = {"history": [
        {"t": 1783209607, "p": 0.355},
        {"t": 1783296004, "p": 0.345},
        {"t": 1785835390, "p": 0.135},
    ]}

    def test_market_id_resolves_to_first_outcome_token(self, monkeypatch):
        router = _install(
            monkeypatch, {"/markets/": _open_market(), "prices-history": self._HISTORY}
        )
        series = _run(mode="history", ids=["2774056"])["data"]["series"][0]

        assert series["outcome"] == "Yes"
        assert series["market_id"] == "2774056"
        assert series["condition_id"].startswith("0x")
        assert series["count"] == 3
        assert series["points"][0]["implied_probability"] == 0.355
        assert series["points"][0]["implied_probability_pct"] == 35.5
        assert series["points"][0]["timestamp"] == "2026-07-05T00:00:07Z"
        assert series["points"][-1]["implied_probability"] == 0.135

        history_call = [c for c in router.calls if "prices-history" in c["url"]][0]
        assert history_call["params"]["market"] == series["clob_token_id"]
        assert history_call["params"]["interval"] == "1m"
        # 1m means one MONTH, so the bar width is one day in minutes.
        assert history_call["params"]["fidelity"] == 1440

    def test_outcome_selects_the_matching_token(self, monkeypatch):
        router = _install(
            monkeypatch, {"/markets/": _open_market(), "prices-history": self._HISTORY}
        )
        series = _run(mode="history", ids=["2774056"], outcome="no")["data"]["series"][0]

        assert series["outcome"] == "No"
        history_call = [c for c in router.calls if "prices-history" in c["url"]][0]
        assert history_call["params"]["market"].startswith("908694940879770186")

    def test_unknown_outcome_is_reported_per_id(self, monkeypatch):
        _install(monkeypatch, {"/markets/": _open_market()})
        series = _run(mode="history", ids=["2774056"], outcome="Maybe")["data"]["series"][0]
        assert "not in ['Yes', 'No']" in series["error"]

    def test_clob_token_id_skips_resolution(self, monkeypatch):
        token = "1" * 60
        router = _install(monkeypatch, {"prices-history": self._HISTORY})
        series = _run(mode="history", ids=[token])["data"]["series"][0]

        assert len(router.calls) == 1
        assert series["clob_token_id"] == token
        assert series["count"] == 3

    def test_real_token_id_skips_resolution(self, monkeypatch):
        """A 77-digit id captured live must not be mistaken for a market id."""
        token = (
            "4623718195790606414562517403988961055381848388222460997372087189068142472534"
        )
        router = _install(monkeypatch, {"prices-history": self._HISTORY})
        _run(mode="history", ids=[token])
        assert len(router.calls) == 1
        assert router.calls[0]["params"]["market"] == token

    def test_out_of_domain_digits_are_not_treated_as_a_token(self, monkeypatch):
        """Above uint256 there is no such token, so resolve it as a market id."""
        router = _install(monkeypatch, {"/markets/": RuntimeError("id not found")})
        series = _run(mode="history", ids=["9" * 80])["data"]["series"][0]

        assert "id not found" in series["error"]
        assert "gamma-api" in router.calls[0]["url"]

    @pytest.mark.parametrize(
        "interval, fidelity",
        [("1h", 1), ("6h", 10), ("1d", 60), ("1w", 360), ("1m", 1440), ("max", 1440)],
    )
    def test_every_accepted_interval_has_a_bar_width(self, monkeypatch, interval, fidelity):
        router = _install(monkeypatch, {"prices-history": self._HISTORY})
        out = _run(mode="history", ids=["9" * 50], interval=interval)
        assert out["data"]["interval"] == interval
        assert router.calls[0]["params"]["fidelity"] == fidelity
        assert out["data"]["series"][0]["bar_minutes"] == fidelity

    def test_max_points_keeps_the_most_recent(self, monkeypatch):
        _install(monkeypatch, {"prices-history": self._HISTORY})
        series = _run(mode="history", ids=["9" * 50], max_points=2)["data"]["series"][0]
        assert series["count"] == 2
        assert [p["implied_probability"] for p in series["points"]] == [0.345, 0.135]

    def test_hard_point_cap_applies(self, monkeypatch):
        big = {"history": [{"t": 1700000000 + i, "p": 0.5} for i in range(5000)]}
        _install(monkeypatch, {"prices-history": big})
        series = _run(mode="history", ids=["9" * 50], max_points=99999)["data"]["series"][0]
        assert series["count"] == 1000

    def test_malformed_points_are_dropped_not_fatal(self, monkeypatch):
        _install(monkeypatch, {"prices-history": {"history": [
            {"t": 1783209607, "p": 0.5},
            {"t": None, "p": 0.4},
            {"t": 1783296004, "p": "junk"},
            "not-a-dict",
        ]}})
        series = _run(mode="history", ids=["9" * 50])["data"]["series"][0]
        assert series["count"] == 1
        assert series["points"][0]["implied_probability"] == 0.5

    def test_empty_history_is_not_an_error(self, monkeypatch):
        _install(monkeypatch, {"prices-history": {"history": []}})
        series = _run(mode="history", ids=["9" * 50])["data"]["series"][0]
        assert series["count"] == 0
        assert "error" not in series

    def test_history_failure_keeps_resolution_context(self, monkeypatch):
        _install(monkeypatch, {"/markets/": _open_market(),
                               "prices-history": RuntimeError("clob 503")})
        series = _run(mode="history", ids=["2774056"])["data"]["series"][0]
        assert series["error"] == "clob 503"
        assert series["outcome"] == "Yes"

    def test_one_failing_series_does_not_abort_the_batch(self, monkeypatch):
        def route(url: str, params: Dict[str, Any]) -> Any:
            if params.get("market", "").startswith("7"):
                raise RuntimeError("token unknown")
            return self._HISTORY

        _install(monkeypatch, {"prices-history": route})
        series = _run(mode="history", ids=["7" * 50, "9" * 50])["data"]["series"]
        assert series[0]["error"] == "token unknown"
        assert series[1]["count"] == 3

    def test_market_without_tokens_is_reported(self, monkeypatch):
        raw = _open_market()
        raw["clobTokenIds"] = "[]"
        _install(monkeypatch, {"/markets/": raw})
        series = _run(mode="history", ids=["2774056"])["data"]["series"][0]
        assert series["error"] == "market exposes no CLOB outcome tokens"


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


class TestHelpers:
    """Decoders that absorb the API's string-typed fields."""

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ('["Yes", "No"]', ["Yes", "No"]),
            (["Yes", "No"], ["Yes", "No"]),
            ("", []),
            (None, []),
            ("not json", []),
            ('{"a": 1}', []),
        ],
    )
    def test_json_list(self, raw, expected):
        assert prediction_market_tool._json_list(raw) == expected

    @pytest.mark.parametrize(
        "raw, expected", [("0.5", 0.5), (0.5, 0.5), (None, None), (True, None), ("x", None)]
    )
    def test_to_float(self, raw, expected):
        assert prediction_market_tool._to_float(raw) == expected

    def test_probability_rounds_scientific_notation(self):
        out = prediction_market_tool._probability("0.0000004113679809846114")
        assert out["implied_probability"] == 0.0
        assert out["implied_probability_pct"] == 0.0

    def test_probability_of_garbage_is_none(self):
        assert prediction_market_tool._probability("n/a") is None

    @pytest.mark.parametrize(
        "raw, expected",
        [
            (10, 10),
            ("10", 10),
            ("  10  ", 10),
            (10.0, 10),
            ("10.0", 10),
            (0, 0),
            (-3, -3),
            (10.5, None),
            ("10.5", None),
            ("ten", None),
            ("", None),
            (True, None),
            (False, None),
            (None, None),
            ([10], None),
            ("nan", None),
            ("inf", None),
        ],
    )
    def test_coerce_int(self, raw, expected):
        assert prediction_market_tool._coerce_int(raw) == expected

    @pytest.mark.parametrize(
        "value, expected",
        [
            # Gamma catalogue ids are sequential database row ids.
            ("2774056", False),
            ("12", False),
            (str(2**63 - 1), False),
            # A uint256 position id cannot fit a signed 64-bit column.
            (str(2**63), True),
            ("1" * 40, True),
            (
                "4623718195790606414562517403988961055381848388222460997372087189068142472534",
                True,
            ),
            (str(2**256 - 1), True),
            # Out of the uint256 domain entirely — not a token id.
            (str(2**256), False),
            ("9" * 80, False),
            # Not decimal at all.
            ("0x60c2c085", False),
            ("", False),
            ("12.5", False),
            ("-" + "1" * 40, False),
            # str.isdigit() is true for these but int() rejects them, so the
            # domain test must screen on ASCII before it parses.
            ("²³", False),
            ("⁵" * 40, False),
            # Arabic-Indic digits parse but are not an id either venue emits.
            ("١" * 40, False),
        ],
    )
    def test_is_clob_token_id(self, value, expected):
        assert prediction_market_tool._is_clob_token_id(value) is expected
