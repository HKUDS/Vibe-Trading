"""Read-only ETF look-through: fund search + constituent holdings, US and A-share.

An ETF price series says nothing about what the fund actually owns. This tool
answers that second question on both sides of the Pacific from free, no-auth
sources, and — because every ETF holdings disclosure is *stale by construction*
— stamps every answer with the report period it belongs to.

United States — SEC N-PORT
--------------------------
Registered funds file Form NPORT-P, whose ``primary_doc.xml`` carries the
**entire** portfolio (``invstOrSecs/invstOrSec``) plus total/net assets. Three
verified facts drive the US path:

* ``company_tickers.json`` (used by :mod:`backtest.loaders.sec_edgar_client`)
  does **not** list most ETFs — IVV, VOO, ARKK and XLK are all absent, because
  the reporting entity is the trust, not the fund. The ticker index that does
  cover them is the Investment Company Series and Class file, which maps
  ``Class Ticker -> (CIK, Series ID, Series Name, Entity Name)``.
* A trust files one NPORT-P per series per period (iShares Trust files
  hundreds), so the filing list must be filtered by ``Series ID``. The only
  endpoint that does that is the EDGAR browse CGI in ``output=atom`` mode.
* ``repPdEnd`` is the fund's **fiscal year end**, not the report period.
  IVV's amendment ``0002071691-26-015790`` carries ``repPdEnd`` 2026-03-31 with
  ``repPdDate`` 2025-09-30, and EDGAR's own "Period of Report" for it reads
  2025-09-30. ``repPdDate`` is therefore the as-of date; reading ``repPdEnd``
  would have stamped September holdings with a March date.
* The newest *filed* document is not the newest *period*: that same amendment
  was filed 2026-07-13, two months after the 2026-03-31 report. Filings are
  therefore ranked by their indexed period, not by filing date.
* Disclosure lags: IVV's period ending 2026-03-31 was filed 2026-05-28.

China A-share — Eastmoney fund archives
---------------------------------------
``fundf10.eastmoney.com/FundArchivesDatas.aspx?type=jjcc`` returns the
stock-holding detail as a JS ``var apidata={content:"<html>",...}`` envelope.
Traps, all confirmed against the live endpoint:

* the request 404s without a ``Referer`` on ``fundf10.eastmoney.com``;
* an out-of-range ``year`` is **silently ignored** and the current year is
  returned instead, so the report period is always read back out of the payload
  and never echoed from the request;
* ``topline`` does nothing on its own. The parameter that unlocks the whole book
  is ``month``: the page's own "显示全部持仓明细" control calls
  ``LoadMore(this, <month>, LoadStockPos)``, which appends that month to
  ``params.month``. ``month=6,12`` expands the June and December periods,
  ``month=3,6,9,12`` expands all four.

Chinese funds disclose the **complete** portfolio in the interim (半年度/中期,
period end 06-30) and annual (年度, period end 12-31) reports, and only the top
holdings in the quarterly ones. Measured on the expanded June/December periods:
510300 → 342 holdings summing 98.66% of net assets, 510500 → 541 / 95.35%,
159915 → 118 / 99.96%. That is the full book, not a top-N slice.

Two things make the "is this the whole book?" question harder than reading the
month off the period end, and both are handled rather than assumed:

* **Row provenance.** Eastmoney merges a second source into the table and says
  so in its own footnote: "注：加*号代表进入上市公司的十大流通股东却没有进入单只
  基金前十大重仓股的个股" — a starred ``序号`` means the row came from the
  *issuer's* top-10 float-holder disclosure, not from the fund's report. On an
  expanded quarterly period 510050 returns 10 fund-reported rows plus 33 starred
  ones. Those rows are real disclosure, but they are a different filing with
  different coverage, so every holding carries ``disclosure_source`` and the
  disclosed-percentage total counts fund-reported rows only.
* **Publication lag.** A period ending 06-30 is served long before its interim
  report exists — until then Eastmoney answers it with the quarterly data. On
  2026-08-04 the expanded 2026-06-30 period for 510300 is 15 rows / 23.26%
  (top-10 index investment + top-5 active), because the interim report is not
  due until 08-31. ``api.fund.eastmoney.com/f10/JJGG?type=3`` lists the fund's
  periodic reports by title ("…2025年年度报告", "…2025年中期报告"), which
  settles authoritatively whether the full portfolio has been published and when.
  That endpoint also needs a ``Referer``; without one it answers ``ErrCode -999``
  with ``Data`` as an empty **string** rather than a list.

Coverage is therefore decided from evidence, never from the calendar alone, and
is deliberately conservative — see :func:`_annotate_cn_period`. Two candidate
signals were tested and rejected: the ``t2`` table class tracks the requested
year rather than detail availability, and a disclosed-percentage threshold
cannot work because a concentrated fund's top-10 alone reaches 91.5% (513050).

Everything routes through :mod:`backtest.loaders._http` so the SEC and Eastmoney
per-host throttles, sessions and User-Agent policy are the project's existing
ones, not a second stack. No optional package is required.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re
import threading
from datetime import date, datetime, timezone
from typing import Any

from defusedxml import ElementTree as DefusedET

from backtest.loaders import sec_edgar_client
from backtest.loaders._http import resolve_min_interval, throttled_get
from backtest.loaders.eastmoney_client import get_json, resolve_secid
from src.agent.tools import BaseTool
from src.tools._result_paging import fit_records

logger = logging.getLogger(__name__)

# ── SEC endpoints ────────────────────────────────────────────────────────────

# Ticker -> (CIK, Series ID, Series Name) for every registered fund share class.
# Published per calendar year; the current year is tried first and the previous
# year is the fallback for the window early in January before it is posted.
_SEC_SERIES_INDEX_URL = (
    "https://www.sec.gov/files/investment/data/other/"
    "investment-company-series-class-information/"
    "investment-company-series-class-{year}.csv"
)
# The only EDGAR index that can be filtered to a single fund series.
_SEC_BROWSE_URL = "https://www.sec.gov/cgi-bin/browse-edgar"
_SEC_ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar/data"
# Full-text search: the one endpoint that reports each accession's period of
# report in bulk, so the newest *period* can be picked without downloading a
# half-megabyte filing per candidate.
_SEC_FTS_URL = "https://efts.sec.gov/LATEST/search-index"

_NPORT_HOST_KEY = "sec"

# ── Eastmoney endpoints ──────────────────────────────────────────────────────

_EM_HOLDINGS_URL = "https://fundf10.eastmoney.com/FundArchivesDatas.aspx"
# Periodic-report announcement shelf (``type``/``NEWCATEGORY`` 3 = 定期报告).
# The one authority on whether a period's full portfolio has been published.
_EM_ANNOUNCEMENT_URL = "https://api.fund.eastmoney.com/f10/JJGG"
_EM_PERIODIC_REPORT_TYPE = "3"
# A fund files four periodic reports a year; 80 covers two decades.
_EM_ANNOUNCEMENT_PAGE_SIZE = 80
# Quote hosts in preference order. ``push2delay`` is tried first because the
# other edges intermittently drop a Python HTTP client before responding
# (measured 0/4 on ``push2`` and ``push2his`` against 4/4 on ``push2delay``,
# while curl reached all three) — the delayed edge is also the one AKShare
# itself uses for the fund list, and delayed quotes are irrelevant here since
# only the fund's name and size are read.
_EM_QUOTE_HOSTS = ("push2delay.eastmoney.com", "push2.eastmoney.com")
_EM_QUOTE_PATH = "/api/qt/stock/get"
_EM_LIST_PATH = "/api/qt/clist/get"
_EM_HOST_KEY = "eastmoney"
_EM_MIN_INTERVAL_ENV = "VIBE_TRADING_EASTMONEY_MIN_INTERVAL"
_EM_DEFAULT_MIN_INTERVAL = 1.0

# Eastmoney board filters for exchange-traded funds, and the per-page cap the
# server enforces (``pz`` above 100 is silently clamped to 100).
_EM_ETF_BOARDS = "b:MK0021,b:MK0022,b:MK0023,b:MK0024,b:MK0827"
_EM_PAGE_SIZE = 100
_EM_MAX_PAGES = 30

# Exchange-listed fund code prefixes, mirroring
# ``backtest.loaders._symbol_utils._ETF_PREFIXES`` but resolved to the exchange
# so a bare six-digit code can be addressed without a suffix.
_CN_PREFIX_EXCHANGE = {
    "15": "SZ", "16": "SZ",
    "50": "SH", "51": "SH", "52": "SH", "56": "SH", "58": "SH",
}

# ── Result shaping ───────────────────────────────────────────────────────────

# The ceiling has to clear a real full portfolio, or ``disclosure='full'`` hands
# back a truncated book while still calling itself complete. Measured on the
# 2025 annual reports: 510500 → 541, 512100 → 1041, 159845 → 1044, and the
# CSI-2000 tracker 159531 → 2031. A broad-market fund is therefore well past a
# thousand names, so the cap is set high enough that no measured A-share
# portfolio reaches it; ``fit_records`` still pages the answer down to one
# result's worth, so a large cap costs nothing per response.
_MAX_TOP_N = 6000
_DEFAULT_TOP_N = 25
_MAX_LOOKUP = 40
_DEFAULT_LOOKUP = 10
# NPORT-P filings are quarterly; ten entries is ~2.5 years of report periods.
_SEC_FILING_COUNT = 10

_MODES = ("lookup", "holdings")
_MARKETS = ("auto", "US", "CN")
_DISCLOSURES = ("latest", "full", "cross_reference")

# ``month`` presets for the A-share archive. The default expands only the two
# periods whose reports carry the complete portfolio; the wide one additionally
# expands the quarterlies, which is where the issuer cross-referenced rows live.
_EM_FULL_DISCLOSURE_MONTHS = "6,12"
_EM_ALL_QUARTER_MONTHS = "3,6,9,12"

# Period ends whose report — when published — discloses the complete portfolio.
_FULL_DISCLOSURE_PERIOD_ENDS = ("-06-30", "-12-31")

# A quarterly report discloses the top ten holdings, plus for an index fund the
# top five active-investment holdings. More fund-reported rows than that on a
# June/December period can only have come from the interim or annual report.
_QUARTERLY_DISCLOSURE_CAP = 15

# How many extra years to fetch when hunting backwards for a full portfolio.
_MAX_FULL_LOOKBACK_FETCHES = 3

# Row provenance, per Eastmoney's own footnote on the starred 序号.
_SOURCE_FUND_REPORT = "fund_report"
_SOURCE_ISSUER_CROSS_REF = "issuer_top10_float_holders"

_COVERAGE_FULL = "full_portfolio"
_COVERAGE_TOP_N = "top_n_disclosed"

# CJK unified ideographs — a lookup query containing one is a Chinese fund name.
_HAN_RE = re.compile(r"[一-鿿]")

# Neither source publishes an expense ratio, so it is declared missing rather
# than estimated. Fund size is only available on the paths noted below.
_NOTE_LAG = (
    "ETF holdings are disclosed with a lag. 'as_of' is the report period the "
    "holdings belong to, NOT today's portfolio."
)


def _error(message: str) -> str:
    """Build the failure envelope as a JSON string.

    Args:
        message: Human-readable error description.

    Returns:
        A ``{"ok": false, "error": ...}`` JSON string.
    """
    return json.dumps({"ok": False, "error": message}, ensure_ascii=False)


# ── Symbol / market classification ───────────────────────────────────────────


def _classify_market(symbol: str) -> str:
    """Route a symbol to the A-share or the US path.

    The repository's shared classifier
    (``backtest.engines._market_hooks._detect_market``) is deliberately not used
    here: it defaults an unrecognized symbol to ``a_share``, which would send a
    bare ``IVV`` down the Eastmoney path. This tool needs the opposite default.

    Args:
        symbol: An ETF symbol such as ``"510050.SH"``, ``"510050"`` or ``"IVV"``.

    Returns:
        ``"CN"`` for a ``.SH`` / ``.SZ`` suffix or a bare six-digit code,
        ``"US"`` otherwise.
    """
    upper = symbol.strip().upper()
    if upper.endswith((".SH", ".SZ")):
        return "CN"
    if len(upper) == 6 and upper.isdigit():
        return "CN"
    return "US"


def _classify_query_market(query: str) -> str:
    """Route a free-text lookup query to the A-share or the US path.

    Adds one rule to :func:`_classify_market`: a query containing Han
    characters is an A-share fund search, since the SEC index holds no Chinese
    fund names and would silently answer "no matches".

    Args:
        query: A ticker, fund name, or theme keyword.

    Returns:
        ``"CN"`` or ``"US"``.
    """
    if _HAN_RE.search(query):
        return "CN"
    return _classify_market(query)


def _cn_code_and_secid(symbol: str) -> tuple[str, str | None]:
    """Split an A-share fund symbol into its bare code and Eastmoney secid.

    A bare six-digit code carries no exchange, so the exchange is derived from
    the listed-fund prefix table before delegating to the shared Eastmoney
    resolver.

    Args:
        symbol: ``"510050.SH"``, ``"510050"`` or ``"159915.sz"``.

    Returns:
        ``(bare_code, secid)``; ``secid`` is ``None`` when the exchange cannot
        be determined.
    """
    upper = symbol.strip().upper()
    if upper.endswith((".SH", ".SZ")):
        return upper.split(".")[0], resolve_secid(upper)
    exchange = _CN_PREFIX_EXCHANGE.get(upper[:2])
    if exchange is None:
        return upper, None
    return upper, resolve_secid(f"{upper}.{exchange}")


# ── HTTP transport (reuses the shared per-host throttles) ────────────────────


def _sec_get_text(url: str, params: dict[str, Any] | None = None) -> str:
    """GET an SEC URL as text through the shared ``"sec"`` throttle bucket.

    The frozen SEC client only decodes JSON, while both endpoints this tool
    needs return XML/CSV, so the transport is reused rather than reimplemented:
    same bucket, same interval floor, same contact User-Agent (env-overridable
    via ``VIBE_TRADING_SEC_UA``).

    Args:
        url: Fully-qualified ``sec.gov`` URL.
        params: Optional query parameters.

    Returns:
        The decoded response body.

    Raises:
        requests.RequestException: Network failure or non-2xx status.
    """
    response = throttled_get(
        url,
        host_key=_NPORT_HOST_KEY,
        min_interval=sec_edgar_client._min_interval(),
        params=params,
        headers={"User-Agent": sec_edgar_client._user_agent()},
        timeout=60.0,
    )
    response.raise_for_status()
    return response.text


def _em_get_text(url: str, *, params: dict[str, Any], referer: str) -> str:
    """GET an Eastmoney URL as text through the shared ``"eastmoney"`` throttle.

    Args:
        url: Fully-qualified Eastmoney URL.
        params: Query parameters.
        referer: Referer header — ``fundf10`` returns 404 without one.

    Returns:
        The decoded response body.

    Raises:
        requests.RequestException: Network failure or non-2xx status.
    """
    response = throttled_get(
        url,
        host_key=_EM_HOST_KEY,
        min_interval=resolve_min_interval(_EM_MIN_INTERVAL_ENV, _EM_DEFAULT_MIN_INTERVAL),
        params=params,
        headers={"Referer": referer},
    )
    response.raise_for_status()
    response.encoding = "utf-8"
    return response.text


# ── US: series/class ticker index ────────────────────────────────────────────

_US_INDEX_CACHE: tuple[int, list[dict[str, Any]]] | None = None
_US_INDEX_LOCK = threading.Lock()


def _parse_series_index(body: str) -> list[dict[str, Any]]:
    """Parse the SEC series/class CSV into ticker-bearing fund records.

    The header carries a UTF-8 BOM and the columns are ``Reporting File
    Number``, ``CIK Number``, ``Entity Name``, ``Entity Org Type``, ``Series
    ID``, ``Series Name``, ``Class ID``, ``Class Name``, ``Class Ticker`` and
    address fields. Rows without a ticker are share classes that cannot be
    searched by symbol and are dropped.

    A row carrying more fields than the header lands under ``DictReader``'s
    rest-key as a *list*, so values are type-checked rather than assumed to be
    strings — one malformed row would otherwise take the whole US path down.

    Args:
        body: Decoded CSV text.

    Returns:
        A list of ``{ticker, cik, series_id, series_name, class_id, class_name,
        entity_name, file_number}`` dicts.
    """
    rows: list[dict[str, Any]] = []
    for raw in csv.DictReader(io.StringIO(body)):
        record = {
            (k or "").lstrip("﻿").strip(): (v.strip() if isinstance(v, str) else "")
            for k, v in raw.items()
        }
        ticker = record.get("Class Ticker", "")
        series_id = record.get("Series ID", "")
        if not ticker or not series_id:
            continue
        rows.append(
            {
                "ticker": ticker.upper(),
                "cik": record.get("CIK Number") or None,
                "series_id": series_id,
                "series_name": record.get("Series Name") or None,
                "class_id": record.get("Class ID") or None,
                # Vanguard's ETF share classes sit inside a mutual fund whose
                # series name says "Fund" (VOO -> "Vanguard 500 Index Fund"),
                # so the class name is the only ETF signal on those rows.
                "class_name": record.get("Class Name") or None,
                "entity_name": record.get("Entity Name") or None,
                "file_number": record.get("Reporting File Number") or None,
            }
        )
    return rows


def _us_series_index() -> tuple[int, list[dict[str, Any]]]:
    """Return ``(index_year, records)`` for the SEC series/class index, memoized.

    Returns:
        The calendar year of the file actually used and its parsed records.

    Raises:
        RuntimeError: When neither the current nor the previous year's file can
            be fetched.
    """
    global _US_INDEX_CACHE
    if _US_INDEX_CACHE is not None:
        return _US_INDEX_CACHE
    with _US_INDEX_LOCK:
        if _US_INDEX_CACHE is None:
            this_year = date.today().year
            failures: list[str] = []
            for year in (this_year, this_year - 1):
                try:
                    body = _sec_get_text(_SEC_SERIES_INDEX_URL.format(year=year))
                except Exception as exc:  # noqa: BLE001 - try the older vintage
                    failures.append(f"{year}: {exc}")
                    continue
                records = _parse_series_index(body)
                if records:
                    _US_INDEX_CACHE = (year, records)
                    break
                failures.append(f"{year}: index parsed to zero rows")
            else:
                raise RuntimeError(
                    "SEC investment-company series/class index unavailable ("
                    + "; ".join(failures)
                    + ")"
                )
    return _US_INDEX_CACHE


def _is_etf_class(record: dict[str, Any]) -> bool:
    """Report whether an index row looks like an exchange-traded share class.

    The SEC series/class file has no ETF flag, so the only available signal is
    the wording: an ETF is named one either in its series name (``iShares
    Semiconductor ETF``) or in its class name (VOO is ``ETF Shares`` of the
    ``Vanguard 500 Index Fund``). This is a ranking heuristic only — nothing is
    dropped on the strength of it, and the underlying names are returned so the
    caller can judge for itself.

    Args:
        record: One parsed index row.

    Returns:
        ``True`` when either name carries the word "ETF".
    """
    return "ETF" in f"{record.get('series_name') or ''} {record.get('class_name') or ''}".upper()


def _us_match(query: str, limit: int) -> list[dict[str, Any]]:
    """Find fund share classes by exact ticker, then by name substring.

    A theme query such as "semiconductor" matches far more mutual fund share
    classes than ETFs, and the index is in filer order, so an unranked answer
    fills the whole first page with non-ETF classes and hides SOXX/SMH/XSD
    behind it. Name matches are therefore ordered ETFs-first, index order kept
    within each group. Exact ticker hits still outrank everything.

    Args:
        query: A ticker, a fund name, or a theme keyword.
        limit: Maximum matches to return.

    Returns:
        Matching index records, exact ticker hits first and ETF share classes
        ahead of other classes.
    """
    _, records = _us_series_index()
    needle = query.strip().upper()
    exact = [r for r in records if r["ticker"] == needle]
    if len(exact) >= limit:
        return exact[:limit]
    seen = {id(r) for r in exact}
    partial = [
        r
        for r in records
        if id(r) not in seen
        and (
            needle in (r["series_name"] or "").upper()
            or needle in (r["entity_name"] or "").upper()
            or (len(needle) >= 2 and r["ticker"].startswith(needle))
        )
    ]
    partial.sort(key=lambda r: not _is_etf_class(r))
    return (exact + partial)[:limit]


# ── US: N-PORT filing index + holdings ───────────────────────────────────────


def _local_name(tag: str) -> str:
    """Strip the XML namespace from a tag, returning its local name."""
    return tag.rpartition("}")[2]


def _us_nport_filings(series_id: str) -> list[dict[str, Any]]:
    """List a fund series' NPORT-P filings, newest first.

    Args:
        series_id: SEC series identifier, e.g. ``"S000004310"``.

    Returns:
        A list of ``{form, accession, filing_date}`` dicts. Empty when the
        series has filed none.

    Raises:
        requests.RequestException: Network failure or non-2xx status.
    """
    body = _sec_get_text(
        _SEC_BROWSE_URL,
        params={
            "action": "getcompany",
            "CIK": series_id,
            "type": "NPORT-P",
            "dateb": "",
            "owner": "include",
            "count": str(_SEC_FILING_COUNT),
            "output": "atom",
        },
    )
    try:
        root = DefusedET.fromstring(body.encode("utf-8", "replace"))
    except Exception as exc:  # noqa: BLE001 - a malformed feed is a data error
        raise RuntimeError(f"EDGAR filing feed did not parse: {exc}") from exc

    filings: list[dict[str, Any]] = []
    for element in root.iter():
        if _local_name(element.tag) != "content":
            continue
        fields = {_local_name(c.tag): (c.text or "").strip() for c in element}
        accession = fields.get("accession-number")
        if not accession:
            continue
        filings.append(
            {
                "form": fields.get("filing-type") or None,
                "accession": accession,
                "filing_date": fields.get("filing-date") or None,
            }
        )
    return filings


def _us_indexed_periods(series_id: str) -> dict[str, str]:
    """Map accession -> period of report for a series, from EDGAR full-text search.

    The atom filing index carries no period, and the newest-filed NPORT-P is
    routinely an amendment of an older period, so the periods are read from the
    full-text index in one request instead of by downloading each candidate
    filing. This is a best-effort enrichment: a failure returns an empty map and
    the caller falls back to filing order.

    Args:
        series_id: SEC series identifier, e.g. ``"S000004310"``.

    Returns:
        Mapping of accession number to ``YYYY-MM-DD`` period of report.
    """
    try:
        body = _sec_get_text(_SEC_FTS_URL, params={"q": f'"{series_id}"', "forms": "NPORT-P"})
        payload = json.loads(body)
    except Exception as exc:  # noqa: BLE001 - enrichment only, never fatal
        logger.warning("EDGAR full-text period lookup failed for %s: %s", series_id, exc)
        return {}

    hits = ((payload.get("hits") or {}).get("hits") or []) if isinstance(payload, dict) else []
    periods: dict[str, str] = {}
    for hit in hits:
        if not isinstance(hit, dict):
            continue
        accession = str(hit.get("_id") or "").split(":", 1)[0]
        period = (hit.get("_source") or {}).get("period_ending")
        if accession and period:
            periods[accession] = str(period)
    return periods


def _select_nport_filing(filings: list[dict[str, Any]], periods: dict[str, str]) -> dict[str, Any]:
    """Pick the filing covering the newest report period, newest vintage first.

    Args:
        filings: Atom-derived filings for one series, newest filed first.
        periods: Accession -> period of report, possibly empty or partial.

    Returns:
        The chosen filing dict, annotated with ``indexed_period``,
        ``period_source`` ("edgar_full_text_index" when a period was known,
        "filing_order" when the newest-filed had to be assumed) and
        ``candidates_without_period``, the number of listed filings the index
        could not date.
    """
    dated = [f for f in filings if periods.get(f["accession"])]
    undated = len(filings) - len(dated)
    if not dated:
        chosen = dict(filings[0])
        chosen["indexed_period"] = None
        chosen["period_source"] = "filing_order"
        chosen["candidates_without_period"] = undated
        return chosen
    # Newest period wins; among filings for the same period the latest vintage
    # wins, so an amendment supersedes the original it corrects.
    chosen = dict(
        max(dated, key=lambda f: (periods[f["accession"]], f["filing_date"] or ""))
    )
    chosen["indexed_period"] = periods[chosen["accession"]]
    chosen["period_source"] = "edgar_full_text_index"
    # The full-text index lags EDGAR's own filing feed, so a just-filed report
    # can be listed with no period yet. Such filings are skipped by the ranking
    # above, which would otherwise quietly answer with the previous quarter —
    # the count is surfaced so a stale answer is visibly stale.
    chosen["candidates_without_period"] = undated
    return chosen


def _nport_document_url(cik: str, accession: str) -> str:
    """Build the ``primary_doc.xml`` URL for one N-PORT accession.

    Args:
        cik: The registrant CIK, padded or not; leading zeros are dropped.
        accession: Accession number such as ``"0002071691-26-012459"``.

    Returns:
        The fully-qualified EDGAR archive URL.
    """
    return (
        f"{_SEC_ARCHIVES_BASE}/{str(cik).lstrip('0') or '0'}/"
        f"{accession.replace('-', '')}/primary_doc.xml"
    )


def _text_of(parent: Any, name: str) -> str | None:
    """Return the stripped text of ``parent``'s first child named ``name``."""
    if parent is None:
        return None
    for child in parent:
        if _local_name(child.tag) == name:
            text = (child.text or "").strip()
            return text or None
    return None


