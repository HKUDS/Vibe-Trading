"""Tests for research_papers: search, read, and the paper-to-factor brief.

Every test mocks ``research_papers_tool.throttled_get``, so nothing here
reaches arXiv or OpenAlex. The XML and JSON fixtures are trimmed copies of
real responses captured from the live endpoints (including their quirks: the
LaTeX ``$1.06$`` / ``\\%`` escaping arXiv abstracts carry, OpenAlex's inverted
abstract index, and OpenAlex's HTML 404 body for an unknown work id).

The extraction assertions are deliberately written as *honesty* tests: a field
the fixture does not state must come back as "not stated in source", never
back-filled.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.config.accessor import reset_env_config
from src.tools import research_papers_tool as rpt
from src.tools.research_papers_tool import ResearchPapersTool

_NOT_STATED = "not stated in source"

_RICH_ABSTRACT = (
    "We present a simple framework for dynamic portfolio management that uses "
    "nothing but daily prices, trading volumes, and market capitalizations. "
    # `&amp;` is how the live feed escapes the LaTeX `S\&P 500`; XML-parsing it
    # yields `S\&P 500`, which is the form the market vocabulary must match.
    "The transition matrices rank the S\\&amp;P 500 names monthly by trailing "
    "return. A portfolio built on the forecasts beats the market on the test "
    "set January 2022 to December 2024, at a Sharpe of $1.06$ against the "
    "market's $0.78$. The maximum drawdown is reported in the appendix."
)

_ARXIV_FEED = f"""<?xml version='1.0' encoding='UTF-8'?>
<feed xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/"
      xmlns:arxiv="http://arxiv.org/schemas/atom"
      xmlns="http://www.w3.org/2005/Atom">
  <opensearch:totalResults>60</opensearch:totalResults>
  <entry>
    <id>http://arxiv.org/abs/2607.27461v2</id>
    <title>Observable Matrix Dynamics for Portfolio Optimization</title>
    <updated>2026-07-30T10:00:00Z</updated>
    <published>2026-07-29T20:53:46Z</published>
    <link href="https://arxiv.org/abs/2607.27461v2" rel="alternate" type="text/html"/>
    <link href="https://arxiv.org/pdf/2607.27461v2" rel="related" type="application/pdf" title="pdf"/>
    <summary>{_RICH_ABSTRACT}</summary>
    <category term="q-fin.PM" scheme="http://arxiv.org/schemas/atom"/>
    <category term="q-fin.RM" scheme="http://arxiv.org/schemas/atom"/>
    <arxiv:comment>50 pages</arxiv:comment>
    <arxiv:journal_ref>J. Fake Finance 1(2026), 1-20</arxiv:journal_ref>
    <arxiv:primary_category term="q-fin.PM"/>
    <author><name>Ada First</name></author>
    <author><name>Bob Second</name></author>
  </entry>
</feed>
"""

_ARXIV_EMPTY_FEED = """<?xml version='1.0' encoding='UTF-8'?>
<feed xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/"
      xmlns="http://www.w3.org/2005/Atom">
  <opensearch:totalResults>0</opensearch:totalResults>
</feed>
"""

_ARXIV_BARE_FEED = """<?xml version='1.0' encoding='UTF-8'?>
<feed xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/"
      xmlns:arxiv="http://arxiv.org/schemas/atom"
      xmlns="http://www.w3.org/2005/Atom">
  <opensearch:totalResults>1</opensearch:totalResults>
  <entry>
    <id>http://arxiv.org/abs/1111.11111v1</id>
    <title>A Note on Hilbert Spaces</title>
    <published>2011-01-01T00:00:00Z</published>
    <updated>2011-01-01T00:00:00Z</updated>
    <summary>This note collects remarks about separable Hilbert spaces.
    No empirical work is involved.</summary>
    <arxiv:primary_category term="math.FA"/>
    <author><name>Solo Author</name></author>
  </entry>
</feed>
"""

# Verbatim shape of a live rejection: the id always carries a reason fragment,
# so a fixture using the bare ".../api/errors" id would test something arXiv
# never actually emits.
_ARXIV_ERROR_FEED = """<?xml version='1.0' encoding='UTF-8'?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>https://arxiv.org/api/errors#start_must_be_an_integer</id>
    <title>Error</title>
    <summary>start must be an integer</summary>
  </entry>
</feed>
"""

# A bad sortBy is rejected with an id that points at the user manual rather than
# at /api/errors, so status-plus-summary is the only handle on the real reason.
_ARXIV_MANUAL_ERROR_FEED = """<?xml version='1.0' encoding='UTF-8'?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>https://arxiv.org/help/api/user-manual#sort</id>
    <title>Error</title>
    <summary>sortBy must be in: relevance, lastUpdatedDate, submittedDate</summary>
  </entry>
