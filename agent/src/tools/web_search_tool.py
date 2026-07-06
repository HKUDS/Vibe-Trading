"""Web search tool: free multi-engine search via ddgs (no API key).

`ddgs` (the successor to `duckduckgo_search`) is a metasearch aggregator: it can
query DuckDuckGo, Google, Bing, Brave, Mojeek, Yahoo and more behind one API,
none of which need an API key.  DuckDuckGo alone rate-limits aggressively from
cloud / shared IPs (issue #231: ``web_search`` showed ❌ while the run still
succeeded via ``read_url``), so we pass an explicit ordered backend list and let
ddgs fall through a throttled engine to the next one, with a short retry/backoff
on top for transient failures.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

from src.agent.tools import BaseTool
from src.security.scanner import with_security_warnings

logger = logging.getLogger(__name__)

# Free, no-key engines aggregated by ddgs, tried in order. A single engine
# returning nothing or being rate-limited no longer fails the whole search.
# Override (or pin to one engine) via VIBE_TRADING_SEARCH_BACKENDS.
_DEFAULT_BACKENDS = "duckduckgo, google, bing, brave, mojeek, yahoo"
_MAX_ATTEMPTS = 3
_BACKOFF_BASE_SECONDS = 0.8


def _aliyun_iqs_search(query: str, max_results: int = 5) -> list[dict] | None:
    """Search via Alibaba Cloud IQS (cloud-iqs.aliyuncs.com) — official API,
    structured (title/link/snippet/hostname), CN-direct (~1s), supports a finance
    category and rerank. Requires ``ALIYUN_IQS_API_KEY``; returns None when unset.
    Pure stdlib.
    """
    key = os.getenv("ALIYUN_IQS_API_KEY", "").strip()
    if not key:
        return None
    import json as _json
    import urllib.request

    body = _json.dumps({
        "query": query,
        "engineType": "Generic",
        "contents": {"mainText": False, "summary": False, "rerankScore": True},
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://cloud-iqs.aliyuncs.com/search/unified",
        data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    resp = urllib.request.urlopen(req, timeout=10)
    data = _json.loads(resp.read().decode("utf-8"))
    out: list[dict] = []
    for item in data.get("pageItems", [])[:max_results]:
        out.append({
            "title": item.get("title", ""),
            "href": item.get("link", ""),
            "body": item.get("snippet", ""),
        })
    return out


def _bing_cn_search(query: str, max_results: int = 5) -> list[dict]:
    """Scrape cn.bing.com organic results — no API key, works where ddgs engines are blocked.

    Used as a fallback when every ddgs backend times out (common behind restricted
    egress, e.g. CN hosts without VPN where duckduckgo/google/brave are unreachable
    but cn.bing.com is). Returns ddgs-shaped dicts (title/href/body) so the caller
    can treat the two paths uniformly. Pure stdlib — no new dependency.
    """
    import re as _re
    import urllib.parse
    import urllib.request

    url = "https://cn.bing.com/search?" + urllib.parse.urlencode({"q": query})
    req = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    )
    html = urllib.request.urlopen(req, timeout=10).read().decode("utf-8", "ignore")
    blocks = _re.findall(r'<li class="b_algo"[^>]*>(.*?)</li>', html, _re.S)
    out: list[dict] = []
    for b in blocks[:max_results]:
        h2 = _re.search(r"<h2[^>]*>(.*?)</h2>", b, _re.S)
        if not h2:
            continue
        a = _re.search(r'<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', h2.group(1), _re.S)
        if not a:
            continue
        title = _re.sub(r"<[^>]+>", "", a.group(2)).strip()
        href = a.group(1)
        snip_m = _re.search(r"<p[^>]*>(.*?)</p>", b, _re.S)
        snippet = _re.sub(r"<[^>]+>", "", snip_m.group(1)).strip() if snip_m else ""
        if title and href.startswith("http"):
            out.append({"title": title, "href": href, "body": snippet[:180]})
    return out


def _sogou_search(query: str, max_results: int = 5) -> list[dict]:
    """Scrape sogou.com results — better CN financial query quality than cn.bing.

    Sogou's organic titles hit financial queries precisely (e.g. '茅台 2024 营收
    1708.99 亿') where cn.bing drifts to regional/tourism results for natural-language
    queries without a ticker. URLs are sogou jump links (/link?url=...) absolute-ized
    so a downstream read_url can follow them. Snippet is left empty because the title
    already carries the key figure. Pure stdlib.
    """
    import re as _re
    import urllib.parse
    import urllib.request

    url = "https://www.sogou.com/web?" + urllib.parse.urlencode({"query": query})
    req = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    )
    html = urllib.request.urlopen(req, timeout=10).read().decode("utf-8", "ignore")
    blocks = _re.split(r'<div class="vrwrap"', html)[1:]
    out: list[dict] = []
    for b in blocks[:max_results]:
        tm = _re.search(r'<a[^>]*target="_blank"[^>]*>(.*?)</a>', b, _re.S)
        hm = _re.search(r'<a[^>]*href="([^"]*)"', b)
        title = _re.sub(r"<[^>]+>", "", tm.group(1)).strip() if tm else ""
        href = hm.group(1) if hm else ""
        if href.startswith("/"):
            href = "https://www.sogou.com" + href
        if title and href:
            out.append({"title": title, "href": href, "body": ""})
    return out


class WebSearchTool(BaseTool):
    """Search the web via ddgs across several free engines and return top results."""

    name = "web_search"

    @classmethod
    def check_available(cls) -> bool:
        """Available only if ddgs or duckduckgo_search is installed."""
        try:
            try:
                import ddgs  # noqa: F401
            except ImportError:
                import duckduckgo_search  # noqa: F401
            return True
        except ImportError:
            return False
    description = (
        "Search the web across free engines (DuckDuckGo, Google, Bing, Brave, "
        "Mojeek, Yahoo). Returns top results with title, URL, and snippet. Use "
        "this to find information, news, or URLs before reading them with read_url."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results to return (default 5, max 10)",
                "default": 5,
            },
        },
        "required": ["query"],
    }
    repeatable = True

    def execute(self, **kwargs: Any) -> str:
        """Run a web search across free engines with retry and backend fallback.

        Args:
            **kwargs: Must include query; optionally max_results.

        Returns:
            JSON envelope with status, query, the backend list used, and results
            (or an actionable error message on persistent failure).
        """
        query = kwargs["query"]
        max_results = min(int(kwargs.get("max_results", 5)), 10)
        backends = os.getenv("VIBE_TRADING_SEARCH_BACKENDS", _DEFAULT_BACKENDS).strip() or "auto"

        # Fast path: Alibaba Cloud IQS if configured (official API, CN-direct,
        # ~1s, structured + snippet, best quality). Skip ddgs entirely when IQS
        # is available — ddgs engines are unreachable from typical CN egress.
        if os.getenv("ALIYUN_IQS_API_KEY", "").strip():
            try:
                raw = _aliyun_iqs_search(query, max_results=max_results)
                if raw:
                    payload = {
                        "status": "ok",
                        "query": query,
                        "backends": "aliyun_iqs",
                        "results": [
                            {"title": r.get("title", ""), "url": r.get("href", ""), "snippet": r.get("body", "")}
                            for r in raw
                        ],
                    }
                    payload = with_security_warnings(
                        payload, fields=("results.*.title", "results.*.snippet")
                    )
                    return json.dumps(payload, ensure_ascii=False)
                logger.warning("aliyun_iqs returned no results, falling through to ddgs")
            except Exception as exc:  # noqa: BLE001
                logger.warning("aliyun_iqs failed: %s, falling through to ddgs", exc)

        try:
            from ddgs import DDGS

            supports_backend = True
        except ImportError:
            try:
                from duckduckgo_search import DDGS  # legacy package, no engine selection
            except ImportError:
                return json.dumps(
                    {
                        "status": "error",
                        "error": "Web search package not installed. Run: pip install ddgs",
                    },
                    ensure_ascii=False,
                )
            supports_backend = False

        last_error: Exception | None = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                with DDGS() as client:
                    if supports_backend:
                        raw = list(client.text(query, max_results=max_results, backend=backends))
                    else:
                        raw = list(client.text(query, max_results=max_results))
            except TypeError:
                # Older ddgs/duckduckgo_search without the backend kwarg.
                supports_backend = False
                continue
            except Exception as exc:  # noqa: BLE001 — surface a clean error to the agent
                last_error = exc
                # "No results found" is a definitive empty answer, not a transient
                # failure — retrying or switching engines won't change it.
                if "no results" in str(exc).lower():
                    return json.dumps(
                        {
                            "status": "ok",
                            "query": query,
                            "backends": backends if supports_backend else "duckduckgo",
                            "results": [],
                            "note": "No results found for this query across the search engines.",
                        },
                        ensure_ascii=False,
                    )
                logger.warning("web_search attempt %d/%d failed: %s", attempt, _MAX_ATTEMPTS, exc)
                # Network/egress errors (timeout, connection refused, unreachable)
                # won't recover on retry — stop retrying ddgs and fall through to
                # the cn.bing fallback instead of wasting ~20-30s on more timeouts.
                err_msg = str(exc).lower()
                if any(s in err_msg for s in ("timeout", "timed out", "unreachable", "connection", "max retries")):
                    break
                if attempt < _MAX_ATTEMPTS:
                    time.sleep(_BACKOFF_BASE_SECONDS * attempt)
                continue

            results = [
                {
                    "title": r.get("title", ""),
                    "url": r.get("href", ""),
                    "snippet": r.get("body", ""),
                }
                for r in raw
            ]
            payload = {
                "status": "ok",
                "query": query,
                "backends": backends if supports_backend else "duckduckgo",
                "results": results,
            }
            payload = with_security_warnings(
                payload,
                fields=("results.*.title", "results.*.snippet"),
            )
            return json.dumps(payload, ensure_ascii=False)

        # Fallback chain when every ddgs backend is blocked (common behind
        # restricted egress, e.g. CN hosts without VPN): sogou first (best CN
        # query quality), then cn.bing (real URLs, broader). Toggle via
        # VIBE_TRADING_SEARCH_BING_FALLBACK (default on).
        fb_err = "disabled"
        if os.getenv("VIBE_TRADING_SEARCH_BING_FALLBACK", "1").strip().lower() in ("1", "true", "yes"):
            for fb_name, fb_fn in (("sogou", _sogou_search), ("bing_cn", _bing_cn_search)):
                try:
                    raw = fb_fn(query, max_results=max_results)
                    if raw:
                        payload = {
                            "status": "ok",
                            "query": query,
                            "backends": f"{fb_name}_fallback",
                            "results": [
                                {"title": r.get("title", ""), "url": r.get("href", ""), "snippet": r.get("body", "")}
                                for r in raw
                            ],
                        }
                        payload = with_security_warnings(
                            payload, fields=("results.*.title", "results.*.snippet")
                        )
                        return json.dumps(payload, ensure_ascii=False)
                    fb_err = f"{fb_name} returned no results"
                except Exception as exc:  # noqa: BLE001
                    logger.warning("%s fallback failed: %s", fb_name, exc)
                    fb_err = f"{fb_name}: {exc}"
                    continue
        return json.dumps(
            {
                "status": "error",
                "error": (
                    f"Web search failed after {_MAX_ATTEMPTS} attempts "
                    f"(backends: {backends if supports_backend else 'duckduckgo'}): {last_error}. "
                    f"CN fallbacks (sogou, bing_cn): {fb_err}. "
                    "Retry shortly, set VIBE_TRADING_SEARCH_BACKENDS to a different engine list, "
                    "set VIBE_TRADING_SEARCH_BING_FALLBACK=0 to disable CN fallback, or read a "
                    "known URL directly with read_url."
                ),
            },
            ensure_ascii=False,
        )