def _child(parent: Any, name: str) -> Any:
    """Return ``parent``'s first child element named ``name``, or ``None``."""
    if parent is None:
        return None
    for element in parent:
        if _local_name(element.tag) == name:
            return element
    return None


def _iso_date(value: Any) -> str | None:
    """Normalize an Eastmoney ``YYYYMMDD`` field to ``YYYY-MM-DD``.

    Args:
        value: The raw field, e.g. ``20260804`` or ``"20260804"``.

    Returns:
        The ISO date, the original string when it is not eight digits, or
        ``None`` when empty.
    """
    text = str(value).strip() if value not in (None, "") else ""
    if not text:
        return None
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return text


def _to_float(value: Any) -> float | None:
    """Coerce a reported value to ``float``, or ``None`` when non-numeric."""
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _parse_nport_holding(node: Any) -> dict[str, Any]:
    """Shape one ``invstOrSec`` element into a holding record.

    Absent fields are omitted rather than defaulted, so a missing identifier is
    visibly missing instead of silently zero or blank.

    Args:
        node: An ``invstOrSec`` element.

    Returns:
        A holding dict keyed by ``name`` / ``pct_of_net_assets`` / ``value_usd``
        and whatever identifiers the filer supplied.
    """
    identifiers = _child(node, "identifiers")
    isin = ticker = None
    if identifiers is not None:
        for element in identifiers:
            local = _local_name(element.tag)
            if local == "isin":
                isin = (element.get("value") or "").strip() or None
            elif local == "ticker":
                ticker = (element.get("value") or "").strip() or None

    holding: dict[str, Any] = {
        "name": _text_of(node, "name"),
        "title": _text_of(node, "title"),
        "cusip": _text_of(node, "cusip"),
        "isin": isin,
        "ticker": ticker,
        # pctVal is already expressed in percent: IVV's Merck line reports
        # 0.5329 against valUSD 3.84e9 / netAssets 7.21e11.
        "pct_of_net_assets": _to_float(_text_of(node, "pctVal")),
        "value_usd": _to_float(_text_of(node, "valUSD")),
        "balance": _to_float(_text_of(node, "balance")),
        "balance_units": _text_of(node, "units"),
        "currency": _text_of(node, "curCd"),
        "payoff_profile": _text_of(node, "payoffProfile"),
        "asset_category": _text_of(node, "assetCat"),
        "issuer_category": _text_of(node, "issuerCat"),
        "country": _text_of(node, "invCountry"),
    }
    return {k: v for k, v in holding.items() if v is not None}


