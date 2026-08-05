"""Read-only academic-paper tool that ends in a factor-implementation brief.

Two free, no-key scholarly endpoints back this tool:

* **arXiv classic API** (``https://export.arxiv.org/api/query``) returns an Atom
  feed of preprints. It is the live source for ``q-fin.*`` plus the ``cs.LG`` /
  ``stat.ML`` work that never reaches a journal. Two field notes from probing
  the live endpoint: the ``http://`` form answers ``301`` (so the URL below is
  pinned to ``https``), and an unknown id in ``id_list`` is *silently dropped*
  from the feed rather than reported — the caller has to diff requested against
  returned ids, which :func:`_read_arxiv` does. Malformed queries answer
  ``400`` with a normal-looking feed whose single entry has the id
  ``https://arxiv.org/api/errors``; that entry's ``summary`` is the real message.
  A quoted phrase is matched as a phrase, which is what makes the search
  usable, but it also makes it brittle: probed live, ``"cross-sectional
  momentum"`` answers 9 hits while the same words AND-ed answer 5,990, and a
  four-word phrase answers 0. :func:`_arxiv_search` therefore falls back to an
  AND-of-terms query when the phrase returns nothing, and reports which form it
  used in ``query_mode``.
* **OpenAlex** (``https://api.openalex.org/works``) covers the *published*
  finance literature that arXiv structurally cannot — the canonical journal
  factor papers. Its abstracts arrive as an inverted index (word → token
  positions) which :func:`_openalex_abstract` re-linearizes. Coverage is
  partial: in a 25-record probe, 20 carried an abstract. A record with no
  abstract yields no extraction, and the tool says so instead of guessing.
  Unknown work ids answer ``404`` with an **HTML** body, so the JSON decode is
  guarded. Set ``VIBE_TRADING_OPENALEX_MAILTO`` to join OpenAlex's polite pool.
  Reads are batched: ``filter=openalex_id:W1|W2`` and ``filter=doi:d1|d2`` both
  accept pipe-OR (probed live), an unknown id inside a batch answers ``200``
  and is simply absent from ``results``, and mixing a DOI into the
  ``openalex_id`` filter answers a JSON ``Invalid query parameters error`` — so
  the two id kinds are split into at most one request each instead of one
  request per id.

Both hosts are hit through the project's shared per-host throttle so neither is
ever called un-throttled.

The point of the tool is not the paper card — it is ``factor_brief``, the
structured hand-off into the existing factor loop (the ``factor-research`` and
``alpha-zoo`` skills). The brief is built under one hard rule:

    **Nothing is inferred.** Every extracted value is anchored to the verbatim
    sentence it came from, tagged with its section and sentence index. A field
    with no matching sentence is emitted as ``"not stated in source"`` and is
    never back-filled from domain knowledge, from the title, or from what a
    paper of that kind "usually" does.

A metric name occurring in the text is *not* on its own a claim that the paper
reports that metric — "the IC engine processed 15 files" is not an information
coefficient and "the accuracy of the estimator" is not a hit rate. Registering
either would put a claim in the brief that the source never made, which breaks
the rule above just as badly as inventing a number. Metric names are therefore
split into two classes (see :data:`_PERFORMANCE_SPECS`): *self-sufficient*
domain terms ("Sharpe ratio", "maximum drawdown", "information coefficient"),
whose occurrence is evidence by itself, and *ambiguous* aliases (a bare ``IC``,
a bare ``alpha``, ``accuracy``, ``annually``), which register only when the
sentence corroborates them — see :func:`_admits_metric`. The gate is
deliberately asymmetric: it prefers a miss to a fabricated claim.

Both APIs expose the abstract only, never the body, so ``extraction_scope``
says so on every brief. Performance figures are the paper's *claims*; they are
labelled as such and are explicitly not Vibe-Trading backtest results.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, NamedTuple
from xml.etree import ElementTree

from backtest.loaders._http import resolve_min_interval, throttled_get
from src.agent.tools import BaseTool
from src.config.accessor import get_env_config

logger = logging.getLogger(__name__)

_ARXIV_URL = "https://export.arxiv.org/api/query"
_ARXIV_HOST_KEY = "arxiv"
_ARXIV_MIN_INTERVAL_ENV = "VIBE_TRADING_ARXIV_MIN_INTERVAL"
# arXiv asks API clients to leave ~3s between calls.
_ARXIV_DEFAULT_MIN_INTERVAL = 3.0
_ARXIV_ERROR_ID = "https://arxiv.org/api/errors"

_OPENALEX_URL = "https://api.openalex.org/works"
_OPENALEX_HOST_KEY = "openalex"
_OPENALEX_MIN_INTERVAL_ENV = "VIBE_TRADING_OPENALEX_MIN_INTERVAL"
_OPENALEX_DEFAULT_MIN_INTERVAL = 1.0
_OPENALEX_MAILTO_ENV = "VIBE_TRADING_OPENALEX_MAILTO"
_OPENALEX_SELECT = (
    "id,doi,title,publication_date,publication_year,type,authorships,"
    "primary_location,abstract_inverted_index,cited_by_count,updated_date"
)
# Read-mode ids come in two flavours and OpenAlex refuses to mix them in one
# filter ("'10.1086/374184' is not a valid OpenAlex ID"), so they are batched
# separately. Both forms accept the pipe-OR filter, verified live.
_OPENALEX_ID_RE = re.compile(r"(?:https?://openalex\.org/)?(W\d+)", re.I)
_DOI_RE = re.compile(r"(?:https?://(?:dx\.)?doi\.org/)?(10\.\d{4,9}/\S+)", re.I)
_DOI_PREFIX_RE = re.compile(r"^https?://(?:dx\.)?doi\.org/", re.I)

_TIMEOUT_S = 30.0
_SOURCES = ("arxiv", "openalex")
_MODES = ("search", "read")
_SORTS = ("relevance", "submitted", "updated")

# Defensive caps: an academic feed can be arbitrarily long and abstracts are
# multi-KB, so both the row count and the per-row text are bounded.
_DEFAULT_MAX_RESULTS = 10
_MAX_RESULTS = 25
_MAX_READ_IDS = 10
_MAX_ABSTRACT_CHARS = 4000
_MAX_AUTHORS = 12
# A paper can state the same metric several times (full sample vs subsample, our
# strategy vs the benchmark). Keeping only the first was silently hiding the
# rest, so the extras travel along, bounded.
_MAX_METRIC_CLAIMS = 4
# Terms an arXiv phrase query is decomposed into when the phrase finds nothing.
_MAX_QUERY_TERMS = 6

_NOT_STATED = "not stated in source"
_CLAIM_DISCLAIMER = (
    "Every figure under claimed_performance is what the PAPER claims. None of "
    "it has been reproduced by a Vibe-Trading backtest."
)

# Unicode the two feeds actually emit (OpenAlex abstracts carry U+2010 hyphens,
# arXiv abstracts carry en/em dashes) folded to ASCII before pattern matching.
_PUNCT_FOLD = {
    0x2010: "-", 0x2011: "-", 0x2012: "-", 0x2013: "-", 0x2014: "-", 0x2212: "-",
    0x2018: "'", 0x2019: "'", 0x201C: '"', 0x201D: '"', 0x00A0: " ",
}

# Sentence boundaries decide which words can corroborate which number, so a bad
# split is a correctness problem, not cosmetics. Two failure modes are guarded:
#   * a period inside an abbreviation ("the U.S. Treasury yield", "J. Smith")
#     is not a boundary -- splitting there truncates the sentence and detaches a
#     metric name from its number;
#   * a period with no space after it ("... 15 files.The IC engine ...") IS a
#     boundary; feeds do emit these, and leaving the two sentences glued lets a
#     number from one corroborate a keyword in the other.
# Only abbreviations that essentially never END a sentence are guarded. "et al."
# and "Inc." routinely do, and wrongly merging two sentences is the dangerous
# direction (it manufactures corroboration), whereas wrongly splitting one only
# costs a link. Every lookbehind is fixed-width because Python's re requires it.
_ABBREV_GUARD = (
    r"(?<!\b[A-Z]\.)(?<![A-Z]\.[A-Z]\.)(?<!\be\.g\.)(?<!\bi\.e\.)"
    r"(?<!\bcf\.)(?<!\bvs\.)(?<!\bFig\.)(?<!\bEq\.)(?<!\bNo\.)(?<!\bpp\.)"
    r"(?<!\bSec\.)(?<!\bRef\.)(?<!\bTab\.)(?<!\bDr\.)"
    r"(?<!\bProf\.)(?<!\bapprox\.)"
)
_SENTENCE_SPLIT = re.compile(
    rf"(?<=[.!?]){_ABBREV_GUARD}"
    rf"(?:\s+(?=[A-Z(\"$\\])|(?<=[a-z][a-z][.!?])(?=[A-Z][a-z]))"
)

# ---------------------------------------------------------------------------
# Extraction vocabularies. Each entry maps a literal surface form that must
# appear in the source text to a capability/market described in plain language.
# No tool names here on purpose: the brief states what DATA the paper needs, and
# the routing layer decides which loader can serve it.
# ---------------------------------------------------------------------------

_CAPABILITY_TERMS: tuple[tuple[str, str], ...] = (
    (r"daily (?:closing |close |adjusted )?price", "daily price history"),
    (r"\bclosing price", "daily price history"),
    (r"price history", "daily price history"),
    (r"monthly return", "monthly return history"),
    (r"daily return", "daily return history"),
    (r"trading volume", "trading volume"),
    (r"\bturnover\b", "turnover"),
    (r"market capitali[sz]ation|\bmarket cap\b", "market capitalization"),
    (r"limit order book|order book|order flow", "order-book / order-flow microstructure data"),
    (r"tick[- ]by[- ]tick|\btick data\b", "tick data"),
    (r"high[- ]frequency|intraday", "intraday bars or higher-frequency data"),
    (r"bid[- ]ask", "bid-ask quotes"),
    (r"fundamental(?:s| data| variable)", "company fundamentals"),
    (r"accounting (?:data|variable|information)", "company fundamentals"),
    (r"balance sheet|income statement|cash flow statement", "financial statements"),
    (r"\bearnings\b", "earnings data"),
    (r"analyst (?:forecast|estimate|recommendation|revision)", "analyst estimates"),
    (r"\bnews\b|headline|press release", "news text"),
    (r"social media|twitter|\bx\.com\b|reddit|stocktwits", "social-media text"),
    (r"sentiment (?:score|data|index)", "sentiment scores"),
    (r"\boption(?:s)? (?:price|data|chain|market)|implied volatility", "options data"),
    (r"macroeconomic|interest rate|inflation|yield curve|term spread", "macroeconomic series"),
    (r"10-K|10-Q|\bSEC filing|annual report|regulatory filing", "regulatory filings"),
    (r"on[- ]chain|blockchain", "on-chain blockchain data"),
    (r"short interest|securities lending", "short-interest data"),
    (r"\bESG\b|sustainability rating", "ESG ratings"),
    (r"insider (?:trading|transaction|holding)", "insider transactions"),
    (r"fund flow|capital flow|mutual fund holding|institutional holding", "fund-flow / holdings data"),
    (r"\bfutures\b", "futures data"),
    (r"funding rate|open interest", "derivatives funding / open-interest data"),
    (r"credit rating|\bCDS\b", "credit data"),
    (r"satellite|alternative data|credit card transaction", "alternative data"),
)

_MARKET_TERMS: tuple[tuple[str, str], ...] = (
    (r"S&P\s?500|S\\&P\s?500|SP500", "S&P 500"),
    (r"Russell\s?\d{4}", "Russell index"),
    (r"NASDAQ|Nasdaq", "NASDAQ"),
    (r"\bNYSE\b", "NYSE"),
    (r"\bAMEX\b", "AMEX"),
    (r"CSI\s?300", "CSI 300"),
    (r"CSI\s?500", "CSI 500"),
    (r"A[- ]share|Shanghai Stock Exchange|Shenzhen Stock Exchange", "China A-share"),
    (r"Chinese (?:stock|equity|market)", "China equities"),
    (r"Hang Seng|Hong Kong (?:stock|equity|market)", "Hong Kong equities"),
    (r"Nikkei|TOPIX|Japanese (?:stock|equity|market)", "Japan equities"),
    (r"KOSPI|KOSDAQ|Korean (?:stock|equity|market)", "Korea equities"),
    (r"\bNSE\b|\bBSE\b|Nifty|Indian (?:stock|equity|market)", "India equities"),
    (r"FTSE|DAX|CAC\s?40|Euro\s?Stoxx|European (?:stock|equity|market)", "Europe equities"),
    (r"\bUS (?:stock|equit|market)|U\.S\. (?:stock|equit|market)", "US equities"),
    (r"cryptocurrenc|crypto market|Bitcoin|\bBTC\b|Ethereum|\bETH\b", "cryptocurrency"),
    (r"foreign exchange|\bforex\b|\bFX\b|currency market", "foreign exchange"),
    (r"commodit", "commodities"),
    (r"Treasury|government bond|corporate bond|\bbond market\b", "fixed income"),
    (r"emerging market", "emerging markets"),
)

# Sentences in which the paper introduces its own contribution. These only
# SELECT which sentence to cite; the sentence is returned verbatim, never
# paraphrased, so a loose match costs precision but can never fabricate.
_SIGNAL_VERB = (
    r"(?:propose|introduce|construct|develop|present|design|build|derive|"
    r"define|document|identify)"
)
_SIGNAL_NOUN = (
    r"(?:factor|signal|alpha|predictor|indicator|anomaly|strateg(?:y|ies)|"
    r"feature|characteristic|measure|framework|model|method|approach|"
    r"portfolio|rule|score)"
)
_SIGNAL_SENTENCES = (
    re.compile(rf"\b{_SIGNAL_VERB}\w*\b[^.]{{0,120}}?\b{_SIGNAL_NOUN}\b", re.I),
    re.compile(
        rf"\b{_SIGNAL_NOUN}\b[^.]{{0,80}}?\bis\s+{_SIGNAL_VERB}(?:d|ed)\b", re.I
    ),
    # "Our monthly liquidity measure ..." — a possessive claim of authorship is
    # as explicit a statement of the contribution as a proposal verb.
    re.compile(rf"\bour\b(?:\s+[\w-]+){{0,4}}\s+{_SIGNAL_NOUN}\b", re.I),
)

_MONTHS = (
    "January|February|March|April|May|June|July|August|September|October|"
    "November|December"
)
_YEAR = r"(?:18|19|20|21)\d{2}"
_RANGE_SEP = r"(?:-|to|through|until|till)"
_PERIOD_PATTERNS = (
    re.compile(
        rf"(?:{_MONTHS})\s+({_YEAR})\s*{_RANGE_SEP}\s*(?:{_MONTHS})\s+({_YEAR})",
        re.I,
    ),
    re.compile(rf"\bbetween\s+({_YEAR})\s+and\s+({_YEAR})\b", re.I),
    re.compile(rf"\b({_YEAR})\s*{_RANGE_SEP}\s*({_YEAR})\b", re.I),
)

_PCT = r"(?:\\?%|percent|per cent|percentage points?)"
# The captured number must start a token. Without the lookbehind, the range
# "55--57% accuracy" (an en-dash folded to ASCII) reads as the number -57, and
# "0.06" can be re-entered at "06".
_NUM = r"(?<![\w.-])(-?\d+(?:\.\d+)?)"

# A percentage attached to a CHANGE in a metric is not the metric. "a 3%
# accuracy improvement", "a 10% drawdown reduction" and "a 20% alpha decay"
# each state a delta; reading one as the level fabricates a number the paper
# never claimed, which is the exact failure this module's gate exists to
# prevent. The guard sits immediately after the alias and consumes nothing, so
# the scan simply moves on to the next alias in the sentence.
_NOT_DELTA = (
    r"(?!\s*[-–]?\s*(?:improvement|gain|increase|uplift|boost|lift|"
    r"reduction|decrease|decline|decay|drop|deterioration|degradation|"
    r"loss|erosion|differential)s?\b)"
)

# Evidence a sentence can offer for an AMBIGUOUS metric alias. A spec lists the
# kinds it will accept; any one of them is enough.
_EV_NUMBER = "linked_number"        # a numeral connected to the alias
_EV_CANONICAL = "canonical_defined"  # the unambiguous long form is in the paper
_EV_CONTEXT = "result_context"       # the sentence is about trading performance


class _MetricSpec(NamedTuple):
    """One claimable performance metric and the evidence it requires.

    Attributes:
        metric: Machine key emitted in the brief.
        label: Human label used in prose and in falsifiable checks.
        unit: ``"ratio"`` / ``"percent"`` / ``"t"``.
        value_patterns: Ordered regexes whose group 1 is the claimed number.
        strong: Regex of self-sufficient surface forms. An occurrence is on its
            own enough to register the claim.
        weak: Regex of ambiguous surface forms (bare abbreviations, ordinary
            English words). An occurrence registers nothing unless the sentence
            corroborates it.
        weak_evidence: Which corroborations this alias accepts; empty means the
            alias never registers on its own.
        weak_veto: Regex of senses that are definitively NOT this metric. A hit
            anywhere in the sentence disqualifies the weak alias outright.
    """

    metric: str
    label: str
    unit: str
    value_patterns: tuple[str, ...]
    strong: str | None
    weak: str | None = None
    weak_evidence: frozenset[str] = frozenset()
    weak_veto: str | None = None


_PERFORMANCE_SPECS: tuple[_MetricSpec, ...] = (
    _MetricSpec(
        "sharpe_ratio", "Sharpe ratio", "ratio",
        (rf"sharpe(?:\s+ratios?|s)?(?:\s+(?:of|is|are|was|were|at|to|reaching|equal\s+to)|\s*[:=])?\s*\$?{_NUM}\$?",),
        strong=r"sharpe",
    ),
    _MetricSpec(
        "information_ratio", "information ratio", "ratio",
        (rf"information\s+ratios?(?:\s+(?:of|is|are|was|were|at|to)|\s*[:=])?\s*\$?{_NUM}\$?",),
        strong=r"information ratio",
    ),
    _MetricSpec(
        "annualized_return", "annualized return", "percent",
        (
            rf"annuali[sz]ed\s+returns?{_NOT_DELTA}[^.]{{0,40}}?{_NUM}\s*{_PCT}",
            rf"{_NUM}\s*{_PCT}\s*(?:per\s+annum|annually|a\s+year|per\s+year)",
        ),
        strong=r"annuali[sz]ed return",
        # "rebalanced annually" is a schedule, not a return. Only a number tied
        # to the adverb makes it one.
        weak=r"per\s+annum|annually|per\s+year",
        weak_evidence=frozenset({_EV_NUMBER}),
    ),
    _MetricSpec(
        "alpha", "alpha", "percent",
        # \b on BOTH sides: a bare \balpha prefix also matches "alphabetical",
        # which turned an unrelated percentage into a claimed alpha.
        (
            rf"\balphas?\b{_NOT_DELTA}[^.]{{0,40}}?{_NUM}\s*{_PCT}",
            rf"{_NUM}\s*{_PCT}\s+alphas?\b{_NOT_DELTA}",
        ),
        strong=None,
        # "alpha" has no unambiguous long form: Jensen's alpha, a significance
        # level, Cronbach's alpha and an alpha channel are all just "alpha". It
        # only counts inside a sentence that is about trading performance.
        weak=r"\balphas?\b",
        weak_evidence=frozenset({_EV_CONTEXT}),
        weak_veto=(
            r"significance level|confidence level|type\s*i\s+error|cronbach|"
            # "alpha decay" is deliberately absent: in finance it is a real
            # thing a paper can claim, and the semiconductor sense is already
            # excluded by the result-context requirement.
            r"alpha[- ]?(?:channel|particle|version|release|numeric|blend)|"
            r"learning rate|smoothing (?:parameter|factor)|dirichlet"
        ),
    ),
    _MetricSpec(
        "excess_return", "excess / abnormal return", "percent",
        (rf"(?:excess|abnormal|risk[- ]adjusted)\s+returns?{_NOT_DELTA}[^.]{{0,40}}?{_NUM}\s*{_PCT}",),
        strong=r"excess return|abnormal return",
    ),
    _MetricSpec(
        "information_coefficient", "information coefficient (IC)", "ratio",
        # The bare "IC" alias is a weak trigger, so it may not reach across 40
        # chars of slack: the number must be linked to it ("IC of 0.05",
        # "IC = 0.05"). Otherwise "The IC engine processed 15 files" scored 15.
        (
            rf"information\s+coefficients?{_NOT_DELTA}[^.]{{0,40}}?{_NUM}",
            rf"\bIC\b\s*(?:of|is|are|was|were|at|equal\s+to|reaching)?\s*[:=]?\s*{_NUM}",
        ),
        strong=r"information\s+coefficients?",
        # A bare IC counts only next to its own number, or once the paper has
        # spelled the term out somewhere ("the information coefficient (IC)").
        weak=r"\bIC\b",
        weak_evidence=frozenset({_EV_NUMBER, _EV_CANONICAL}),
        weak_veto=r"\bIC\s*(?:chip|die|wafer|fabricat)|integrated circuit",
    ),
    _MetricSpec(
        "t_statistic", "t-statistic", "t",
        # Leading \b is load-bearing: without it "emergent statistical" and
        # "constituent values" match as "t stat" / "t value" across the word
        # boundary and bind whatever number follows.
        (rf"\bt-?\s?(?:stat(?:istic)?s?|values?){_NOT_DELTA}[^.]{{0,30}}?{_NUM}",),
        strong=r"\bt-?\s?stat|\bt-?\s?value",
    ),
    _MetricSpec(
        "max_drawdown", "maximum drawdown", "percent",
        (
            rf"(?:maximum|max\.?)\s+drawdowns?{_NOT_DELTA}[^.]{{0,40}}?{_NUM}\s*{_PCT}",
            # The \s+ after "maximum" is load-bearing: without it the branch
            # only ever matched "18% max drawdown" / "18% drawdown" and the
            # canonical "18% maximum drawdown" fell through to value: null.
            rf"{_NUM}\s*{_PCT}\s+(?:maximum\s+|max\.?\s*)?drawdowns?{_NOT_DELTA}",
        ),
        strong=r"drawdown",
    ),
    _MetricSpec(
        "hit_rate", "hit rate / accuracy", "percent",
        (
            rf"(?:hit\s+rate|win\s+rate|(?:directional\s+)?accuracy){_NOT_DELTA}[^.]{{0,40}}?{_NUM}\s*{_PCT}",
            rf"{_NUM}\s*{_PCT}\s+(?:directional\s+)?(?:accuracy|hit\s+rate|win\s+rate){_NOT_DELTA}",
        ),
        strong=r"hit\s+rate|win\s+rate|directional\s+accuracy",
        # Bare "accuracy" is an ordinary English word: the accuracy of an
        # estimator, of a solver, of an ImageNet run. Only a trading-performance
        # sentence turns it into a claimed hit rate.
        weak=r"accurac(?:y|ies)",
        weak_evidence=frozenset({_EV_CONTEXT}),
        weak_veto=r"numerical accuracy|accuracy of the (?:estimator|approximation|solver|integrator)",
    ),
)

# ---------------------------------------------------------------------------
# Context gate for ambiguous metric aliases.
#
# A number counts as belonging to an alias only when everything between the two
# is connective: copulas, hedges, comparatives, determiners, and the handful of
# nouns a result is normally attributed to. "IC of 0.06" links; "IC engine
# processed 15 files" does not, because "engine"/"processed" are not connective.
# ---------------------------------------------------------------------------

_LINK_TOKENS = frozenset("""
a about above achieve achieved achieves achieving all almost an and approximately approx
are around as at attain attained attains attaining average averaged averages averaging
be been below by close compared delivered delivers deliver delivering equal equalling
equals estimated exceed exceeded exceeding exceeds generate generated generates generating
greater high higher in is its just larger less lower more near nearly obtain obtained
obtains of only or our over per percent percentage point points produce produced produces
producing record recorded records report reported reports reporting reach reached reaches
reaching respectively roughly significant significantly smaller some than that the their
these this those to up versus vs was were with yield yielded yields yielding
annual annualized annualised monthly daily weekly quarterly mean median sample
model models strategy strategies portfolio portfolios signal signals factor factors
method methods approach classifier predictor forecast forecasts prediction predictions
algorithm framework system rule
""".split())

# Nouns an alias may legitimately head ("IC values of 0.06", "alpha estimates").
# Used both as link tokens and to tell a head noun from a compound modifier.
_METRIC_HEAD_WORDS = frozenset("""
ratio ratios value values score scores statistic statistics coefficient coefficients
estimate estimates level levels measure measures metric metrics spread spreads
premium premiums premia return returns performance number numbers figure figures
result results term terms component components exposure exposures series
""".split())

_DETERMINERS = frozenset("a an the this that these those our its their his her one".split())

# Vocabulary that makes a sentence a statement about trading performance. Kept
# deliberately finance-specific: generic research words ("evaluate", "benchmark",
# "estimator") are what let "the accuracy of the estimator" through.
_RESULT_CONTEXT = re.compile(
    r"\b(?:portfolios?|strateg(?:y|ies)|trading|traded|trades?|backtest\w*|"
    r"out[- ]of[- ]sample|in[- ]sample|long[- /]short|risk[- ]adjusted|abnormal|"
    r"excess\s+returns?|investors?|markets?|stocks?|equit(?:y|ies)|returns?|"
    r"prices?|sharpe|profit\w*|hedg\w*|holdings?|positions?|assets?)\b",
    re.I,
)

_TOKEN = re.compile(r"\S+")
_NUMBER_TOKEN = re.compile(r"-?\d+(?:\.\d+)?")
_TOKEN_TRIM = "\"'()[]{}<>.,;:!?$~=%\\"
# How far a connective-only chain may run before the number stops being "linked".
_MAX_LINK_TOKENS = 6


def _linked_number(sentence: str, start: int, end: int) -> bool:
    """Check whether a numeral is bound to the alias at ``[start, end)``.

    Walks outward in both directions, one token at a time, and stops at the
    first token that is neither connective nor a metric head noun. A number
    reached before that stop is bound to the alias; a number reached after some
    unrelated word is not.

    Args:
        sentence: The sentence the alias was matched in.
        start: Start offset of the alias match.
        end: End offset of the alias match.

    Returns:
        True when a numeral is connected to the alias.
    """
    for chunk, backwards in ((sentence[end:], False), (sentence[:start], True)):
        words = _TOKEN.findall(chunk)
        if backwards:
            words.reverse()
        for word in words[:_MAX_LINK_TOKENS]:
            bare = word.strip(_TOKEN_TRIM).lower()
            if not bare:
                continue
            if _NUMBER_TOKEN.fullmatch(bare):
                return True
            if bare in _LINK_TOKENS or bare in _METRIC_HEAD_WORDS:
                continue
            break
    return False


def _is_compound_modifier(sentence: str, start: int, end: int) -> bool:
    """Check whether the alias is modifying a following noun instead of heading.

    ``the IC engine`` / ``the alpha channel`` use the alias as an adjective for
    something that is not a metric; ``the IC of 0.06`` / ``the alpha estimates``
    do not.

    Args:
        sentence: The sentence the alias was matched in.
        start: Start offset of the alias match.
        end: End offset of the alias match.

    Returns:
        True when the alias reads as a compound modifier.
    """
    following = re.match(r"\s+([A-Za-z][\w'-]*)", sentence[end:])
    preceding = re.search(r"([A-Za-z][\w'-]*)\s+$", sentence[:start])
    if following is None or preceding is None:
        return False
    if preceding.group(1).lower() not in _DETERMINERS:
        return False
    word = following.group(1).lower()
    return word not in _LINK_TOKENS and word not in _METRIC_HEAD_WORDS


def _admits_metric(spec: _MetricSpec, sentence: str, document: str) -> bool:
    """Decide whether a sentence may register a claim for one metric.

    A self-sufficient surface form needs nothing else. An ambiguous alias must
    survive the sense veto, must not read as a compound modifier, and must carry
    at least one of the corroborations the spec accepts.

    Args:
        spec: The metric being tested.
        sentence: Candidate sentence, already normalized.
        document: Title plus abstract, used for the canonical-form test.

    Returns:
        True when the sentence is admissible evidence for this metric.
    """
    if spec.strong and re.search(spec.strong, sentence, re.I):
        return True
    if not spec.weak:
        return False
    if spec.weak_veto and re.search(spec.weak_veto, sentence, re.I):
        return False

    corroborated = (
        _EV_CANONICAL in spec.weak_evidence
        and spec.strong is not None
        and re.search(spec.strong, document, re.I) is not None
    ) or (
        _EV_CONTEXT in spec.weak_evidence
        and _RESULT_CONTEXT.search(sentence) is not None
    )
    wants_number = _EV_NUMBER in spec.weak_evidence

    for match in re.finditer(spec.weak, sentence, re.I):
        if _is_compound_modifier(sentence, match.start(), match.end()):
            continue
        if corroborated:
            return True
        if wants_number and _linked_number(sentence, match.start(), match.end()):
            return True
    return False

_NEXT_ACTIONS = (
    "load_skill('alpha-zoo') first — check whether an equivalent factor already "
    "exists in the bundled zoos before reimplementing the paper.",
    "load_skill('factor-research') — build the factor panel plus the aligned "
    "forward-return panel, then run factor_analysis for IC / IR and quantile "
    "spreads on OUR data.",
    "Only after our own IC and backtest do the paper's claimed numbers become "
    "anything other than a claim; treat every falsifiable_check as a pass/fail "
    "gate on the reproduction, not as a result.",
)


def _error(message: str) -> str:
    """Build the failure envelope as a JSON string.

    Args:
        message: Human-readable error description.

    Returns:
        A ``{"ok": false, "error": ...}`` JSON string.
    """
    return json.dumps({"ok": False, "error": message}, ensure_ascii=False)


def _normalize(text: str) -> str:
    """Fold provider punctuation to ASCII and collapse whitespace.

    Args:
        text: Raw title or abstract straight off the feed.

    Returns:
        A single-line string safe to run the extraction regexes over.
    """
    return re.sub(r"\s+", " ", text.translate(_PUNCT_FOLD)).strip()


def _split_sentences(text: str) -> list[str]:
    """Split normalized text into sentences.

    Args:
        text: Whitespace-normalized paragraph.

    Returns:
        Non-empty sentence strings in source order.
    """
    return [s.strip() for s in _SENTENCE_SPLIT.split(text) if s.strip()]


def _evidence(section: str, index: int, sentence: str) -> dict[str, Any]:
    """Build the citation stub attached to every extracted value.

    Args:
        section: ``"title"`` or ``"abstract"``.
        index: Zero-based sentence index inside that section.
        sentence: The verbatim sentence the value was read from.

    Returns:
        A dict carrying the source location and the quoted sentence.
    """
    return {"section": section, "sentence_index": index, "quote": sentence}


def _segments(title: str, abstract: str) -> list[tuple[str, int, str]]:
    """Enumerate every citable ``(section, index, sentence)`` of a paper.

    Normalization is re-applied here (it is idempotent) so no caller can feed
    raw provider punctuation straight into the extractors and silently miss a
    match on an en-dash or a non-breaking space.

    Args:
        title: Paper title.
        abstract: Paper abstract; empty when the source carries none.

    Returns:
        The title as one segment followed by the abstract's sentences.
    """
    out: list[tuple[str, int, str]] = []
    if title := _normalize(title):
        out.append(("title", 0, title))
    for i, sentence in enumerate(_split_sentences(_normalize(abstract))):
        out.append(("abstract", i, sentence))
    return out


def _extract_signal(segments: list[tuple[str, int, str]]) -> dict[str, Any]:
    """Collect the sentences in which the paper states its own contribution.

    Sentences are returned verbatim — the tool never summarizes what the signal
    "really is", because that would be an inference.

    Args:
        segments: Output of :func:`_segments`.

    Returns:
        ``{"status": "stated", "statements": [...]}`` or ``{"status":
        "not stated in source"}``.
    """
    hits = [
        _evidence(section, index, sentence)
        for section, index, sentence in segments
        if any(p.search(sentence) for p in _SIGNAL_SENTENCES)
    ]
    if not hits:
        return {"status": _NOT_STATED}
    return {"status": "stated", "statements": hits}


def _extract_vocabulary(
    segments: list[tuple[str, int, str]],
    vocabulary: tuple[tuple[str, str], ...],
    label_key: str,
) -> list[dict[str, Any]]:
    """Match a literal-term vocabulary against the paper text.

    Args:
        segments: Output of :func:`_segments`.
        vocabulary: ``(pattern, label)`` pairs; the pattern must literally occur.
        label_key: Output key for the label (``"capability"`` / ``"market"``).

    Returns:
        One de-duplicated row per label, carrying the term actually matched and
        the sentence it was matched in.
    """
    found: dict[str, dict[str, Any]] = {}
    for section, index, sentence in segments:
        for pattern, label in vocabulary:
            if label in found:
                continue
            match = re.search(pattern, sentence, re.I)
            if match:
                found[label] = {
                    label_key: label,
                    "matched_text": match.group(0),
                    "evidence": _evidence(section, index, sentence),
                }
    return list(found.values())


def _extract_period(segments: list[tuple[str, int, str]]) -> dict[str, Any]:
    """Extract the sample window the paper says it tested over.

    Only explicit year ranges count. A lone year, or a phrase like "recent
    data", is not a window and is left unstated.

    Args:
        segments: Output of :func:`_segments`.

    Returns:
        ``{"status": "stated", "start_year", "end_year", "matched_text",
        "evidence"}`` or ``{"status": "not stated in source"}``.
    """
    for section, index, sentence in segments:
        for pattern in _PERIOD_PATTERNS:
            match = pattern.search(sentence)
            if not match:
                continue
            start, end = int(match.group(1)), int(match.group(2))
            if end < start:
                continue
            return {
                "status": "stated",
                "start_year": start,
                "end_year": end,
                "matched_text": match.group(0),
                "evidence": _evidence(section, index, sentence),
            }
    return {"status": _NOT_STATED}


def _extract_performance(segments: list[tuple[str, int, str]]) -> list[dict[str, Any]]:
    """Extract the performance figures the paper claims for itself.

    Only sentences that pass :func:`_admits_metric` for a metric can contribute
    to it, so a metric name used in an unrelated sense registers nothing at all.

    A metric whose name appears in an admissible sentence but whose number
    cannot be read off the text is still reported, with ``value: null`` and
    ``value_status`` set to ``"not stated in source"`` — the claim exists even
    when the magnitude does not, and dropping it would hide a claim.

    A paper often states the same metric more than once (full sample versus
    subsample, our strategy versus the benchmark). The first stated number stays
    the row's ``value``; the rest travel in ``other_claimed_values`` with their
    own evidence rather than being discarded.

    Args:
        segments: Output of :func:`_segments`.

    Returns:
        One row per metric found, each anchored to its sentence.
    """
    document = " ".join(sentence for _, _, sentence in segments)
    rows: list[dict[str, Any]] = []
    for spec in _PERFORMANCE_SPECS:
        base = {
            "metric": spec.metric,
            "label": spec.label,
            "unit": spec.unit,
            "claimed_by": "paper",
            "verified_by_vibe_trading": False,
        }
        values: list[dict[str, Any]] = []
        keyword_row: dict[str, Any] | None = None
        for section, index, sentence in segments:
            if not _admits_metric(spec, sentence, document):
                continue
            hit = None
            for pattern in spec.value_patterns:
                if hit := re.search(pattern, sentence, re.I):
                    break
            if hit is not None:
                value = float(hit.group(1))
                if all(v["value"] != value for v in values):
                    values.append({
                        "value": value,
                        "matched_text": hit.group(0),
                        "evidence": _evidence(section, index, sentence),
                    })
                if len(values) >= _MAX_METRIC_CLAIMS:
                    break
            elif keyword_row is None:
                keyword_row = {
                    **base,
                    "value": None,
                    "value_status": _NOT_STATED,
                    "evidence": _evidence(section, index, sentence),
                }
        if values:
            rows.append({**base, **values[0], "other_claimed_values": values[1:]})
        elif keyword_row is not None:
            rows.append(keyword_row)
    return rows


def _build_checks(
    performance: list[dict[str, Any]],
    period: dict[str, Any],
    markets: list[dict[str, Any]],
    capabilities: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Turn the extracted claims into pass/fail reproduction gates.

    Every check is assembled purely from fields that were actually extracted;
    an unstated field is spelled out as unstated inside the check text rather
    than being filled in. When nothing was extracted, no checks are emitted.

    Args:
        performance: Rows from :func:`_extract_performance`.
        period: Row from :func:`_extract_period`.
        markets: Rows from the market vocabulary pass.
        capabilities: Rows from the capability vocabulary pass.

    Returns:
        Check rows, each carrying the evidence it was derived from.
    """
    market_text = (
        ", ".join(m["market"] for m in markets) if markets else f"an unstated market ({_NOT_STATED})"
    )
    period_text = (
        f"{period['start_year']}-{period['end_year']}"
        if period.get("status") == "stated"
        else f"an unstated window ({_NOT_STATED})"
    )

    checks: list[dict[str, Any]] = []
    for row in performance:
        if row.get("value") is None:
            checks.append({
                "check": (
                    f"The paper claims a {row['label']} but states no number; "
                    f"read the number off the full text before any reproduction "
                    f"target can be set."
                ),
                "derived_from": row["evidence"],
            })
            continue
        unit = "%" if row["unit"] == "percent" else ""
        others = row.get("other_claimed_values") or []
        extra = (
            " The paper states more than one figure for this metric ("
            + ", ".join(f"{o['value']}{unit}" for o in others)
            + "); reconcile against the full text before fixing the target."
            if others else ""
        )
        checks.append({
            "check": (
                f"Reproduce {row['label']} = {row['value']}{unit} on {market_text} "
                f"over {period_text}. FAIL if our own backtest does not recover "
                f"it.{extra}"
            ),
            "derived_from": [row["evidence"], *(o["evidence"] for o in others)]
            if others else row["evidence"],
        })

    if period.get("status") == "stated":
        checks.append({
            "check": (
                f"Re-run outside the claimed window: the signal FAILS if it does "
                f"not survive out-of-sample after {period['end_year']}."
            ),
            "derived_from": period["evidence"],
        })

    if capabilities:
        names = ", ".join(c["capability"] for c in capabilities)
        checks.append({
            "check": (
                f"Confirm every stated input is obtainable for the target "
                f"universe ({names}). If any is unavailable, the result cannot "
                f"be reproduced as stated."
            ),
            "derived_from": [c["evidence"] for c in capabilities],
        })
    return checks


