"""Read-only tool: OTC fund NAV history from Gildata (恒生聚源).

Chinese off-exchange funds (场外基金 — ``110022.OF``-style open-end funds)
publish no OHLCV bars; their tradable series is the daily NAV. The project's
loader layer is an OHLCV contract and deliberately stays that way, so this
agent-facing tool serves NAV history instead, straight from the vendor's
``NetFundUnitValueReport`` raw-api tool.

Each fund code resolves to a 聚源内码 through the same recall machinery the
loader uses (:mod:`backtest.loaders.gildata_codes`), with an exact
``ref_code`` match and the shared disk cache. Requires ``GILDATA_TOKEN``;
without it the tool is silently excluded from the registry.

Field mapping (vendor -> served):
    enddate               -> date
    unitnv                -> unit_nav        (单位净值)
    accumulatedunitnv     -> accumulated_nav (单位累计净值)
    unitnvrestored        -> adjusted_nav    (复权单位净值)
    nvdailygrowthrate     -> daily_growth_pct (单位基金净值增长率 %)
"""

from __future__ import annotations

import json
import logging
import math
from datetime import date
from typing import Any

from backtest.loaders.gildata_codes import resolve_vendor_code
from backtest.loaders.gildata_loader import _call_tool, _recall_candidates
from src.agent.tools import BaseTool
from src.config.accessor import get_env_config
from src.config.limits import TOOL_RESULT_LIMIT

logger = logging.getLogger(__name__)

_NAV_TOOL = "NetFundUnitValueReport"

# Keep the most-recent rows when the window exceeds the cap.
_DEFAULT_LIMIT = 2000
_MAX_LIMIT = 5000

# Vendor row fields -> served names. Adjusted NAV keeps its own key (not every
# fund publishes a meaningful 复权因子 — rows may carry nulls).
_ROW_FIELDS = {
    "enddate": "date",
    "unitnv": "unit_nav",
    "accumulatedunitnv": "accumulated_nav",
    "unitnvrestored": "adjusted_nav",
    "nvdailygrowthrate": "daily_growth_pct",
}


def _normalize_fund_code(raw: Any) -> str | None:
    """Normalize a project fund code onto the vendor's ``NNNNNN.OF`` ref.

    Bare 6-digit codes are treated as off-exchange (``.OF``); a ``.OF`` /
    ``.of`` suffix is upper-cased; an explicit exchange suffix (``.SH`` /
    ``.SZ``) means an exchange-listed fund, which the OHLCV loaders already
    serve — the caller is told so instead of getting a wrong series.

    Returns:
        The normalized ``NNNNNN.OF`` code, or ``None`` for non-fund inputs.
    """
    if not isinstance(raw, str):
        return None
    code = raw.strip().upper()
    if not code:
        return None
    if code.endswith(".OF"):
        digits = code[: -len(".OF")]
        return code if len(digits) == 6 and digits.isdigit() else None
    if code.endswith((".SH", ".SZ")):
        return None  # exchange-listed: served by get_market_data, not NAV
    if len(code) == 6 and code.isdigit():
        return code + ".OF"
    return None


def _error(message: str) -> str:
    return json.dumps({"ok": False, "error": message}, ensure_ascii=False)


