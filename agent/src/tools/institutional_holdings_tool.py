"""Read-only tool: SEC Form 13F-HR institutional holdings from EDGAR.

Every institutional investment manager exercising discretion over more than
$100M of U.S. exchange-traded equities must file Form 13F-HR within 45 days of
each calendar quarter end. The holdings themselves live in a separate
INFORMATION TABLE document inside the filing, not in the primary document.
Three free, no-auth SEC endpoints carry everything this tool needs:

* ``https://efts.sec.gov/LATEST/search-index`` — EDGAR full-text search. Beyond
  free text (``q``) it accepts ``forms``, ``ciks``, ``entityName``, ``startdt``,
  ``enddt`` and ``from``, and each hit's ``_source`` carries ``ciks``,
  ``display_names``, ``form``, ``file_date``, ``period_ending``, ``adsh`` and —
  crucially — ``file_type``, which is literally ``"INFORMATION TABLE"`` for the
  holdings document. Because the info table is indexed as text, searching a
  CUSIP finds every manager that reported it. Coverage starts in 2001; the
  result window is hard-capped at ``from + size <= 10000``.
* ``https://www.sec.gov/Archives/edgar/data/<cik>/<accession_no_dashes>/index.json``
  — the document list for one filing, with per-file byte sizes. The information
  table's filename is filer-chosen (``infotable.xml``, ``53405.xml``,
  ``MJPinftable.xml`` have all been observed), so it is discovered here and then
  confirmed by its XML root tag rather than guessed.
* ``https://data.sec.gov/submissions/CIK##########.json`` — the per-company
  filing index, used as a fallback when full-text search is unavailable.

Information-table XML (namespace
``http://www.sec.gov/edgar/document/thirteenf/informationtable``) repeats one
``<infoTable>`` per position with ``nameOfIssuer``, ``titleOfClass``, ``cusip``,
``value``, ``shrsOrPrnAmt/{sshPrnamt,sshPrnamtType}``, ``putCall`` (options
only), ``investmentDiscretion``, ``otherManager`` and
``votingAuthority/{Sole,Shared,None}``. A manager that splits discretion across
sub-advisers emits **several rows for the same CUSIP** (Berkshire Hathaway's
2026-03-31 table carries four separate ALLY FINL INC rows), so rows are
aggregated by CUSIP before anything is ranked.

A quarter is a *chain of filings*, not one filing. ``primary_doc.xml`` carries
``formData/coverPage/isAmendment``, ``amendmentNo`` and
``amendmentInfo/amendmentType``, and the amendment type decides how the
information table relates to what came before. Measured over four full SEC
Form 13F data sets (2016Q1, 2020Q3, 2023Q2 and the 2026-03-01..2026-05-31 set —
about 40,000 cover pages) ``amendmentType`` takes exactly two values,
``RESTATEMENT`` and ``NEW HOLDINGS``, and nothing else. DZ BANK's 2020-09-30
quarter is the whole rule in one filer: the original (1,851 rows,
$41.70B) was replaced by a ``RESTATEMENT`` (1,776 rows, $41.68B) and then
*extended* by a ``NEW HOLDINGS`` amendment carrying 2 rows and $1.17M whose own
cover page says it exists "to add new holdings ... that were inadvertently
omitted from the original Form 13F". Reading only the original, only the newest,
or only the largest document all give a different and wrong answer.

Four gotchas this module compensates for, each verified against live filings:

1. **The value column changed units.** 13F ``value`` used to be reported in
   thousands and is now reported in whole dollars. The changeover is not clean:
   Berkshire's table filed 2022-11-14 totals 296,096,640 (thousands) while its
   2023-02-14 table totals 299,007,622,119 (dollars), yet BancFirst Trust &
   Investment Management filed on 2023-01-03 with an implied AAPL price of
   $0.1296 — still thousands — while Rede Wealth filed 2023-01-17 at $129.93.
   A pure filing-date rule is therefore wrong by 1000x for some filings. The
   filing date only sets a *prior*; the decision is confirmed against the median
   implied price (value / shares) of the share-denominated rows, and both the
   chosen unit and the basis for choosing it are reported.
2. **Pre-2013 filings have no XML at all.** Berkshire's 2011-11-14 filing
   contains one plain-text document (``d254132d13fhr.txt``). Those filings are
   reported as unparseable rather than silently returned empty.
3. **The form suffix and the cover page disagree, in both directions.** In the
   2026-03-01..2026-05-31 data set 8 filings are submitted as ``13F-HR/A`` while
   their cover page carries no ``isAmendment`` and no ``amendmentType`` at all
   (AEGON ASSET MANAGEMENT UK Plc, eight quarters in one batch — confirmed
   against the raw ``primary_doc.xml``), and 1 filing is submitted as plain
   ``13F-HR`` while its cover page declares ``isAmendment=true``,
   ``amendmentNo=1``, ``NEW HOLDINGS`` (Nova Wealth Management). So neither
   signal alone classifies a filing: a document is treated as an amendment when
   *either* says so, and an amendment whose type is absent or outside the known
   set is reported as unresolved rather than assumed to restate or to extend.
4. **SEC rate-limits by source IP** and asks for a contact ``User-Agent``.
   Every request here shares the ``"sec"`` throttle bucket and the User-Agent of
   :mod:`backtest.loaders.sec_edgar_client`, so this tool cannot burst past the
   other SEC callers in the process. Bursting without spacing does fail in
   practice — an unthrottled probe loop got a payload with no ``hits`` key back
   from full-text search.

Filer discovery is windowed on the statutory deadline rather than on a flat
lag. Full-text search answers newest-first, so a window running 120 days past
quarter end starts inside the *next* quarter's filing season: for target
2026-03-31 the first page of ``2026-04-01..2026-07-29`` was 97/100 filings for
2026-06-30 and only 1 for the target, all of which were then discarded.
Searching ``2026-04-01..2026-05-15`` — quarter end through the 45-day deadline —
returns 96/100 on target instead. The late tail is a second, separate window so
nothing that the flat lag used to reach is lost.

Ticker -> CUSIP has no SEC lookup table, so it is resolved from the SEC's own
"fails to deliver" data (``SETTLEMENT DATE|CUSIP|SYMBOL|QUANTITY (FAILS)|
DESCRIPTION|PRICE``), which is authoritative but only lists securities that had
a settlement failure in the covered half-month — 13,025 distinct symbols in the
2026-07-01..2026-07-15 file. Anything absent must be passed as an explicit
``cusip``; no mapping is ever guessed from an issuer name.

Markets: United States only.
"""

from __future__ import annotations

import io
import json
import logging
import re
import threading
import time
import xml.etree.ElementTree as ET
import zipfile
from datetime import date, timedelta
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from backtest.loaders._http import throttled_get
from backtest.loaders.sec_edgar_client import get_submissions

# The SEC User-Agent and the throttle floor are deliberately imported from the
# shared client rather than restated: one contact string, one rate limit, one
# place to change them. Both are stable module-level helpers.
from backtest.loaders.sec_edgar_client import _min_interval, _pad_cik, _user_agent
from src.agent.tools import BaseTool
from src.config.accessor import get_env_config
from src.config.limits import TOOL_RESULT_LIMIT
from src.tools._result_paging import fit_records

logger = logging.getLogger(__name__)

_HOST_KEY = "sec"
_FTS_URL = "https://efts.sec.gov/LATEST/search-index"
_ARCHIVES = "https://www.sec.gov/Archives/edgar/data"
_FTD_INDEX_URL = "https://www.sec.gov/data/foiadocsfailsdatahtm"

_MODES = ("manager_holdings", "ticker_holders", "top_managers")

# EDGAR full-text search returns 100 hits per page and refuses from + size > 10000.
_FTS_PAGE = 100
_FTS_MAX_FROM = 9900

# Defensive caps. Each keeps one call bounded in both wall-clock and characters.
_MAX_TOP_N = 100
_DEFAULT_TOP_N = 25
_MAX_HOLDER_SAMPLE = 25
_DEFAULT_HOLDER_SAMPLE = 10
_MAX_SCAN = 300
# Each scanned filing is its own SEC round trip and EDGAR answers in roughly a
# second, so a scan of 100 would overrun the default wall-clock budget and come
# back short. 30 fits comfortably inside it.
_DEFAULT_SCAN = 30
_MAX_INFOTABLE_ROWS = 20_000
_MAX_CHANGES = 200
# Share of the tool-result budget the quarter-over-quarter change list may take.
# It sits in the fixed part of the envelope, outside the paged position list, so
# it has to be bounded on its own or it starves and then overflows the result.
_CHANGES_BUDGET_SHARE = 0.5
# A filing's document list can name several XML files. Candidates are ordered by
# how much the filename looks like an information table before any of them is
# fetched, so the cap only bites on filings that carry many decoys. Across 150
# sampled live filings (105 from 2026, 45 from 2016) every single one carried
# exactly one non-``primary_doc.xml`` XML document, so this ceiling is defensive
# rather than something observed to be hit.
_MAX_TABLE_CANDIDATES = 8
# Filenames containing any of these are probed before anything else.
_TABLE_NAME_HINTS = ("infotable", "informationtable", "inftable", "information", "table", "info")

# 13F reporting began in 1978 but EDGAR electronic filing (and therefore
# anything reachable here) starts in the 1990s.
_MIN_QUARTER_YEAR = 1993
# Managers have 45 days after quarter end to file; 46 is the first day the
# quarter can be assumed populated, and 120 days covers late amendments.
_FILING_LAG_DAYS = 46
_FILING_DEADLINE_DAYS = 45
_FILING_WINDOW_DAYS = 120
_QUARTER_ENDS = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}

# Cover-page amendment vocabulary. These are the only two values `amendmentType`
# took across the four SEC Form 13F data sets sampled in the module docstring;
# anything else (including a blank) is deliberately NOT mapped to a behaviour.
_ROLE_ORIGINAL = "original"
_ROLE_RESTATEMENT = "restatement"
_ROLE_NEW_HOLDINGS = "new_holdings"
_ROLE_UNSPECIFIED = "unspecified_amendment"
_AMENDMENT_ROLES = {"RESTATEMENT": _ROLE_RESTATEMENT, "NEW HOLDINGS": _ROLE_NEW_HOLDINGS}
# What bounds this is filings per filer-quarter, not `amendmentNo`: across the
# 8,933 filer-quarters in the 2023q2 Form 13F data set the busiest filer made 7
# filings for one quarter and none made more than 7, so 12 leaves room without
# letting one pathological filer turn into an unbounded scan. `amendmentNo` is
# NOT a proxy for that count — it is filer-entered and reaches 99 (STATE STREET
# CORP, 0000093751-23-000581) in that same data set.
_MAX_CHAIN_FILINGS = 12
_TRUE_TEXT = {"TRUE", "T", "Y", "YES", "1"}
_FALSE_TEXT = {"FALSE", "F", "N", "NO", "0"}

# Whole-dollar reporting took over around the start of 2023; see the module
# docstring for why this is only a prior and never the final word.
_DOLLAR_UNITS_FROM = "2023-01-03"
# Median implied price (value / shares) below this while expecting dollars means
# the filing is really in thousands; above the upper bound while expecting
# thousands means the opposite. Real equity portfolios sit between the two.
_IMPLIED_PRICE_MIN_USD = 1.0
_IMPLIED_PRICE_MAX_THOUSANDS = 3.0
_MIN_ROWS_FOR_UNIT_CHECK = 5