def _factor_brief(paper: dict[str, Any], source: str) -> dict[str, Any]:
    """Build the paper-to-factor hand-off block for one paper.

    Args:
        paper: A normalized paper record carrying ``title`` and ``abstract``.
        source: ``"arxiv"`` or ``"openalex"``.

    Returns:
        The ``factor_brief`` dict, including the list of fields that stayed
        unstated so the agent can see the gaps rather than guess at them.
    """
    title = _normalize(paper.get("title") or "")
    abstract = _normalize(paper.get("abstract") or "")
    scope = (
        f"title + abstract as served by {source}; the full text was NOT "
        f"retrieved, so nothing below reflects the paper's body"
    )
    if not abstract:
        return {
            "extraction_scope": scope,
            "abstract_available": False,
            "note": (
                f"{source} returned no abstract for this record, so no field "
                f"could be extracted. Everything is {_NOT_STATED}."
            ),
            "proposed_signal": {"status": _NOT_STATED},
            "input_data_requirements": {"status": _NOT_STATED},
            "claimed_backtest_period": {"status": _NOT_STATED},
            "claimed_markets": {"status": _NOT_STATED},
            "claimed_performance": {"status": _NOT_STATED},
            "falsifiable_checks": [],
            "unstated_fields": [
                "proposed_signal", "input_data_requirements",
                "claimed_backtest_period", "claimed_markets", "claimed_performance",
            ],
            "next_actions": list(_NEXT_ACTIONS),
        }

    segments = _segments(title, abstract)
    signal = _extract_signal(segments)
    capabilities = _extract_vocabulary(segments, _CAPABILITY_TERMS, "capability")
    markets = _extract_vocabulary(segments, _MARKET_TERMS, "market")
    period = _extract_period(segments)
    performance = _extract_performance(segments)

    unstated = [name for name, value in (
        ("proposed_signal", signal.get("status") == "stated"),
        ("input_data_requirements", bool(capabilities)),
        ("claimed_backtest_period", period.get("status") == "stated"),
        ("claimed_markets", bool(markets)),
        ("claimed_performance", bool(performance)),
    ) if not value]

    return {
        "extraction_scope": scope,
        "abstract_available": True,
        "disclaimer": _CLAIM_DISCLAIMER,
        "proposed_signal": signal,
        "input_data_requirements": (
            capabilities if capabilities else {"status": _NOT_STATED}
        ),
        "claimed_backtest_period": period,
        "claimed_markets": markets if markets else {"status": _NOT_STATED},
        "claimed_performance": (
            performance if performance else {"status": _NOT_STATED}
        ),
        "falsifiable_checks": _build_checks(performance, period, markets, capabilities),
        "unstated_fields": unstated,
        "next_actions": list(_NEXT_ACTIONS),
    }


