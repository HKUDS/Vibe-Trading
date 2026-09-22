"""Read-only tool: A-share shareholder count history via Eastmoney datacenter.

Eastmoney's datacenter report API publishes the "股东户数" (number of
registered shareholders) disclosure for mainland A-shares. The history comes
from the per-period detail report: one row per disclosure, each with the change
against the previous disclosed period (the interval varies — quarterly reports,
plus intra-quarter ad-hoc disclosures — and each row states its own
``prev_period_end``). Average holding value per account exists only on the
latest-only report, so it is joined onto the newest row when the two agree.

Only mainland A-shares (``.SH`` / ``.SZ`` / ``.BJ``) carry this disclosure;
other markets return an error envelope.
"""

from __future__ import annotations

import json
from typing import Any

from backtest.loaders.eastmoney_client import datacenter_rejection, get_json, resolve_secid
from src.agent.tools import BaseTool

# Eastmoney datacenter report endpoint + the two shareholder-number reports:
# the per-period detail report (one row per disclosure, what max_periods pages
# over) and the latest-only report (one row per symbol, the only carrier of the
# average-holding and market-cap columns).
_DATACENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
_DETAIL_REPORT = "RPT_HOLDERNUM_DET"
_LATEST_REPORT = "RPT_HOLDERNUMLATEST"

_DETAIL_COLUMNS = "SECUCODE,END_DATE,HOLDER_NUM,HOLDER_NUM_CHANGE,HOLDER_NUM_RATIO"
# Per-account market value is ``AVG_MARKET_CAP``; the older ``AVG_HOLD_AMT`` name
# no longer exists upstream, and asking for it makes the datacenter reject the
# whole request (HTTP 200, ``success: false``, ``result: null``).
_LATEST_COLUMNS = (
    "SECUCODE,SECURITY_CODE,END_DATE,PRE_END_DATE,HOLDER_NUM,HOLDER_NUM_CHANGE,"
    "HOLDER_NUM_RATIO,AVG_MARKET_CAP,AVG_HOLD_NUM,TOTAL_MARKET_CAP"
)

# Hard cap on returned periods so a long history cannot bloat the payload.
_MAX_PERIODS = 24

# A-share exchange suffixes this disclosure covers.
_A_SHARE_SUFFIXES = ("SH", "SZ", "BJ")



class ShareholderCountTool(BaseTool):
    """Fetch A-share shareholder count history with per-period change and avg holding."""

    name = "get_shareholder_count"
    description = (
        "Fetch mainland A-share shareholder count history (股东户数) from the "
        "Eastmoney datacenter: holder count per disclosed period, the change "
        "against the previous disclosed period (absolute and percent; the "
        "interval varies and each row states its own prev_period_end), and "
        "average holding (shares and market value) per account on the newest "
        "row. Markets: China A-shares only (.SH / .SZ / .BJ). "
        'Example: {"code": "600519.SH"}.'
    )
    parameters = {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": (
                    "A-share symbol in <code>.<exchange> form, exchange suffix one of "
                    "SH / SZ / BJ (e.g. '600519.SH', '000001.SZ', '830799.BJ')."
                ),
            },
            "max_periods": {
                "type": "integer",
                "description": (
                    "Maximum number of most-recent report periods to return "
                    f"(1-{_MAX_PERIODS}). Defaults to {_MAX_PERIODS}."
                ),
                "default": _MAX_PERIODS,
            },
        },
        "required": ["code"],
    }

    def execute(self, **kwargs: Any) -> str:
        """Resolve the symbol, query the report, and return a JSON envelope.

        Args:
            **kwargs: ``code`` (required A-share symbol) and optional
                ``max_periods`` (period cap).

        Returns:
            A JSON string envelope. On success:
            ``{"ok": true, "market": "CN", "source": "eastmoney",
            "data": {"code", "periods": [...]}}``. On failure:
            ``{"ok": false, "error": str}``.
        """
        code = kwargs.get("code")
        if not isinstance(code, str) or not code.strip():
            return _error("'code' is required and must be a non-empty A-share symbol")
        code = code.strip().upper()

        suffix = code.rpartition(".")[2]
        if suffix not in _A_SHARE_SUFFIXES:
            return _error(
                f"shareholder count is China A-share only (.SH/.SZ/.BJ); got '{code}'"
            )
        if resolve_secid(code) is None:
            return _error(f"could not resolve A-share symbol '{code}'")

        limit = _clamp_periods(kwargs.get("max_periods", _MAX_PERIODS))

        try:
            detail_payload = get_json(
                _DATACENTER_URL,
                params={
                    "reportName": _DETAIL_REPORT,
                    "columns": _DETAIL_COLUMNS,
                    "filter": f'(SECUCODE="{code}")',
                    "sortColumns": "END_DATE",
                    "sortTypes": "-1",
                    "pageNumber": "1",
                    # One row past the limit: the oldest returned period's
                    # prev_period_end comes from the row after it.
                    "pageSize": str(limit + 1),
                    "source": "WEB",
                    "client": "WEB",
                },
            )
        except Exception as exc:  # noqa: BLE001 - surface any fetch failure as envelope
            return _error(f"eastmoney datacenter request failed: {exc}")

        rejection = datacenter_rejection(detail_payload)
        if rejection is not None:
            return _error(f"eastmoney datacenter rejected the request: {rejection}")

        periods = _parse_periods(detail_payload)
        warnings: list[str] = []
        if periods:
            # The per-period report has no average-holding or market-cap
            # columns; the latest-only report carries them, so join its row
            # onto the newest period when the two agree on the end date.
            latest, problem = _fetch_latest_row(code)
            if problem is not None:
                warnings.append(
                    f"average holding and market cap unavailable: latest-only report {problem}"
                )
            if latest is not None and periods[0]["end_date"] == latest["end_date"]:
                for key in ("avg_hold_shares", "avg_hold_amount", "total_market_cap"):
                    periods[0][key] = latest.get(key)
        else:
            # Some symbols only surface on the latest-only report; answer the
            # single latest period rather than nothing.
            latest, problem = _fetch_latest_row(code)
            if problem is not None:
                return _error(f"eastmoney latest-only report {problem}")
            if latest is None:
                return _error(f"no shareholder-count disclosure found for '{code}'")
            periods = [latest]

        data: dict[str, Any] = {"code": code, "periods": periods[:limit]}
        if warnings:
            data["warnings"] = warnings
        return json.dumps(
            {"ok": True, "market": "CN", "source": "eastmoney", "data": data},
            ensure_ascii=False,
        )