# A manager only has to file 13F once it exercises discretion over more than
# $100M of section 13(f) securities, so a cover-page total that lands *below*
# that under the whole-dollar prior is far more likely still denominated in
# thousands than it is a genuine sub-threshold portfolio. Measured against 40
# consecutive 2026-06-30 filers, 2 of them (CapitalatWork S.A., Eurizon Asset
# Management Slovakia — both non-U.S. managers) report exactly this way, so the
# prior misreads roughly 5% of filers by 1000x. Because that error *shrinks* a
# portfolio it silently drops real managers out of a value ranking, so the
# ambiguous minority is resolved against the filing's own information table
# instead of being guessed either way.
_FILING_THRESHOLD_USD = 100_000_000.0

_ENV_MAX_XML_MB = "VIBE_TRADING_SEC_13F_MAX_XML_MB"
_ENV_BUDGET_S = "VIBE_TRADING_SEC_13F_BUDGET_S"
_ENV_FTD_URL = "VIBE_TRADING_SEC_FTD_URL"
_ENV_FTD_FILES = "VIBE_TRADING_SEC_FTD_FILES"

_DEFAULT_MAX_XML_MB = 25.0
_DEFAULT_BUDGET_S = 120.0
_DEFAULT_FTD_FILES = 1
_MAX_FTD_FILES = 6

# Process-wide memoized ticker -> (cusip, description) map, built lazily and
# only when a ticker actually has to be resolved.
_CUSIP_CACHE: Optional[Dict[str, Tuple[str, str]]] = None
_CUSIP_CACHE_SOURCES: List[str] = []
_CUSIP_CACHE_LOCK = threading.Lock()


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #


def _sec_get(url: str, params: Optional[Dict[str, Any]] = None) -> Any:
    """GET ``url`` through the shared SEC throttle bucket.

    Args:
        url: Fully-qualified SEC endpoint.
        params: Optional query parameters.

    Returns:
        The :class:`requests.Response`, already ``raise_for_status``-checked.

    Raises:
        requests.RequestException: On a non-2xx status.
    """
    response = throttled_get(
        url,
        host_key=_HOST_KEY,
        min_interval=_min_interval(),
        params=params,
        headers={"User-Agent": _user_agent()},
        timeout=30.0,
    )
    response.raise_for_status()
    return response


def _fts(params: Dict[str, Any]) -> Dict[str, Any]:
    """Run one EDGAR full-text search and return its ``hits`` block.

    Args:
        params: Query parameters (``q`` / ``forms`` / ``ciks`` / ``entityName`` /
            ``startdt`` / ``enddt`` / ``from``).

    Returns:
        ``{"total": int, "total_is_lower_bound": bool, "hits": [source-dicts
        with an extra "_id" key]}``. Elasticsearch stops counting at 10,000 and
        reports ``relation: "gte"``, so a total at that ceiling is a floor and
        must never be presented as an exact count.

    Raises:
        RuntimeError: When the response carries no ``hits`` block — full-text
            search answers HTTP 200 with an error document when it is unhappy.
        requests.RequestException: On transport failure.
    """
    payload = _sec_get(_FTS_URL, {"q": "", **params}).json()
    hits = payload.get("hits") if isinstance(payload, dict) else None
    if not isinstance(hits, dict):
        message = payload.get("errorMessage") if isinstance(payload, dict) else None
        raise RuntimeError(f"EDGAR full-text search returned no hits block: {message or payload}")
    rows: List[Dict[str, Any]] = []
    for hit in hits.get("hits") or []:
        source = hit.get("_source") if isinstance(hit, dict) else None
        if isinstance(source, dict):
            rows.append({**source, "_id": hit.get("_id")})
    total = hits.get("total") if isinstance(hits.get("total"), dict) else {}
    return {
        "total": int(total.get("value") or 0),
        "total_is_lower_bound": total.get("relation") == "gte",
        "hits": rows,
    }


def _positive(value: float, default: float) -> float:
    """Return *value* when it is positive, else *default*.

    The config layer already drops unparseable overrides; this only guards
    against a syntactically valid but nonsensical zero or negative bound.
    """
    return value if value > 0 else default


def _max_xml_bytes() -> int:
    """Return the per-document byte ceiling for an information table."""
    configured = get_env_config().data.vibe_trading_sec_13f_max_xml_mb
    return int(_positive(configured, _DEFAULT_MAX_XML_MB) * 1024 * 1024)


class _Budget:
    """Monotonic wall-clock guard so a wide scan stops instead of grinding on."""

    def __init__(self) -> None:
        budget = get_env_config().data.vibe_trading_sec_13f_budget_s
        self.deadline = time.monotonic() + _positive(budget, _DEFAULT_BUDGET_S)
        self.exhausted = False

    def ok(self) -> bool:
        """Return ``True`` while budget remains, latching ``exhausted`` when not."""
        if time.monotonic() >= self.deadline:
            self.exhausted = True
            return False
        return True


# --------------------------------------------------------------------------- #
# Quarter handling
# --------------------------------------------------------------------------- #


def _parse_quarter(value: Any) -> str:
    """Normalize a quarter argument to the ``YYYY-MM-DD`` calendar quarter end.

    Accepts ``"2026Q1"``, ``"2026-q1"``, ``"2026-03-31"`` and ``"2026-3-31"``.

    Args:
        value: The raw ``quarter`` argument.

    Returns:
        The quarter-end date as ``YYYY-MM-DD``.

    Raises:
        ValueError: When the text is not a recognizable quarter, the year is
            outside ``1993..current+1``, or the date is not a quarter end.
    """
    text = str(value).strip().upper().replace(" ", "")
    match = re.fullmatch(r"(\d{4})-?Q([1-4])", text)
    if match:
        year, quarter = int(match.group(1)), int(match.group(2))
    else:
        match = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", text)
        if not match:
            raise ValueError(
                f"quarter {value!r} is not recognizable; use '2026Q1' or a quarter-end date '2026-03-31'"
            )
        year, month, day = (int(g) for g in match.groups())
        quarter = next((q for q, md in _QUARTER_ENDS.items() if md == (month, day)), None)
        if quarter is None:
            raise ValueError(
                f"quarter {value!r} is not a calendar quarter end; use 03-31, 06-30, 09-30 or 12-31"
            )
    if not _MIN_QUARTER_YEAR <= year <= date.today().year + 1:
        raise ValueError(f"quarter year {year} is outside {_MIN_QUARTER_YEAR}..{date.today().year + 1}")
    month, day = _QUARTER_ENDS[quarter]
    return f"{year:04d}-{month:02d}-{day:02d}"


def _quarter_label(period_end: Optional[str]) -> Optional[str]:
    """Render a ``YYYY-MM-DD`` quarter end as ``YYYYQn``, or ``None`` if unusable."""
    if not period_end or len(str(period_end)) < 7:
        return None
    text = str(period_end)
    try:
        year, month = int(text[:4]), int(text[5:7])
    except ValueError:
        return None
    quarter = next((q for q, md in _QUARTER_ENDS.items() if md[0] == month), None)
    return f"{year}Q{quarter}" if quarter else None


def _latest_reportable_quarter(today: Optional[date] = None) -> str:
    """Return the newest quarter end whose 45-day filing deadline has passed."""
    cutoff = (today or date.today()) - timedelta(days=_FILING_LAG_DAYS)
    year = cutoff.year
    for quarter in (4, 3, 2, 1):
        month, day = _QUARTER_ENDS[quarter]
        if date(year, month, day) <= cutoff:
            return f"{year:04d}-{month:02d}-{day:02d}"
    return f"{year - 1:04d}-12-31"


def _discovery_windows(period_end: str) -> List[Tuple[str, str]]:
    """Return the full-text-search windows for a quarter, densest first.

    Full-text search sorts newest-first, so one flat 120-day window spends its
    early pages inside the following quarter's filing season and throws almost
    all of them away — measured live at 3 usable hits out of the first 100 for
    target 2026-03-31. Splitting the same span at the 45-day statutory deadline
    puts the filing season itself in the first window (96/100 on target) and
    leaves the late tail as a second window that is only paged when the first
    one has not filled the sample. The union is exactly the old window, so no
    filing that used to be reachable stops being reachable.

    Args:
        period_end: Quarter end as ``YYYY-MM-DD``.

    Returns:
        ``[(startdt, enddt), ...]`` from the deadline window to the late tail.
    """
    end = date.fromisoformat(period_end)

    def day(offset: int) -> str:
        return (end + timedelta(days=offset)).isoformat()

    return [(day(1), day(_FILING_DEADLINE_DAYS)), (day(_FILING_DEADLINE_DAYS + 1), day(_FILING_WINDOW_DAYS))]


# --------------------------------------------------------------------------- #
# Ticker -> CUSIP (SEC fails-to-deliver data)
# --------------------------------------------------------------------------- #


def _ftd_urls() -> List[str]:
    """Discover the most recent SEC fails-to-deliver archive URLs.

    The FOIA landing page is scraped rather than the filenames being computed,
    because the SEC has served the same series from two different directories
    (``/files/data/fails-deliver-data/`` and ``/files/data/other/fails-deliver-data/``)
    and only the page knows which is which.

    Returns:
        Newest-first absolute ``.zip`` URLs, at most the configured file count.

    Raises:
        requests.RequestException: If the landing page cannot be fetched.
        RuntimeError: If the page lists no archives.
    """
    data_config = get_env_config().data
    pinned = data_config.vibe_trading_sec_ftd_url.strip()
    if pinned:
        return [pinned]
    wanted = max(1, min(data_config.vibe_trading_sec_ftd_files, _MAX_FTD_FILES))
    html = _sec_get(_FTD_INDEX_URL).text
    hrefs = re.findall(r'href="(/[^"]*cnsfails\d{6}[ab]\.zip)"', html)
    if not hrefs:
        raise RuntimeError("SEC fails-to-deliver index listed no archives")
    ordered = sorted(dict.fromkeys(hrefs), key=lambda h: h.rsplit("/", 1)[-1], reverse=True)
    return [f"https://www.sec.gov{h}" for h in ordered[:wanted]]


def _load_ftd_map(url: str, into: Dict[str, Tuple[str, str]]) -> None:
    """Merge one fails-to-deliver archive into ``into`` as ticker -> (cusip, description).

    The pipe-delimited payload is ``SETTLEMENT DATE|CUSIP|SYMBOL|QUANTITY
    (FAILS)|DESCRIPTION|PRICE``. Earlier entries win, so a newer archive passed
    first keeps precedence over an older one.

    Args:
        url: Absolute URL of a ``cnsfailsYYYYMM{a,b}.zip`` archive.
        into: Accumulator mutated in place.

    Raises:
        requests.RequestException: On transport failure.
        zipfile.BadZipFile: If the payload is not a zip archive.
    """
    archive = zipfile.ZipFile(io.BytesIO(_sec_get(url).content))
    for member in archive.namelist():
        for line in archive.read(member).decode("utf-8", "replace").splitlines()[1:]:
            parts = line.split("|")
            if len(parts) < 5:
                continue
            symbol, cusip = parts[2].strip().upper(), parts[1].strip().upper()
            if symbol and cusip and symbol not in into:
                into[symbol] = (cusip, parts[4].strip())


def _cusip_map() -> Tuple[Dict[str, Tuple[str, str]], List[str]]:
    """Return the memoized ticker -> (cusip, description) map and its source URLs.

    Raises:
        Exception: Any fetch/parse failure from the first successful build
            attempt is propagated so the caller can report it verbatim.
    """
    global _CUSIP_CACHE
    if _CUSIP_CACHE is not None:
        return _CUSIP_CACHE, _CUSIP_CACHE_SOURCES
    with _CUSIP_CACHE_LOCK:
        if _CUSIP_CACHE is None:
            urls = _ftd_urls()
            mapping: Dict[str, Tuple[str, str]] = {}
            for url in urls:
                _load_ftd_map(url, mapping)
            _CUSIP_CACHE = mapping
            _CUSIP_CACHE_SOURCES[:] = urls
    return _CUSIP_CACHE, _CUSIP_CACHE_SOURCES