# ---------------------------------------------------------------------------
# arXiv
# ---------------------------------------------------------------------------

_ATOM = "{http://www.w3.org/2005/Atom}"
_ARXIV_NS = "{http://arxiv.org/schemas/atom}"
_OPENSEARCH = "{http://a9.com/-/spec/opensearch/1.1/}"


def _arxiv_get(params: dict[str, Any]) -> ElementTree.Element:
    """Call the arXiv API and return the parsed feed root.

    Args:
        params: Query parameters for the classic API.

    Returns:
        The parsed ``<feed>`` element.

    Raises:
        ValueError: When arXiv answers with its error entry, or when the body
            is not parseable XML.
        requests.RequestException: Propagated from the HTTP layer.
    """
    response = throttled_get(
        _ARXIV_URL,
        host_key=_ARXIV_HOST_KEY,
        min_interval=resolve_min_interval(
            _ARXIV_MIN_INTERVAL_ENV, _ARXIV_DEFAULT_MIN_INTERVAL
        ),
        params=params,
        timeout=_TIMEOUT_S,
    )
    try:
        root = ElementTree.fromstring(response.text)
    except ElementTree.ParseError as exc:
        raise ValueError(f"arXiv returned unparseable XML (HTTP {response.status_code})") from exc

    entries = root.findall(f"{_ATOM}entry")
    for entry in entries:
        entry_id = (entry.findtext(f"{_ATOM}id") or "").strip()
        if entry_id.startswith(_ARXIV_ERROR_ID):
            raise ValueError(
                f"arXiv rejected the query: {(entry.findtext(f'{_ATOM}summary') or '').strip()}"
            )
    if response.status_code >= 400:
        # Not every rejection uses an /api/errors id -- a bad sortBy answers 400
        # with the id pointing at the user manual instead -- but the real
        # message is always the single entry's summary, so read it off directly
        # rather than degrading to a bare status code.
        detail = (entries[0].findtext(f"{_ATOM}summary") or "").strip() if entries else ""
        raise ValueError(
            f"arXiv rejected the query: {detail}" if detail
            else f"arXiv returned HTTP {response.status_code}"
        )
    return root


