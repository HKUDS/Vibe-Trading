"""Read-only tool: SEC EDGAR filings for one issuer, plus optional Firecrawl filing text.

SEC EDGAR stays the primary source. The tool first runs the existing
``get_sec_filings`` lookup and keeps its envelope: the same keys in the same
order and the same filings in the same order. It then appends a separate
``firecrawl_context`` key. Firecrawl never adds, edits or reorders SEC filings.

When ``FIRECRAWL_API_KEY`` is set (environment or ``agent/.env``), the tool
scrapes the primary document of up to three of the newest filings on the
returned page through Firecrawl /scrape and adds a text excerpt of each. Every
context item carries the filing URL and filing date taken from the SEC filing
index, plus the form and accession number. A filing whose index row has no
document URL or no filing date is listed under ``skipped`` and never scraped,
so no URL or date is ever inferred.

The result stays within the tool output budget. Excerpts are capped first; when
the envelope is still too large, the SEC page holds fewer whole filings and its
``paging`` block says where the list continues (pass ``offset`` to continue).

Behavior without a key or on failure:

* No key: the tool is hidden from the agent registry. A direct call returns the
  SEC envelope with ``firecrawl_context.enabled = false`` and a note, and makes
  no Firecrawl request.
* Request failure (timeout, HTTP 4xx/5xx, rate limit, unusable body): no retry.
  The tool stops scraping, keeps the items already fetched, and reports what
  failed in ``firecrawl_context.error``. The SEC part is still returned.
* The SEC lookup and each Firecrawl request are separate data-gateway reads,
  each with its own wall-clock deadline (``VIBE_GATEWAY_SOURCE_TIMEOUT``, 6 s by
  default). A slow or stalled scrape therefore ends only that request; the SEC
  result already in hand is still returned.

Excerpts are third-party filing text passed to the model as context, not
instructions. Context is fetched while the agent gathers research context;
Research Lab replays saved fundamental and event columns and never calls this
tool.

Example (run from ``agent/``)::

    python src/skills/sec-edgar/scripts/firecrawl_filing_context_example.py --offline
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

import requests

from backtest.loaders._http import throttled_post_json
from backtest.loaders.acquisition import remaining_timeout
from src.agent.tools import BaseTool
from src.config.accessor import get_env_config
from src.config.limits import TOOL_RESULT_LIMIT
from src.data_gateway import get_gateway
from src.tools._result_paging import fit_records
from src.tools.sec_filings_tool import SecFilingsTool

_SCRAPE_URL = "https://api.firecrawl.dev/v2/scrape"
_HOST_KEY = "firecrawl"
_MIN_INTERVAL_S = 0.2
_REQUEST_TIMEOUT_S = 30.0
_DEADLINE_MARGIN_S = 0.5
_MIN_REQUEST_S = 1.5
_ORIGIN = "vibe-trading"

_DEFAULT_FILINGS = 1
_MAX_FILINGS = 3
_DEFAULT_CHARS = 1500
_MAX_CHARS = 3000
_MIN_CHARS = 200
_CONTEXT_BUDGET = 4500
_QUERY_WINDOWS = 3
_QUERY_BEFORE = 100
_QUERY_AFTER = 500

DISABLED_NOTE = "Firecrawl filing context disabled: set FIRECRAWL_API_KEY to enable"


class _UnusableResponse(Exception):
    """Firecrawl answered, but without text we can use for this filing."""


class FirecrawlFilingContextTool(BaseTool):
    """SEC filings for one U.S. issuer, with optional Firecrawl text for the newest ones."""

    name = "get_filing_context"
    description = (
        "Fetch SEC EDGAR filings for one U.S. issuer (the get_sec_filings "
        "envelope), then append readable text excerpts of up to three of the "
        "newest listed filings, scraped with Firecrawl (one request per filing). "
        "Each excerpt carries the SEC filing URL, filing date, form and accession "
        "number. SEC data comes first and is never reordered; Firecrawl context "
        "needs FIRECRAWL_API_KEY. Markets: United States only. "
        'Example: {"ticker": "AAPL", "form": "8-K", "max_filings": 1, '
        '"query": "Item 8.01"}.'
    )
    parameters = {
        "type": "object",
        "properties": {
            "ticker": {
                "type": "string",
                "description": "U.S. equity ticker, case-insensitive (e.g. 'AAPL').",
            },
            "form": {
                "type": "string",
                "description": (
                    "Optional SEC form type filter (e.g. '10-K', '10-Q', '8-K'), " "passed to the SEC lookup unchanged."
                ),
            },
            "offset": {
                "type": "integer",
                "description": (
                    "Index of the first SEC filing to return, newest first; "
                    "defaults to 0. Read paging.next_offset to continue."
                ),
            },
            "max_filings": {
                "type": "integer",
                "description": (
                    f"How many of the first filings on the page to scrape "
                    f"(1-{_MAX_FILINGS}). Defaults to {_DEFAULT_FILINGS}."
                ),
                "default": _DEFAULT_FILINGS,
            },
            "query": {
                "type": "string",
                "description": (
                    "Optional phrase to look for in each filing, e.g. 'Item 8.01' "
                    "or 'risk factors'. When found, the excerpt is built from the "
                    "text around the first matches instead of the document start."
                ),
            },
            "max_chars": {
                "type": "integer",
                "description": (
                    f"Maximum excerpt length per filing ({_MIN_CHARS}-{_MAX_CHARS}). "
                    f"Defaults to {_DEFAULT_CHARS}. All excerpts together stay "
                    f"within {_CONTEXT_BUDGET} characters."
                ),
                "default": _DEFAULT_CHARS,
            },
        },
        "required": ["ticker"],
    }

    @classmethod
    def check_available(cls) -> bool:
        """Register the tool only when a Firecrawl API key is configured.

        Returns:
            ``True`` when ``FIRECRAWL_API_KEY`` is set, otherwise ``False``.
        """
        return bool(get_env_config().data.firecrawl_api_key)

    def execute(self, **kwargs: Any) -> str:
        """Return the SEC envelope with a ``firecrawl_context`` block appended.

        Not wrapped in ``public_data_read``: ``get_sec_filings`` and every
        Firecrawl request (``throttled_post_json`` is a ``managed_reader``) are
        bounded gateway reads on their own, so an expired scrape cannot take the
        SEC result down with it.

        Args:
            **kwargs: ``ticker`` (required), optional ``form``, ``offset``,
                ``max_filings``, ``query`` and ``max_chars``.

        Returns:
            A JSON string. When the SEC lookup fails, its error envelope is
            returned as is and Firecrawl is not called. Otherwise the SEC
            envelope followed by ``firecrawl_context``:
            ``{"enabled": bool, "items": [...], "skipped": [...]}`` plus
            ``note`` when disabled or ``error`` when a request failed. Each
            item is ``{"source": "firecrawl", "filing_url", "filing_date",
            "form", "accession_number", "excerpt", "text_chars"}``, with
            ``query_found`` when a query was given. In the rare case that even
            a context block without excerpts cannot fit the tool output budget,
            the ``get_sec_filings`` result is returned unchanged, without
            ``firecrawl_context``.
        """
        sec_kwargs = {k: kwargs[k] for k in ("ticker", "form", "offset") if k in kwargs}
        sec_result = SecFilingsTool().execute(**sec_kwargs)
        try:
            envelope = json.loads(sec_result)
        except ValueError:
            return sec_result
        if not isinstance(envelope, dict) or not envelope.get("ok"):
            return sec_result

        api_key = get_env_config().data.firecrawl_api_key
        if not api_key:
            context = {"enabled": False, "note": DISABLED_NOTE, "items": [], "skipped": []}
            return _fit_with_context(envelope, lambda chars: context, 0, fallback=sec_result)

        max_filings = _clamp(kwargs.get("max_filings"), _DEFAULT_FILINGS, 1, _MAX_FILINGS)
        max_chars = _clamp(kwargs.get("max_chars"), _DEFAULT_CHARS, _MIN_CHARS, _MAX_CHARS)
        query = kwargs.get("query")
        query = query.strip() if isinstance(query, str) and query.strip() else None

        candidates = ((envelope.get("data") or {}).get("filings") or [])[:max_filings]
        scraped: List[Dict[str, Any]] = []
        skipped: List[Dict[str, Any]] = []
        error: Optional[str] = None
        for filing in candidates:
            filing_url = filing.get("document_url")
            filing_date = filing.get("filing_date")
            if not filing_url or not filing_date:
                skipped.append(
                    {
                        "accession_number": filing.get("accession_number"),
                        "reason": "SEC index row has no filing URL or filing date",
                    }
                )
                continue
            budget = _request_budget()
            if budget < _MIN_REQUEST_S:
                error = (
                    f"not enough request time left to scrape {filing.get('accession_number')}; "
                    "raise VIBE_GATEWAY_SOURCE_TIMEOUT or lower max_filings"
                )
                break
            try:
                text = _scrape_text(filing_url, api_key, budget)
            except Exception as exc:  # noqa: BLE001 - any failure falls back to SEC-only
                error = f"{_describe_failure(exc, budget)} for {filing.get('accession_number')}"
                break
            scraped.append(
                {
                    "source": "firecrawl",
                    "filing_url": filing_url,
                    "filing_date": filing_date,
                    "form": filing.get("form"),
                    "accession_number": filing.get("accession_number"),
                    "text": text,
                }
            )
        if error is not None:
            error += f"; scraped {len(scraped)} of {len(candidates)} requested filings"

        def context_for(chars: int) -> Dict[str, Any]:
            context: Dict[str, Any] = {
                "enabled": True,
                "items": [_item(entry, query, chars) for entry in scraped],
                "skipped": skipped,
            }
            if error is not None:
                context["error"] = error
            return context

        start_chars = min(max_chars, _CONTEXT_BUDGET // max(1, len(scraped)))
        return _fit_with_context(envelope, context_for, start_chars, keep=len(candidates), fallback=sec_result)


def _fit_with_context(envelope: Dict[str, Any], context_for, chars: int, *, fallback: str, keep: int = 1) -> str:
    """Serialize the SEC envelope plus context within the tool output budget.

    SEC filings keep their order and content. The page is cut to whole filings
    only when needed, and never below the ``keep`` filings the context refers
    to; past that point the excerpts are shortened. When even the shortest
    excerpts do not fit, the items are dropped and the context says so; when
    the context still does not fit, the original SEC result is returned.

    Args:
        envelope: Decoded ``get_sec_filings`` success envelope.
        context_for: Callable building the context block for an excerpt length.
        chars: Starting excerpt length.
        fallback: The original ``get_sec_filings`` result, which already fits.
        keep: Minimum number of SEC filings the page must keep.

    Returns:
        The serialized envelope.
    """
    sec_paging = envelope.get("paging") or {}
    base_offset = sec_paging.get("offset") or 0
    page = envelope["data"].get("filings") or []
    total = sec_paging.get("total", base_offset + len(page))
    keep = min(max(keep, 1), len(page)) if page else 0

    while True:
        if chars >= 0:
            context = context_for(chars)
        else:
            context = context_for(0)
            if context["items"]:
                context = {**context, "items": [], "dropped": "excerpts did not fit the tool output budget"}
            keep = min(1, keep)
        returned = [len(page)]

        def _build(records: List[Any], _meta: Dict[str, Any]) -> Dict[str, Any]:
            returned[0] = len(records)
            next_offset = base_offset + len(records)
            out = dict(envelope)
            out["paging"] = {
                "total": total,
                "offset": base_offset,
                "returned": len(records),
                "next_offset": None if next_offset >= total else next_offset,
                "complete": next_offset >= total,
            }
            out["data"] = {**envelope["data"], "filings": records}
            out["firecrawl_context"] = context
            return out

        result = fit_records(page, 0, _build)
        if len(result) <= TOOL_RESULT_LIMIT and returned[0] >= keep:
            return result
        if chars < 0:
            return fallback
        chars = chars // 2 if chars > _MIN_CHARS else -1


def _request_budget() -> float:
    """Seconds one Firecrawl request may take inside its gateway deadline."""
    try:
        limit = remaining_timeout(min(_REQUEST_TIMEOUT_S, get_gateway().config.source_timeout))
    except TimeoutError:
        return 0.0
    return limit - _DEADLINE_MARGIN_S


def _scrape_text(url: str, api_key: str, budget: float) -> str:
    """Scrape one filing document through Firecrawl and return its cleaned text.

    Args:
        url: SEC primary-document URL.
        api_key: Firecrawl API key, sent only in the Authorization header.
        budget: Seconds the request may take, used for both the client socket
            timeout and the Firecrawl-side scrape timeout.

    Returns:
        The document text with markdown images, links, table rules and extra
        whitespace removed.

    Raises:
        requests.RequestException: Transport failure, timeout or non-2xx status.
        _UnusableResponse: Firecrawl answered without readable filing text, or
            the filing page itself returned an error status.
    """
    payload = throttled_post_json(
        _SCRAPE_URL,
        host_key=_HOST_KEY,
        min_interval=_MIN_INTERVAL_S,
        json_body={
            "url": url,
            "formats": ["markdown"],
            "onlyMainContent": True,
            "excludeTags": ["div[style*='display:none']"],
            "timeout": int(budget * 1000),
            "origin": _ORIGIN,
        },
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=budget,
    )
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(payload, dict) or not payload.get("success") or not isinstance(data, dict):
        raise _UnusableResponse("Firecrawl response did not include scraped content")
    status = (data.get("metadata") or {}).get("statusCode")
    if isinstance(status, int) and status >= 400:
        raise _UnusableResponse(f"filing page returned HTTP {status} to Firecrawl")
    markdown = data.get("markdown")
    text = _clean(markdown) if isinstance(markdown, str) else ""
    if not text:
        raise _UnusableResponse("filing page has no readable text")
    return text


def _clean(markdown: str) -> str:
    """Reduce scraped markdown to plain readable text."""
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", markdown)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\|\s*-{3,}\s*", " ", text)
    text = re.sub(r"(\*\s*){3,}", " ", text)
    text = text.replace("|", " ")
    return re.sub(r"\s+", " ", text).strip()


def _item(entry: Dict[str, Any], query: Optional[str], chars: int) -> Dict[str, Any]:
    """Build one context item with an excerpt of at most ``chars`` characters."""
    text = entry["text"]
    item = {key: value for key, value in entry.items() if key != "text"}
    if query is None:
        item["excerpt"] = text[:chars]
    else:
        windows = _query_windows(text, query)
        item["query_found"] = bool(windows)
        item["excerpt"] = (" ... ".join(windows) if windows else text)[:chars]
    item["text_chars"] = len(text)
    return item


def _query_windows(text: str, query: str) -> List[str]:
    """Return non-overlapping text windows around the first matches of ``query``."""
    windows: List[str] = []
    covered = 0
    for match in re.finditer(re.escape(query), text, flags=re.IGNORECASE):
        if match.start() < covered:
            continue
        start = max(covered, match.start() - _QUERY_BEFORE)
        covered = match.end() + _QUERY_AFTER
        windows.append(text[start:covered])
        if len(windows) >= _QUERY_WINDOWS:
            break
    return windows


def _describe_failure(exc: Exception, budget: float) -> str:
    """Describe a Firecrawl failure from fixed messages, never from request data."""
    if isinstance(exc, _UnusableResponse):
        return str(exc)
    if isinstance(exc, (requests.Timeout, TimeoutError)):
        return f"Firecrawl request timed out after {budget:.1f}s"
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        status = exc.response.status_code
        return f"Firecrawl returned HTTP {status}" + (" (rate limited)" if status == 429 else "")
    return f"Firecrawl request failed ({type(exc).__name__})"


def _clamp(value: Any, default: int, low: int, high: int) -> int:
    """Coerce ``value`` to an int within ``low..high``, else ``default``."""
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return max(low, min(number, high))