def _cusip_for_ticker(ticker: str) -> Tuple[Optional[str], Optional[str], List[str]]:
    """Resolve a ticker to a CUSIP via SEC fails-to-deliver data.

    The fails-to-deliver feed writes share classes without a separator
    (Berkshire class B is ``BRKB``, not ``BRK.B``), so the separator-stripped
    form is tried as well. Nothing is ever inferred from an issuer name.

    Args:
        ticker: A U.S. ticker, case-insensitive.

    Returns:
        ``(cusip, description, source_urls)``; ``cusip`` is ``None`` when the
        symbol is absent from the covered half-month.

    Raises:
        Exception: Propagated from the one-time map build.
    """
    mapping, sources = _cusip_map()
    candidate = ticker.strip().upper()
    for key in (candidate, candidate.replace(".", "").replace("-", "")):
        if key in mapping:
            cusip, description = mapping[key]
            return cusip, description, sources
    return None, None, sources


# --------------------------------------------------------------------------- #
# Filing discovery
# --------------------------------------------------------------------------- #


def _looks_like_cik(text: str) -> bool:
    """Return ``True`` when ``text`` is a bare (optionally ``CIK``-prefixed) number."""
    return bool(re.fullmatch(r"(?:CIK)?[\s#-]*\d{1,10}", text.strip().upper()))


def _resolve_manager(manager: str) -> Tuple[str, Optional[str], List[Dict[str, str]]]:
    """Resolve a manager name or CIK to a padded CIK.

    Args:
        manager: A 13F filer name (e.g. ``"Bridgewater Associates"``) or a CIK.

    Returns:
        ``(padded_cik, display_name, other_candidates)``. ``other_candidates``
        lists the further name matches so an ambiguous name is visible rather
        than silently collapsed to one filer.

    Raises:
        ValueError: When the name matches no 13F filer.
        RuntimeError: When full-text search returns an unusable payload.
        requests.RequestException: On transport failure.
    """
    if _looks_like_cik(manager):
        return _pad_cik(manager), None, []
    result = _fts({"forms": "13F-HR", "entityName": manager.strip()})
    seen: Dict[str, str] = {}
    for hit in result["hits"]:
        for cik in hit.get("ciks") or []:
            if cik not in seen:
                seen[cik] = (hit.get("display_names") or [""])[0]
    if not seen:
        raise ValueError(f"no 13F-HR filer matched manager name {manager!r}")
    items = list(seen.items())
    primary_cik, primary_name = items[0]
    others = [{"cik": c, "name": n} for c, n in items[1:6]]
    return _pad_cik(primary_cik), primary_name or None, others


def _list_13f_filings(cik: str, limit: int = 200) -> List[Dict[str, Any]]:
    """List a filer's 13F-HR filings, newest first.

    Full-text search is preferred because it reports ``period_ending`` directly
    and reaches further back than the submissions "recent" block; the
    submissions document is the fallback.

    The limit is deliberately generous because the result is truncated by
    *filing date* while callers group it by *reporting period*, and amendments
    arrive years late: DZ BANK amended its 2020-09-30 quarter on 2026-05-04, so
    a 40-filing cut kept the two 2026 amendments and dropped the 2020 original
    they amend — half of that quarter's chain, silently.

    Args:
        cik: Padded 10-digit CIK.
        limit: Maximum filings to return.

    Returns:
        Dicts of ``{accession, form, filing_date, period_end, is_amendment}``,
        deduplicated by accession and sorted newest filing date first.
    """
    filings: List[Dict[str, Any]] = []
    try:
        for hit in _fts({"forms": "13F-HR", "ciks": cik})["hits"]:
            accession = hit.get("adsh")
            if not accession:
                continue
            form = str(hit.get("form") or "")
            filings.append(
                {
                    "accession": accession,
                    "form": form,
                    "filing_date": hit.get("file_date"),
                    "period_end": hit.get("period_ending"),
                    "is_amendment": form.upper().endswith("/A"),
                }
            )
    except Exception as exc:  # noqa: BLE001 - full-text search is the preferred path, not the only one
        logger.warning("13F full-text filing index failed for CIK %s: %s", cik, exc)

    if not filings:
        recent = ((get_submissions(cik).get("filings") or {}).get("recent")) or {}
        forms = recent.get("form") or []
        for idx, raw_form in enumerate(forms):
            form = str(raw_form or "")
            if not form.upper().startswith("13F-HR"):
                continue
            filings.append(
                {
                    "accession": _at(recent.get("accessionNumber"), idx),
                    "form": form,
                    "filing_date": _at(recent.get("filingDate"), idx),
                    "period_end": _at(recent.get("reportDate"), idx),
                    "is_amendment": form.upper().endswith("/A"),
                }
            )

    unique: Dict[str, Dict[str, Any]] = {}
    for filing in filings:
        if filing["accession"] and filing["accession"] not in unique:
            unique[filing["accession"]] = filing
    ordered = sorted(unique.values(), key=lambda f: str(f.get("filing_date") or ""), reverse=True)
    return ordered[:limit]


def _target_period(filings: List[Dict[str, Any]], period_end: Optional[str]) -> Optional[str]:
    """Resolve the quarter to read, defaulting to the newest one indexed.

    Args:
        filings: Filings from :func:`_list_13f_filings`.
        period_end: Explicit quarter end, or ``None`` to take the newest.

    Returns:
        The quarter end as ``YYYY-MM-DD``, or ``None`` when no filing carries
        one (the submissions fallback can omit ``reportDate``).
    """
    if period_end:
        return period_end
    periods = [str(f.get("period_end")) for f in filings if f.get("period_end")]
    return max(periods) if periods else None


def _filings_for_period(
    filings: List[Dict[str, Any]], period_end: Optional[str]
) -> List[Dict[str, Any]]:
    """Return every filing a filer made for one quarter, original and amendments alike."""
    if period_end is None:
        return filings[:1]
    return [f for f in filings if f.get("period_end") == period_end]


def _information_table_urls(cik: str, accession: str) -> Tuple[List[str], Optional[str]]:
    """List candidate information-table document URLs for one filing.

    Args:
        cik: CIK in any form; leading zeros are dropped for the archive path.
        accession: Accession number with or without dashes.

    Candidates are ordered before any of them is fetched: a filename that reads
    like an information table goes first, then the largest documents, then the
    order EDGAR listed them. Ranking matters more than the cap does — the cap
    exists only so a filing stuffed with decoy XML cannot turn one lookup into
    an unbounded probe loop, and cutting the list at document order alone can
    drop the real table when it happens to be listed late.

    Returns:
        ``(urls, note)`` where ``note`` explains an empty list (for example a
        pre-XML text filing or an oversized document).

    Raises:
        requests.RequestException: If the filing index cannot be fetched.
    """
    cik_digits = str(cik).lstrip("0") or "0"
    base = f"{_ARCHIVES}/{cik_digits}/{str(accession).replace('-', '')}"
    items = (_sec_get(f"{base}/index.json").json().get("directory") or {}).get("item") or []

    ranked: List[Tuple[int, int, int, str]] = []
    oversized = False
    ceiling = _max_xml_bytes()
    for order, item in enumerate(items):
        name = str((item or {}).get("name") or "")
        lowered = name.lower()
        if not lowered.endswith(".xml") or lowered == "primary_doc.xml":
            continue
        try:
            size = int(item.get("size") or 0)
        except (TypeError, ValueError):
            size = 0
        if size > ceiling:
            oversized = True
            continue
        looks_like_table = any(hint in lowered for hint in _TABLE_NAME_HINTS)
        ranked.append((0 if looks_like_table else 1, -size, order, f"{base}/{name}"))

    urls = [entry[-1] for entry in sorted(ranked)[:_MAX_TABLE_CANDIDATES]]
    if urls:
        return urls, None
    if oversized:
        return [], f"information table exceeds the {ceiling} byte ceiling ({_ENV_MAX_XML_MB})"
    return [], "filing carries no XML information table (pre-2013 filings are plain text)"


# --------------------------------------------------------------------------- #
# Information-table parsing
# --------------------------------------------------------------------------- #


def _local(tag: Any) -> str:
    """Strip an XML namespace from a tag name."""
    return str(tag).rsplit("}", 1)[-1]


def _parse_information_table(raw: bytes, cusip_filter: Optional[str] = None) -> List[Dict[str, Any]]:
    """Stream one information-table XML into position rows.

    Parsed incrementally and cleared as it goes: a large manager's table runs to
    tens of thousands of rows, and holding the whole tree would cost far more
    memory than the rows themselves. Bytes (not text) are parsed because filers
    do emit non-UTF-8 declarations such as ``windows-1252``.

    Args:
        raw: The raw XML document bytes.
        cusip_filter: When set, only rows with this CUSIP are kept.

    Returns:
        Row dicts with ``issuer``, ``title_of_class``, ``cusip``, ``value_raw``,
        ``shares``, ``share_type``, ``put_call``, ``discretion``,
        ``other_manager`` and ``voting_sole``/``voting_shared``/``voting_none``.

    Raises:
        ValueError: When the document root is not ``informationTable``.
        xml.etree.ElementTree.ParseError: On malformed XML.
    """
    context = ET.iterparse(io.BytesIO(raw), events=("start", "end"))
    _, root = next(context)
    if _local(root.tag) != "informationTable":
        raise ValueError(f"document root is <{_local(root.tag)}>, not <informationTable>")

    wanted = cusip_filter.strip().upper() if cusip_filter else None
    rows: List[Dict[str, Any]] = []
    for event, element in context:
        if event != "end" or _local(element.tag) != "infoTable":
            continue
        fields = {_local(node.tag): (node.text or "").strip() for node in element.iter()}
        element.clear()
        root.clear()
        cusip = fields.get("cusip", "").upper()
        if wanted and cusip != wanted:
            continue
        rows.append(
            {
                "issuer": fields.get("nameOfIssuer") or None,
                "title_of_class": fields.get("titleOfClass") or None,
                "cusip": cusip or None,
                "value_raw": _to_number(fields.get("value")),
                "shares": _to_number(fields.get("sshPrnamt")),
                "share_type": fields.get("sshPrnamtType") or None,
                "put_call": fields.get("putCall") or None,
                "discretion": fields.get("investmentDiscretion") or None,
                "other_manager": fields.get("otherManager") or None,
                "voting_sole": _to_number(fields.get("Sole")),
                "voting_shared": _to_number(fields.get("Shared")),
                "voting_none": _to_number(fields.get("None")),
            }
        )
        if len(rows) >= _MAX_INFOTABLE_ROWS:
            break
    return rows