def _parse_nport(xml_text: str) -> dict[str, Any]:
    """Parse an N-PORT ``primary_doc.xml`` into fund metadata plus holdings.

    Args:
        xml_text: The raw filing document.

    Returns:
        ``{series_id, series_name, registrant, as_of, fiscal_year_end,
        total_assets_usd, net_assets_usd, holdings}``.

    Raises:
        RuntimeError: When the document is not parseable XML.
    """
    try:
        root = DefusedET.fromstring(xml_text.encode("utf-8", "replace"))
    except Exception as exc:  # noqa: BLE001 - a malformed filing is a data error
        raise RuntimeError(f"N-PORT document did not parse: {exc}") from exc

    form_data = _child(root, "formData")
    gen_info = _child(form_data, "genInfo")
    fund_info = _child(form_data, "fundInfo")
    securities = _child(form_data, "invstOrSecs")

    holdings = []
    if securities is not None:
        holdings = [
            _parse_nport_holding(node)
            for node in securities
            if _local_name(node.tag) == "invstOrSec"
        ]

    return {
        "series_id": _text_of(gen_info, "seriesId"),
        "series_name": _text_of(gen_info, "seriesName"),
        "registrant": _text_of(gen_info, "regName"),
        # repPdDate is the date the holdings are reported as of; repPdEnd is the
        # fund's fiscal year end. They diverge (IVV: repPdEnd 2026-03-31 with
        # repPdDate 2025-09-30 on the amendment), and EDGAR's own "Period of
        # Report" tracks repPdDate, so that is the as-of.
        "as_of": _text_of(gen_info, "repPdDate"),
        "fiscal_year_end": _text_of(gen_info, "repPdEnd"),
        "total_assets_usd": _to_float(_text_of(fund_info, "totAssets")),
        "net_assets_usd": _to_float(_text_of(fund_info, "netAssets")),
        "holdings": holdings,
    }