def _arxiv_paper(entry: ElementTree.Element) -> dict[str, Any]:
    """Normalize one arXiv Atom ``<entry>`` into a paper record.

    The entry id looks like ``http://arxiv.org/abs/2607.27461v1``; the bare id
    and the version are split apart because downstream staleness judgements need
    both (an abstract can change between v1 and v2).

    Args:
        entry: An Atom ``<entry>`` element.

    Returns:
        A paper record with ``paper_id``, ``version``, dates, links and text.
    """
    raw_id = (entry.findtext(f"{_ATOM}id") or "").strip()
    tail = raw_id.rsplit("/abs/", 1)[-1] if "/abs/" in raw_id else raw_id
    version_match = re.search(r"(v\d+)$", tail)
    version = version_match.group(1) if version_match else None
    paper_id = tail[: -len(version)] if version else tail

    links = {
        link.get("title") or link.get("rel"): link.get("href")
        for link in entry.findall(f"{_ATOM}link")
    }
    authors = [
        (a.findtext(f"{_ATOM}name") or "").strip()
        for a in entry.findall(f"{_ATOM}author")
    ]
    abstract = _normalize(entry.findtext(f"{_ATOM}summary") or "")
    truncated = len(abstract) > _MAX_ABSTRACT_CHARS
    primary = entry.find(f"{_ARXIV_NS}primary_category")

    return {
        "paper_id": paper_id,
        "version": version,
        "title": _normalize(entry.findtext(f"{_ATOM}title") or ""),
        "authors": authors[:_MAX_AUTHORS],
        "author_count": len(authors),
        "published": (entry.findtext(f"{_ATOM}published") or "").strip() or None,
        "updated": (entry.findtext(f"{_ATOM}updated") or "").strip() or None,
        "primary_category": primary.get("term") if primary is not None else None,
        "categories": [
            c.get("term") for c in entry.findall(f"{_ATOM}category") if c.get("term")
        ],
        "abstract": abstract[:_MAX_ABSTRACT_CHARS],
        "abstract_truncated": truncated,
        "url": links.get("alternate") or raw_id or None,
        "pdf_url": links.get("pdf"),
        "doi": (entry.findtext(f"{_ARXIV_NS}doi") or "").strip() or None,
        "journal_ref": (entry.findtext(f"{_ARXIV_NS}journal_ref") or "").strip() or None,
        "comment": (entry.findtext(f"{_ARXIV_NS}comment") or "").strip() or None,
    }