def _detect_value_units(rows: List[Dict[str, Any]], filing_date: Optional[str]) -> Tuple[int, str, str]:
    """Decide whether ``value`` is whole dollars or thousands of dollars.

    The filing date sets the prior (whole dollars from 2023-01-03). Because
    filers straddled that boundary in practice, the prior is then checked
    against the median implied price of the share-denominated rows and
    overridden when the two disagree; an equity portfolio priced in dollars
    cannot plausibly have a sub-$1 median share price, and one priced in
    thousands cannot plausibly show a median above $3.

    Args:
        rows: Parsed information-table rows.
        filing_date: The filing's ``YYYY-MM-DD`` date, if known.

    Returns:
        ``(multiplier, units, basis)`` where ``multiplier`` converts ``value_raw``
        to USD, ``units`` is ``"usd"`` or ``"usd_thousands"`` and ``basis`` names
        the evidence used.
    """
    dollars = str(filing_date or "9999-99-99") >= _DOLLAR_UNITS_FROM
    implied = sorted(
        row["value_raw"] / row["shares"]
        for row in rows
        if row.get("share_type") in (None, "SH")
        and row.get("shares")
        and row.get("value_raw") is not None
        and row["shares"] > 0
    )
    if len(implied) >= _MIN_ROWS_FOR_UNIT_CHECK:
        median = implied[len(implied) // 2]
        if dollars and median < _IMPLIED_PRICE_MIN_USD:
            return 1000, "usd_thousands", f"implied_price_override (median {median:.4f} per share)"
        if not dollars and median > _IMPLIED_PRICE_MAX_THOUSANDS:
            return 1, "usd", f"implied_price_override (median {median:.4f} per share)"
        return (1, "usd", "filing_date+implied_price") if dollars else (
            1000,
            "usd_thousands",
            "filing_date+implied_price",
        )
    return (1, "usd", "filing_date") if dollars else (1000, "usd_thousands", "filing_date")


def _aggregate(rows: List[Dict[str, Any]], multiplier: int) -> List[Dict[str, Any]]:
    """Collapse duplicate rows for one security into a single position.

    A manager that spreads discretion across sub-advisers files one row per
    sub-adviser for the same CUSIP, so ranking the raw rows would both split and
    understate the real position.

    Args:
        rows: Parsed information-table rows.
        multiplier: Factor converting ``value_raw`` to USD.

    Returns:
        Positions sorted by USD value, largest first.
    """
    merged: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
    for row in rows:
        key = (row["cusip"], row["title_of_class"], row["put_call"], row["share_type"])
        position = merged.get(key)
        if position is None:
            position = {
                "issuer": row["issuer"],
                "cusip": row["cusip"],
                "title_of_class": row["title_of_class"],
                "put_call": row["put_call"],
                "share_type": row["share_type"],
                "value_usd": 0.0,
                "shares": 0.0,
                "rows": 0,
            }
            merged[key] = position
        position["value_usd"] += (row["value_raw"] or 0.0) * multiplier
        position["shares"] += row["shares"] or 0.0
        position["rows"] += 1

    positions = sorted(merged.values(), key=lambda p: p["value_usd"], reverse=True)
    total = sum(p["value_usd"] for p in positions) or 0.0
    for position in positions:
        position["value_usd"] = round(position["value_usd"], 2)
        position["weight_pct"] = round(100.0 * position["value_usd"] / total, 4) if total else None
    return positions


def _fetch_holdings(cik: str, filing: Dict[str, Any], cusip_filter: Optional[str] = None) -> Dict[str, Any]:
    """Fetch and shape one filing's holdings. Never raises.

    Args:
        cik: Padded CIK of the filer.
        filing: A filing dict from :func:`_list_13f_filings`.
        cusip_filter: Restrict parsing to a single CUSIP.

    Returns:
        The filing metadata plus ``positions`` on success, or an ``error`` key
        describing why this one filing could not be read.
    """
    result = {
        "accession": filing.get("accession"),
        "form": filing.get("form"),
        "filing_date": filing.get("filing_date"),
        "quarter": _quarter_label(filing.get("period_end")),
        "period_end": filing.get("period_end"),
    }
    try:
        urls, note = _information_table_urls(cik, filing["accession"])
    except Exception as exc:  # noqa: BLE001 - one unreadable filing must not kill the batch
        return {**result, "error": f"filing index request failed: {exc}"}
    if not urls:
        return {**result, "error": note or "no information table found"}

    last_error: Optional[str] = None
    for url in urls:
        try:
            raw = _sec_get(url).content
        except Exception as exc:  # noqa: BLE001 - try the next candidate document
            last_error = f"{url.rsplit('/', 1)[-1]}: {exc}"
            continue
        if len(raw) > _max_xml_bytes():
            last_error = f"{url.rsplit('/', 1)[-1]}: document exceeds the size ceiling"
            continue
        try:
            rows = _parse_information_table(raw, cusip_filter)
        except Exception as exc:  # noqa: BLE001 - a non-table XML is expected among candidates
            last_error = f"{url.rsplit('/', 1)[-1]}: {exc}"
            continue
        # Unit detection must see the whole table; a CUSIP-filtered read has too
        # few rows for the median check, so it is re-derived from all rows.
        scale_rows = rows if cusip_filter is None else _parse_information_table(raw)
        multiplier, units, basis = _detect_value_units(scale_rows, filing.get("filing_date"))
        return {
            **result,
            "document_url": url,
            "value_units": units,
            "value_units_basis": basis,
            "row_count": len(rows),
            "truncated_rows": len(rows) >= _MAX_INFOTABLE_ROWS,
            "positions": _aggregate(rows, multiplier),
        }
    return {**result, "error": last_error or "no parseable information table"}


def _fetch_summary(cik: str, accession: str) -> Dict[str, Any]:
    """Read a filing's ``primary_doc.xml`` cover and summary page. Never raises.

    The cover page is the only place the amendment semantics are recorded, so
    ``isAmendment``, ``amendmentNo`` and ``amendmentInfo/amendmentType`` are read
    verbatim here and interpreted in :func:`_classify_filing`. Each of those tag
    names occurs at most once per document, so the flat first-wins field map is
    safe for them.

    Args:
        cik: CIK in any form.
        accession: Accession number.

    Returns:
        ``{manager, report_type, period_of_report, total_value_raw,
        holdings_count, is_amendment, amendment_no, amendment_type}`` where
        known, or ``{"error": ...}``.
    """
    cik_digits = str(cik).lstrip("0") or "0"
    url = f"{_ARCHIVES}/{cik_digits}/{str(accession).replace('-', '')}/primary_doc.xml"
    try:
        root = ET.fromstring(_sec_get(url).content)
    except Exception as exc:  # noqa: BLE001 - one bad cover page must not kill a scan
        return {"error": str(exc)}
    fields: Dict[str, str] = {}
    for node in root.iter():
        name = _local(node.tag)
        text = (node.text or "").strip()
        if text and name not in fields:
            fields[name] = text
    return {
        "manager": fields.get("name"),
        "report_type": fields.get("reportType"),
        "period_of_report": fields.get("reportCalendarOrQuarter"),
        "total_value_raw": _to_number(fields.get("tableValueTotal")),
        "holdings_count": _to_number(fields.get("tableEntryTotal")),
        "is_amendment": _to_bool(fields.get("isAmendment")),
        "amendment_no": _to_number(fields.get("amendmentNo")),
        "amendment_type": (fields.get("amendmentType") or "").strip().upper() or None,
    }


def _summary_value_usd(summary: Dict[str, Any], filing_date: Optional[str]) -> Optional[float]:
    """Convert a cover page's reported total to USD using the filing-date prior.

    A cover page carries no per-share figures, so the implied-price check that
    guards :func:`_detect_value_units` is unavailable here and the filing-date
    prior is all there is. Callers must present the result as approximate; use
    :func:`_summary_units` when the prior needs checking against evidence.
    """
    total = summary.get("total_value_raw")
    if total is None:
        return None
    return round(total * (1 if str(filing_date or "") >= _DOLLAR_UNITS_FROM else 1000), 2)


def _summary_units(
    cik: str,
    filing: Dict[str, Any],
    summary: Dict[str, Any],
) -> Tuple[Optional[float], Optional[str], str]:
    """Scale a cover-page total to USD, checking the prior when it looks wrong.

    The filing-date prior alone misreads the roughly 5% of managers who still
    report in thousands (see :data:`_FILING_THRESHOLD_USD`). Whenever the prior
    produces a total below the $100M level that compels filing at all, the
    filing's own information table is read and its implied-price verdict — the
    same evidence :func:`_detect_value_units` uses — decides the unit. Nothing
    is rescaled on the strength of the threshold alone.

    Args:
        cik: Padded CIK of the filer.
        filing: Filing dict carrying ``accession`` and ``filing_date``.
        summary: The parsed cover page from :func:`_fetch_summary`.

    Returns:
        ``(value_usd, units, basis)``; ``value_usd`` is ``None`` when the cover
        page carried no total.
    """
    value = _summary_value_usd(summary, filing.get("filing_date"))
    dollars = str(filing.get("filing_date") or "") >= _DOLLAR_UNITS_FROM
    units = "usd" if dollars else "usd_thousands"
    if value is None or not 0 < value < _FILING_THRESHOLD_USD:
        return value, units, "filing_date"

    detail = _fetch_holdings(cik, filing)
    if "error" in detail:
        return value, units, f"filing_date (unverified: {detail['error']})"
    table_units = detail.get("value_units")
    if table_units == units:
        return value, units, "filing_date+information_table"
    raw = summary.get("total_value_raw") or 0.0
    multiplier = 1000 if table_units == "usd_thousands" else 1
    return round(raw * multiplier, 2), str(table_units), "information_table_implied_price"


# --------------------------------------------------------------------------- #
# Amendment chain
# --------------------------------------------------------------------------- #


def _without_positions(detail: Dict[str, Any]) -> Dict[str, Any]:
    """Return a filing detail stripped of its position list, safe to embed in an envelope."""
    return {k: v for k, v in detail.items() if k != "positions"}


def _classify_filing(filing: Dict[str, Any], summary: Dict[str, Any]) -> Dict[str, Any]:
    """Decide what one filing does to the quarter it belongs to.

    Two independent signals exist and live filings show them disagreeing in both
    directions (see gotcha 3 in the module docstring), so a filing counts as an
    amendment when *either* the submission type ends in ``/A`` or the cover page
    sets ``isAmendment``. Only then does ``amendmentType`` choose between
    replacing the quarter and extending it; a type that is absent or outside the
    two values SEC filers actually use resolves to
    :data:`_ROLE_UNSPECIFIED`, which no caller acts on.

    Args:
        filing: A filing dict carrying at least ``form``.
        summary: The parsed cover page from :func:`_fetch_summary`.

    Returns:
        ``{is_amendment, amendment_no, amendment_type, amendment_type_known,
        role, role_basis}``. ``role_basis`` names every signal that was read so
        a caller can see *why* a filing was classified the way it was.
    """
    form = str(filing.get("form") or "").upper()
    form_says = form.endswith("/A")
    cover_error = summary.get("error")
    cover_says = None if cover_error else summary.get("is_amendment")
    declared = None if cover_error else summary.get("amendment_type")

    is_amendment = bool(cover_says) or form_says
    role = _AMENDMENT_ROLES.get(declared or "", _ROLE_UNSPECIFIED) if is_amendment else _ROLE_ORIGINAL

    signals = [f"submissionType={form or 'unknown'}"]
    if cover_error:
        signals.append(f"coverPage=unreadable ({cover_error})")
    else:
        signals.append(f"coverPage.isAmendment={cover_says}")
        signals.append(f"coverPage.amendmentType={declared or 'absent'}")
    return {
        "is_amendment": is_amendment,
        "amendment_no": None if cover_error else summary.get("amendment_no"),
        "amendment_type": declared,
        "amendment_type_known": (role != _ROLE_UNSPECIFIED) if is_amendment else None,
        "role": role,
        "role_basis": "; ".join(signals),
    }


def _quarter_chain(
    cik: str, filings: List[Dict[str, Any]], budget: Optional["_Budget"] = None
) -> Tuple[List[Dict[str, Any]], bool]:
    """Read one quarter's filings into an ordered amendment chain.

    Ordering is the order the filings take effect: originals first, then
    amendments oldest-first by filing date with ``amendmentNo`` breaking ties.
    DZ BANK filed both of its 2020-09-30 amendments on 2026-05-04, so the number
    is what puts the ``RESTATEMENT`` (no. 1) ahead of the ``NEW HOLDINGS``
    (no. 2) that extends it.

    Args:
        cik: Padded CIK of the filer.
        filings: Every filing that filer made for the one quarter.
        budget: Optional wall-clock guard; the chain stops short rather than
            overrunning it.

    Returns:
        ``(chain, truncated)``; each entry is the filing dict plus its parsed
        ``summary`` and the verdict from :func:`_classify_filing`.
    """
    truncated = len(filings) > _MAX_CHAIN_FILINGS
    chain: List[Dict[str, Any]] = []
    for filing in filings[:_MAX_CHAIN_FILINGS]:
        if budget is not None and not budget.ok():
            truncated = True
            break
        summary = _fetch_summary(cik, filing["accession"])
        chain.append({**filing, "summary": summary, **_classify_filing(filing, summary)})
    chain.sort(
        key=lambda f: (
            0 if f["role"] == _ROLE_ORIGINAL else 1,
            str(f.get("filing_date") or ""),
            f["amendment_no"] if f["amendment_no"] is not None else 0.0,
            str(f.get("accession") or ""),
        )
    )
    return chain, truncated


def _merge_positions(
    base: List[Dict[str, Any]], extra: List[Dict[str, Any]]
) -> Tuple[List[Dict[str, Any]], int]:
    """Union two aggregated position lists, summing anything they both report.

    Both sides are already scaled to USD by :func:`_aggregate`, which is what
    makes this safe across a chain whose filings use different value units — DZ
    BANK's 2020-09-30 original is denominated in thousands and its 2026
    amendments in whole dollars.

    A ``NEW HOLDINGS`` amendment is meant to carry securities the original
    omitted, so overlap should be empty. When it is not, the rows are summed
    (that is what "add new holdings" says) and the overlap is counted so the
    caller can see that the filer reported the same security twice rather than
    having it silently folded in.

    Args:
        base: Positions accumulated so far.
        extra: Positions from the amendment being merged in.

    Returns:
        ``(positions, overlapping_securities)`` sorted by USD value, largest first.
    """
    merged: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
    overlaps = 0
    for source in (base, extra):
        for position in source:
            key = (
                position["cusip"],
                position["title_of_class"],
                position["put_call"],
                position["share_type"],
            )
            slot = merged.get(key)
            if slot is None:
                merged[key] = dict(position)
                continue
            if source is extra:
                overlaps += 1
            slot["value_usd"] += position["value_usd"]
            slot["shares"] += position["shares"]
            slot["rows"] += position["rows"]
            slot["issuer"] = slot["issuer"] or position["issuer"]

    positions = sorted(merged.values(), key=lambda p: p["value_usd"], reverse=True)
    total = sum(p["value_usd"] for p in positions) or 0.0
    for position in positions:
        position["value_usd"] = round(position["value_usd"], 2)
        position["weight_pct"] = round(100.0 * position["value_usd"] / total, 4) if total else None
    return positions, overlaps


def _unresolved_reason(role: str) -> Optional[str]:
    """Explain why a filing cannot be applied, or ``None`` when it can be.

    Two filings in one quarter cannot both be applied without a rule saying how,
    and only ``amendmentType`` supplies such a rule. A second filing that is not
    an amendment at all supplies none. It is rare but it does happen — none of
    the 9,312 filer-quarters in the 2026-03-01..2026-05-31 Form 13F data set
    produced one, yet 2 of the 8,933 filer-quarters in 2023q2 did — so rather
    than inventing a merge-or-replace convention off two observations, it is
    reported unapplied and the caller is told.
    """
    if role == _ROLE_UNSPECIFIED:
        return (
            "the cover page declares an amendment but names no amendmentType, so whether this "
            "table replaces the quarter or only adds to it is UNKNOWN"
        )
    if role == _ROLE_ORIGINAL:
        return (
            "a second filing for this quarter that is not marked as an amendment, so whether it "
            "supersedes or supplements the first is UNKNOWN"
        )
    return None


def _resolution_label(applied_roles: List[str], unresolved_amendments: int, unresolved_originals: int) -> str:
    """Name what the chain walk actually did, in one machine-readable token."""
    if applied_roles[:1] == [_ROLE_NEW_HOLDINGS]:
        # Nothing to add to: a NEW HOLDINGS amendment reports only what a base
        # filing omitted, so on its own it is a fragment of a quarter and must
        # not be labelled as though a base had been found and extended.
        return "new_holdings_without_base"
    if unresolved_amendments:
        return "incomplete_unspecified_amendment"
    if unresolved_originals:
        return "incomplete_duplicate_originals"
    if _ROLE_RESTATEMENT in applied_roles and _ROLE_NEW_HOLDINGS in applied_roles:
        return "restated_then_extended"
    if _ROLE_RESTATEMENT in applied_roles:
        return "restated"
    if _ROLE_NEW_HOLDINGS in applied_roles:
        return "original_plus_new_holdings"
    return "original_only"


def _walk_chain(
    cik: str,
    chain: List[Dict[str, Any]],
    cusip_filter: Optional[str],
    budget: Optional["_Budget"],
    skip_superseded: bool,
) -> Dict[str, Any]:
    """Walk an amendment chain into the quarter's actual holdings. Never raises.

    ``RESTATEMENT`` replaces everything accumulated so far; ``NEW HOLDINGS`` is
    merged on top of it; an amendment whose type the filer left blank is fetched
    and described but **not** applied, because applying it either way would be a
    guess. When such an amendment is the only readable table for the quarter it
    is reported anyway — there is nothing else — and the resolution says so.

    Args:
        cik: Padded CIK of the filer.
        chain: Ordered chain from :func:`_quarter_chain`.
        cusip_filter: Restrict every table read to a single CUSIP.
        budget: Optional wall-clock guard.

    Returns:
        ``{positions, standing_filing, sources, resolution, resolution_note,
        unresolved_amendments, overlapping_positions}`` or ``{"error": ...}``
        when no table in the chain could be read.
    """
    positions: Optional[List[Dict[str, Any]]] = None
    standing: Optional[Dict[str, Any]] = None
    sources: List[Dict[str, Any]] = []
    unresolved: List[Tuple[int, Dict[str, Any]]] = []
    unresolved_originals = 0
    applied_roles: List[str] = []
    overlaps = 0
    last_error: Optional[str] = None

    # A filing that a later RESTATEMENT wipes out contributes nothing, so its
    # table is never downloaded. Skipping it is not just cheaper: DZ BANK's
    # superseded 2020-09-30 original is a 1,851-row document read only to be
    # discarded. If the restatement then turns out to be unreadable the walk is
    # repeated over the whole chain (``superseded`` is cleared), so nothing is
    # lost to the optimization.
    replacements = [i for i, e in enumerate(chain) if e["role"] == _ROLE_RESTATEMENT]
    superseded: set = set()
    if skip_superseded and replacements:
        superseded = {
            i for i in range(replacements[-1]) if chain[i]["role"] in (_ROLE_ORIGINAL, _ROLE_RESTATEMENT)
        }

    for index, entry in enumerate(chain):
        if budget is not None and not budget.ok():
            break
        record = {
            "accession": entry.get("accession"),
            "form": entry.get("form"),
            "filing_date": entry.get("filing_date"),
            "role": entry["role"],
            "amendment_no": entry["amendment_no"],
            "amendment_type": entry["amendment_type"],
            "amendment_type_known": entry["amendment_type_known"],
            "role_basis": entry["role_basis"],
        }
        if index in superseded:
            sources.append(
                {
                    **record,
                    "applied": False,
                    "not_applied_reason": "superseded by a later RESTATEMENT for the same quarter",
                }
            )
            continue
        detail = _fetch_holdings(cik, entry, cusip_filter)
        if "error" in detail:
            last_error = detail["error"]
            sources.append({**record, "applied": False, "error": detail["error"]})
            continue
        record.update(
            row_count=detail["row_count"],
            document_url=detail["document_url"],
            value_units=detail["value_units"],
            value_units_basis=detail["value_units_basis"],
        )

        # An unspecified amendment is never applied. A plain filing is applied
        # only while nothing has been applied yet — a second one has no stated
        # relationship to the first.
        blocked = entry["role"] == _ROLE_UNSPECIFIED or (
            entry["role"] == _ROLE_ORIGINAL and positions is not None
        )
        if blocked:
            sources.append(
                {**record, "applied": False, "not_applied_reason": _unresolved_reason(entry["role"])}
            )
            if entry["role"] == _ROLE_ORIGINAL:
                unresolved_originals += 1
            else:
                unresolved.append((len(sources) - 1, detail))
            continue

        if positions is None or entry["role"] == _ROLE_RESTATEMENT:
            effect = "replace" if entry["role"] == _ROLE_RESTATEMENT else "base"
            positions, standing = detail["positions"], _without_positions(detail)
            sources.append({**record, "applied": True, "effect": effect})
        else:
            positions, hit = _merge_positions(positions, detail["positions"])
            overlaps += hit
            sources.append({**record, "applied": True, "effect": "merge"})
        applied_roles.append(entry["role"])

    if positions is None and unresolved:
        index, detail = unresolved[-1]
        positions, standing = detail["positions"], _without_positions(detail)
        sources[index] = {
            **sources[index],
            "applied": True,
            "effect": "only_readable_table",
            "not_applied_reason": None,
        }
        note = (
            "The only readable table for this quarter is an amendment whose cover page names no "
            "amendmentType. It is reported as-is and is NOT confirmed to be the complete quarter."
        )
        return {
            "positions": positions,
            "standing_filing": standing,
            "sources": sources,
            "resolution": "unverified_amendment_only",
            "resolution_note": note,
            "unresolved_amendments": len(unresolved),
            "unresolved_duplicate_originals": unresolved_originals,
            "overlapping_positions": overlaps,
        }

    if positions is None:
        return {"error": last_error or "no readable information table in this quarter's filings"}

    resolution = _resolution_label(applied_roles, len(unresolved), unresolved_originals)
    notes = {
        "original_only": "One original 13F-HR, no amendment applied.",
        "restated": (
            "A 13F-HR/A of type RESTATEMENT replaced the earlier table for this quarter; the "
            "superseded filing is listed in 'sources' with applied=false."
        ),
        "original_plus_new_holdings": (
            "A 13F-HR/A of type NEW HOLDINGS reports only securities omitted from the base "
            "filing, so its rows were merged on top of it rather than replacing it."
        ),
        "restated_then_extended": (
            "The quarter was restated and then extended: the RESTATEMENT replaced the base table "
            "and the NEW HOLDINGS amendment was merged on top of the restated table."
        ),
        "incomplete_unspecified_amendment": (
            f"{len(unresolved)} amendment(s) for this quarter declare no amendmentType, so it is "
            "UNKNOWN whether they replace these positions or add to them. They were NOT applied; "
            "each is listed in 'sources' with its own row count and document URL so the caller "
            "can decide. Treat these positions as provisional."
        ),
        "incomplete_duplicate_originals": (
            f"{unresolved_originals} further filing(s) for this quarter are not marked as "
            "amendments, so their relationship to the applied filing is UNKNOWN and they were "
            "NOT applied. Treat these positions as provisional."
        ),
        # Whether a base filing is absent or merely unreadable changes what the
        # caller should do about it, so the note must not assert the stronger
        # claim when 'sources' itself lists a base filing that failed to fetch.
        "new_holdings_without_base": (
            "The earliest applicable filing for this quarter is a NEW HOLDINGS amendment, which "
            "reports only securities a base filing omitted — and "
            + (
                "the base filing(s) for this quarter are listed in 'sources' but none could be "
                "read, so none was applied"
                if any(s["role"] in (_ROLE_ORIGINAL, _ROLE_RESTATEMENT) for s in sources)
                else "no base filing was found in this filer's 13F index"
            )
            + ". These positions are therefore a FRAGMENT of the quarter, not the "
            "manager's portfolio."
        ),
    }
    return {
        "positions": positions,
        "standing_filing": standing,
        "sources": sources,
        "resolution": resolution,
        "resolution_note": notes[resolution],
        "unresolved_amendments": len(unresolved),
        "unresolved_duplicate_originals": unresolved_originals,
        "overlapping_positions": overlaps,
    }


def _resolve_chain_holdings(
    cik: str,
    chain: List[Dict[str, Any]],
    cusip_filter: Optional[str] = None,
    budget: Optional["_Budget"] = None,
) -> Dict[str, Any]:
    """Resolve one quarter's holdings, retrying the superseded filings if needed.

    The fast walk never downloads a table a later ``RESTATEMENT`` replaces. The
    only thing that entitles it to skip those tables is the restatement actually
    being applied, so the walk is repeated over the full chain whenever no
    restatement was — whether it left the quarter unreadable outright or merely
    left a ``NEW HOLDINGS`` fragment standing in for a base filing that was
    never downloaded. Checking only for an outright error is not enough: DZ
    BANK's real 2020-09-30 chain is original + RESTATEMENT + NEW HOLDINGS, so a
    single failed restatement fetch would otherwise return the 2-row amendment
    and leave the 1,851-row original skipped.

    Args:
        cik: Padded CIK of the filer.
        chain: Ordered chain from :func:`_quarter_chain`.
        cusip_filter: Restrict every table read to a single CUSIP.
        budget: Optional wall-clock guard.

    Returns:
        The dict described by :func:`_walk_chain`.
    """
    resolved = _walk_chain(cik, chain, cusip_filter, budget, skip_superseded=True)
    if not any(entry["role"] == _ROLE_RESTATEMENT for entry in chain):
        return resolved
    if any(s.get("applied") and s["role"] == _ROLE_RESTATEMENT for s in resolved.get("sources") or []):
        return resolved
    return _walk_chain(cik, chain, cusip_filter, budget, skip_superseded=False)


def _resolve_chain_value(
    cik: str, chain: List[Dict[str, Any]]
) -> Tuple[Optional[float], Optional[str], str, Dict[str, Any]]:
    """Total a quarter's reported portfolio value from cover pages alone.

    Cheaper than :func:`_resolve_chain_holdings` — used by ``top_managers``,
    where only the total is ranked — and follows the same rules: a
    ``RESTATEMENT`` cover total replaces, a ``NEW HOLDINGS`` cover total is
    added, an unspecified amendment is skipped and flagged. Every filing's total
    is scaled to USD independently by :func:`_summary_units`, which is required
    when a 2020 original in thousands is restated in 2026 in whole dollars.

    Args:
        cik: Padded CIK of the filer.
        chain: Ordered chain from :func:`_quarter_chain`.

    Returns:
        ``(value_usd, units, basis, amendment_block)``.
    """
    value: Optional[float] = None
    units: Optional[str] = None
    basis = "no_readable_cover_page"
    applied_roles: List[str] = []
    unresolved: List[Dict[str, Any]] = []
    unresolved_originals = 0
    merged = 0
    standing: Optional[Dict[str, Any]] = None

    replacements = [i for i, e in enumerate(chain) if e["role"] == _ROLE_RESTATEMENT]
    superseded = (
        {i for i in range(replacements[-1]) if chain[i]["role"] in (_ROLE_ORIGINAL, _ROLE_RESTATEMENT)}
        if replacements
        else set()
    )

    for index, entry in enumerate(chain):
        summary = entry.get("summary") or {}
        if "error" in summary or index in superseded:
            continue
        entry_value, entry_units, entry_basis = _summary_units(cik, entry, summary)
        blocked = entry["role"] == _ROLE_UNSPECIFIED or (
            entry["role"] == _ROLE_ORIGINAL and value is not None
        )
        if blocked:
            if entry["role"] == _ROLE_ORIGINAL:
                unresolved_originals += 1
                continue
            unresolved.append(
                {
                    "accession": entry.get("accession"),
                    "form": entry.get("form"),
                    "filing_date": entry.get("filing_date"),
                    "reported_value_usd": entry_value,
                    "holdings_count": summary.get("holdings_count"),
                }
            )
            continue
        if value is None or entry["role"] == _ROLE_RESTATEMENT:
            value, units, basis, standing = entry_value, entry_units, entry_basis, entry
        else:
            value = round((value or 0.0) + (entry_value or 0.0), 2)
            merged += 1
        applied_roles.append(entry["role"])

    if value is None and unresolved:
        # Same rule as the holdings walk: an unverified amendment is still the
        # only number this quarter has, so it is reported and labelled.
        fallback = unresolved[-1]
        value = fallback["reported_value_usd"]
        units, basis = None, "unverified_amendment_only"

    resolution = (
        "unverified_amendment_only"
        if basis == "unverified_amendment_only"
        else _resolution_label(applied_roles, len(unresolved), unresolved_originals)
    )
    if merged:
        basis = f"{basis}+merged_{merged}_new_holdings_amendment"
    return (
        value,
        units,
        basis,
        {
            "resolution": resolution,
            "standing_accession": (standing or {}).get("accession"),
            "filings_applied": len(applied_roles),
            "unresolved_amendments": unresolved,
            "unresolved_duplicate_originals": unresolved_originals,
        },
    )


def _amendment_digest(resolved: Dict[str, Any]) -> Dict[str, Any]:
    """Compress a chain walk to the few fields a per-row listing can afford."""
    return {
        "resolution": resolved.get("resolution"),
        "filings_applied": sum(1 for s in resolved.get("sources") or [] if s.get("applied")),
        "unresolved_amendments": resolved.get("unresolved_amendments", 0),
        "unresolved_duplicate_originals": resolved.get("unresolved_duplicate_originals", 0),
        "standing_accession": (resolved.get("standing_filing") or {}).get("accession"),
        "standing_form": (resolved.get("standing_filing") or {}).get("form"),
    }


# --------------------------------------------------------------------------- #
# Quarter-over-quarter changes
# --------------------------------------------------------------------------- #


def _diff_positions(current: List[Dict[str, Any]], prior: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Classify quarter-over-quarter position changes.

    Keyed on ``(cusip, put_call)`` rather than the class title, because filers
    spell ``titleOfClass`` inconsistently across quarters while the CUSIP is
    stable.

    Args:
        current: Aggregated positions for the newer quarter.
        prior: Aggregated positions for the older quarter.

    Returns:
        Every change, sorted by the absolute USD move, largest first. Unchanged
        positions are omitted. The list is deliberately uncapped so the caller's
        per-action counts describe the whole quarter; trimming for the result
        budget happens afterwards in :func:`_fit_changes`.
    """
    def index(positions: Iterable[Dict[str, Any]]) -> Dict[Tuple[Any, Any], Dict[str, Any]]:
        out: Dict[Tuple[Any, Any], Dict[str, Any]] = {}
        for position in positions:
            key = (position["cusip"], position["put_call"])
            merged = out.setdefault(
                key, {"issuer": position["issuer"], "value_usd": 0.0, "shares": 0.0}
            )
            merged["value_usd"] += position["value_usd"]
            merged["shares"] += position["shares"]
        return out

    now, before = index(current), index(prior)
    changes: List[Dict[str, Any]] = []
    for key in set(now) | set(before):
        cusip, put_call = key
        new_side = now.get(key)
        old_side = before.get(key)
        new_shares = new_side["shares"] if new_side else 0.0
        old_shares = old_side["shares"] if old_side else 0.0
        if new_side is None:
            action = "closed"
        elif old_side is None:
            action = "new"
        elif new_shares > old_shares:
            action = "increased"
        elif new_shares < old_shares:
            action = "reduced"
        else:
            continue
        new_value = new_side["value_usd"] if new_side else 0.0
        old_value = old_side["value_usd"] if old_side else 0.0
        changes.append(
            {
                "action": action,
                "issuer": (new_side or old_side)["issuer"],
                "cusip": cusip,
                "put_call": put_call,
                "shares_before": round(old_shares, 4),
                "shares_after": round(new_shares, 4),
                "shares_change": round(new_shares - old_shares, 4),
                "shares_change_pct": round(100.0 * (new_shares - old_shares) / old_shares, 4)
                if old_shares
                else None,
                "value_usd_before": round(old_value, 2),
                "value_usd_after": round(new_value, 2),
                "value_usd_change": round(new_value - old_value, 2),
            }
        )
    changes.sort(key=lambda c: abs(c["value_usd_change"]), reverse=True)
    return changes


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #


def _fit_changes(changes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Trim the change list to the share of the result budget reserved for it.

    ``fit_records`` pages the position list but the changes block rides along
    inside the fixed part of the envelope, so without this a busy quarter
    (Bridgewater's 2026Q1 diff runs to 200 changes and 60,419 characters) would
    blow the whole result past its cap and be cut mid-structure downstream —
    the exact silent truncation the paging helper exists to prevent.

    Args:
        changes: Changes already sorted by descending dollar impact.

    Returns:
        The longest prefix whose serialization fits the reserved share.
    """
    budget = int(TOOL_RESULT_LIMIT * _CHANGES_BUDGET_SHARE)
    kept = changes[:_MAX_CHANGES]
    while len(kept) > 1:
        size = len(json.dumps(kept, ensure_ascii=False))
        if size <= budget:
            break
        # Shrink proportionally to the overflow so a wide record set converges
        # in a couple of rounds rather than one element at a time.
        kept = kept[: max(1, min(len(kept) - 1, int(len(kept) * budget / size)))]
    return kept


def _to_number(value: Any) -> Optional[float]:
    """Coerce a text field to ``float``, or ``None`` when absent/non-numeric."""
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _to_bool(value: Any) -> Optional[bool]:
    """Coerce a cover-page flag to ``bool``, or ``None`` when absent/unreadable.

    ``None`` is a third state, not a false: a cover page that never wrote
    ``isAmendment`` says nothing about whether the filing amends anything, and
    collapsing that to ``False`` is exactly the assumption this module refuses
    to make.
    """
    if value is None:
        return None
    text = str(value).strip().upper()
    if text in _TRUE_TEXT:
        return True
    if text in _FALSE_TEXT:
        return False
    return None


def _at(seq: Any, idx: int) -> Optional[str]:
    """Return ``seq[idx]`` as a stripped string, or ``None`` when out of range/empty."""
    if not isinstance(seq, list) or idx >= len(seq):
        return None
    value = seq[idx]
    return (str(value).strip() or None) if value is not None else None


def _clamp(value: Any, default: int, maximum: int) -> int:
    """Coerce a count into ``1..maximum``, falling back to ``default``."""
    try:
        return max(1, min(int(value), maximum))
    except (TypeError, ValueError, OverflowError):
        return default


def _error(message: str, **extra: Any) -> str:
    """Render a failure envelope as a JSON string."""
    return json.dumps({"ok": False, "error": message, **extra}, ensure_ascii=False)


def _envelope(mode: str, data: Dict[str, Any], records: List[Any], record_key: str, offset: int) -> str:
    """Serialize an envelope whose ``record_key`` list is paged to fit one result."""

    def build(page: List[Any], paging: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "ok": True,
            "market": "US",
            "source": "sec_edgar_13f",
            "mode": mode,
            "paging": paging,
            "data": {**data, record_key: page},
        }

    return fit_records(records, offset, build)


# --------------------------------------------------------------------------- #
# Tool
# --------------------------------------------------------------------------- #


class InstitutionalHoldingsTool(BaseTool):
    """Query SEC Form 13F-HR institutional holdings three ways."""

    name = "get_institutional_holdings"
    description = (
        "U.S. institutional equity holdings from SEC Form 13F-HR (free EDGAR "
        "data, quarterly, filed within 45 days of quarter end). Three modes: "
        "mode='manager_holdings' returns one manager's portfolio for a quarter, "
        "largest position first, optionally with quarter-over-quarter changes "
        "(new / increased / reduced / closed); mode='ticker_holders' returns "
        "which managers reported a given stock; mode='top_managers' ranks "
        "managers by reported 13F portfolio value. Position values are "
        "normalized to USD and each result states which unit the filing used. "
        "Amendments are followed rather than ignored: a quarter is resolved "
        "across every filing the manager made for it, where a 13F-HR/A of type "
        "RESTATEMENT replaces the earlier table and one of type NEW HOLDINGS is "
        "merged on top of it, and 'amendment_resolution' reports which filing "
        "each answer stands on. "
        "LIMITS: 13F covers only U.S.-listed long equity, options and "
        "convertibles reported by managers over $100M — no shorts, no cash, no "
        "non-U.S. listings, and the data is 45+ days stale by construction. "
        "ticker_holders needs a ticker->CUSIP match in the SEC fails-to-deliver "
        "file (broad but not universal); pass 'cusip' directly when a ticker "
        "cannot be resolved. top_managers ranks within a bounded scanned sample, "
        "not the full filer universe. A minority of amendments name no "
        "amendmentType at all; those are NOT applied and the result is flagged "
        "'incomplete_unspecified_amendment' rather than guessed. Example: "
        '{"mode": "manager_holdings", "manager": "Berkshire Hathaway", '
        '"quarter": "2026Q1", "include_changes": true}.'
    )
    parameters = {
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "enum": list(_MODES),
                "description": (
                    "'manager_holdings' = one manager's reported portfolio; "
                    "'ticker_holders' = which managers hold one security; "
                    "'top_managers' = managers ranked by reported portfolio value."
                ),
                "default": "manager_holdings",
            },
            "manager": {
                "type": "string",
                "description": (
                    "Required for mode='manager_holdings'. A 13F filer name "
                    "(e.g. 'Berkshire Hathaway', 'Bridgewater Associates') or a "
                    "CIK (e.g. '0001067983'). Ambiguous names return the best "
                    "match plus the other candidates."
                ),
            },
            "ticker": {
                "type": "string",
                "description": (
                    "For mode='ticker_holders': the U.S. ticker to look up "
                    "(e.g. 'AAPL'). Resolved to a CUSIP via SEC fails-to-deliver "
                    "data; supply 'cusip' instead when the symbol is not covered."
                ),
            },
            "cusip": {
                "type": "string",
                "description": (
                    "For mode='ticker_holders': the 9-character CUSIP to search "
                    "for directly. Takes precedence over 'ticker'."
                ),
            },
            "quarter": {
                "type": "string",
                "description": (
                    "Calendar quarter as '2026Q1' or as the quarter-end date "
                    "'2026-03-31'. Defaults to the most recent quarter whose "
                    "45-day filing deadline has passed."
                ),
            },
            "include_changes": {
                "type": "boolean",
                "description": (
                    "For mode='manager_holdings': also diff this quarter against "
                    "the manager's previous 13F, classifying every position as "
                    "new / increased / reduced / closed. Costs one extra filing "
                    "fetch."
                ),
                "default": False,
            },
            "top_n": {
                "type": "integer",
                "description": (
                    f"Maximum records to rank and return (1-{_MAX_TOP_N}). "
                    f"Defaults to {_DEFAULT_TOP_N} for manager_holdings, "
                    f"{_DEFAULT_HOLDER_SAMPLE} for ticker_holders and 20 for "
                    "top_managers. For ticker_holders this is also the number of "
                    "filings actually downloaded, so it is capped at "
                    f"{_MAX_HOLDER_SAMPLE}."
                ),
            },
            "scan_limit": {
                "type": "integer",
                "description": (
                    f"For mode='top_managers': how many filings to read before "
                    f"ranking (1-{_MAX_SCAN}, default {_DEFAULT_SCAN}). The "
                    "ranking is only valid within this scanned sample."
                ),
            },
            "offset": {
                "type": "integer",
                "description": (
                    "Index of the first record to return. Records are returned "
                    "whole and only as many as fit one result — read "
                    "paging.next_offset and call again to continue."
                ),
            },
        },
        "required": [],
    }

    def execute(self, **kwargs: Any) -> str:
        """Dispatch to the requested 13F mode and return a JSON envelope.

        Args:
            **kwargs: ``mode`` (default ``"manager_holdings"``) plus that mode's
                arguments — see :attr:`parameters`.

        Returns:
            A JSON string. On success ``{"ok": true, "market": "US", "source":
            "sec_edgar_13f", "mode": ..., "paging": {...}, "data": {...}}``; on
            failure ``{"ok": false, "error": ...}``.
        """
        mode = kwargs.get("mode", "manager_holdings")
        if not isinstance(mode, str) or mode not in _MODES:
            return _error(f"mode must be one of {list(_MODES)}")

        try:
            offset = max(int(kwargs.get("offset") or 0), 0)
        except (TypeError, ValueError):
            return _error("offset must be an integer")

        quarter_arg = kwargs.get("quarter")
        period_end: Optional[str] = None
        if quarter_arg not in (None, ""):
            try:
                period_end = _parse_quarter(quarter_arg)
            except ValueError as exc:
                return _error(str(exc))

        handler: Callable[..., str] = {
            "manager_holdings": self._manager_holdings,
            "ticker_holders": self._ticker_holders,
            "top_managers": self._top_managers,
        }[mode]
        try:
            return handler(kwargs, period_end, offset)
        except ValueError as exc:
            return _error(str(exc))
        except Exception as exc:  # noqa: BLE001 - every failure leaves as an envelope
            logger.exception("get_institutional_holdings failed in mode %s", mode)
            return _error(f"SEC 13F request failed: {exc}")

    # -- modes ------------------------------------------------------------- #

    def _manager_holdings(self, kwargs: Dict[str, Any], period_end: Optional[str], offset: int) -> str:
        """Return one manager's reported portfolio, optionally with QoQ changes."""
        manager = kwargs.get("manager")
        if not isinstance(manager, str) or not manager.strip():
            return _error("mode='manager_holdings' requires 'manager' (a filer name or CIK)")

        cik, name, candidates = _resolve_manager(manager)
        filings = _list_13f_filings(cik)
        if not filings:
            return _error(f"no 13F-HR filings found for CIK {cik}", cik=cik, manager=name)

        target = _target_period(filings, period_end)
        pool = _filings_for_period(filings, target)
        if not pool:
            # Only the most recent filings are indexed here, so an unmatched
            # quarter means "not in the window searched", which is not the same
            # claim as "never filed".
            return _error(
                f"quarter ending {period_end} is not among the {len(filings)} most recent "
                f"13F-HR filings of CIK {cik} (searched back to "
                f"{filings[-1].get('period_end')})",
                cik=cik,
                manager=name,
                available_quarters=[f.get("period_end") for f in filings[:12]],
            )

        budget = _Budget()
        chain, chain_truncated = _quarter_chain(cik, pool, budget)
        resolved = _resolve_chain_holdings(cik, chain, budget=budget)
        if "error" in resolved:
            return _error(
                f"could not read information table: {resolved['error']}",
                cik=cik,
                manager=name,
                quarter=_quarter_label(target),
                filings_tried=[
                    {"accession": f.get("accession"), "form": f.get("form"), "role": f["role"]}
                    for f in chain
                ],
            )

        top_n = _clamp(kwargs.get("top_n", _DEFAULT_TOP_N), _DEFAULT_TOP_N, _MAX_TOP_N)
        positions = resolved["positions"]
        total_value = round(sum(p["value_usd"] for p in positions), 2)

        data: Dict[str, Any] = {
            "cik": cik,
            "manager": name,
            # ``filing`` is the document whose table currently stands for the
            # quarter, which is the restatement rather than the original once a
            # quarter has been restated.
            "filing": resolved["standing_filing"],
            "amendment_resolution": {
                "resolution": resolved["resolution"],
                "note": resolved["resolution_note"],
                "unresolved_amendments": resolved["unresolved_amendments"],
                "unresolved_duplicate_originals": resolved["unresolved_duplicate_originals"],
                "overlapping_positions": resolved["overlapping_positions"],
                "chain_truncated": chain_truncated,
                "filings": resolved["sources"],
            },
            "position_count": len(positions),
            # ``paging`` describes the ranked slice, so on its own a complete
            # page of a top_n-capped list reads as the whole portfolio. The
            # smallest positions are the ones dropped; say so rather than
            # leaving it to be inferred from position_count.
            "positions_truncated": len(positions) > top_n,
            "positions_ranked_limit": top_n,
            "portfolio_value_usd": total_value,
        }
        if candidates:
            data["other_name_matches"] = candidates

        if kwargs.get("include_changes"):
            data["changes"] = self._changes_block(cik, filings, target, positions, budget)

        return _envelope("manager_holdings", data, positions[:top_n], "positions", offset)

    def _changes_block(
        self,
        cik: str,
        filings: List[Dict[str, Any]],
        period_end: Optional[str],
        positions: List[Dict[str, Any]],
        budget: "_Budget",
    ) -> Dict[str, Any]:
        """Diff a resolved quarter against the manager's next-older quarter.

        The prior quarter is resolved through the same amendment chain as the
        current one — a diff against a superseded original would invent position
        changes the manager never made.
        """
        older = [
            str(f.get("period_end"))
            for f in filings
            if f.get("period_end") and str(f["period_end"]) < str(period_end or "")
        ]
        if not older:
            return {"error": "no earlier 13F-HR filing available to compare against"}
        prior_period = max(older)
        prior_chain, _ = _quarter_chain(cik, _filings_for_period(filings, prior_period), budget)
        prior = _resolve_chain_holdings(cik, prior_chain, budget=budget)
        if "error" in prior:
            return {
                "error": f"prior quarter unreadable: {prior['error']}",
                "prior_quarter": _quarter_label(prior_period),
            }
        changes = _diff_positions(positions, prior["positions"])
        counts: Dict[str, int] = {}
        for change in changes:
            counts[change["action"]] = counts.get(change["action"], 0) + 1
        # ``counts`` is derived from every change, so the per-action totals stay
        # correct even when the item list below is cut to fit.
        kept = _fit_changes(changes)
        standing = prior["standing_filing"] or {}
        return {
            "prior_quarter": _quarter_label(prior_period),
            "prior_period_end": prior_period,
            "prior_accession": standing.get("accession"),
            "prior_amendment_resolution": _amendment_digest(prior),
            "counts": counts,
            "total": len(changes),
            "returned": len(kept),
            "truncated": len(kept) < len(changes),
            "items": kept,
        }

    def _ticker_holders(self, kwargs: Dict[str, Any], period_end: Optional[str], offset: int) -> str:
        """Return the managers that reported a given security in a quarter."""
        cusip = kwargs.get("cusip")
        ticker = kwargs.get("ticker")
        resolution: Dict[str, Any] = {}

        if isinstance(cusip, str) and cusip.strip():
            cusip = cusip.strip().upper()
            resolution = {"cusip_source": "caller"}
        elif isinstance(ticker, str) and ticker.strip():
            try:
                cusip, description, sources = _cusip_for_ticker(ticker)
            except Exception as exc:  # noqa: BLE001 - report the mapping failure, don't guess
                return _error(
                    f"ticker->CUSIP resolution failed: {exc}. Pass 'cusip' directly to continue.",
                    ticker=ticker.strip().upper(),
                )
            if not cusip:
                return _error(
                    f"ticker {ticker.strip().upper()!r} is not in the SEC fails-to-deliver file, "
                    "which only covers securities that had a settlement failure in the period. "
                    "No CUSIP was guessed; pass 'cusip' directly.",
                    ticker=ticker.strip().upper(),
                    cusip_sources=sources,
                )
            resolution = {
                "cusip_source": "sec_fails_to_deliver",
                "cusip_sources": sources,
                "cusip_description": description,
                "ticker": ticker.strip().upper(),
            }
        else:
            return _error("mode='ticker_holders' requires 'ticker' or 'cusip'")

        target = period_end or _latest_reportable_quarter()
        sample_size = _clamp(
            kwargs.get("top_n", _DEFAULT_HOLDER_SAMPLE), _DEFAULT_HOLDER_SAMPLE, _MAX_HOLDER_SAMPLE
        )
        budget = _Budget()

        # Full-text search hits are documents, not filers: one filing contributes
        # both its cover page and its information table, and a hit may be an
        # amendment for an older quarter. Pages are read only until enough
        # distinct filers for the requested sample have accumulated.
        seen: Dict[str, Dict[str, Any]] = {}
        # Every page of one window repeats that window's total, so the totals are
        # taken per window and only then summed — the windows are disjoint date
        # ranges, so their sum is the document count for the whole span.
        window_totals: List[int] = []
        universe_is_floor = False
        for start, end in _discovery_windows(target):
            cursor = 0
            window_total = 0
            while len(seen) < sample_size and cursor <= _FTS_MAX_FROM and budget.ok():
                page = _fts(
                    {"q": f'"{cusip}"', "forms": "13F-HR", "startdt": start, "enddt": end, "from": cursor}
                )
                window_total = max(window_total, page["total"])
                universe_is_floor = universe_is_floor or page["total_is_lower_bound"]
                if not page["hits"]:
                    break
                for hit in page["hits"]:
                    if hit.get("file_type") != "INFORMATION TABLE" or hit.get("period_ending") != target:
                        continue
                    cik = (hit.get("ciks") or [None])[0]
                    if not cik or cik in seen or not hit.get("adsh"):
                        continue
                    seen[cik] = {
                        "cik": cik,
                        "manager": (hit.get("display_names") or [None])[0],
                        "accession": hit.get("adsh"),
                        "form": hit.get("form"),
                        "filing_date": hit.get("file_date"),
                        "period_end": hit.get("period_ending"),
                        "is_amendment": str(hit.get("form") or "").upper().endswith("/A"),
                    }
                cursor += _FTS_PAGE
            window_totals.append(window_total)
            if len(seen) >= sample_size or not budget.ok():
                break
        universe_documents = sum(window_totals)

        holders: List[Dict[str, Any]] = []
        for discovered in list(seen.values())[:sample_size]:
            if not budget.ok():
                break
            holders.append(self._holder_row(discovered, cusip, target, budget))
        # A filer whose restatement dropped the security is reported as not
        # holding it rather than as an error, and both sort below real holders.
        holders.sort(key=lambda h: (h["value_usd"] is None, -(h["value_usd"] or 0.0)))

        data = {
            "cusip": cusip,
            **resolution,
            "quarter": _quarter_label(target),
            "period_end": target,
            "filers_seen": len(seen),
            "matching_documents_total": universe_documents,
            "matching_documents_total_is_lower_bound": universe_is_floor,
            "sampled": len(holders),
            "budget_exhausted": budget.exhausted,
            "ranking_note": (
                "Ranked by position value WITHIN the sampled filers only. The sample is the "
                "first filers EDGAR full-text search returned for this CUSIP, NOT the largest "
                f"holders. 'matching_documents_total' ({universe_documents}"
                f"{'+' if universe_is_floor else ''}) counts matching EDGAR documents in the "
                "filing windows, not filers, and only bounds how many managers reported this "
                "security. Reading every one of them is out of scope for a single call. Each "
                "holder's position is resolved through that filer's full amendment chain for "
                "the quarter, so a filer that appears here because its ORIGINAL filing named "
                "this CUSIP but whose later RESTATEMENT dropped it is reported with held=false."
            ),
        }
        return _envelope("ticker_holders", data, holders, "holders", offset)

    def _holder_row(
        self, discovered: Dict[str, Any], cusip: str, target: str, budget: "_Budget"
    ) -> Dict[str, Any]:
        """Resolve one discovered filer's position through its whole amendment chain.

        Discovery finds a *document*; the answer needs the *quarter*. Reading
        only the document that matched would report a holding a later
        RESTATEMENT removed, or report a ``NEW HOLDINGS`` fragment as if it were
        the filer's whole position.
        """
        cik = discovered["cik"]
        row: Dict[str, Any] = {
            "cik": cik,
            "manager": discovered["manager"],
            "accession": discovered["accession"],
            "form": discovered["form"],
            "filing_date": discovered["filing_date"],
        }
        try:
            pool = _filings_for_period(_list_13f_filings(cik), target) or [discovered]
            scope = "filer_index"
        except Exception as exc:  # noqa: BLE001 - fall back to the matched document alone
            pool, scope = [discovered], f"discovered_document_only ({exc})"

        chain, _ = _quarter_chain(cik, pool, budget)
        resolved = _resolve_chain_holdings(cik, chain, cusip_filter=cusip, budget=budget)
        if "error" in resolved:
            return {**row, "value_usd": None, "shares": None, "held": None, "error": resolved["error"]}

        standing = resolved["standing_filing"] or {}
        position = (resolved["positions"] or [None])[0]
        return {
            **row,
            "standing_accession": standing.get("accession"),
            "standing_form": standing.get("form"),
            "held": position is not None,
            "value_usd": position["value_usd"] if position else None,
            "shares": position["shares"] if position else None,
            "put_call": position["put_call"] if position else None,
            "value_units": standing.get("value_units"),
            "amendment_resolution": _amendment_digest(resolved),
            "amendment_scope": scope,
            "error": None,
        }

    def _top_managers(self, kwargs: Dict[str, Any], period_end: Optional[str], offset: int) -> str:
        """Rank 13F filers by reported portfolio value within a bounded sample."""
        target = period_end or _latest_reportable_quarter()
        scan_limit = _clamp(kwargs.get("scan_limit", _DEFAULT_SCAN), _DEFAULT_SCAN, _MAX_SCAN)
        top_n = _clamp(kwargs.get("top_n", 20), 20, _MAX_TOP_N)

        budget = _Budget()
        candidates: Dict[str, Dict[str, Any]] = {}
        # Distinct on-target accessions per filer. Two or more means the quarter
        # was amended inside the windows, so the chain has to be resolved even if
        # the matched document looks plain. Counting accessions rather than hits
        # matters: one filing shows up as several full-text-search documents.
        filings_seen: Dict[str, set] = {}
        # See ticker_holders: one window's total repeats on every page of it, so
        # the per-window totals are summed rather than the per-page ones.
        window_totals: List[int] = []
        universe_is_floor = False
        for start, end in _discovery_windows(target):
            cursor = 0
            window_total = 0
            while len(candidates) < scan_limit and cursor <= _FTS_MAX_FROM and budget.ok():
                page = _fts({"forms": "13F-HR", "startdt": start, "enddt": end, "from": cursor})
                window_total = max(window_total, page["total"])
                universe_is_floor = universe_is_floor or page["total_is_lower_bound"]
                if not page["hits"]:
                    break
                for hit in page["hits"]:
                    cik = (hit.get("ciks") or [None])[0]
                    if not cik or not hit.get("adsh") or hit.get("period_ending") != target:
                        continue
                    filings_seen.setdefault(cik, set()).add(hit["adsh"])
                    if cik in candidates or len(candidates) >= scan_limit:
                        continue
                    candidates[cik] = {
                        "cik": cik,
                        "manager": (hit.get("display_names") or [None])[0],
                        "accession": hit.get("adsh"),
                        "form": hit.get("form"),
                        "filing_date": hit.get("file_date"),
                        "period_end": hit.get("period_ending"),
                    }
                cursor += _FTS_PAGE
            window_totals.append(window_total)
            if len(candidates) >= scan_limit or not budget.ok():
                break
        universe_total = sum(window_totals)

        managers: List[Dict[str, Any]] = []
        for candidate in candidates.values():
            if not budget.ok():
                break
            managers.append(self._manager_row(candidate, target, filings_seen, budget))
        managers.sort(
            key=lambda m: (m["portfolio_value_usd"] is None, -(m["portfolio_value_usd"] or 0.0))
        )

        data = {
            "quarter": _quarter_label(target),
            "period_end": target,
            "scanned": len(managers),
            "scan_limit": scan_limit,
            # Same trap as manager_holdings: more filers can be scanned than are
            # ranked back, and a full page would otherwise look exhaustive.
            "managers_truncated": len(managers) > top_n,
            "managers_ranked_limit": top_n,
            "universe_documents": universe_total,
            "universe_documents_is_lower_bound": universe_is_floor,
            "budget_exhausted": budget.exhausted,
            "ranking_note": (
                "Ranked by the portfolio value each filer reports on its own 13F cover page, "
                "WITHIN the scanned sample only — the sample is what EDGAR full-text search "
                "returned first for the quarter, not the largest filers, so this is a "
                "discovery aid and NOT a league table of the largest managers. Cover-page "
                "totals carry no per-share figures, so their USD unit starts from the filing "
                "date; when that lands below the $100M level that compels filing at all, the "
                "information table is read and its implied-price verdict decides. Each row "
                "reports the unit it used in 'value_units_basis'. Amendments are followed: a "
                "RESTATEMENT's total replaces the original's and a NEW HOLDINGS total is added "
                "to it, so a filer is never ranked on a fragment. 'amendment_scope' says "
                "whether that check ran against the filer's whole 13F index or only against "
                "the documents the discovery windows returned. Raising scan_limit widens the "
                "sample but each extra filing is a separate SEC request; when the time budget "
                "runs out 'budget_exhausted' is true and the sample is short."
            ),
        }
        return _envelope("top_managers", data, managers[:top_n], "managers", offset)

    def _manager_row(
        self,
        candidate: Dict[str, Any],
        target: str,
        filings_seen: Dict[str, set],
        budget: "_Budget",
    ) -> Dict[str, Any]:
        """Value one discovered filer, following its amendment chain when there is one.

        The filer's full 13F index is only pulled when this quarter is actually
        implicated in an amendment — the matched document says so, or discovery
        saw more than one filing from that filer for the quarter. Amendments run
        at roughly 4% of filings, so the common filer still costs exactly one
        cover-page request and a wide scan does not double in length.
        """
        cik = candidate["cik"]
        summary = _fetch_summary(cik, candidate["accession"])
        verdict = _classify_filing(candidate, summary)
        chain = [{**candidate, "summary": summary, **verdict}]
        scope = "discovery_window"

        if verdict["is_amendment"] or len(filings_seen.get(cik) or ()) > 1:
            try:
                indexed = _filings_for_period(_list_13f_filings(cik), target)
            except Exception as exc:  # noqa: BLE001 - keep the discovered document
                indexed, scope = [], f"discovery_window (filer index unavailable: {exc})"
            if indexed:
                chain, _ = _quarter_chain(cik, indexed, budget)
                scope = "filer_index"

        value, units, basis, amendment = _resolve_chain_value(cik, chain)
        standing = next((f for f in chain if f.get("accession") == amendment["standing_accession"]), None)
        return {
            **candidate,
            "manager": summary.get("manager") or candidate["manager"],
            "report_type": summary.get("report_type"),
            "holdings_count": ((standing or {}).get("summary") or summary).get("holdings_count"),
            "portfolio_value_usd": value,
            "value_units": units,
            "value_units_basis": basis,
            "amendment_resolution": amendment,
            "amendment_scope": scope,
            "error": summary.get("error"),
        }