def _lag_days(as_of: str | None, filing_date: str | None) -> int | None:
    """Return the whole days between a report period end and its filing date."""
    if not as_of or not filing_date:
        return None
    try:
        return (
            datetime.strptime(filing_date, "%Y-%m-%d").date()
            - datetime.strptime(as_of, "%Y-%m-%d").date()
        ).days
    except ValueError:
        return None


# ── A-share: Eastmoney fund archives ─────────────────────────────────────────

# ``var apidata={ content:"<html>",arryear:[2026,...],curyear:2026};``
_APIDATA_RE = re.compile(r'content:"(?P<content>.*?)",\s*arryear:\[(?P<years>[^\]]*)\]', re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_ROW_RE = re.compile(r"<tr>(?P<row>.*?)</tr>", re.S)
# A cell ends at its closing tag, at the next cell's opening tag, or at the end
# of the row. The last two alternatives are not defensiveness for its own sake:
# Eastmoney emits rows whose 相关资讯 cell is never closed — 510500's 2025 annual
# report carries ``<td class='xglj'>…<td class='tor'>0.00%</td>`` for the NEEQ
# line 400174 中天3 — and requiring ``</td>`` merges that cell with the next one,
# shifting every later column left by one. That silently reported the holding's
# share count (1,877.51) as its weight in percent.
_CELL_RE = re.compile(r"<t[dh][^>]*>(?P<cell>.*?)(?=</t[dh]>|<t[dh][^>]*>|\Z)", re.S)
# Quote links carry the Eastmoney market prefix: 1 = Shanghai, 0 = Shenzhen.
_QUOTE_LINK_RE = re.compile(r"quote\.eastmoney\.com/unify/r/(?P<market>\d)\.(?P<code>\d{6})")
_ASOF_RE = re.compile(r"截止至：\s*<font[^>]*>(?P<date>[\d-]+)</font>")
_FUND_NAME_RE = re.compile(r"title='(?P<name>[^']*)'")
_PERIOD_RE = re.compile(r"(?P<label>\d{4}年\d季度[^<]*)</label>")
_EM_MARKET_SUFFIX = {"1": "SH", "0": "SZ"}
# Present while a period is still collapsed to its top rows; its absence means
# this payload already carries everything Eastmoney holds for that period.
_EXPAND_LINK = "显示全部持仓明细"

# Periodic-report titles, e.g. "华泰柏瑞沪深300交易型开放式指数证券投资基金2025年
# 年度报告". The 摘要 (abstract) editions are excluded: they are a companion to
# the full report, and only the full report carries the portfolio schedule.
_ANNUAL_REPORT_RE = re.compile(r"(?P<year>\d{4})年年度报告(?!摘要)")
_INTERIM_REPORT_RE = re.compile(r"(?P<year>\d{4})年(?:中期|半年度)报告(?!摘要)")


def _strip_html(fragment: str) -> str:
    """Flatten an HTML fragment to its visible text."""
    return _TAG_RE.sub("", fragment).replace("&nbsp;", " ").replace("&amp;", "&").strip()


def _cn_column_map(header_row: str) -> dict[str, tuple[int, float]]:
    """Map logical holding columns to ``(index, unit_scale)`` from the table head.

    Eastmoney reports 持股数 in 万股 and 持仓市值 in 万元 (both ten-thousands),
    but the exact header wording varies between funds, so the scale is read from
    the header text rather than assumed.

    Args:
        header_row: The raw ``<tr>`` inner HTML of the table head.

    Returns:
        Mapping of ``"code"`` / ``"name"`` / ``"pct"`` / ``"shares"`` /
        ``"value"`` to ``(column_index, scale)``. Absent columns are omitted.
    """
    columns: dict[str, tuple[int, float]] = {}
    for index, match in enumerate(_CELL_RE.finditer(header_row)):
        text = _strip_html(match.group("cell"))
        scale = 10_000.0 if "万" in text else 1.0
        if "序号" in text:
            # Carries the provenance marker: a trailing '*' means the row came
            # from the issuer's float-holder disclosure, not the fund's report.
            columns["seq"] = (index, 1.0)
        elif "股票代码" in text:
            columns["code"] = (index, 1.0)
        elif "股票名称" in text:
            columns["name"] = (index, 1.0)
        elif "占净值" in text:
            columns["pct"] = (index, 1.0)
        elif "持股数" in text:
            columns["shares"] = (index, scale)
        elif "持仓市值" in text:
            columns["value"] = (index, scale)
    return columns


def _parse_cn_period(block: str) -> dict[str, Any] | None:
    """Parse one report period's holdings block from the Eastmoney fund archive.

    Every holding is stamped with the disclosure it came from, because the table
    merges two of them: unstarred rows are the fund's own periodic report, and a
    starred ``序号`` is Eastmoney cross-referencing the *issuer's* top-10 float
    holders. Mixing the two would inflate the apparent coverage of the fund's
    filing, so the totals are kept apart rather than summed.

    Args:
        block: One ``boxitem`` fragment, header table included.

    Returns:
        ``{as_of, report_label, fund_name, holdings, unparseable_rows,
        expandable, source_labelled, fund_report_holdings,
        cross_referenced_holdings, pct_of_net_assets_disclosed,
        pct_of_net_assets_cross_referenced}``, or ``None`` when the block
        carries no parseable table.
    """
    rows = _ROW_RE.findall(block)
    if len(rows) < 2:
        return None
    columns = _cn_column_map(rows[0])
    if "code" not in columns or "pct" not in columns:
        return None

    width = len(_CELL_RE.findall(rows[0]))
    holdings: list[dict[str, Any]] = []
    malformed = 0
    for row in rows[1:]:
        cells = [m.group("cell") for m in _CELL_RE.finditer(row)]
        # Column indices come from the header, so a row of a different width has
        # them pointing at the wrong values. Dropping it loses one holding;
        # keeping it reports one column's number under another column's name.
        # The count is returned so the loss is never silent.
        if len(cells) != width:
            malformed += 1
            continue

        def cell(key: str) -> tuple[str, float] | None:
            spec = columns.get(key)
            if spec is None or spec[0] >= len(cells):
                return None
            return _strip_html(cells[spec[0]]), spec[1]

        code_cell = cell("code")
        if code_cell is None or not code_cell[0]:
            continue
        link = _QUOTE_LINK_RE.search(row)
        suffix = _EM_MARKET_SUFFIX.get(link.group("market")) if link else None
        code = code_cell[0]

        seq_cell = cell("seq")
        cross_referenced = bool(seq_cell and "*" in seq_cell[0])
        holding: dict[str, Any] = {
            "symbol": f"{code}.{suffix}" if suffix else code,
            "disclosure_source": (
                _SOURCE_ISSUER_CROSS_REF if cross_referenced else _SOURCE_FUND_REPORT
            ),
        }
        name_cell = cell("name")
        if name_cell and name_cell[0]:
            holding["name"] = name_cell[0]
        pct_cell = cell("pct")
        if pct_cell:
            holding["pct_of_net_assets"] = _to_float(pct_cell[0].rstrip("%"))
        shares_cell = cell("shares")
        shares = _to_float(shares_cell[0]) if shares_cell else None
        if shares is not None:
            # Rounded because the ten-thousands rescale otherwise leaks binary
            # float noise into a share count (6816530699.999999 CNY).
            holding["shares"] = round(shares * shares_cell[1], 2)
        value_cell = cell("value")
        value = _to_float(value_cell[0]) if value_cell else None
        if value is not None:
            holding["market_value_cny"] = round(value * value_cell[1], 2)
        holdings.append({k: v for k, v in holding.items() if v is not None})

    if not holdings:
        return None
    as_of = _ASOF_RE.search(block)
    label = _PERIOD_RE.search(block)
    name = _FUND_NAME_RE.search(block)
    fund_rows = [h for h in holdings if h["disclosure_source"] == _SOURCE_FUND_REPORT]
    return {
        "as_of": as_of.group("date") if as_of else None,
        "report_label": label.group("label").strip() if label else None,
        "fund_name": name.group("name") if name else None,
        "holdings": holdings,
        "unparseable_rows": malformed,
        # Still collapsed: Eastmoney holds more rows for this period than this
        # payload carries, so nothing here may be called a complete portfolio.
        "expandable": _EXPAND_LINK in block,
        # Without the 序号 column there is no way to tell the two disclosures
        # apart, so the period is barred from claiming full coverage.
        "source_labelled": "seq" in columns,
        "fund_report_holdings": len(fund_rows),
        "cross_referenced_holdings": len(holdings) - len(fund_rows),
        "pct_of_net_assets_disclosed": round(
            sum(h.get("pct_of_net_assets") or 0.0 for h in fund_rows), 4
        ),
        "pct_of_net_assets_cross_referenced": round(
            sum(
                h.get("pct_of_net_assets") or 0.0
                for h in holdings
                if h["disclosure_source"] == _SOURCE_ISSUER_CROSS_REF
            ),
            4,
        ),
    }


def _cn_holdings_periods(code: str, year: int | None, months: str) -> list[dict[str, Any]]:
    """Fetch a fund's disclosed stock holdings by period, newest period first.

    The endpoint silently ignores an out-of-range ``year`` and answers with the
    current one instead, so the caller must read ``as_of`` off each returned
    period rather than assuming the year it asked for.

    Args:
        code: Bare six-digit fund code, e.g. ``"510050"``.
        year: Calendar year to request, or ``None`` for the endpoint default.
        months: Report months to expand past their top rows, as the page's own
            control sends them — ``"6,12"`` for the interim/annual periods,
            ``"3,6,9,12"`` for every quarter. An unexpanded period comes back
            collapsed to its top ten rows.

    Returns:
        Parsed period blocks in the order Eastmoney returns them (newest first).

    Raises:
        requests.RequestException: Network failure or non-2xx status.
    """
    body = _em_get_text(
        _EM_HOLDINGS_URL,
        params={
            "type": "jjcc",
            "code": code,
            "topline": str(_MAX_TOP_N),
            "year": str(year) if year else "",
            "month": months,
        },
        referer=f"https://fundf10.eastmoney.com/ccmx_{code}.html",
    )
    match = _APIDATA_RE.search(body)
    if match is None:
        return []
    content = match.group("content")
    blocks = content.split("<div class='boxitem")[1:]
    periods = [p for p in (_parse_cn_period(b) for b in blocks) if p is not None]
    return periods


def _cn_periodic_reports(code: str) -> dict[str, dict[str, str]]:
    """Map period end to the interim/annual report that discloses it in full.

    This is the only authority on whether a June or December period's complete
    portfolio is actually public yet: the archive serves such a period from the
    quarterly data until the interim/annual report lands, and looks no different
    when it does. Best-effort by design — a failure returns an empty map, and
    the caller then declines to claim full coverage rather than guessing.

    Args:
        code: Bare six-digit fund code.

    Returns:
        ``{"YYYY-06-30": {"report": title, "published": "YYYY-MM-DD"}}``. When a
        report was published more than once, the earliest date wins, since that
        is when the holdings became public.
    """
    try:
        body = _em_get_text(
            _EM_ANNOUNCEMENT_URL,
            params={
                "fundcode": code,
                "pageIndex": "1",
                "pageSize": str(_EM_ANNOUNCEMENT_PAGE_SIZE),
                "type": _EM_PERIODIC_REPORT_TYPE,
            },
            referer=f"https://fundf10.eastmoney.com/jjgg_{code}_3.html",
        )
        payload = json.loads(body)
    except Exception as exc:  # noqa: BLE001 - corroboration only, never fatal
        logger.warning("Eastmoney periodic-report index failed for %s: %s", code, exc)
        return {}

    # Without a Referer the endpoint answers 200 with ErrCode -999 and Data as
    # an empty *string*, so the shape is checked rather than assumed.
    records = payload.get("Data") if isinstance(payload, dict) else None
    if payload.get("ErrCode") != 0 or not isinstance(records, list):
        logger.warning("Eastmoney periodic-report index rejected the request for %s", code)
        return {}

    reports: dict[str, dict[str, str]] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        title = str(record.get("TITLE") or "")
        published = str(record.get("PUBLISHDATEDesc") or "").strip()
        if annual := _ANNUAL_REPORT_RE.search(title):
            period_end = f"{annual.group('year')}-12-31"
        elif interim := _INTERIM_REPORT_RE.search(title):
            period_end = f"{interim.group('year')}-06-30"
        else:
            continue
        known = reports.get(period_end)
        if known is None or (published and published < known["published"]):
            reports[period_end] = {"report": title, "published": published}
    return reports


def _annotate_cn_period(period: dict[str, Any], reports: dict[str, dict[str, str]]) -> None:
    """Decide in place what a parsed period's rows actually cover.

    ``full_portfolio`` is claimed only when every one of these holds, so the
    label errs towards understating coverage rather than overstating it:

    * the period end is a June or December one, the only reports that carry the
      complete portfolio;
    * the block was expanded, so no rows are being withheld;
    * row provenance was readable, so fund-reported rows are separable from the
      issuer cross-referenced ones;
    * more fund-reported rows came back than a quarterly report may disclose
      (:data:`_QUARTERLY_DISCLOSURE_CAP`), which is what distinguishes a
      published interim/annual report from the quarterly data still standing in
      for it — on 2026-08-04 the expanded 2026-06-30 period is 15 rows;
    * the announcement index does not contradict it. A fund whose complete book
      genuinely runs to fifteen names or fewer is therefore reported as
      ``top_n_disclosed``; the disclosed percentage is published alongside so
      that understatement is visible rather than misleading.

    Args:
        period: A parsed period block, mutated with its coverage verdict.
        reports: Output of :func:`_cn_periodic_reports`, possibly empty.
    """
    as_of = period["as_of"] or ""
    report = reports.get(as_of)
    # None = the announcement index was unreachable, so it neither confirms nor
    # denies; False = it was read and holds no such report for this period.
    confirmed = None if not reports else report is not None

    period["report"] = report["report"] if report else None
    period["report_published"] = report["published"] if report else None
    period["report_confirmed"] = confirmed
    period["disclosure_lag_days"] = _lag_days(
        as_of, report["published"] if report else None
    )
    period["coverage"] = (
        _COVERAGE_FULL
        if (
            as_of.endswith(_FULL_DISCLOSURE_PERIOD_ENDS)
            and not period["expandable"]
            and period["source_labelled"]
            and period["fund_report_holdings"] > _QUARTERLY_DISCLOSURE_CAP
            and confirmed is not False
        )
        else _COVERAGE_TOP_N
    )


def _em_push_json(path: str, params: dict[str, Any]) -> Any:
    """Call an Eastmoney quote endpoint, trying each edge host in turn.

    Args:
        path: Endpoint path such as ``"/api/qt/stock/get"``.
        params: Query parameters.

    Returns:
        The decoded JSON payload from the first host that answers.

    Raises:
        requests.RequestException: When every host fails; the last failure is
            re-raised so the caller reports a real cause.
    """
    last: Exception | None = None
    for host in _EM_QUOTE_HOSTS:
        try:
            return get_json(f"https://{host}{path}", params=params)
        except Exception as exc:  # noqa: BLE001 - fall through to the next edge
            logger.warning("eastmoney %s failed on %s: %s", path, host, exc)
            last = exc
    raise last if last is not None else RuntimeError("no Eastmoney quote host configured")


def _cn_quote(secid: str) -> dict[str, Any]:
    """Fetch one A-share fund's name and market size from the Eastmoney quote API.

    Args:
        secid: Eastmoney secid such as ``"1.510050"``.

    Returns:
        The ``data`` mapping (``f57`` code, ``f58`` name, ``f43`` last price,
        ``f116`` total market value, ``f117`` free-float market value), or an
        empty dict when the payload carries none.

    Raises:
        requests.RequestException: Network failure or non-2xx status.
    """
    payload = _em_push_json(
        _EM_QUOTE_PATH,
        {"secid": secid, "fltt": "2", "invt": "2", "fields": "f43,f57,f58,f86,f116,f117"},
    )
    data = payload.get("data") if isinstance(payload, dict) else None
    return data if isinstance(data, dict) else {}


_CN_LIST_CACHE: list[dict[str, Any]] | None = None
_CN_LIST_LOCK = threading.Lock()


def _cn_etf_list() -> tuple[list[dict[str, Any]], bool]:
    """Return every exchange-traded fund Eastmoney lists, memoized when complete.

    The quote server caps a page at 100 rows regardless of the requested ``pz``,
    so the ~1,500-row universe takes about sixteen throttled requests. A run
    that dies part-way is returned as-is with ``complete=False`` and is *not*
    cached, so a truncated universe can neither be mistaken for the whole one
    nor poison later calls.

    Returns:
        ``(rows, complete)`` where each row is ``{symbol, code, name,
        total_market_cap_cny, quote_date}``.

    Raises:
        requests.RequestException: Network failure on the very first page.
    """
    global _CN_LIST_CACHE
    if _CN_LIST_CACHE is not None:
        return _CN_LIST_CACHE, True
    with _CN_LIST_LOCK:
        if _CN_LIST_CACHE is not None:
            return _CN_LIST_CACHE, True
        rows: list[dict[str, Any]] = []
        expected: int | None = None
        for page in range(1, _EM_MAX_PAGES + 1):
            try:
                payload = _em_push_json(
                    _EM_LIST_PATH,
                    {
                        "pn": str(page),
                        "pz": str(_EM_PAGE_SIZE),
                        "po": "1",
                        "np": "1",
                        "fltt": "2",
                        "invt": "2",
                        "fid": "f12",
                        "fs": _EM_ETF_BOARDS,
                        "fields": "f12,f13,f14,f20,f21,f297",
                    },
                )
            except Exception:
                if page == 1:
                    raise
                logger.warning("eastmoney ETF universe truncated at page %d", page)
                return rows, False
            data = payload.get("data") if isinstance(payload, dict) else None
            page_rows = data.get("diff") if isinstance(data, dict) else None
            if not isinstance(page_rows, list) or not page_rows:
                break
            total = data.get("total") if isinstance(data, dict) else None
            if isinstance(total, int) and total > 0:
                expected = total
            for row in page_rows:
                if not isinstance(row, dict):
                    continue
                code = str(row.get("f12") or "").strip()
                if not code:
                    continue
                suffix = _EM_MARKET_SUFFIX.get(str(row.get("f13")))
                rows.append(
                    {
                        "symbol": f"{code}.{suffix}" if suffix else code,
                        "code": code,
                        "name": row.get("f14"),
                        "total_market_cap_cny": _to_float(row.get("f20")),
                        "quote_date": _iso_date(row.get("f297")),
                    }
                )
            if expected is not None and len(rows) >= expected:
                break
        complete = expected is None or len(rows) >= expected
        if complete:
            _CN_LIST_CACHE = rows
        return rows, complete


# ── Mode handlers ────────────────────────────────────────────────────────────


def _lookup_us(query: str, limit: int, offset: int) -> str:
    """Search US fund share classes by ticker or name and render the envelope."""
    try:
        index_year, _ = _us_series_index()
        matches = _us_match(query, limit)
    except Exception as exc:  # noqa: BLE001 - surface any fetch failure as envelope
        return _error(f"SEC series/class index lookup failed: {exc}")

    def build(page: list[Any], paging: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": True,
            "mode": "lookup",
            "market": "US",
            "source": "sec_investment_company_series_class_index",
            "as_of": {"index_year": index_year},
            "missing_fields": ["net_assets", "expense_ratio"],
            "notes": (
                "The SEC series/class index carries identity only. Call "
                "mode='holdings' for net assets and the portfolio; no free SEC "
                "endpoint publishes an expense ratio."
            ),
            "paging": paging,
            "data": {"query": query, "matches": page},
        }

    return fit_records(matches, offset, build)


def _lookup_cn(query: str, limit: int, offset: int) -> str:
    """Search A-share ETFs by code or name and render the envelope."""
    needle = query.strip()
    matches: list[dict[str, Any]] = []
    quote_as_of: Any = None
    universe_complete = True

    if _classify_market(needle) == "CN":
        code, secid = _cn_code_and_secid(needle)
        if secid is None:
            return _error(f"'{needle}' is not a recognizable A-share fund code")
        try:
            quote = _cn_quote(secid)
        except Exception as exc:  # noqa: BLE001 - surface as envelope
            return _error(f"Eastmoney quote request failed: {exc}")
        if quote:
            record = {
                "symbol": f"{code}.{_CN_PREFIX_EXCHANGE.get(code[:2], '')}".rstrip("."),
                "code": quote.get("f57") or code,
                "name": quote.get("f58"),
                "last_price": _to_float(quote.get("f43")),
                # Shares outstanding x last price, i.e. an exchange-side size
                # proxy — not the fund's officially struck NAV-based AUM.
                "fund_size_cny": _to_float(quote.get("f116")),
            }
            matches = [{k: v for k, v in record.items() if v is not None}]
            # f86 is the quote's epoch second; an ISO instant is what downstream
            # reasoning can actually compare against a report period.
            epoch = _to_float(quote.get("f86"))
            if epoch is not None:
                quote_as_of = datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()
    else:
        try:
            universe, universe_complete = _cn_etf_list()
        except Exception as exc:  # noqa: BLE001 - surface as envelope
            return _error(f"Eastmoney ETF universe request failed: {exc}")
        lowered = needle.lower()
        matches = [row for row in universe if lowered in str(row.get("name") or "").lower()][:limit]
        quote_as_of = next((m.get("quote_date") for m in matches), None)

    notes = (
        "fund_size_cny / total_market_cap_cny is shares outstanding x last "
        "traded price, an exchange-side size proxy rather than the fund's "
        "struck NAV. Eastmoney publishes no expense ratio on this endpoint."
    )
    if not universe_complete:
        notes += (
            " WARNING: the ETF universe fetch was cut short by an upstream "
            "failure, so these matches are drawn from a PARTIAL list and a "
            "matching fund may be missing. Retry before concluding none exists."
        )

    def build(page: list[Any], paging: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": True,
            "mode": "lookup",
            "market": "CN",
            "source": "eastmoney_quote",
            "as_of": quote_as_of,
            "universe_complete": universe_complete,
            "missing_fields": ["expense_ratio"],
            "notes": notes,
            "paging": paging,
            "data": {"query": needle, "matches": page},
        }

    return fit_records(matches, offset, build)


def _holdings_us(symbol: str, top_n: int, offset: int) -> str:
    """Fetch and render one US ETF's latest N-PORT portfolio."""
    try:
        matches = _us_match(symbol, 1)
    except Exception as exc:  # noqa: BLE001 - surface as envelope
        return _error(f"SEC series/class index lookup failed: {exc}")
    if not matches or matches[0]["ticker"] != symbol.strip().upper():
        return _error(
            f"'{symbol}' is not a fund share class in the SEC series/class index. "
            "Note that unit investment trusts (SPY among them) do not appear there "
            "and file no NPORT-P. Use mode='lookup' to find the right ticker."
        )
    fund = matches[0]

    try:
        filings = _us_nport_filings(fund["series_id"])
    except Exception as exc:  # noqa: BLE001 - surface as envelope
        return _error(f"EDGAR NPORT-P filing index request failed: {exc}")
    if not filings:
        return _error(f"no NPORT-P filing found for {fund['ticker']} ({fund['series_id']})")

    filing = _select_nport_filing(filings, _us_indexed_periods(fund["series_id"]))
    document_url = _nport_document_url(fund["cik"] or "0", filing["accession"])
    try:
        parsed = _parse_nport(_sec_get_text(document_url))
    except Exception as exc:  # noqa: BLE001 - surface as envelope
        return _error(f"N-PORT document request failed: {exc}")

    if parsed["series_id"] and parsed["series_id"] != fund["series_id"]:
        return _error(
            f"filing {filing['accession']} reports series {parsed['series_id']}, "
            f"expected {fund['series_id']} — refusing to attribute it to {fund['ticker']}"
        )

    holdings = parsed["holdings"]
    total_holdings = len(holdings)
    holdings = sorted(
        holdings, key=lambda h: h.get("pct_of_net_assets") or 0.0, reverse=True
    )[:top_n]
    # The document is primary; the full-text index is only how the filing was
    # chosen, so a disagreement is reported rather than reconciled silently.
    as_of = parsed["as_of"] or filing["indexed_period"]

    notes = _NOTE_LAG
    if filing["candidates_without_period"]:
        notes += (
            f" WARNING: {filing['candidates_without_period']} of the "
            f"{len(filings)} listed NPORT-P filings carry no period in EDGAR's "
            "full-text index and were skipped when picking the newest period. "
            "If one of them is a just-filed report the index has not caught up "
            "with, a newer portfolio than this one exists."
        )

    def build(page: list[Any], paging: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": True,
            "mode": "holdings",
            "market": "US",
            "source": "sec_nport",
            "as_of": as_of,
            "coverage": "full_portfolio",
            "notes": notes,
            "missing_fields": ["expense_ratio"],
            "paging": paging,
            "data": {
                "symbol": fund["ticker"],
                "fund": {
                    "series_name": parsed["series_name"] or fund["series_name"],
                    "registrant": parsed["registrant"] or fund["entity_name"],
                    "cik": fund["cik"],
                    "series_id": fund["series_id"],
                    "class_id": fund["class_id"],
                    "fiscal_year_end": parsed["fiscal_year_end"],
                    "total_assets_usd": parsed["total_assets_usd"],
                    "net_assets_usd": parsed["net_assets_usd"],
                },
                "filing": {
                    "form": filing["form"],
                    "accession": filing["accession"],
                    "filing_date": filing["filing_date"],
                    "disclosure_lag_days": _lag_days(as_of, filing["filing_date"]),
                    "period_source": filing["period_source"],
                    "indexed_period": filing["indexed_period"],
                    "candidates_without_period": filing["candidates_without_period"],
                    "document_url": document_url,
                },
                "holdings_in_filing": total_holdings,
                "holdings_returned_of_top_n": len(holdings),
                "holdings": page,
            },
        }

    return fit_records(holdings, offset, build)


def _cn_fetch_year(
    code: str, year: int | None, months: str, reports: dict[str, dict[str, str]]
) -> list[dict[str, Any]]:
    """Fetch one calendar year of report periods, each annotated with coverage."""
    periods = _cn_holdings_periods(code, year, months)
    for period in periods:
        _annotate_cn_period(period, reports)
    return periods


def _newest_full_period(reports: dict[str, dict[str, str]]) -> dict[str, str] | None:
    """Return the newest period the announcement index says is fully disclosed."""
    if not reports:
        return None
    as_of = max(reports)
    return {"as_of": as_of, **reports[as_of]}


def _holdings_cn(
    symbol: str, top_n: int, offset: int, year: int | None, disclosure: str
) -> str:
    """Fetch and render one A-share ETF's disclosed holdings for a report period."""
    code, _ = _cn_code_and_secid(symbol)
    if not (len(code) == 6 and code.isdigit()):
        return _error(f"'{symbol}' is not a six-digit A-share fund code")

    months = (
        _EM_ALL_QUARTER_MONTHS
        if disclosure == "cross_reference"
        else _EM_FULL_DISCLOSURE_MONTHS
    )
    reports = _cn_periodic_reports(code)
    try:
        periods = _cn_fetch_year(code, year, months, reports)
        # A June/December period is served from the quarterly data until its
        # report lands, so the newest full portfolio is routinely in an earlier
        # year. The announcement index says which year to ask for, so the walk
        # back is a targeted refetch rather than a blind sweep.
        if disclosure == "full" and year is None:
            fetched = {int(p["as_of"][:4]) for p in periods if p["as_of"]}
            # One request serves a whole year, and a year contributes both its
            # June and December report, so the years are de-duplicated — the
            # fetch budget must not be spent asking for the same one twice.
            candidates: list[int] = []
            for as_of in sorted(reports, reverse=True):
                year_of = int(as_of[:4])
                if year_of not in fetched and year_of not in candidates:
                    candidates.append(year_of)
            for candidate in candidates[:_MAX_FULL_LOOKBACK_FETCHES]:
                if any(p["coverage"] == _COVERAGE_FULL for p in periods):
                    break
                periods = _cn_fetch_year(code, candidate, months, reports)
    except Exception as exc:  # noqa: BLE001 - surface as envelope
        return _error(f"Eastmoney fund-holdings request failed: {exc}")
    if not periods:
        return _error(
            f"Eastmoney published no stock-holding detail for fund {code}. This "
            "endpoint covers equity holdings only, so a commodity fund (gold, "
            "e.g. 518880.SH) or a pure bond fund legitimately has none."
        )

    # Eastmoney returns the periods newest-first, but the report period is what
    # the answer is stamped with, so it is picked by date rather than by
    # trusting the server's ordering.
    full_periods = [p for p in periods if p["coverage"] == _COVERAGE_FULL]
    if disclosure == "full":
        if not full_periods:
            known = _newest_full_period(reports)
            scope = f" in {year}" if year is not None else ""
            if not known:
                hint = (
                    " The announcement index lists no interim or annual report "
                    "for this fund yet."
                )
            elif year is not None and not known["as_of"].startswith(str(year)):
                hint = (
                    f" The fund's newest one is '{known['report']}' (period "
                    f"{known['as_of']}), which the requested year excludes — drop "
                    "'year' to reach it."
                )
            else:
                hint = (
                    f" The fund's newest such report is '{known['report']}' "
                    f"(published {known['published']}, period {known['as_of']}), "
                    "but the archive is not yet serving its holdings detail."
                )
            return _error(
                f"no fully-disclosed portfolio is available for fund {code}{scope}. "
                "Only the interim (June) and annual (December) reports carry the "
                "complete portfolio." + hint + " Call again with "
                "disclosure='latest' for the most recent partial disclosure."
            )
        chosen = max(full_periods, key=lambda p: p["as_of"] or "")
    else:
        chosen = max(periods, key=lambda p: p["as_of"] or "")

    holdings = chosen["holdings"][:top_n]
    # ``top_n`` cuts the period's rows before paging, so paging reports the cut
    # length as its total and a caller who pages to the end sees no sign that
    # anything was withheld. That is exactly how a complete portfolio turns into
    # a silently partial one, so the cut is reported rather than assumed benign.
    truncated = len(chosen["holdings"]) - len(holdings)
    complete = chosen["coverage"] == _COVERAGE_FULL

    if complete:
        notes = (
            _NOTE_LAG
            + " These are ALL the fund's disclosed stock holdings for this "
            "period: Chinese funds publish the complete portfolio in the interim "
            "and annual reports, and pct_of_net_assets_disclosed shows how much "
            "of net assets they add up to."
        )
    else:
        notes = (
            _NOTE_LAG
            + " This period is a quarterly disclosure, which carries only the "
            "fund's largest holdings — pct_of_net_assets_disclosed shows how "
            "much of the portfolio that covers. The complete portfolio exists "
            "only for interim (June) and annual (December) periods, once their "
            "report is published; call again with disclosure='full' for the "
            "newest one."
        )
    if chosen["cross_referenced_holdings"]:
        notes += (
            f" {chosen['cross_referenced_holdings']} of these rows are marked "
            f"disclosure_source='{_SOURCE_ISSUER_CROSS_REF}': the fund's report "
            "does not list them, they are positions large enough to put the fund "
            "in the ISSUER's top-10 float holders. Real disclosure, different "
            "filing, and not counted in pct_of_net_assets_disclosed."
        )
    if chosen["unparseable_rows"]:
        notes += (
            f" WARNING: {chosen['unparseable_rows']} row(s) in this period had a "
            "cell count the table header does not explain and were dropped "
            "rather than read against mismatched columns, so this period is "
            "missing that many holdings."
        )
    if chosen["report_confirmed"] is None:
        notes += (
            " The periodic-report announcement index was unreachable, so the "
            "report behind this period could not be confirmed and its "
            "publication date is unknown."
        )
    if truncated:
        notes += (
            f" NOTE: top_n={top_n} cut {truncated} of this period's "
            f"{len(chosen['holdings'])} disclosed rows before paging, so paging "
            "to the end yields the largest top_n holdings rather than the whole "
            f"period. Raise top_n (max {_MAX_TOP_N}) to page through all of it."
        )

    missing = ["expense_ratio", "net_assets"]
    if not complete or truncated:
        missing.insert(1, "full_portfolio")
    newest_full = _newest_full_period(reports)

    def build(page: list[Any], paging: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": True,
            "mode": "holdings",
            "market": "CN",
            "source": "eastmoney_fund_archives",
            "as_of": chosen["as_of"],
            "coverage": chosen["coverage"],
            "notes": notes,
            "missing_fields": missing,
            "paging": paging,
            "data": {
                "symbol": symbol.strip().upper(),
                "fund": {"code": code, "name": chosen["fund_name"]},
                "report_label": chosen["report_label"],
                "disclosure": {
                    "requested": disclosure,
                    "report": chosen["report"],
                    "report_published": chosen["report_published"],
                    "report_confirmed": chosen["report_confirmed"],
                    "disclosure_lag_days": chosen["disclosure_lag_days"],
                },
                "holdings_in_period": chosen["fund_report_holdings"],
                "cross_referenced_in_period": chosen["cross_referenced_holdings"],
                "unparseable_rows": chosen["unparseable_rows"],
                # Rows this period holds that top_n cut before paging ever saw
                # them; 0 means paging really can reach the whole period.
                "holdings_withheld_by_top_n": truncated,
                "pct_of_net_assets_disclosed": chosen["pct_of_net_assets_disclosed"],
                "pct_of_net_assets_cross_referenced": (
                    chosen["pct_of_net_assets_cross_referenced"]
                ),
                # What the caller could have instead, so a partial answer never
                # hides the existence of the complete one.
                "full_portfolio_available": None if complete else newest_full,
                "available_periods": [
                    {
                        "as_of": p["as_of"],
                        "report_label": p["report_label"],
                        "coverage": p["coverage"],
                        "holdings_in_period": p["fund_report_holdings"],
                        "pct_of_net_assets_disclosed": p["pct_of_net_assets_disclosed"],
                    }
                    for p in periods
                ],
                "holdings": page,
            },
        }

    return fit_records(holdings, offset, build)


class EtfHoldingsTool(BaseTool):
    """Look through an ETF to its constituents, or search the ETF universe."""

    name = "etf_holdings"
    description = (
        "ETF look-through across two markets. mode='holdings' returns an ETF's "
        "constituent holdings (security, weight, market value) — for U.S. funds "
        "the FULL portfolio from the SEC N-PORT filing, for A-share funds the "
        "holdings disclosed in the fund's own periodic report. "
        "mode='lookup' searches funds by ticker, name or theme and returns their "
        "identity and size. Market is auto-detected: '.SH'/'.SZ' or a bare "
        "six-digit code goes to the A-share path, anything else to the U.S. path. "
        "For A-share funds, disclosure='full' returns the COMPLETE portfolio from "
        "the newest interim or annual report (hundreds of names, ~95-100% of net "
        "assets) while the default disclosure='latest' returns the most recent "
        "period, which between reports is a quarterly top-N — read 'coverage' and "
        "'pct_of_net_assets_disclosed' to tell which you got. "
        "Every answer carries 'as_of', the report period the holdings belong to — "
        "ETF holdings are disclosed with a lag and are never live, and the full "
        "A-share portfolio is the more complete but older of the two. Fields the "
        "source does not publish (expense ratio in particular) are listed under "
        "'missing_fields' and never estimated. "
        'Examples: {"mode": "holdings", "symbol": "IVV", "top_n": 20} or '
        '{"mode": "holdings", "symbol": "510300.SH", "disclosure": "full", '
        '"top_n": 400} or {"mode": "lookup", "query": "semiconductor"}.'
    )
    parameters = {
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "enum": list(_MODES),
                "description": (
                    "'lookup' searches the ETF universe by ticker/name/theme; "
                    "'holdings' returns one fund's constituent holdings."
                ),
            },
            "symbol": {
                "type": "string",
                "description": (
                    "Required for mode='holdings'. A U.S. ETF ticker ('IVV', "
                    "'SOXX', 'ARKK') or an A-share fund code ('510050.SH', "
                    "'159915.SZ', or bare '510050')."
                ),
            },
            "query": {
                "type": "string",
                "description": (
                    "Required for mode='lookup'. A ticker, fund name or theme "
                    "keyword, e.g. 'IVV', 'semiconductor', '黄金'."
                ),
            },
            "market": {
                "type": "string",
                "enum": list(_MARKETS),
                "description": (
                    "Override the auto-detected market (case-insensitive). In "
                    "'auto' a lookup query goes to the A-share path when it is "
                    "a six-digit fund code or contains Chinese characters. "
                    "A-share fund names are Chinese, so a CN keyword search "
                    "only matches a Chinese query ('黄金', '半导体') — a "
                    "Latin-script keyword against market='CN' legitimately "
                    "returns zero matches."
                ),
                "default": "auto",
            },
            "top_n": {
                "type": "integer",
                "description": (
                    "For mode='holdings', how many largest holdings by weight to "
                    f"consider (1-{_MAX_TOP_N}). Defaults to {_DEFAULT_TOP_N}."
                ),
                "default": _DEFAULT_TOP_N,
            },
            "limit": {
                "type": "integer",
                "description": (
                    f"For mode='lookup', maximum matches (1-{_MAX_LOOKUP}). "
                    f"Defaults to {_DEFAULT_LOOKUP}."
                ),
                "default": _DEFAULT_LOOKUP,
            },
            "disclosure": {
                "type": "string",
                "enum": list(_DISCLOSURES),
                "description": (
                    "A-share holdings only; ignored for U.S. funds, which are "
                    "always the full portfolio. 'latest' (default) returns the "
                    "newest report period, which between reports is a quarterly "
                    "top-N disclosure. 'full' returns the newest period whose "
                    "COMPLETE portfolio has been published — only the interim "
                    "(June) and annual (December) reports carry it, so this is "
                    "the fuller but older answer; it searches back through "
                    "earlier years automatically unless 'year' pins one. "
                    "'cross_reference' additionally expands the quarterly "
                    "periods to include positions disclosed by the ISSUER "
                    "rather than the fund (the fund entered that company's "
                    "top-10 float holders); those rows are real but come from a "
                    "different filing and are labelled disclosure_source on "
                    "every holding."
                ),
                "default": "latest",
            },
            "year": {
                "type": "integer",
                "description": (
                    "A-share holdings only: calendar year of the reports to "
                    "request. Omit for the most recent. The endpoint silently "
                    "ignores an unavailable year, so always read the returned "
                    "'as_of' rather than assuming this value. Pinning a year "
                    "also stops disclosure='full' from searching earlier ones."
                ),
            },
            "offset": {
                "type": "integer",
                "description": (
                    "Index of the first record to return. Records are returned "
                    "whole and only as many as fit one result — read "
                    "paging.next_offset and call again to continue."
                ),
                "default": 0,
            },
        },
        "required": ["mode"],
    }

    def execute(self, **kwargs: Any) -> str:
        """Route to the requested mode and market, returning a JSON envelope.

        Args:
            **kwargs: ``mode`` ("lookup"|"holdings", required), ``symbol``
                (required for holdings), ``query`` (required for lookup),
                ``market`` ("auto"|"US"|"CN"), ``disclosure``
                ("latest"|"full"|"cross_reference", A-share holdings only),
                ``top_n``, ``limit``, ``year`` and ``offset``.

        Returns:
            A JSON string. On success ``{"ok": true, "mode", "market",
            "source", "as_of", "coverage"?, "missing_fields", "paging",
            "data"}``; on failure ``{"ok": false, "error": str}``.
        """
        mode = kwargs.get("mode")
        if mode not in _MODES:
            return _error(f"mode must be one of {list(_MODES)}")

        # Models routinely send 'us'/'cn'/'Auto'; case is not a user error.
        market = str(kwargs.get("market") or "auto").strip()
        market = "auto" if market.lower() == "auto" else market.upper()
        if market not in _MARKETS:
            return _error(f"market must be one of {list(_MARKETS)}")

        try:
            offset = max(int(kwargs.get("offset") or 0), 0)
        except (TypeError, ValueError):
            return _error("offset must be an integer")

        if mode == "lookup":
            query = kwargs.get("query")
            if not isinstance(query, str) or not query.strip():
                return _error("'query' is required and must be a non-empty string for mode='lookup'")
            limit = _clamp(kwargs.get("limit", _DEFAULT_LOOKUP), _DEFAULT_LOOKUP, _MAX_LOOKUP)
            resolved = market if market != "auto" else _classify_query_market(query)
            return _lookup_cn(query, limit, offset) if resolved == "CN" else _lookup_us(query, limit, offset)

        symbol = kwargs.get("symbol")
        if not isinstance(symbol, str) or not symbol.strip():
            return _error("'symbol' is required and must be a non-empty string for mode='holdings'")
        top_n = _clamp(kwargs.get("top_n", _DEFAULT_TOP_N), _DEFAULT_TOP_N, _MAX_TOP_N)
        resolved = market if market != "auto" else _classify_market(symbol)
        if resolved == "CN":
            year = kwargs.get("year")
            if year is not None and (not isinstance(year, int) or isinstance(year, bool)):
                return _error("year must be an integer")
            disclosure = str(kwargs.get("disclosure") or "latest").strip().lower()
            if disclosure not in _DISCLOSURES:
                return _error(f"disclosure must be one of {list(_DISCLOSURES)}")
            return _holdings_cn(symbol, top_n, offset, year, disclosure)
        return _holdings_us(symbol, top_n, offset)


def _clamp(value: Any, default: int, maximum: int) -> int:
    """Coerce a requested count into ``1..maximum``, falling back to ``default``."""
    try:
        n = int(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return max(1, min(n, maximum))