# Words that would eat a term slot in the fallback without narrowing anything.
_QUERY_STOPWORDS = frozenset(
    "a an the of and or for in on to with by from as at is are its our".split()
)


def _arxiv_run(clauses: list[str], max_results: int, sort_by: str) -> dict[str, Any]:
    """Execute one arXiv query and unpack the feed.

    Args:
        clauses: Query clauses, AND-ed together.
        max_results: Row cap, already clamped by the caller.
        sort_by: ``relevance`` / ``submitted`` / ``updated``.

    Returns:
        ``{"papers": [...], "total_available": int | None, "search_query": str}``.

    Raises:
        ValueError: When arXiv rejects the query.
    """
    search_query = " AND ".join(clauses)
    root = _arxiv_get({
        "search_query": search_query,
        "start": 0,
        "max_results": max_results,
        "sortBy": {
            "relevance": "relevance",
            "submitted": "submittedDate",
            "updated": "lastUpdatedDate",
        }[sort_by],
        "sortOrder": "descending",
    })
    total = root.findtext(f"{_OPENSEARCH}totalResults")
    return {
        "papers": [_arxiv_paper(e) for e in root.findall(f"{_ATOM}entry")],
        "total_available": int(total) if total and total.isdigit() else None,
        "search_query": search_query,
    }


