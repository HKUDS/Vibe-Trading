"""Optional single-security, cross-domain Gildata queries."""

from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any

from src.agent.tools import BaseTool
from src.config.accessor import get_env_config
from src.tools.gildata_srv import call_srv_tool_results

_PLACEHOLDER_TOKENS = {"", "your-gildata-token"}
_QUOTE_LABELS = {"开盘价": "open", "今开盘": "open", "最高价": "high", "最低价": "low",
                 "收盘价": "close", "最新价": "price", "前收盘": "prev_close",
                 "前收盘价": "prev_close", "昨收": "prev_close"}
_AMOUNT_SCALES = {"元": 1, "万元": 10_000, "亿元": 100_000_000}


def _numeric(value: Any) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        number = Decimal(str(value).strip())
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


def _number(value: Decimal) -> int | float:
    return int(value) if value == value.to_integral_value() else float(value)


def _normalize_table(table: dict[str, Any], table_index: int) -> dict[str, Any]:
    """Give each observation one numeric path, using explicit vendor units only."""
    if not isinstance(table, dict):
        raise ValueError("Unsupported table")
    columns, rows = table.get("columns"), table.get("rows")
    if (not isinstance(columns, dict) or not isinstance(rows, list)
            or any(not isinstance(k, str) or not isinstance(v, str) for k, v in columns.items())
            or any(not isinstance(row, dict) for row in rows)):
        raise ValueError("Unsupported table")
    renames = {}
    for field, label in columns.items():
        base = re.sub(r"[（(].*[）)]", "", label).strip()
        canonical = _QUOTE_LABELS.get(base)
        if label in {"交易日", "交易日期"}:
            canonical = "trade_date"
        elif label == "交易时间":
            canonical = "timestamp"
        if canonical and canonical != field:
            renames[field] = canonical
    names = [renames.get(field, field) for field in columns]
    if len(names) != len(set(names)) or (renames and "vendor_fields" in table):
        raise ValueError("Colliding fields")
    normalized = []
    for row_index, row in enumerate(rows):
        if len({renames.get(field, field) for field in row}) != len(row):
            raise ValueError("Colliding fields")
        converted = {}
        metric = next((row[field] for field, label in columns.items()
                       if label.endswith("科目名称") and isinstance(row.get(field), str)), None)
        for field, value in row.items():
            label = columns.get(field, "")
            target = renames.get(field, field)
            leaf = None
            if re.search(r"代码|内码", label):
                converted[target] = str(value) if value is not None else None
                continue
            number = _numeric(value)
            suffix = re.search(r"[（(]\s*(亿元|万元|元)\s*[）)]", label)
            unit = suffix.group(1) if suffix else None
            if unit is None and re.search(r"(?:金额|数额|总额|投入)$", label):
                unit = row.get("unit")
            if number is not None and unit in _AMOUNT_SCALES:
                amount = _number(number * _AMOUNT_SCALES[unit])
                if target in _QUOTE_LABELS.values():
                    value = amount
                else:
                    value = {"amount": amount, "unit": "元", "source_unit": unit}
                    display_unit = "亿元" if abs(amount) >= 100_000_000 else "万元" if abs(amount) >= 10_000 else "元"
                    display = Decimal(str(amount)) / _AMOUNT_SCALES[display_unit]
                    display = f"{display:f}{display_unit}"
                    value["display"] = display
                    leaf = "amount"
                    if isinstance(row.get("currency"), str):
                        value["currency"] = row["currency"]
            elif re.search(r"[%％]", label) or unit in {"%", "％"}:
                percent = _numeric(value.strip()[:-1]) if isinstance(value, str) and value.strip().endswith(("%", "％")) else number
                if percent is not None:
                    value = {"percent": _number(percent), "unit": "%"}
                    display, leaf = f"{percent:f}%", "percent"
            if leaf is not None:
                note = f"{row.get('gilcode') or ''} {metric or label}".strip()
                note = note.replace("|", " ").replace("\n", " ").replace("\r", " ")
                value["citation"] = (f"{display} | observed | {note} | "
                                     f"data.tables[{table_index}].rows[{row_index}].{target}.{leaf}")
            converted[target] = value
        normalized.append(converted)
    return {**table, "columns": dict(zip(names, columns.values())), "rows": normalized,
            **({"vendor_fields": {new: old for old, new in renames.items()}} if renames else {})}


class GildataFinQueryTool(BaseTool):
    """Query a known security across market, financial and operating data."""

    name = "gildata_fin_query"
    description = (
        "Gildata/聚源 FinQuery: query one security's market, financial and operating "
        "indicators together using a full natural-language question. Requires GILDATA_TOKEN. "
        "Results retain actual periods, disclosure/trading dates and quote adjustment. "
        "Monetary amount leaves use base currency units; percent leaves are percentage points. "
        "Latest-available substitutions are not point-in-time backtest observations."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Full question including entity, indicators and periods; may combine prices, financials and operating metrics."},
        },
        "required": ["query"],
    }
    repeatable = True

    @classmethod
    def check_available(cls) -> bool:
        return get_env_config().data.gildata_token.strip() not in _PLACEHOLDER_TOKENS

    def execute(self, **kwargs: Any) -> str:
        if not self.check_available():
            return json.dumps({"ok": False, "error_type": "not_configured", "error": "GILDATA_TOKEN is not configured"})
        query = kwargs.get("query")
        if not isinstance(query, str) or not 1 <= len(query.strip()) <= 4000:
            return json.dumps({"ok": False, "error_type": "invalid_query",
                               "error": "query must contain 1 to 4000 characters"})
        try:
            results = call_srv_tool_results("FinQuery", query.strip())
        except Exception:
            # Transport exceptions may include credentials or response bodies.
            return json.dumps({"ok": False, "source": "gildata", "error_type": "service_error",
                               "error": "FinQuery request failed. Check service access and query scope."})
        try:
            tables = [_normalize_table(table, index) for index, table in enumerate(results)]
            return json.dumps({"ok": True, "source": "gildata", "vendor_tool": "FinQuery",
                               "query": query.strip(), "data": {"tables": tables},
                               "has_data": any(table["rows"] for table in tables)},
                              ensure_ascii=False, allow_nan=False, indent=2)
        except (ValueError, TypeError, OverflowError):
            return json.dumps({"ok": False, "source": "gildata", "error_type": "unsupported_data",
                               "error": "Unsupported FinQuery data; no alternate source was called."})
