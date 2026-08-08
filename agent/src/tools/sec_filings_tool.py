"""Read-only tool: U.S. SEC EDGAR filing index + XBRL GAAP metric series.

The U.S. SEC publishes free, no-auth JSON for every reporting company: a recent
filing index (10-K / 10-Q / 8-K and friends) and the full set of XBRL financial
concepts the company has reported. This tool wraps both behind the project's
BaseTool contract and the frozen, IP-throttled SEC client so the agent never
hits ``sec.gov`` un-throttled and never re-implements provider plumbing.

Two answers from one tool:

* a list of recent filings (optionally filtered to one ``form`` such as 10-K),
  each with accession number, filing/report dates, and the primary document URL;
* when ``metric`` is given, the reported time series for a single us-gaap
  concept (e.g. ``Revenues``, ``NetIncomeLoss``) drawn from XBRL companyfacts.

Markets: United States only. A ticker that the SEC table does not list returns
an error envelope.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from backtest.loaders import sec_frames
from backtest.loaders.sec_edgar_client import (
    cik_for,
    get_company_facts,
    get_submissions,
)
from src.agent.tools import BaseTool
from src.tools._result_paging import fit_records

# Hard caps so a long filing history or metric series cannot bloat the payload.
_MAX_LIMIT = 40
_DEFAULT_LIMIT = 20

# SEC primary-document URLs are built from the un-padded CIK + the accession
# number with its dashes stripped.
_DOC_BASE = "https://www.sec.gov/Archives/edgar/data"


class SecFilingsTool(BaseTool):
    """List recent SEC filings and optionally one XBRL us-gaap metric series."""

    name = "get_sec_filings"
    description = (
        "Fetch U.S. SEC EDGAR data for a public company: a list of recent "
        "filings (10-K / 10-Q / 8-K, etc.) with accession number, filing and "
        "report dates, and the primary-document URL; or, when 'metric' is given, "
        "the reported XBRL us-gaap financial series for that concept (e.g. "
        "Revenues, NetIncomeLoss, Assets). Markets: United States only. "
        'Example: {"ticker": "AAPL", "form": "10-K", "limit": 5}.'
    )
    parameters = {
        "type": "object",
        "properties": {
            "ticker": {
                "type": "string",
                "description": (
                    "U.S. equity ticker, case-insensitive (e.g. 'AAPL', 'msft'). "
                    "Resolved to a CIK via the SEC company-tickers table."
                ),
            },
            "form": {
                "type": "string",
                "description": (
                    "Optional SEC form type to filter the filing list, "
                    "case-insensitive (e.g. '10-K', '10-Q', '8-K'). Omit to "
                    "return all recent forms."
                ),
            },
            "metric": {
                "type": "string",
                "description": (
                    "Optional XBRL us-gaap concept name (e.g. 'Revenues', "
                    "'NetIncomeLoss', 'Assets'). When set, the response also "
                    "carries the reported time series for that concept."
                ),
            },
            "offset": {
                "type": "integer",
                "description": (
                    "Index of the first filing to return, newest first; "
                    "defaults to 0. Filings are returned whole and only as many "
                    "as fit one result — read paging.total and paging.next_offset "
                    "and call again to continue."
                ),
            },
            "limit": {
                "type": "integer",
                "description": (
                    f"Maximum number of most-recent filings and metric points to "
                    f"return (1-{_MAX_LIMIT}). Defaults to {_DEFAULT_LIMIT}."
                ),
                "default": _DEFAULT_LIMIT,
            },
        },
        "required": ["ticker"],
    }

    def execute(self, **kwargs: Any) -> str:
        """Resolve the ticker, fetch filings/facts, and return a JSON envelope.

        Args:
            **kwargs: ``ticker`` (required U.S. symbol), optional ``form`` filter,
                optional ``metric`` (us-gaap concept), and optional ``limit``.

        Returns:
            A JSON string envelope. On success:
            ``{"ok": true, "market": "US", "source": "sec_edgar",
            "paging": {...}, "data": {"ticker", "cik", "filings": [...],
            "metric": {...}}}`` (``metric`` present only when requested).
            ``filings`` is paged: read ``paging.next_offset`` to continue.
            On failure:
            ``{"ok": false, "error": str}``.
        """
        ticker = kwargs.get("ticker")
        if not isinstance(ticker, str) or not ticker.strip():
            return _error("'ticker' is required and must be a non-empty U.S. symbol")
        ticker = ticker.strip().upper()

        form = kwargs.get("form")
        form_filter = form.strip().upper() if isinstance(form, str) and form.strip() else None

        metric = kwargs.get("metric")
        metric_name = metric.strip() if isinstance(metric, str) and metric.strip() else None

        limit = _clamp_limit(kwargs.get("limit", _DEFAULT_LIMIT))

        try:
            cik = cik_for(ticker)
        except Exception as exc:  # noqa: BLE001 - surface any fetch failure as envelope
            return _error(f"SEC ticker lookup failed: {exc}")
        if not cik:
            return _error(f"ticker '{ticker}' not found in the SEC company table (US only)")

        try:
            submissions = get_submissions(cik)
        except Exception as exc:  # noqa: BLE001 - surface any fetch failure as envelope
            return _error(f"SEC submissions request failed: {exc}")

        filings = _parse_filings(submissions, form_filter, cik)

        metric_block: Dict[str, Any] | None = None
        if metric_name is not None:
            try:
                facts = get_company_facts(cik)
            except Exception as exc:  # noqa: BLE001 - surface any fetch failure as envelope
                return _error(f"SEC companyfacts request failed: {exc}")
            metric_block = _parse_metric(facts, metric_name, limit)

        try:
            offset = max(int(kwargs.get("offset") or 0), 0)
        except (TypeError, ValueError):
            return _error("offset must be an integer")

        # The filing index is the bulk of this envelope — 12,077 of 12,190
        # characters for a bare AAPL call, i.e. the default request already
        # overflowed the result budget and lost its tail without saying so.
        def _build(page: List[Any], paging: Dict[str, Any]) -> Dict[str, Any]:
            data: Dict[str, Any] = {"ticker": ticker, "cik": cik, "filings": page}
            if metric_block is not None:
                data["metric"] = metric_block
            return {
                "ok": True,
                "market": "US",
                "source": "sec_edgar",
                "paging": paging,
                "data": data,
            }

        return fit_records(filings, offset, _build)


def _clamp_limit(value: Any) -> int:
    """Coerce a requested count into the supported ``1.._MAX_LIMIT`` range."""
    try:
        n = int(value)
    except (TypeError, ValueError, OverflowError):
        return _DEFAULT_LIMIT
    return max(1, min(n, _MAX_LIMIT))


def _parse_filings(
    submissions: Any, form_filter: Optional[str], cik: str
) -> List[Dict[str, Any]]:
    """Extract recent filings from a submissions payload, newest first.

    The SEC submissions document stores the recent filing index as parallel
    arrays under ``filings.recent`` (``form``, ``accessionNumber``,
    ``filingDate``, ``reportDate``, ``primaryDocument``, ...). A row whose form
    does not match ``form_filter`` is skipped; a malformed row never aborts the
    batch.

    Args:
        submissions: Decoded submissions JSON.
        form_filter: Upper-cased form type to keep, or ``None`` for all forms.
        cik: The company CIK, used to build primary-document URLs.

    Returns:
        A list of normalized filing dicts (already newest-first from the SEC),
        capped at ``_MAX_LIMIT``.
    """
    recent = _recent_block(submissions)
    if recent is None:
        return []

    forms = recent.get("form") or []
    accessions = recent.get("accessionNumber") or []
    filing_dates = recent.get("filingDate") or []
    report_dates = recent.get("reportDate") or []
    primary_docs = recent.get("primaryDocument") or []
    descriptions = recent.get("primaryDocDescription") or []

    out: List[Dict[str, Any]] = []
    for idx, raw_form in enumerate(forms):
        form_type = str(raw_form).strip() if raw_form is not None else ""
        if form_filter is not None and form_type.upper() != form_filter:
            continue
        accession = _at(accessions, idx)
        out.append(
            {
                "form": form_type or None,
                "accession_number": accession,
                "filing_date": _at(filing_dates, idx),
                "report_date": _at(report_dates, idx) or None,
                "primary_document": _at(primary_docs, idx) or None,
                "description": _at(descriptions, idx) or None,
                "document_url": _document_url(cik, accession, _at(primary_docs, idx)),
            }
        )
        if len(out) >= _MAX_LIMIT:
            break
    return out


def _recent_block(submissions: Any) -> Optional[Dict[str, Any]]:
    """Return the ``filings.recent`` mapping from a submissions payload, or ``None``."""
    if not isinstance(submissions, dict):
        return None
    filings = submissions.get("filings")
    if not isinstance(filings, dict):
        return None
    recent = filings.get("recent")
    return recent if isinstance(recent, dict) else None


def _document_url(cik: str, accession: Optional[str], primary_doc: Optional[str]) -> Optional[str]:
    """Build the SEC primary-document URL, or ``None`` when parts are missing.

    Args:
        cik: Padded or un-padded CIK; leading zeros are dropped for the URL.
        accession: Accession number like ``0000320193-23-000106``.
        primary_doc: Primary document filename within the filing.

    Returns:
        A fully-qualified ``sec.gov`` document URL, or ``None``.
    """
    if not accession or not primary_doc:
        return None
    cik_digits = str(cik).lstrip("0") or "0"
    accession_nodash = str(accession).replace("-", "")
    return f"{_DOC_BASE}/{cik_digits}/{accession_nodash}/{primary_doc}"


def _parse_metric(facts: Any, metric_name: str, limit: int) -> Dict[str, Any]:
    """Extract one us-gaap concept's reported series from a companyfacts payload.

    XBRL companyfacts nest as ``facts.us-gaap.<Concept>.units.<Unit>`` -> a list
    of points (``{start?, end, val, fy, fp, form, accn, filed, frame?}``). We
    surface the most populated unit, deduplicated to one point per ``(start,
    end)`` span, sorted oldest first and truncated to the most recent ``limit``.
    Each point carries its span so a year-to-date frame can never be read as a
    quarter.

    Args:
        facts: Decoded companyfacts JSON.
        metric_name: The us-gaap concept name to look up.
        limit: Maximum number of most-recent points to return.

    Returns:
        ``{"concept", "unit", "label", "points": [...]}``; ``unit`` and
        ``points`` are empty when the concept is absent or carries no data.
    """
    base: Dict[str, Any] = {"concept": metric_name, "unit": None, "label": None, "points": []}
    if not isinstance(facts, dict):
        return base
    gaap = (facts.get("facts") or {}).get("us-gaap")
    if not isinstance(gaap, dict):
        return base
    concept = gaap.get(metric_name)
    if not isinstance(concept, dict):
        return base

    base["label"] = concept.get("label")
    units = concept.get("units")
    if not isinstance(units, dict) or not units:
        return base

    unit_key, rows = _pick_unit(units)
    base["unit"] = unit_key

    points = [p for p in (_normalize_point(r) for r in rows) if p is not None]
    # A period is filed once and then repeated as a comparative in every later
    # filing, so keeping each vintage both inflates the series and pushes real
    # history out of ``limit``. Identity is the ``(start, end)`` span; the
    # newest filing wins so a restatement is what surfaces.
    latest: Dict[tuple[Any, Any], Dict[str, Any]] = {}
    for point in points:
        key = (point["start"], point["end"])
        prior = latest.get(key)
        if prior is None or str(point["filed"] or "") >= str(prior["filed"] or ""):
            latest[key] = point
    points = sorted(
        latest.values(),
        key=lambda point: (str(point["end"] or ""), str(point["start"] or "")),
    )
    base["points"] = points[-limit:] if limit > 0 else points
    return base


def _pick_unit(units: Dict[str, Any]) -> tuple[str, List[Any]]:
    """Choose the unit bucket with the most reported rows.

    Args:
        units: The ``units`` mapping of a us-gaap concept.

    Returns:
        ``(unit_key, rows)`` for the richest unit; ``rows`` is ``[]`` when none.
    """
    best_key = ""
    best_rows: List[Any] = []
    for key, rows in units.items():
        if isinstance(rows, list) and len(rows) >= len(best_rows):
            best_key, best_rows = str(key), rows
    return best_key, best_rows


def _normalize_point(row: Any) -> Optional[Dict[str, Any]]:
    """Map one XBRL fact row to our metric point, or ``None`` if unusable.

    A row without both a value and an end date carries no signal and is dropped.

    Args:
        row: One element of a unit's fact list.

    Returns:
        ``{end, val, start, period_days, period_type, filed, fiscal_year,
        fiscal_period, form, accession, frame}`` or ``None``.
    """
    if not isinstance(row, dict):
        return None
    end = row.get("end")
    val = _to_number(row.get("val"))
    if not end and val is None:
        return None
    days = sec_frames.span_days(row)
    return {
        "end": end,
        "val": val,
        # Without the span a nine-month year-to-date figure is indistinguishable
        # from the quarter ending the same day, and both are reported under the
        # same fiscal_period on the same 10-Q.
        "start": row.get("start"),
        "period_days": days,
        "period_type": sec_frames.classify_span(days),
        "filed": row.get("filed"),
        "fiscal_year": row.get("fy"),
        "fiscal_period": row.get("fp"),
        "form": row.get("form"),
        "accession": row.get("accn"),
        "frame": row.get("frame"),
    }


def _at(seq: Any, idx: int) -> Optional[str]:
    """Return ``seq[idx]`` as a stripped string, or ``None`` when out of range/empty."""
    if not isinstance(seq, list) or idx >= len(seq):
        return None
    value = seq[idx]
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _to_number(value: Any) -> Optional[float]:
    """Coerce a fact value to ``float``, or ``None`` when absent/non-numeric."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _error(message: str) -> str:
    """Render a failure envelope as a JSON string."""
    return json.dumps({"ok": False, "error": message}, ensure_ascii=False)