def _arxiv_search(
    query: str | None,
    categories: list[str],
    start_date: str | None,
    end_date: str | None,
    max_results: int,
    sort_by: str,
) -> dict[str, Any]:
    """Run an arXiv search, widening the phrase query when it finds nothing.

    Args:
        query: Free text matched against title and abstract.
        categories: arXiv category terms, OR-ed together.
        start_date: Inclusive ``YYYY-MM-DD`` submission lower bound.
        end_date: Inclusive ``YYYY-MM-DD`` submission upper bound.
        max_results: Row cap, already clamped by the caller.
        sort_by: ``relevance`` / ``submitted`` / ``updated``.

    Returns:
        ``{"papers": [...], "total_available": int, "search_query": str,
        "query_mode": str}``.

    Raises:
        ValueError: When no search clause could be built, or arXiv errors.
    """
    filters: list[str] = []
    if categories:
        filters.append("(" + " OR ".join(f"cat:{c}" for c in categories) + ")")
    if start_date or end_date:
        low = (start_date or "1990-01-01").replace("-", "") + "0000"
        high = (end_date or "2099-12-31").replace("-", "") + "2359"
        filters.append(f"submittedDate:[{low} TO {high}]")

    # Quoted phrase first, deliberately. Probed live: the unquoted multi-word
    # form OR-s the individual words ("cross-sectional momentum" -> 126,113
    # hits) while the quoted phrase matches the concept (9 hits). The inner
    # quotes are stripped so a user-supplied quote cannot break out.
    phrase = query.replace('"', " ").strip() if query else ""
    if not phrase and not filters:
        raise ValueError("search needs at least one of: query, categories, start_date/end_date")
    if not phrase:
        return {**_arxiv_run(filters, max_results, sort_by), "query_mode": "filters_only"}

    result = _arxiv_run([f'(ti:"{phrase}" OR abs:"{phrase}")', *filters], max_results, sort_by)
    result["query_mode"] = "exact_phrase"

    # A phrase that is one word too long answers 0, not "close enough": probed
    # live, "cross-sectional momentum" -> 9 hits but the same phrase plus two
    # more words -> 0, while the terms AND-ed -> 5,990. An empty answer is
    # therefore retried as an AND of the individual terms rather than handed
    # back as "no such literature".
    terms = [
        term for term in re.split(r"\s+", phrase)
        if len(term) > 1 and term.lower() not in _QUERY_STOPWORDS
    ][:_MAX_QUERY_TERMS]
    if result["papers"] or len(terms) < 2:
        return result

    try:
        widened = _arxiv_run(
            [" AND ".join(f'(ti:"{t}" OR abs:"{t}")' for t in terms), *filters],
            max_results,
            sort_by,
        )
    except Exception as exc:  # noqa: BLE001 - an empty answer is still an answer
        logger.warning("arxiv widened query failed, keeping the phrase result: %s", exc)
        return result
    if not widened["papers"]:
        return result
    widened["query_mode"] = "all_terms"
    widened["phrase_query_returned_nothing"] = result["search_query"]
    return widened


def _read_arxiv(paper_ids: list[str]) -> dict[str, Any]:
    """Fetch specific arXiv papers by id.

    arXiv drops unknown ids from the feed without any error marker, so the
    requested set is diffed against what came back and the difference is
    surfaced as ``missing_ids``.

    Args:
        paper_ids: arXiv ids, with or without a ``vN`` suffix.

    Returns:
        ``{"papers": [...], "missing_ids": [...]}``.

    Raises:
        ValueError: When arXiv rejects the request.
    """
    root = _arxiv_get({"id_list": ",".join(paper_ids), "max_results": len(paper_ids)})
    papers = [_arxiv_paper(e) for e in root.findall(f"{_ATOM}entry")]
    returned = {p["paper_id"] for p in papers}
    missing = [
        pid for pid in paper_ids if re.sub(r"v\d+$", "", pid.strip()) not in returned
    ]
    return {"papers": papers, "missing_ids": missing}


