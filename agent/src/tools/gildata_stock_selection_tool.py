"""Optional Gildata screening with cross-period metrics in the same request."""
from __future__ import annotations

import json
from typing import Any

from src.agent.tools import BaseTool
from src.config.accessor import get_env_config
from src.tools.gildata_fin_query_tool import _normalize_table
from src.tools.gildata_srv import call_srv_tool_results


class GildataStockSelectionTool(BaseTool):
    """Screen and enrich vendor-selected stocks without client-side query splitting."""

    name = "gildata_stock_selection"
    description = (
        "聚源智能选股：一次查询完成指定日期的股票筛选/TopN排名，并返回所选股票跨报告期的财务金额、估值或行情指标。 "
        "Example: 沪深300权重最高的10只成分股及2023、2024年全年营业收入. "
        "Use gildata_fin_query for attribute/history queries without screening. "
        "Requires GILDATA_TOKEN; read-only."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "One complete question: universe, screening/ranking criteria and date, plus all requested indicators and report periods. Specify monetary units for amounts; distinguish amounts from growth rates."},
            "topk": {"type": "integer", "description": "Optional result count; positive integer, or -1 only when all results are explicitly requested."},
        },
        "required": ["query"],
    }
    repeatable = True

    @classmethod
    def check_available(cls) -> bool:
        return get_env_config().data.gildata_token.strip() not in {"", "your-gildata-token"}

    def execute(self, **kwargs: Any) -> str:
        if not self.check_available():
            return json.dumps({"ok": False, "error_type": "not_configured", "error": "GILDATA_TOKEN is not configured"})
        query, topk = kwargs.get("query"), kwargs.get("topk")
        if not isinstance(query, str) or not 1 <= len(query.strip()) <= 4000:
            return json.dumps({"ok": False, "error_type": "invalid_query", "error": "query must contain 1 to 4000 characters"})
        if topk is not None and (type(topk) is not int or topk == 0 or topk < -1):
            return json.dumps({"ok": False, "error_type": "invalid_topk", "error": "topk must be a positive integer or -1"})
        try:
            results = call_srv_tool_results("SmartStockSelection", query.strip(), **({"topk": topk} if topk is not None else {}))
        except Exception:
            return json.dumps({"ok": False, "source": "gildata", "error_type": "service_error",
                               "error": "Stock selection request failed. Check service access and query scope."})
        try:
            tables = [_normalize_table(table, index) for index, table in enumerate(results)]
            return json.dumps({"ok": True, "source": "gildata", "vendor_tool": "SmartStockSelection",
                               "query": query.strip(), "data": {"tables": tables},
                               "has_data": any(table["rows"] for table in tables)},
                              ensure_ascii=False, allow_nan=False, indent=2)
        except (ValueError, TypeError, OverflowError):
            return json.dumps({"ok": False, "source": "gildata", "error_type": "unsupported_data",
                               "error": "Unsupported stock selection data; no alternate source was called."})