def _clamp_periods(value: Any) -> int:
    """Coerce a requested period count into the supported ``1.._MAX_PERIODS`` range."""
    try:
        n = int(value)
    except (TypeError, ValueError, OverflowError):
        return _MAX_PERIODS
    return max(1, min(n, _MAX_PERIODS))


def _parse_periods(payload: Any) -> list[dict]:
    """Extract per-period shareholder records from a datacenter payload.

    Args:
        payload: Decoded datacenter JSON; rows live under ``result.data``.

    Returns:
        A list of normalized period dicts (newest first), empty when the payload
        carries no usable rows.
    """
    if not isinstance(payload, dict):
        return []
    result = payload.get("result")
    if not isinstance(result, dict):
        return []
    rows = result.get("data")
    if not isinstance(rows, list):
        return []

    periods: list[dict] = []
    for row in rows:
        record = _normalize_row(row)
        if record is not None:
            periods.append(record)
    # Each row's change columns are measured against the previous disclosed
    # period; state that interval per row instead of calling it
    # quarter-over-quarter (#1503 measured PRE_END_DATE drifting to nine
    # months or nine years on the latest-only report).
    for i, record in enumerate(periods):
        # the detail report carries no PRE_END_DATE; the latest-only fallback
        # row already carries its own, so only fill the gap
        if record.get("prev_period_end") is None:
            record["prev_period_end"] = (
                periods[i + 1]["end_date"] if i + 1 < len(periods) else None
            )
    return periods


def _normalize_row(row: Any) -> dict | None:
    """Map one raw datacenter row to our period record, or ``None`` if unusable.

    A row missing both an end date and a holder count carries no signal and is
    dropped; a single bad row never aborts the batch.

    Args:
        row: One element of ``result.data``.

    Returns:
        ``{end_date, holder_count, holder_count_change, holder_count_change_pct,
        avg_hold_shares, avg_hold_amount, total_market_cap}`` or ``None``.
    """
    if not isinstance(row, dict):
        return None
    end_date = _clean_date(row.get("END_DATE"))
    holder_count = _to_number(row.get("HOLDER_NUM"))
    if end_date is None and holder_count is None:
        return None
    return {
        "end_date": end_date,
        "holder_count": holder_count,
        "holder_count_change": _to_number(row.get("HOLDER_NUM_CHANGE")),
        "holder_count_change_pct": _to_number(row.get("HOLDER_NUM_RATIO")),
        "avg_hold_shares": _to_number(row.get("AVG_HOLD_NUM")),
        "avg_hold_amount": _to_number(row.get("AVG_MARKET_CAP")),
        "total_market_cap": _to_number(row.get("TOTAL_MARKET_CAP")),
        "prev_period_end": _clean_date(row.get("PRE_END_DATE")),
    }


def _fetch_latest_row(code: str) -> tuple[dict | None, str | None]:
    """Fetch the latest-only report's single row for ``code``.

    Used for the average-holding / market-cap columns the detail report does
    not carry, and as the single-period answer when the detail report has no
    rows for the symbol. A failure is returned, not raised, so the caller can
    keep the history it has and say what is missing.

    Returns:
        ``(row, None)`` on success, ``(None, None)`` when the report has no
        row, or ``(None, problem)`` when the request failed or was rejected.
    """
    try:
        payload = get_json(
            _DATACENTER_URL,
            params={
                "reportName": _LATEST_REPORT,
                "columns": _LATEST_COLUMNS,
                "filter": f'(SECUCODE="{code}")',
                "sortColumns": "END_DATE",
                "sortTypes": "-1",
                "pageNumber": "1",
                "pageSize": "1",
                "source": "WEB",
                "client": "WEB",
            },
        )
    except Exception as exc:  # noqa: BLE001 - reported to the caller, never raised
        return None, f"request failed: {exc}"
    rejection = datacenter_rejection(payload)
    if rejection is not None:
        return None, f"rejected the request: {rejection}"
    periods = _parse_periods(payload)
    return (periods[0] if periods else None), None


def _clean_date(value: Any) -> str | None:
    """Trim a datacenter timestamp to its ``YYYY-MM-DD`` date, or ``None``."""
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip().split(" ", 1)[0]


def _to_number(value: Any) -> float | None:
    """Coerce a datacenter cell to ``float``, or ``None`` when absent/non-numeric."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _error(message: str) -> str:
    """Render a failure envelope as a JSON string."""
    return json.dumps({"ok": False, "error": message}, ensure_ascii=False)