# ---------------------------------------------------------------------------
# OpenAlex
# ---------------------------------------------------------------------------


def _openalex_get(path: str, params: dict[str, Any]) -> Any:
    """Call OpenAlex and decode the JSON body.

    Args:
        path: Path appended to the works endpoint (``""`` or ``"/W123"``).
        params: Query parameters.

    Returns:
        The decoded JSON payload.

    Raises:
        ValueError: On a non-2xx status or an undecodable body — OpenAlex
            answers unknown ids with an HTML 404, not JSON.
        requests.RequestException: Propagated from the HTTP layer.
    """
    merged = dict(params)
    if mailto := get_env_config().data.vibe_trading_openalex_mailto.strip():
        merged["mailto"] = mailto
    response = throttled_get(
        f"{_OPENALEX_URL}{path}",
        host_key=_OPENALEX_HOST_KEY,
        min_interval=resolve_min_interval(
            _OPENALEX_MIN_INTERVAL_ENV, _OPENALEX_DEFAULT_MIN_INTERVAL
        ),
        params=merged,
        timeout=_TIMEOUT_S,
    )
    if response.status_code >= 400:
        raise ValueError(f"OpenAlex returned HTTP {response.status_code}")
    try:
        return response.json()
    except ValueError as exc:
        raise ValueError("OpenAlex returned a non-JSON body") from exc


def _openalex_abstract(inverted: dict[str, list[int]] | None) -> str:
    """Re-linearize an OpenAlex inverted-index abstract.

    Args:
        inverted: ``{word: [token positions]}``, or ``None`` when the record
            carries no abstract (roughly a fifth of records in a live probe).

    Returns:
        The abstract text, or ``""`` when unavailable.
    """
    if not isinstance(inverted, dict):
        return ""
    positions: dict[int, str] = {}
    for word, slots in inverted.items():
        if isinstance(slots, list):
            for slot in slots:
                if isinstance(slot, int):
                    positions[slot] = word
    return " ".join(positions[i] for i in sorted(positions))


def _openalex_paper(work: dict[str, Any]) -> dict[str, Any]:
    """Normalize one OpenAlex work into the same paper record shape as arXiv.

    OpenAlex has no preprint version counter — nothing in the record maps to
    arXiv's ``vN`` — so ``version`` carries the location's version label
    (``publishedVersion`` / ``acceptedVersion`` / ``submittedVersion``) and
    ``updated`` carries the record's own ``updated_date``, which is the only
    staleness handle the source actually offers.

    Args:
        work: One ``works`` record.

    Returns:
        A paper record aligned with :func:`_arxiv_paper`.
    """
    location = work.get("primary_location") or {}
    venue = (location.get("source") or {}).get("display_name")
    abstract = _normalize(_openalex_abstract(work.get("abstract_inverted_index")))
    authors = [
        ((a.get("author") or {}).get("display_name") or "").strip()
        for a in (work.get("authorships") or [])
    ]
    authors = [a for a in authors if a]
    work_id = (work.get("id") or "").rsplit("/", 1)[-1]

    return {
        "paper_id": work_id,
        "version": location.get("version"),
        "title": _normalize(work.get("title") or ""),
        "authors": authors[:_MAX_AUTHORS],
        "author_count": len(authors),
        "published": work.get("publication_date"),
        "updated": work.get("updated_date"),
        "primary_category": work.get("type"),
        "categories": [],
        "abstract": abstract[:_MAX_ABSTRACT_CHARS],
        "abstract_truncated": len(abstract) > _MAX_ABSTRACT_CHARS,
        "url": location.get("landing_page_url") or work.get("doi") or work.get("id"),
        "pdf_url": location.get("pdf_url"),
        "doi": work.get("doi"),
        "journal_ref": venue,
        "comment": None,
        "cited_by_count": work.get("cited_by_count"),
    }


def _openalex_search(
    query: str | None,
    start_date: str | None,
    end_date: str | None,
    max_results: int,
    sort_by: str,
) -> dict[str, Any]:
    """Run an OpenAlex works search.

    Args:
        query: Free text; OpenAlex full-text search.
        start_date: Inclusive ``YYYY-MM-DD`` publication lower bound.
        end_date: Inclusive ``YYYY-MM-DD`` publication upper bound.
        max_results: Row cap, already clamped by the caller.
        sort_by: ``relevance`` keeps OpenAlex's ranking; the other two sort by
            publication date, since OpenAlex has no separate submission date.

    Returns:
        ``{"papers": [...], "total_available": int, "search_query": str}``.

    Raises:
        ValueError: When no search clause could be built, or OpenAlex errors.
    """
    filters = []
    if start_date:
        filters.append(f"from_publication_date:{start_date}")
    if end_date:
        filters.append(f"to_publication_date:{end_date}")
    if not query and not filters:
        raise ValueError("search needs at least one of: query, start_date/end_date")

    params: dict[str, Any] = {"per-page": max_results, "select": _OPENALEX_SELECT}
    if query:
        params["search"] = query
    if filters:
        params["filter"] = ",".join(filters)
    if sort_by != "relevance" or not query:
        params["sort"] = "publication_date:desc"

    payload = _openalex_get("", params)
    results = payload.get("results") if isinstance(payload, dict) else None
    meta = payload.get("meta") if isinstance(payload, dict) else None
    return {
        "papers": [_openalex_paper(w) for w in (results or []) if isinstance(w, dict)],
        "total_available": (meta or {}).get("count"),
        "search_query": json.dumps(params.get("search") or params.get("filter")),
        # OpenAlex runs its own full-text search, so there is no phrase-vs-terms
        # decision to report the way there is for arXiv.
        "query_mode": "full_text" if query else "filters_only",
    }


def _openalex_fetch(filter_key: str, keys: list[str]) -> list[dict[str, Any]]:
    """Fetch a group of works in one request, falling back to one request each.

    Args:
        filter_key: ``"openalex_id"`` or ``"doi"``.
        keys: Normalized ids of that kind.

    Returns:
        The work records that came back; ids OpenAlex does not know are simply
        absent (a batch containing an unknown id still answers ``200``).
    """
    try:
        payload = _openalex_get("", {
            "filter": f"{filter_key}:{'|'.join(keys)}",
            "select": _OPENALEX_SELECT,
            "per-page": len(keys),
        })
        results = payload.get("results") if isinstance(payload, dict) else None
        return [w for w in (results or []) if isinstance(w, dict)]
    except Exception as exc:  # noqa: BLE001 - a bad batch must not lose good ids
        logger.warning("openalex batch read failed (%s): %s", filter_key, exc)

    works: list[dict[str, Any]] = []
    for key in keys:
        # The single-work path needs the "doi:" prefix; a bare DOI answers 404.
        path = f"/{key}" if filter_key == "openalex_id" else f"/doi:{key}"
        try:
            work = _openalex_get(path, {"select": _OPENALEX_SELECT})
        except Exception as exc:  # noqa: BLE001 - one bad id must not kill the rest
            logger.warning("openalex read failed for %s: %s", key, exc)
            continue
        if isinstance(work, dict) and work.get("id"):
            works.append(work)
    return works


def _read_openalex(paper_ids: list[str]) -> dict[str, Any]:
    """Fetch specific OpenAlex works, batching by id kind.

    Work ids and DOIs cannot share a filter, so each kind costs at most one
    request instead of one request per id. An id that is neither is reported
    missing without spending a request on it.

    Args:
        paper_ids: OpenAlex work ids (``W...``, bare or as an openalex.org URL)
            or DOIs (bare or as a doi.org URL).

    Returns:
        ``{"papers": [...], "missing_ids": [...]}``. Papers come back grouped by
        id kind rather than in the requested order.
    """
    groups: dict[str, dict[str, str]] = {"openalex_id": {}, "doi": {}}
    missing: list[str] = []
    for pid in paper_ids:
        raw = pid.strip()
        if match := _OPENALEX_ID_RE.fullmatch(raw):
            groups["openalex_id"][match.group(1).upper()] = raw
        elif match := _DOI_RE.fullmatch(raw):
            groups["doi"][match.group(1).lower().rstrip(".")] = raw
        else:
            missing.append(raw)

    papers: list[dict[str, Any]] = []
    for filter_key, wanted in groups.items():
        if not wanted:
            continue
        found: dict[str, dict[str, Any]] = {}
        for work in _openalex_fetch(filter_key, list(wanted)):
            if filter_key == "openalex_id":
                key = (work.get("id") or "").rsplit("/", 1)[-1].upper()
            else:
                key = _DOI_PREFIX_RE.sub("", work.get("doi") or "").lower()
            if key in wanted:
                found[key] = work
        for key, requested in wanted.items():
            if key in found:
                papers.append(_openalex_paper(found[key]))
            else:
                missing.append(requested)
    return {"papers": papers, "missing_ids": missing}