class GildataFundNavTool(BaseTool):
    """Fetch off-exchange Chinese fund NAV history from Gildata."""

    name = "get_fund_nav"
    description = (
        "Fetch the daily NAV history of Chinese off-exchange funds (场外基金, "
        "e.g. 110022.OF 易方达消费行业): unit NAV (单位净值), accumulated NAV "
        "(累计净值), dividend-adjusted NAV (复权净值) and the daily growth rate, "
        "over an optional date window. Exchange-listed ETF/LOF (510300.SH-style) "
        "are OHLCV instruments — use get_market_data for those. Requires the "
        'commercial GILDATA_TOKEN. Example: {"funds": ["110022"], '
        '"start_date": "2024-01-01"}.'
    )
    parameters = {
        "type": "object",
        "properties": {
            # Deliberately NOT named codes/symbols: those keys enroll a tool
            # in the grounding identity gate (src/agent/grounding/identity.py
            # _SYMBOL_ARGUMENT_KEYS), which demands a search_symbol lock the
            # resolver cannot obtain for off-exchange fund codes. This tool
            # self-resolves identities deterministically (exact ref_code match
            # against the vendor) and echoes fund_name in every result, so the
            # gate adds no safety here — it only made the tool uncallable.
            "funds": {
                "type": "array",
                "items": {"type": "string"},
                "description": ("Fund codes, bare 6-digit ('110022') or '.OF'-suffixed ('110022.OF')."),
            },
            "start_date": {
                "type": "string",
                "description": ("Inclusive window start, YYYY-MM-DD. Omit for the vendor's default history window."),
            },
            "end_date": {
                "type": "string",
                "description": ("Inclusive window end, YYYY-MM-DD. Omit through the latest published NAV."),
            },
            "limit": {
                "type": "integer",
                "description": (
                    f"Maximum number of most-recent rows per fund (1-{_MAX_LIMIT}). Defaults to {_DEFAULT_LIMIT}."
                ),
                "default": _DEFAULT_LIMIT,
            },
        },
        "required": ["funds"],
    }

    @classmethod
    def check_available(cls) -> bool:
        """Available only when ``GILDATA_TOKEN`` is configured."""
        return bool(get_env_config().data.gildata_token)

    def execute(self, **kwargs: Any) -> str:
        """Fetch NAV history for one or more funds and return a JSON envelope.

        Args:
            **kwargs: ``funds`` (required list), optional ``start_date`` /
                ``end_date`` (inclusive YYYY-MM-DD) and ``limit``.

        Returns:
            JSON envelope. On success: ``{"ok": true, "source": "gildata",
            "funds": {"110022.OF": {"ok": true, "fund_name", "rows": [...],
            "count"}}}``; a failing fund carries ``{"ok": false, "error"}``
            and never aborts the rest of the batch.
        """
        if not get_env_config().data.gildata_token:
            return _error("GILDATA_TOKEN is not configured")

        raw_codes = kwargs.get("funds")
        if isinstance(raw_codes, str):
            raw_codes = [raw_codes]
        if not isinstance(raw_codes, list) or not raw_codes:
            return _error("'funds' is required and must be a non-empty list")
        if len(raw_codes) > 50 or any(not isinstance(item, str) or len(item) > 20 for item in raw_codes):
            return _error("Request at most 50 fund codes, each at most 20 characters")
        codes = [_normalize_fund_code(item) for item in raw_codes]
        if all(code is None for code in codes):
            return _error(
                "no valid off-exchange fund codes in request (expected "
                "6-digit or .OF codes; exchange-listed funds are served by "
                "get_market_data)"
            )

        try:
            # Only an omitted limit takes the default; an explicit 0 clamps to 1
            # like any other out-of-range value instead of becoming 2000 rows.
            raw_limit = kwargs.get("limit")
            limit = _DEFAULT_LIMIT if raw_limit is None else int(raw_limit)
        except (TypeError, ValueError):
            limit = _DEFAULT_LIMIT
        limit = max(1, min(_MAX_LIMIT, limit))

        window: dict[str, str] = {}
        for key in ("start_date", "end_date"):
            value = kwargs.get(key)
            if isinstance(value, str) and value.strip():
                try:
                    window[key] = date.fromisoformat(value.strip()).isoformat()
                except ValueError:
                    return _error(f"{key} must be a YYYY-MM-DD date")
        if window.get("start_date", "") > window.get("end_date", "9999-12-31"):
            return _error("start_date must not be after end_date")

        funds: dict[str, Any] = {}
        for raw, code in zip(raw_codes, codes):
            if code is None:
                funds[str(raw)] = {
                    "ok": False,
                    "error": "not an off-exchange fund code",
                }
                continue
            try:
                funds[code] = self._fetch_one(code, window, limit)
            except Exception as exc:  # never abort the batch
                message = str(exc).replace(get_env_config().data.gildata_token, "[redacted]")[:300]
                logger.warning("get_fund_nav failed for %s: %s", code, message)
                funds[code] = {"ok": False, "error": message}

        envelope = {"ok": any(fund.get("ok") for fund in funds.values()), "source": "gildata", "funds": funds}
        while True:
            encoded = json.dumps(envelope, ensure_ascii=False)
            if len(encoded) <= TOOL_RESULT_LIMIT:
                return encoded
            largest = max(funds.values(), key=lambda fund: len(fund.get("rows", [])))
            rows = largest.get("rows", [])
            if len(rows) <= 1:
                return _error(
                    "NAV response metadata or one row exceeds the tool result limit. Request fewer funds and a narrower date window."
                )
            keep = max(1, min(len(rows) - 1, int(len(rows) * TOOL_RESULT_LIMIT / len(encoded))))
            largest["rows"] = rows[-keep:]
            largest["count"] = keep
            largest["truncated"] = True
            largest["recovery"] = "Narrow the date window to retrieve omitted NAV rows."

    def _fetch_one(self, code: str, window: dict[str, str], limit: int) -> dict[str, Any]:
        """Resolve one fund's 内码 and fetch its NAV rows."""
        vendor_code = resolve_vendor_code("otc_fund", code, _recall_candidates)
        if vendor_code is None:
            return {"ok": False, "error": f"fund {code} not found"}

        arguments: dict[str, Any] = {
            "fundObject": [vendor_code],
            "statisticalPeriod": 0,  # 0-日
        }
        if window.get("start_date"):
            arguments["beginDate"] = window["start_date"]
        if window.get("end_date"):
            arguments["endDate"] = window["end_date"]

        entry = _call_tool(_NAV_TOOL, arguments)
        rows = entry.get("rows") if isinstance(entry, dict) else None
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError("gildata NAV response has an unsupported rows shape")

        served: list[dict[str, Any]] = []
        fund_name = ""
        for row in rows:
            if not isinstance(row, dict) or not row.get("enddate"):
                continue
            if not fund_name and row.get("fundname"):
                fund_name = str(row["fundname"])
            day = str(row["enddate"])[:10]
            date.fromisoformat(day)
            if day < window.get("start_date", "") or day > window.get("end_date", "9999-12-31"):
                continue
            item = {"date": day}
            for vendor_field, served_name in _ROW_FIELDS.items():
                if served_name == "date":
                    continue
                value = row.get(vendor_field)
                if value is not None:
                    if isinstance(value, bool):
                        raise ValueError("NAV values must be finite numbers")
                    value = float(value)
                    if not math.isfinite(value):
                        raise ValueError("NAV values must be finite numbers")
                item[served_name] = value
            served.append(item)
        # Vendor rows arrive newest-first; serve ascending like every other
        # dated series in the project, keeping the most-recent `limit` rows.
        available_count = len(served)
        served = sorted(served, key=lambda r: str(r["date"]))[-limit:]

        if not served:
            return {"ok": False, "error": "no NAV rows in the requested window"}
        return {
            "ok": True,
            "fund_name": fund_name,
            "rows": served,
            "count": len(served),
            "returned_by_vendor": available_count,
            "truncated": available_count > len(served),
        }
