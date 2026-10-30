"""Optional Gildata stock candidates for the existing symbol resolver."""
import re

from backtest.loaders.gildata_loader import _call_tool_results
from src.config.accessor import get_env_config


def search_candidates(query: str, limit: int) -> tuple[list[dict], str | None]:
    if get_env_config().data.gildata_token.strip() in {"", "your-gildata-token"}:
        return [], None
    domains = {"StockDailyQuote": "a", "HKStockDailyQuotes": "hk", "USStockDailyQuotes": "us"}
    keyword = query[:-3] if query.upper().endswith(".US") else query
    try:
        results = _call_tool_results("ParamCandidateRecall", {"recall_list": [
            {"api_name": api, "param_name": "stockObject", "keyword": keyword, "top_k": limit}
            for api in domains
        ]})
        candidates = []
        for result in results:
            market = domains.get(result.get("api_name"))
            for row in result.get("candidates", []):
                ref = str(row.get("ref_code") or "").upper()
                if market == "a" and re.fullmatch(r"\d{6}\.(?:SH|SZ|BJ)", ref):
                    symbol = ref
                elif market == "hk" and re.fullmatch(r"\d{3,5}\.HK", ref):
                    symbol = ref.split(".")[0].zfill(5) + ".HK"
                elif market == "us" and re.fullmatch(r"[A-Z][A-Z0-9.\-]*\.[A-Z]+", ref):
                    symbol = ref.rsplit(".", 1)[0] + ".US"
                else:
                    continue
                candidates.append({"symbol": symbol, "name": row.get("caption"), "market": market,
                                   "type": "equity", "source": "gildata",
                                   "vendor_code": row.get("code"), "vendor_ref_code": ref})
        # Exact matches take precedence over fuzzy recall, retaining every venue.
        exact = [c for c in candidates if query.casefold() in {
            str(c["name"]).casefold(), c["symbol"].casefold(), c["symbol"].split(".")[0].casefold()}]
        return (exact or candidates), "ok"
    except Exception:
        # Do not expose authenticated URLs, response bodies or credentials.
        return [], "gildata recall failed; check service access and quota"
