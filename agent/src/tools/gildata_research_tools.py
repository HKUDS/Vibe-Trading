"""Read-only tools: Gildata (恒生聚源) NL research over the srv-tool endpoint.

Three agent-facing wrappers around the vendor's 标准版 natural-language tools,
picked for value the project does not already cover:

* ``get_cn_macro_series`` — ``MacroIndustryData``: China macro / regional /
  industry EDB time series (the project's macro coverage is FRED, i.e.
  US/global only).
* ``get_cn_announcements`` — ``AnnouncementData``: A-share / HK / fund
  announcement retrieval with highlighted excerpts (the existing
  ``get_sec_filings`` covers SEC filings only).
* ``search_broker_reports`` — ``FinancialResearchReport``: broker research
  search over the Juyuan report library (deeper metadata than the existing
  eastmoney-backed ``get_research_reports``; both coexist).

Separate modules wrap FinQuery and SmartStockSelection. Existing news and
screening sources remain available alongside them.

The agent authors the natural-language ``query``; the server routes it. The
routed ``api_names`` are echoed in every envelope so a mis-routed question is
visible and the agent can re-ask. Rows are the vendor's structured dicts,
capped to ``limit`` in the vendor's returned order.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from src.agent.tools import BaseTool
from src.config.accessor import get_env_config
from src.config.limits import TOOL_RESULT_LIMIT
from src.tools._result_paging import fit_records
from src.tools.gildata_srv import call_srv_tool

logger = logging.getLogger(__name__)

_DEFAULT_LIMIT = 50
_MAX_LIMIT = 200


def _error(message: str) -> str:
    return json.dumps({"ok": False, "error": message}, ensure_ascii=False)


def _envelope(vendor_tool: str, query: str, payload: dict[str, Any], limit: int) -> str:
    """Build the shared success envelope from a call_srv_tool payload."""
    rows = payload.get("rows") or []

    def build(page, meta):
        return {
            "ok": True,
            "source": "gildata",
            "vendor_tool": vendor_tool,
            "query": query,
            "api_names": payload.get("api_names") or [],
            "rows": page,
            "count": len(page),
            "returned_by_vendor": len(rows),
            "truncated": len(page) < len(rows),
            "recovery": "Narrow the query date range or topic to retrieve omitted rows."
            if len(page) < len(rows)
            else None,
        }

    result = fit_records(rows, 0, build, max_records=limit)
    if len(result) > TOOL_RESULT_LIMIT:
        return _error(
            "A single vendor record exceeds the tool result limit. Narrow the query or request a shorter excerpt."
        )
    return result


def _clean_query(kwargs: Any) -> str | None:
    query = kwargs.get("query")
    if not isinstance(query, str) or not query.strip() or len(query) > 4000:
        return None
    return query.strip()


def _clean_limit(kwargs: Any) -> int:
    try:
        limit = int(kwargs.get("limit", _DEFAULT_LIMIT) or _DEFAULT_LIMIT)
    except (TypeError, ValueError):
        limit = _DEFAULT_LIMIT
    return max(1, min(_MAX_LIMIT, limit))


class _GildataSrvToolBase(BaseTool):
    """Shared plumbing for the srv-tool wrappers."""

    vendor_tool: str = ""

    @classmethod
    def check_available(cls) -> bool:
        """Available only when ``GILDATA_TOKEN`` is configured."""
        return bool(get_env_config().data.gildata_token)

    def execute(self, **kwargs: Any) -> str:
        if not get_env_config().data.gildata_token:
            return _error("GILDATA_TOKEN is not configured")
        query = _clean_query(kwargs)
        if query is None:
            return _error("'query' must contain 1 to 4000 characters")
        limit = _clean_limit(kwargs)
        try:
            payload = call_srv_tool(self.vendor_tool, query)
        except Exception as exc:
            message = str(exc).replace(get_env_config().data.gildata_token, "[redacted]")[:300]
            logger.warning("%s failed: %s", self.name, message)
            return _error(message)
        return _envelope(self.vendor_tool, query, payload, limit)


class GetCnMacroSeriesTool(_GildataSrvToolBase):
    """China macro / regional / industry economic time series (EDB)."""

    name = "get_cn_macro_series"
    vendor_tool = "MacroIndustryData"
    description = (
        "Fetch China macro / regional / industry economic indicator series "
        "(宏观 EDB): GDP, CPI, PPI, PMI, money supply, interest rates, "
        "imports/exports, plus 31 industry series (prices, output, inventory) "
        "and regional data — as dated observations with unit and frequency. "
        'Ask in natural language, e.g. {"query": "2023年至2024年中国季度'
        'GDP同比增速和CPI同比"}. Complements get_macro_series (FRED, '
        "US/global). Requires GILDATA_TOKEN."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "Natural-language indicator request naming the indicators, "
                    "geography and date range, e.g. '2024年中国月度CPI同比' or "
                    "'近三年半导体行业销售额'."
                ),
            },
            "limit": {
                "type": "integer",
                "description": f"Maximum rows returned (1-{_MAX_LIMIT}). Defaults to {_DEFAULT_LIMIT}.",
                "default": _DEFAULT_LIMIT,
            },
        },
        "required": ["query"],
    }


class GetCnAnnouncementsTool(_GildataSrvToolBase):
    """A-share / HK / fund announcement retrieval with highlighted excerpts."""

    name = "get_cn_announcements"
    vendor_tool = "AnnouncementData"
    description = (
        "Search Chinese-market company announcements (公告): A-share, HK and "
        "fund filings — annual reports, earnings, dividends, buybacks, "
        "restructuring, regulatory inquiry letters — with title, publish date "
        "and a highlighted excerpt of the relevant passage. Ask in natural "
        'language, e.g. {"query": "贵州茅台2024年年度分红公告"}. For US '
        "filings use get_sec_filings. Requires GILDATA_TOKEN."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "Natural-language announcement request naming the company "
                    "/ fund, announcement type and time window, e.g. '宁德时代"
                    "最近三个月的回购公告'."
                ),
            },
            "limit": {
                "type": "integer",
                "description": f"Maximum rows returned (1-{_MAX_LIMIT}). Defaults to {_DEFAULT_LIMIT}.",
                "default": _DEFAULT_LIMIT,
            },
        },
        "required": ["query"],
    }


class SearchBrokerReportsTool(_GildataSrvToolBase):
    """Broker research search over the Juyuan report library."""

    name = "search_broker_reports"
    vendor_tool = "FinancialResearchReport"
    description = (
        "Search sell-side broker research (券商研报) over the Juyuan library: "
        "report title, broker, analyst, industry, rating and a highlighted "
        "excerpt of the argument — for company deep-dives, industry views and "
        'macro commentary. Ask in natural language, e.g. {"query": "最近三'
        '个月白酒行业的券商研报观点"}. Coexists with get_research_reports '
        "(eastmoney-backed). Requires GILDATA_TOKEN."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "Natural-language research request naming the company / "
                    "industry / theme and time window, e.g. '比亚迪2024年报"
                    "点评'."
                ),
            },
            "limit": {
                "type": "integer",
                "description": f"Maximum rows returned (1-{_MAX_LIMIT}). Defaults to {_DEFAULT_LIMIT}.",
                "default": _DEFAULT_LIMIT,
            },
        },
        "required": ["query"],
    }