</feed>
"""


def _inverted(text: str) -> dict[str, list[int]]:
    """Encode plain text the way OpenAlex serves abstracts.

    Args:
        text: Whitespace-separated abstract text.

    Returns:
        A ``{word: [positions]}`` inverted index.
    """
    index: dict[str, list[int]] = {}
    for position, word in enumerate(text.split()):
        index.setdefault(word, []).append(position)
    return index


_OPENALEX_ABSTRACT = (
    "Our monthly liquidity measure relies on order flow. "
    "From 1966 through 1999, the average return on high-sensitivity stocks "
    "exceeds the rest by 7.5 percent annually in US equities."
)

_OPENALEX_WORK = {
    "id": "https://openalex.org/W3021190191",
    "doi": "https://doi.org/10.1086/374184",
    "title": "Liquidity Risk and Expected Stock Returns",
    "publication_date": "2003-06-01",
    # Live field: OpenAlex re-stamps records long after publication.
    "updated_date": "2026-08-01T09:00:35.917206",
    "type": "article",
    "cited_by_count": 5658,
    "authorships": [{"author": {"display_name": "Lubos Pastor"}}],
    "primary_location": {
        "landing_page_url": "https://doi.org/10.1086/374184",
        "pdf_url": None,
        "version": "publishedVersion",
        "source": {"display_name": "Journal of Political Economy"},
    },
    "abstract_inverted_index": _inverted(_OPENALEX_ABSTRACT),
}

_OPENALEX_NO_ABSTRACT = {
    "id": "https://openalex.org/W3123379704",
    "title": "Have we solved the idiosyncratic volatility puzzle?",
    "publication_date": "2016-02-28",
    "authorships": [],
    "primary_location": {},
    "abstract_inverted_index": None,
}


def _response(*, text: str = "", payload: object = None, status: int = 200):
    """Build a minimal stand-in for a ``requests.Response``.

    Args:
        text: Body used by the XML path.
        payload: Object returned by ``.json()``; ``None`` raises like a
            non-JSON body would.
        status: HTTP status code.

    Returns:
        A namespace exposing ``text``, ``status_code`` and ``json()``.
    """
    def _json():
        if payload is None:
            raise ValueError("not json")
        return payload

    return SimpleNamespace(text=text, status_code=status, json=_json)


def _brief(paper_ids, response):
    """Run read-mode against a single mocked response and return the envelope.

    Args:
        paper_ids: Ids to request.
        response: Mocked ``throttled_get`` return value.

    Returns:
        The decoded JSON envelope.
    """
    with patch.object(rpt, "throttled_get", return_value=response):
        return json.loads(ResearchPapersTool().execute(mode="read", paper_ids=paper_ids))


# --------------------------------------------------------------------------
# argument validation
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs, fragment",
    [
        ({}, "mode must be one of"),
        ({"mode": "browse"}, "mode must be one of"),
        ({"mode": "search", "source": "ssrn"}, "source must be one of"),
        ({"mode": "search", "query": "x", "start_date": "2024"}, "start_date must be"),
        ({"mode": "search", "query": "x", "end_date": "12-2024"}, "end_date must be"),
        ({"mode": "search", "query": "   "}, "query must be a non-empty string"),
        ({"mode": "search", "query": "x", "categories": "q-fin"}, "categories must be a list"),
        ({"mode": "search", "query": "x", "max_results": 0}, "max_results must be"),
        ({"mode": "search", "query": "x", "max_results": True}, "max_results must be"),
        ({"mode": "search", "query": "x", "sort_by": "citations"}, "sort_by must be one of"),
        ({"mode": "read"}, "requires a non-empty paper_ids"),
        ({"mode": "read", "paper_ids": []}, "requires a non-empty paper_ids"),
        ({"mode": "read", "paper_ids": [""]}, "must be a non-empty string"),
    ],
)
def test_argument_validation_rejects_before_any_request(kwargs, fragment):
    with patch.object(rpt, "throttled_get") as mock_get:
        payload = json.loads(ResearchPapersTool().execute(**kwargs))
    assert payload["ok"] is False
    assert fragment in payload["error"]
    mock_get.assert_not_called()


def test_search_without_any_clause_is_an_error():
    with patch.object(rpt, "throttled_get") as mock_get:
        payload = json.loads(ResearchPapersTool().execute(mode="search"))
    assert payload["ok"] is False
    assert "at least one of" in payload["error"]
    mock_get.assert_not_called()


# --------------------------------------------------------------------------
# arXiv
# --------------------------------------------------------------------------


def test_arxiv_search_builds_phrase_query_and_throttles():
    with patch.object(
        rpt, "throttled_get", return_value=_response(text=_ARXIV_FEED)
    ) as mock_get:
        payload = json.loads(
            ResearchPapersTool().execute(
                mode="search",
                query='cross-sectional "momentum"',
                categories=["q-fin.PM", "q-fin.ST"],
                start_date="2024-01-01",
                end_date="2024-12-31",
                max_results=500,
            )
        )

    assert payload["ok"] is True
    assert payload["total_available"] == 60
    kwargs = mock_get.call_args.kwargs
    assert kwargs["host_key"] == "arxiv"
    assert kwargs["min_interval"] == 3.0
    query = kwargs["params"]["search_query"]
    # The user quote is stripped, the phrase stays quoted, and every clause ANDs.
    assert 'ti:"cross-sectional  momentum"' in query
    assert 'abs:"cross-sectional  momentum"' in query
    assert "(cat:q-fin.PM OR cat:q-fin.ST)" in query
    assert "submittedDate:[202401010000 TO 202412312359]" in query
    # max_results is clamped, never passed through raw.
    assert kwargs["params"]["max_results"] == rpt._MAX_RESULTS


def test_arxiv_search_falls_back_to_date_sort_without_a_query():
    with patch.object(
        rpt, "throttled_get", return_value=_response(text=_ARXIV_FEED)
    ) as mock_get:
        payload = json.loads(
            ResearchPapersTool().execute(
                mode="search", categories=["q-fin.PM"], sort_by="relevance"
            )
        )
    assert payload["sort_by"] == "submitted"
    assert mock_get.call_args.kwargs["params"]["sortBy"] == "submittedDate"


def test_arxiv_phrase_query_widens_to_all_terms_when_it_finds_nothing():
    # Probed live: "cross-sectional momentum" -> 9 hits, the same phrase plus two
    # more words -> 0, the terms AND-ed -> 5,990. A phrase one word too long must
    # not read as "no such literature".
    responses = [_response(text=_ARXIV_EMPTY_FEED), _response(text=_ARXIV_FEED)]
    with patch.object(rpt, "throttled_get", side_effect=responses) as mock_get:
        payload = json.loads(
            ResearchPapersTool().execute(
                mode="search", query="cross-sectional momentum in the crypto market",
                categories=["q-fin.PM"],
            )
        )

    assert mock_get.call_count == 2
    first, second = (c.kwargs["params"]["search_query"] for c in mock_get.call_args_list)
    assert first.startswith('(ti:"cross-sectional momentum in the crypto market"')
    # Stopwords do not eat a term slot, and every filter clause survives.
    assert '(ti:"cross-sectional" OR abs:"cross-sectional")' in second
    assert '(ti:"crypto" OR abs:"crypto")' in second
    assert '(ti:"the" OR abs:"the")' not in second
    assert "(cat:q-fin.PM)" in second

    assert payload["query_mode"] == "all_terms"
    assert payload["returned"] == 1
    assert payload["phrase_query_returned_nothing"] == first


def test_a_phrase_that_finds_papers_is_never_widened():
    with patch.object(
        rpt, "throttled_get", return_value=_response(text=_ARXIV_FEED)
    ) as mock_get:
        payload = json.loads(
            ResearchPapersTool().execute(mode="search", query="momentum crash")
        )
    assert mock_get.call_count == 1
    assert payload["query_mode"] == "exact_phrase"
    assert "phrase_query_returned_nothing" not in payload


@pytest.mark.parametrize(
    "query, second_feed", [("momentum", None), ("momentum crash", _ARXIV_EMPTY_FEED)]
)
def test_an_empty_result_is_reported_as_empty_not_papered_over(query, second_feed):
    feeds = [_ARXIV_EMPTY_FEED] + ([second_feed] if second_feed else [])
    with patch.object(
        rpt, "throttled_get", side_effect=[_response(text=f) for f in feeds]
    ) as mock_get:
        payload = json.loads(ResearchPapersTool().execute(mode="search", query=query))
    # A one-word query has nothing to widen into, so it costs one request.
    assert mock_get.call_count == len(feeds)
    assert payload["returned"] == 0
    assert payload["query_mode"] == "exact_phrase"


def test_arxiv_search_records_carry_metadata_but_no_brief():
    with patch.object(rpt, "throttled_get", return_value=_response(text=_ARXIV_FEED)):
        payload = json.loads(
            ResearchPapersTool().execute(mode="search", query="portfolio")
        )
    paper = payload["papers"][0]
    assert paper["paper_id"] == "2607.27461"
    assert paper["version"] == "v2"
    assert paper["published"] == "2026-07-29T20:53:46Z"
    assert paper["updated"] == "2026-07-30T10:00:00Z"
    assert paper["primary_category"] == "q-fin.PM"
    assert paper["categories"] == ["q-fin.PM", "q-fin.RM"]
    assert paper["authors"] == ["Ada First", "Bob Second"]
    assert paper["pdf_url"].endswith(".pdf") or "/pdf/" in paper["pdf_url"]
    assert paper["journal_ref"] == "J. Fake Finance 1(2026), 1-20"
    assert "factor_brief" not in paper
    assert "mode='read'" in payload["next_step"]


def test_arxiv_read_reports_silently_dropped_ids():
    payload = _brief(["2607.27461v2", "9999.99999"], _response(text=_ARXIV_FEED))
    assert payload["ok"] is True
    assert payload["returned"] == 1
    assert payload["missing_ids"] == ["9999.99999"]


def test_arxiv_read_clamps_the_id_batch():
    ids = [f"240{i}.0000{i}" for i in range(30)]
    with patch.object(
        rpt, "throttled_get", return_value=_response(text=_ARXIV_FEED)
    ) as mock_get:
        payload = json.loads(ResearchPapersTool().execute(mode="read", paper_ids=ids))
    assert payload["requested"] == rpt._MAX_READ_IDS
    assert mock_get.call_args.kwargs["params"]["id_list"].count(",") == rpt._MAX_READ_IDS - 1


def test_arxiv_error_entry_becomes_an_error_envelope():
    payload = _brief(["2607.27461"], _response(text=_ARXIV_ERROR_FEED, status=400))
    assert payload["ok"] is False
    assert "arXiv rejected the query" in payload["error"]
    # The reason itself must survive, not just the status code.
    assert "start must be an integer" in payload["error"]


def test_arxiv_error_id_outside_api_errors_still_surfaces_the_reason():
    payload = _brief(["2607.27461"], _response(text=_ARXIV_MANUAL_ERROR_FEED, status=400))
    assert payload["ok"] is False
    assert "sortBy must be in" in payload["error"]


def test_unparseable_body_becomes_an_error_envelope():
    payload = _brief(["2607.27461"], _response(text="<html>gateway timeout", status=504))
    assert payload["ok"] is False
    assert "unparseable XML" in payload["error"]


def test_transport_failure_becomes_an_error_envelope():
    with patch.object(rpt, "throttled_get", side_effect=RuntimeError("connection reset")):
        payload = json.loads(
            ResearchPapersTool().execute(mode="search", query="momentum")
        )
    assert payload["ok"] is False
    assert "connection reset" in payload["error"]


# --------------------------------------------------------------------------
# factor brief — extraction
# --------------------------------------------------------------------------


def test_factor_brief_extracts_every_field_with_evidence():
    brief = _brief(["2607.27461"], _response(text=_ARXIV_FEED))["papers"][0]["factor_brief"]

    assert brief["abstract_available"] is True
    assert "full text was NOT" in brief["extraction_scope"]
    assert brief["unstated_fields"] == []

    signal = brief["proposed_signal"]
    assert signal["status"] == "stated"
    assert signal["statements"][0]["quote"].startswith("We present a simple framework")
    assert signal["statements"][0]["section"] == "abstract"
    assert signal["statements"][0]["sentence_index"] == 0

    capabilities = {c["capability"] for c in brief["input_data_requirements"]}
    assert {"daily price history", "trading volume", "market capitalization"} <= capabilities
    for row in brief["input_data_requirements"]:
        # Every capability must quote a sentence that literally contains its match.
        assert row["matched_text"].lower() in row["evidence"]["quote"].lower()

    period = brief["claimed_backtest_period"]
    assert (period["start_year"], period["end_year"]) == (2022, 2024)
    assert period["matched_text"] == "January 2022 to December 2024"

    assert [m["market"] for m in brief["claimed_markets"]] == ["S&P 500"]

    sharpe = next(r for r in brief["claimed_performance"] if r["metric"] == "sharpe_ratio")
    assert sharpe["value"] == 1.06
    assert sharpe["claimed_by"] == "paper"
    assert sharpe["verified_by_vibe_trading"] is False
    assert "Sharpe" in sharpe["evidence"]["quote"]


def test_metric_named_without_a_number_keeps_the_claim_but_not_a_value():
    brief = _brief(["2607.27461"], _response(text=_ARXIV_FEED))["papers"][0]["factor_brief"]
    drawdown = next(r for r in brief["claimed_performance"] if r["metric"] == "max_drawdown")
    assert drawdown["value"] is None
    assert drawdown["value_status"] == _NOT_STATED
    assert "drawdown" in drawdown["evidence"]["quote"].lower()


def test_checks_are_derived_only_from_extracted_claims():
    brief = _brief(["2607.27461"], _response(text=_ARXIV_FEED))["papers"][0]["factor_brief"]
    checks = [c["check"] for c in brief["falsifiable_checks"]]
    assert any("Sharpe ratio = 1.06 on S&P 500 over 2022-2024" in c for c in checks)
    assert any("out-of-sample after 2024" in c for c in checks)
    assert any("obtainable for the target universe" in c for c in checks)
    for check in brief["falsifiable_checks"]:
        assert check["derived_from"]


def test_nothing_is_invented_for_a_paper_that_states_nothing():
    brief = _brief(["1111.11111"], _response(text=_ARXIV_BARE_FEED))["papers"][0]["factor_brief"]
    assert brief["input_data_requirements"] == {"status": _NOT_STATED}
    assert brief["claimed_backtest_period"] == {"status": _NOT_STATED}
    assert brief["claimed_markets"] == {"status": _NOT_STATED}
    assert brief["claimed_performance"] == {"status": _NOT_STATED}
    assert brief["falsifiable_checks"] == []
    assert set(brief["unstated_fields"]) >= {
        "input_data_requirements",
        "claimed_backtest_period",
        "claimed_markets",
        "claimed_performance",
    }


def test_claims_are_labelled_as_the_papers_own():
    payload = _brief(["2607.27461"], _response(text=_ARXIV_FEED))
    assert "None of it has been reproduced by a Vibe-Trading backtest" in payload["disclaimer"]
    brief = payload["papers"][0]["factor_brief"]
    assert brief["disclaimer"] == payload["disclaimer"]
    assert any("alpha-zoo" in a for a in brief["next_actions"])
    assert any("factor-research" in a for a in brief["next_actions"])


def test_version_and_dates_travel_with_the_brief_for_staleness_checks():
    paper = _brief(["2607.27461"], _response(text=_ARXIV_FEED))["papers"][0]
    assert (paper["version"], paper["published"][:4], paper["updated"][:4]) == ("v2", "2026", "2026")


# --------------------------------------------------------------------------
# extraction internals
# --------------------------------------------------------------------------


def test_unicode_dashes_are_folded_before_matching():
    period = rpt._extract_period(rpt._segments("", "Sampled over 1966–1999 monthly."))
    assert (period["start_year"], period["end_year"]) == (1966, 1999)


def test_a_reversed_year_range_is_not_a_window():
    assert rpt._extract_period(rpt._segments("", "Compare 2020-1990."))["status"] == _NOT_STATED


def test_a_lone_year_is_not_a_window():
    assert rpt._extract_period(rpt._segments("", "We use 2020 data."))["status"] == _NOT_STATED


def test_percent_written_out_is_still_a_percent():
    rows = rpt._extract_performance(
        rpt._segments("", "The spread earns 7.5 percent annually.")
    )
    annual = next(r for r in rows if r["metric"] == "annualized_return")
    assert (annual["value"], annual["unit"]) == (7.5, "percent")


def test_ic_ir_and_t_stat_are_read_off_the_text():
    rows = {
        r["metric"]: r["value"]
        for r in rpt._extract_performance(
            rpt._segments(
                "",
                "The information coefficient of 0.043 is stable. The "
                "t-statistic is 3.21. The information ratio of 0.85 holds.",
            )
        )
    }
    assert rows["information_coefficient"] == 0.043
    assert rows["t_statistic"] == 3.21
    assert rows["information_ratio"] == 0.85


def test_title_evidence_is_labelled_as_title():
    segments = rpt._segments("We propose a liquidity factor", "")
    assert rpt._extract_signal(segments)["statements"][0]["section"] == "title"


# --------------------------------------------------------------------------
# OpenAlex
# --------------------------------------------------------------------------


def test_openalex_search_reconstructs_the_inverted_abstract():
    payload = {"meta": {"count": 11064}, "results": [_OPENALEX_WORK]}
    with patch.object(
        rpt, "throttled_get", return_value=_response(payload=payload)
    ) as mock_get:
        out = json.loads(
            ResearchPapersTool().execute(
                mode="search", source="openalex", query="liquidity risk",
                start_date="2000-01-01", end_date="2010-12-31",
            )
        )

    assert mock_get.call_args.kwargs["host_key"] == "openalex"
    # OpenAlex runs its own full-text search, so there is no phrase widening.
    assert out["query_mode"] == "full_text"
    params = mock_get.call_args.kwargs["params"]
    assert params["filter"] == "from_publication_date:2000-01-01,to_publication_date:2010-12-31"
    assert params["search"] == "liquidity risk"

    paper = out["papers"][0]
    assert out["total_available"] == 11064
    assert paper["paper_id"] == "W3021190191"
    assert paper["journal_ref"] == "Journal of Political Economy"
    assert paper["doi"] == "https://doi.org/10.1086/374184"
    assert paper["cited_by_count"] == 5658
    assert paper["abstract"] == _OPENALEX_ABSTRACT


def test_openalex_read_batches_ids_into_one_request():
    # Probed live: an unknown id inside a pipe-OR filter answers 200 and is just
    # absent from `results`, exactly like arXiv silently dropping an id.
    payload = {"meta": {"count": 1}, "results": [_OPENALEX_WORK]}
    with patch.object(
        rpt, "throttled_get", return_value=_response(payload=payload)
    ) as mock_get:
        out = json.loads(
            ResearchPapersTool().execute(
                mode="read", source="openalex", paper_ids=["W3021190191", "W99999"]
            )
        )

    assert mock_get.call_count == 1
    assert mock_get.call_args.kwargs["params"]["filter"] == (
        "openalex_id:W3021190191|W99999"
    )
    assert out["returned"] == 1
    assert out["missing_ids"] == ["W99999"]
    brief = out["papers"][0]["factor_brief"]
    assert brief["proposed_signal"]["statements"][0]["quote"].startswith("Our monthly liquidity")
    assert (
        brief["claimed_backtest_period"]["start_year"],
        brief["claimed_backtest_period"]["end_year"],
    ) == (1966, 1999)
    assert [m["market"] for m in brief["claimed_markets"]] == ["US equities"]
    annual = next(r for r in brief["claimed_performance"] if r["metric"] == "annualized_return")
    assert annual["value"] == 7.5


def test_openalex_splits_work_ids_and_dois_into_separate_batches():
    # Live probe: mixing a DOI into the openalex_id filter answers
    # {"error": "Invalid query parameters error."}, so the two kinds cannot share
    # one request -- but each kind accepts pipe-OR on its own.
    responses = [
        _response(payload={"meta": {"count": 1}, "results": [_OPENALEX_WORK]}),
        _response(payload={"meta": {"count": 0}, "results": []}),
    ]
    with patch.object(rpt, "throttled_get", side_effect=responses) as mock_get:
        out = json.loads(
            ResearchPapersTool().execute(
                mode="read",
                source="openalex",
                paper_ids=[
                    "https://openalex.org/W3021190191",
                    "https://doi.org/10.1086/999999",
                    "not-an-id",
                ],
            )
        )

    filters = [call.kwargs["params"]["filter"] for call in mock_get.call_args_list]
    assert filters == ["openalex_id:W3021190191", "doi:10.1086/999999"]
    assert out["returned"] == 1
    # The unusable id costs no request at all.
    assert set(out["missing_ids"]) == {"https://doi.org/10.1086/999999", "not-an-id"}


def test_openalex_batch_failure_falls_back_to_one_request_per_id():
    responses = [
        _response(text="<html>500", status=500),
        _response(payload=_OPENALEX_WORK),
        _response(text="<html>404", status=404),
    ]
    with patch.object(rpt, "throttled_get", side_effect=responses) as mock_get:
        out = json.loads(
            ResearchPapersTool().execute(
                mode="read", source="openalex", paper_ids=["W3021190191", "W99999"]
            )
        )

    assert mock_get.call_count == 3
    assert out["returned"] == 1
    assert out["missing_ids"] == ["W99999"]


def test_openalex_carries_the_record_update_stamp():
    # OpenAlex has no vN preprint counter; updated_date is the only staleness
    # handle it offers, and it is requested in `select` (verified live).
    payload = {"meta": {"count": 1}, "results": [_OPENALEX_WORK]}
    with patch.object(
        rpt, "throttled_get", return_value=_response(payload=payload)
    ) as mock_get:
        out = json.loads(
            ResearchPapersTool().execute(
                mode="read", source="openalex", paper_ids=["W3021190191"]
            )
        )
    assert "updated_date" in mock_get.call_args.kwargs["params"]["select"]
    assert out["papers"][0]["updated"] == "2026-08-01T09:00:35.917206"
    assert out["papers"][0]["version"] == "publishedVersion"


def test_openalex_record_without_an_abstract_extracts_nothing():
    payload = {"meta": {"count": 1}, "results": [_OPENALEX_NO_ABSTRACT]}
    with patch.object(rpt, "throttled_get", return_value=_response(payload=payload)):
        out = json.loads(
            ResearchPapersTool().execute(
                mode="read", source="openalex", paper_ids=["W3123379704"]
            )
        )
    brief = out["papers"][0]["factor_brief"]
    assert brief["abstract_available"] is False
    assert brief["falsifiable_checks"] == []
    assert brief["proposed_signal"] == {"status": _NOT_STATED}
    assert "no abstract" in brief["note"]


def test_openalex_mailto_is_env_driven_and_absent_by_default(monkeypatch):
    monkeypatch.delenv(rpt._OPENALEX_MAILTO_ENV, raising=False)
    with patch.object(
        rpt, "throttled_get", return_value=_response(payload={"results": [], "meta": {}})
    ) as mock_get:
        ResearchPapersTool().execute(mode="search", source="openalex", query="x")
    assert "mailto" not in mock_get.call_args.kwargs["params"]

    # The env value is read through the cached EnvConfig singleton, which the
    # first call above populated. Changing os.environ mid-test is only visible
    # after the same reset settings_routes.py performs when it rewrites .env.
    monkeypatch.setenv(rpt._OPENALEX_MAILTO_ENV, "team@example.com")
    reset_env_config()
    with patch.object(
        rpt, "throttled_get", return_value=_response(payload={"results": [], "meta": {}})
    ) as mock_get:
        ResearchPapersTool().execute(mode="search", source="openalex", query="x")
    assert mock_get.call_args.kwargs["params"]["mailto"] == "team@example.com"


def test_openalex_non_json_body_becomes_an_error_envelope():
    with patch.object(rpt, "throttled_get", return_value=_response(text="<html>", status=200)):
        out = json.loads(
            ResearchPapersTool().execute(mode="search", source="openalex", query="x")
        )
    assert out["ok"] is False
    assert "non-JSON" in out["error"]


# --------------------------------------------------------------------------
# registry contract
# --------------------------------------------------------------------------


def test_tool_contract():
    tool = ResearchPapersTool()
    assert tool.name == "research_papers"
    assert tool.is_readonly is True
    assert tool.repeatable is True
    assert tool.check_available() is True
    schema = tool.to_openai_schema()["function"]
    assert schema["parameters"]["required"] == ["mode"]
    assert set(schema["parameters"]["properties"]) == {
        "mode", "source", "query", "categories", "start_date", "end_date",
        "max_results", "sort_by", "paper_ids",
    }


# --------------------------------------------------------------------------
# metric-claim context gate
#
# Two paired corpora. The negatives are sentences in which a metric NAME occurs
# in some other sense; registering the metric there puts a claim in the brief
# that the paper never made -- a value-less claim is still a fabricated claim,
# and it still produces a falsifiable_check telling the agent to go chase a
# number that does not exist. The positives are the same metrics genuinely
# claimed, and exist so the gate cannot be "fixed" by simply extracting less.
#
# Measured with these two sets (see the module docstring for the rule):
#   before the gate: 17/17 positives registered (16/17 with the right value),
#                    12/16 negatives falsely registered
#   after the gate:  17/17 positives registered (17/17 with the right value),
#                     0/16 negatives falsely registered
# --------------------------------------------------------------------------

_METRIC_POSITIVES = [
    ("The strategy attains a Sharpe ratio of 1.8.", "sharpe_ratio", 1.8),
    ("Sharpe ratios exceed one in every subperiod.", "sharpe_ratio", None),
    ("We report an information ratio of 0.85 for the tilted portfolio.", "information_ratio", 0.85),
    ("The annualized return of the long leg is 12.3%.", "annualized_return", 12.3),
    ("The spread earns 7.5 percent annually.", "annualized_return", 7.5),
    ("The long-short alpha is 6.2% per year.", "alpha", 6.2),
    ("The strategy delivers significant alpha after controlling for size and value.", "alpha", None),
    ("Our factor earns an excess return of 4.2% per year relative to the market.", "excess_return", 4.2),
    ("Abnormal returns average 1.4% in the month after the event.", "excess_return", 1.4),
    ("The signal has an IC of 0.06 out of sample.", "information_coefficient", 0.06),
    # A bare IC counts once the paper has spelled the term out.
    ("We compute the information coefficient (IC) each month. The IC is stable across subsamples.",
     "information_coefficient", None),
    ("The spread carries a t-statistic of 3.4.", "t_statistic", 3.4),
    ("Maximum drawdown is 18.4% over the sample.", "max_drawdown", 18.4),
    ("The maximum drawdown is reported in the appendix.", "max_drawdown", None),
    ("The hit rate of the rule is 54%.", "hit_rate", 54.0),
    ("Directional accuracy reaches 58% for daily stock returns.", "hit_rate", 58.0),
    ("Our classifier attains 62% accuracy in predicting next-day stock returns.", "hit_rate", 62.0),
]

_METRIC_NEGATIVES = [
    # The reported bug: an integrated circuit is not an information coefficient.
    ("The IC engine processed 15 files.", "information_coefficient"),
    ("The IC layout of the chip is described in Section 4.", "information_coefficient"),
    ("The IC is discussed at length in the literature review.", "information_coefficient"),
    # The reported sibling: an estimator's accuracy is not a trading hit rate.
    ("We evaluate the accuracy of the estimator under misspecification.", "hit_rate"),
    ("Numerical accuracy of the solver degrades for stiff systems.", "hit_rate"),
    ("Model accuracy on the ImageNet suite is not our concern.", "hit_rate"),
    # A rebalancing schedule is not an annualized return.
    ("The portfolio is rebalanced annually using calendar rules.", "annualized_return"),
    ("We rebalance the book annually and report turnover.", "annualized_return"),
    ("Positions are held for a year and rolled forward.", "annualized_return"),
    # Every other sense of the word "alpha".
    ("Cronbach's alpha for the survey instrument is 0.81.", "alpha"),
    ("We set the significance level alpha to 0.05 throughout the analysis.", "alpha"),
    ("The alpha channel occupies 25% of the market data buffer.", "alpha"),
    ("Alpha decay in semiconductor packaging is unrelated to our setting.", "alpha"),
    # Word-boundary bleed: "emergent statistical", "constituent values".
    ("We exploit emergent statistical properties observed since 2019.", "t_statistic"),
    ("The constituent values reached 42% in the sample.", "t_statistic"),
    ("We sort the alphabetical list and find 12% of names respond.", "alpha"),
]


def _claimed(abstract):
    """Extract claimed_performance rows keyed by metric.

    Args:
        abstract: Abstract text to run the brief over.

    Returns:
        ``{metric: row}``; empty when nothing was claimed.
    """
    brief = rpt._factor_brief({"title": "Test", "abstract": abstract}, "arxiv")
    claimed = brief["claimed_performance"]
    return {r["metric"]: r for r in claimed} if isinstance(claimed, list) else {}


@pytest.mark.parametrize("abstract, forbidden", _METRIC_NEGATIVES)
def test_a_metric_name_in_another_sense_registers_no_claim(abstract, forbidden):
    brief = rpt._factor_brief({"title": "Test", "abstract": abstract}, "arxiv")
    assert forbidden not in _claimed(abstract)
    # No claim means no reproduction gate either -- that is the whole point:
    # a value-less claim still emits a check telling the agent to hunt a number.
    assert all(forbidden not in c["check"] for c in brief["falsifiable_checks"])


@pytest.mark.parametrize("abstract, metric, value", _METRIC_POSITIVES)
def test_genuine_metrics_still_extract(abstract, metric, value):
    row = _claimed(abstract).get(metric)
    assert row is not None, "the gate must not be paid for by dropping real claims"
    assert row.get("value") == value
    if value is None:
        assert row["value_status"] == _NOT_STATED
    assert row["evidence"]["quote"]


def test_the_gate_is_measurably_better_on_both_sides():
    """The precision/recall claim in the section header, as an executable check."""
    registered = sum(
        1 for abstract, metric, _ in _METRIC_POSITIVES if metric in _claimed(abstract)
    )
    correct_values = sum(
        1 for abstract, metric, value in _METRIC_POSITIVES
        if _claimed(abstract).get(metric, {}).get("value") == value
    )
    false_positives = sum(
        1 for abstract, metric in _METRIC_NEGATIVES if metric in _claimed(abstract)
    )
    assert (registered, correct_values, false_positives) == (
        len(_METRIC_POSITIVES), len(_METRIC_POSITIVES), 0
    )


@pytest.mark.parametrize(
    "abstract, metric",
    [
        # All three are verbatim from live arXiv q-fin abstracts, and all three
        # made the extractor state a number the paper never stated.
        # "F1" was read as the information coefficient's value 1.0.
        ("Our framework employs rigorous quantitative metrics, including Sharpe "
         "ratio, maximum drawdown, Sortino ratio, information coefficient, F1 "
         "score and precision.", "information_coefficient"),
        # A pairwise correlation was read as the paper's alpha.
        ("We present formulas for 101 real-life quantitative trading alphas. The "
         "average pair-wise correlation of these alphas is low, 15.9%.", "alpha"),
        # An en-dashed range folds to "55--57%", which read as the number -57.
        ("Most models struggle to exceed 55--57% accuracy on stock returns.",
         "hit_rate"),
        # A percentage attached to a CHANGE in the metric is not the metric.
        # The percent-first patterns read every one of these as the level.
        ("Our model yields a 3% accuracy improvement over the benchmark for "
         "S&P 500 stocks.", "hit_rate"),
        ("The method delivers a 2.4 percent accuracy gain relative to the "
         "baseline on equity returns.", "hit_rate"),
        ("The overlay adds a 4% win rate improvement for the portfolio.",
         "hit_rate"),
        ("The overlay achieves a 10% maximum drawdown reduction for the "
         "portfolio.", "max_drawdown"),
        ("We document a 20% alpha decay per month in the cross-section of "
         "stocks.", "alpha"),
        # The same shape read forwards.
        ("The strategy shows an accuracy improvement of 3% on stock returns.",
         "hit_rate"),
        ("We report a maximum drawdown reduction of 10% for the portfolio.",
         "max_drawdown"),
    ],
)
def test_a_number_the_paper_never_attached_to_the_metric_is_not_its_value(abstract, metric):
    row = _claimed(abstract).get(metric)
    assert row is None or row["value"] is None


@pytest.mark.parametrize(
    "abstract, metric, value",
    [
        # The delta guard must not eat the level stated in the same shape: these
        # are the percent-first phrasings the forward-only patterns used to miss.
        ("The long-short portfolio earns a 37 percent alpha per year.", "alpha", 37.0),
        ("The trading model attains 96.41% accuracy on stock returns.", "hit_rate", 96.41),
        ("We obtain a 60% hit rate on the portfolio.", "hit_rate", 60.0),
        # "maximum" needs its own space in the alternation, or the canonical
        # phrasing silently falls through to value: null.
        ("The strategy suffers an 18% maximum drawdown.", "max_drawdown", 18.0),
        ("The portfolio shows a 22% drawdown over the sample.", "max_drawdown", 22.0),
    ],
)
def test_a_level_stated_percent_first_is_still_extracted(abstract, metric, value):
    assert _claimed(abstract).get(metric, {}).get("value") == value


def test_an_ambiguous_alias_used_as_a_modifier_is_not_a_metric():
    assert rpt._is_compound_modifier("The IC engine ran.", 4, 6) is True
    assert rpt._is_compound_modifier("The IC of 0.06 holds.", 4, 6) is False
    # "values" is a legitimate head noun for a metric, "engine" is not.
    assert rpt._is_compound_modifier("The IC values are stable.", 4, 6) is False


def test_a_number_behind_an_unrelated_word_is_not_linked_to_the_alias():
    sentence = "The IC engine processed 15 files."
    assert rpt._linked_number(sentence, 4, 6) is False
    sentence = "The IC of 0.06 survives."
    assert rpt._linked_number(sentence, 4, 6) is True
    # The number may also precede the alias ("7.5 percent annually").
    sentence = "The spread earns 7.5 percent annually."
    assert rpt._linked_number(sentence, 29, 37) is True


# --------------------------------------------------------------------------
# repeated claims, sentence boundaries
# --------------------------------------------------------------------------


def test_every_stated_figure_for_a_metric_survives_not_just_the_first():
    rows = rpt._extract_performance(rpt._segments(
        "",
        "The Sharpe ratio is 1.42 in the full sample. The Sharpe ratio of 0.91 "
        "holds after costs. Sharpe ratios of 1.42 recur in the appendix.",
    ))
    sharpe = next(r for r in rows if r["metric"] == "sharpe_ratio")
    assert sharpe["value"] == 1.42
    # The second figure travels; the repeat of the first does not duplicate.
    assert [o["value"] for o in sharpe["other_claimed_values"]] == [0.91]
    assert sharpe["other_claimed_values"][0]["evidence"]["sentence_index"] == 1

    checks = rpt._build_checks([sharpe], {"status": _NOT_STATED}, [], [])
    assert "more than one figure" in checks[0]["check"]
    assert len(checks[0]["derived_from"]) == 2


def test_an_abbreviation_period_is_not_a_sentence_boundary():
    # Splitting at "U.S." would truncate the sentence before its Sharpe number.
    assert rpt._split_sentences(
        "We regress on the U.S. Treasury yield and report a Sharpe of 1.2."
    ) == ["We regress on the U.S. Treasury yield and report a Sharpe of 1.2."]
    assert rpt._split_sentences("See Fig. 3 for the equity curve.") == [
        "See Fig. 3 for the equity curve."
    ]


def test_an_abbreviation_that_can_end_a_sentence_still_splits():
    # "et al." is deliberately NOT guarded: merging two sentences manufactures
    # corroboration, which is worse than losing a link.
    assert rpt._split_sentences("We follow Fama et al. The Sharpe is 1.2.") == [
        "We follow Fama et al.", "The Sharpe is 1.2."
    ]


def test_a_period_with_no_space_after_it_still_splits():
    # Left glued, the 15 sits in the same sentence as a metric name and can
    # corroborate it.
    sentences = rpt._split_sentences("The run wrote 15 files.The IC of 0.06 holds.")
    assert sentences == ["The run wrote 15 files.", "The IC of 0.06 holds."]


def test_a_glued_boundary_does_not_leak_a_number_into_the_next_claim():
    rows = rpt._extract_performance(
        rpt._segments("", "The IC engine processed 15 files.The strategy is simple.")
    )
    assert all(r["metric"] != "information_coefficient" for r in rows)