def _valid_date(value: Any) -> bool:
    """Check a date argument is a ``YYYY-MM-DD`` string.

    Args:
        value: Raw argument value.

    Returns:
        True when the value is a well-formed date string.
    """
    return isinstance(value, str) and bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", value))


class ResearchPapersTool(BaseTool):
    """Search academic finance papers and convert them into factor briefs."""

    name = "research_papers"
    repeatable = True
    description = (
        "Search academic finance/ML papers and turn a paper into a FACTOR BRIEF "
        "that feeds our own factor loop. Sources: arxiv (preprints, q-fin/cs.LG) "
        "and openalex (published journal literature, incl. the classic factor "
        "papers arXiv does not have). mode='search' finds papers by topic / "
        "category / date window; mode='read' returns the structured record for "
        "specific ids PLUS a factor_brief extracting the proposed signal, the "
        "input data it needs, the claimed backtest window and market, the "
        "claimed performance, and falsifiable reproduction checks. Extraction is "
        "evidence-only: every value quotes the sentence it came from, and "
        "anything the paper does not state is returned as 'not stated in "
        "source' — never inferred. Only the abstract is available, never the "
        "full text, and claimed performance is the PAPER's claim, not our "
        'backtest result. Example: {"mode": "search", "source": "arxiv", '
        '"query": "cross-sectional momentum", "categories": ["q-fin.PM"], '
        '"start_date": "2024-01-01"}.'
    )
    parameters = {
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "enum": list(_MODES),
                "description": (
                    "'search' to find papers; 'read' to fetch specific ids and "
                    "get the factor_brief for each."
                ),
            },
            "source": {
                "type": "string",
                "enum": list(_SOURCES),
                "description": (
                    "'arxiv' = preprints (q-fin.*, cs.LG, stat.ML). 'openalex' = "
                    "published journal literature; ~1 in 5 OpenAlex records has "
                    "no abstract, and those yield no extraction."
                ),
                "default": "arxiv",
            },
            "query": {
                "type": "string",
                "description": (
                    "Topic. On arXiv this is matched as an EXACT PHRASE against "
                    "title and abstract, so keep it to 2-4 words ('momentum "
                    "crash', 'limit order book'), not a sentence; if the phrase "
                    "finds nothing the terms are retried AND-ed and query_mode "
                    "says 'all_terms'. OpenAlex runs its own full-text search."
                ),
            },
            "categories": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    'arXiv categories, OR-ed, e.g. ["q-fin.PM", "q-fin.ST", '
                    '"q-fin.TR", "cs.LG"]. Ignored for source=openalex.'
                ),
            },
            "start_date": {
                "type": "string",
                "description": "Inclusive lower bound, YYYY-MM-DD.",
            },
            "end_date": {
                "type": "string",
                "description": "Inclusive upper bound, YYYY-MM-DD.",
            },
            "max_results": {
                "type": "integer",
                "description": f"Rows to return for mode='search' (1-{_MAX_RESULTS}).",
                "default": _DEFAULT_MAX_RESULTS,
            },
            "sort_by": {
                "type": "string",
                "enum": list(_SORTS),
                "description": (
                    "'relevance' needs a query. 'submitted'/'updated' sort "
                    "newest first (OpenAlex sorts by publication date for both)."
                ),
                "default": "relevance",
            },
            "paper_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    f"For mode='read' (max {_MAX_READ_IDS}). arXiv ids like "
                    '"2607.27461" or "2607.27461v1"; OpenAlex work ids like '
                    '"W3021190191" or a DOI URL.'
                ),
            },
        },
        "required": ["mode"],
    }

    def execute(self, **kwargs: Any) -> str:
        """Search papers or read specific ids and emit factor briefs.

        Args:
            **kwargs: ``mode`` ("search"|"read", required), ``source``
                ("arxiv"|"openalex", default "arxiv"), ``query``,
                ``categories``, ``start_date``, ``end_date``, ``max_results``,
                ``sort_by``, ``paper_ids``.

        Returns:
            A JSON string ``{"ok": true, "mode": ..., "source": ..., "papers":
            [...]}`` where read-mode papers carry ``factor_brief``, or
            ``{"ok": false, "error": ...}`` on a request-level failure.
        """
        mode = kwargs.get("mode")
        if mode not in _MODES:
            return _error(f"mode must be one of {list(_MODES)}")

        source = kwargs.get("source", "arxiv")
        if source not in _SOURCES:
            return _error(f"source must be one of {list(_SOURCES)}")

        for key in ("start_date", "end_date"):
            if kwargs.get(key) is not None and not _valid_date(kwargs[key]):
                return _error(f"{key} must be a YYYY-MM-DD string")

        if mode == "read":
            paper_ids = kwargs.get("paper_ids")
            if not isinstance(paper_ids, list) or not paper_ids:
                return _error("mode='read' requires a non-empty paper_ids list")
            if any(not isinstance(p, str) or not p.strip() for p in paper_ids):
                return _error("every paper_id must be a non-empty string")
            paper_ids = [p.strip() for p in paper_ids][:_MAX_READ_IDS]
            reader = _read_arxiv if source == "arxiv" else _read_openalex
            try:
                result = reader(paper_ids)
            except Exception as exc:  # noqa: BLE001 - surfaced as an error envelope
                logger.warning("%s read failed: %s", source, exc)
                return _error(f"{source} read failed: {exc}")
            for paper in result["papers"]:
                paper["factor_brief"] = _factor_brief(paper, source)
            return json.dumps({
                "ok": True,
                "mode": "read",
                "source": source,
                "disclaimer": _CLAIM_DISCLAIMER,
                "requested": len(paper_ids),
                "returned": len(result["papers"]),
                "missing_ids": result["missing_ids"],
                "papers": result["papers"],
                "next_actions": list(_NEXT_ACTIONS),
            }, ensure_ascii=False)

        query = kwargs.get("query")
        if query is not None and (not isinstance(query, str) or not query.strip()):
            return _error("query must be a non-empty string when provided")
        query = query.strip() if isinstance(query, str) else None

        categories = kwargs.get("categories") or []
        if not isinstance(categories, list) or any(
            not isinstance(c, str) or not c.strip() for c in categories
        ):
            return _error("categories must be a list of non-empty strings")
        categories = [c.strip() for c in categories]

        max_results = kwargs.get("max_results", _DEFAULT_MAX_RESULTS)
        if not isinstance(max_results, int) or isinstance(max_results, bool) or max_results < 1:
            return _error("max_results must be a positive integer")
        max_results = min(max_results, _MAX_RESULTS)

        sort_by = kwargs.get("sort_by", "relevance")
        if sort_by not in _SORTS:
            return _error(f"sort_by must be one of {list(_SORTS)}")
        if sort_by == "relevance" and not query:
            sort_by = "submitted"

        try:
            if source == "arxiv":
                result = _arxiv_search(
                    query, categories, kwargs.get("start_date"),
                    kwargs.get("end_date"), max_results, sort_by,
                )
            else:
                result = _openalex_search(
                    query, kwargs.get("start_date"), kwargs.get("end_date"),
                    max_results, sort_by,
                )
        except Exception as exc:  # noqa: BLE001 - surfaced as an error envelope
            logger.warning("%s search failed: %s", source, exc)
            return _error(f"{source} search failed: {exc}")

        envelope = {
            "ok": True,
            "mode": "search",
            "source": source,
            "search_query": result["search_query"],
            "query_mode": result["query_mode"],
            "sort_by": sort_by,
            "total_available": result["total_available"],
            "returned": len(result["papers"]),
            "papers": result["papers"],
            "next_step": (
                "Call mode='read' with the paper_ids worth pursuing to get the "
                "factor_brief (proposed signal, required inputs, claimed window "
                "and market, claimed performance, falsifiable checks)."
            ),
        }
        if fallback := result.get("phrase_query_returned_nothing"):
            envelope["phrase_query_returned_nothing"] = fallback
        return json.dumps(envelope, ensure_ascii=False)
