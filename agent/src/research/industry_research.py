"""Industry research service.

The service keeps provider-specific fetching, report normalization, AI
generation, and the local cache behind one small API boundary.  It deliberately
degrades to deterministic evidence cards when an optional provider or the LLM
is unavailable; the UI must never turn missing data into fabricated numbers.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections.abc import Iterator
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from src.a_share_data import eastmoney_industry_reports
from src.config.paths import get_runtime_root

logger = logging.getLogger(__name__)

_REPORT_SEARCH_URL = "https://openapi.iwencai.com/v1/comprehensive/search"
_REPORT_SEARCH_SKILL_VERSION = "2.0.0"
_CACHE_HOURS = 24
_MAX_REPORTS = 100
_MAX_COMPANIES = 10
_INDUSTRY_REFRESH_SECONDS = 900

_INDUSTRY_SYNONYMS: dict[str, tuple[str, ...]] = {
    "humanoid-robot": ("机器人", "人形", "具身智能", "减速器", "谐波", "丝杠", "力传感器", "灵巧手", "机器人产业链"),
}

_HUMANOID_SECTIONS = (
    ("harmonic", "谐波减速器", "谐波减速器的产业链位置、核心标的与行情跟踪。"),
    ("planetary", "行星滚珠丝杠", "行星滚珠丝杠的供应格局、技术进展与公司跟踪。"),
    ("frameless-torque", "无框力矩电机", "无框力矩电机的产品、应用场景与相关公司。"),
    ("six-axis-force", "六维力传感器", "六维力传感器的技术路线、渗透率与产业链。"),
    ("dexterous-hand", "灵巧手", "灵巧手的结构方案、关键零部件与量产进展。"),
    ("ball-screw", "滚珠丝杠", "滚珠丝杠的市场空间、竞争格局与跟踪指标。"),
)

_INDUSTRIES = {
    "humanoid-robot": {
        "id": "humanoid-robot",
        "name": "人形机器人",
        "description": "围绕核心零部件和产业链环节建立跟踪模板。",
        "demand": "本体机器人及工业、服务和具身智能应用场景。",
        "segments": [name for _, name, _ in _HUMANOID_SECTIONS],
        "upstream": ["稀土永磁", "精密磨床", "特种材料"],
        "sections": [
            {"id": "overview", "label": "总览", "description": "人形机器人产业链总览、核心公司与重要事件。"},
            {"id": "reports", "label": "研报库", "description": "人形机器人产业链行业研报。"},
            *({"id": sid, "label": label, "description": desc} for sid, label, desc in _HUMANOID_SECTIONS),
        ],
    },
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return (value or _now()).isoformat()


def _local_date() -> str:
    """Return the operator's local calendar date for daily refresh decisions."""
    return datetime.now().astimezone().date().isoformat()


def _safe_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _safe_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_json(item) for item in value]
    if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
        return None
    return value


def _report_key(report: dict[str, Any]) -> str:
    url = str(report.get("source_url") or report.get("pdf_url") or "").strip()
    if url:
        return f"url:{url}"
    raw = "|".join(str(report.get(field) or "").strip().lower() for field in ("title", "institution", "publish_time"))
    return "text:" + hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _date_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            timestamp = float(value)
            # iWenCai may return Unix seconds while some A-share providers
            # return Unix milliseconds.  Treat the magnitude as the unit so
            # valid reports do not appear as dates in January 1970.
            if timestamp > 100_000_000_000:
                timestamp /= 1000
            return datetime.fromtimestamp(timestamp, timezone.utc).date().isoformat()
        except (ValueError, OSError, OverflowError):
            return None
    text = str(value).strip()
    if text.isdigit():
        try:
            timestamp = float(text)
            if timestamp > 100_000_000_000:
                timestamp /= 1000
            return datetime.fromtimestamp(timestamp, timezone.utc).date().isoformat()
        except (ValueError, OSError, OverflowError):
            return None
    return text[:10] if text else None


def _first(record: dict[str, Any], *names: str) -> Any:
    for name in names:
        value = record.get(name)
        if value not in (None, "", "-"):
            return value
    return None


def _normalize_report(record: dict[str, Any], industry_id: str, source: str) -> dict[str, Any] | None:
    title = str(_first(record, "title", "report_title", "name") or "").strip()
    if not title:
        return None
    target_price = _first(record, "target_price", "targetPrice", "target_price_text")
    try:
        target_price = float(str(target_price).replace(",", "")) if target_price is not None else None
    except (TypeError, ValueError):
        target_price = None
    company_code = _first(record, "company_code", "stockCode", "stock_code", "code", "secCode", "ticker")
    return {
        "report_id": str(_first(record, "report_id", "infoCode", "uid", "id") or _report_key({"title": title})),
        "title": title,
        "summary": _first(record, "summary", "abstr", "abstract", "content"),
        "institution": _first(record, "institution", "orgSName", "orgName", "inst_csname", "source"),
        "author": _first(record, "author", "analyst", "authors"),
        "publish_time": _date_text(_first(record, "publish_time", "publishDate", "trade_date", "date")),
        "rating": _first(record, "rating", "ratingName", "institution_rating"),
        "target_price": target_price,
        "source": source,
        "sources": [source],
        "company_code": company_code,
        "source_url": _first(record, "url", "source_url", "link", "report_url"),
        "pdf_url": _first(record, "pdf_url", "pdf", "download_url"),
        "industry_id": industry_id,
        "section_id": _first(record, "section_id", "segment"),
    }


def _walk_report_records(value: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if any(key in value for key in ("title", "report_title")):
            found.append(value)
        for child in value.values():
            found.extend(_walk_report_records(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_walk_report_records(child))
    return found


def _industry_slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return f"sector-{slug or hashlib.sha1(name.encode('utf-8')).hexdigest()[:10]}"


class ReportSearchClient:
    """Optional report-search client following the bundled gateway contract."""

    def __init__(self) -> None:
        self.last_raw_response: dict[str, Any] | None = None

    def search(self, query: str, size: int = 20) -> tuple[list[dict[str, Any]], str]:
        api_key = os.getenv("IWENCAI_API_KEY", "").strip()
        if not api_key:
            self.last_raw_response = None
            return [], "unavailable"
        body = json.dumps({"query": query, "channels": ["report"], "app_id": "AIME_SKILL", "size": max(1, min(size, 50))}, ensure_ascii=False).encode("utf-8")
        request = Request(
            os.getenv("IWENCAI_BASE_URL", "https://openapi.iwencai.com").rstrip("/") + "/v1/comprehensive/search",
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
                "X-Claw-Call-Type": "normal",
                "X-Claw-Skill-Id": "report-search",
                "X-Claw-Skill-Version": _REPORT_SEARCH_SKILL_VERSION,
                "X-Claw-Plugin-Id": "none",
                "X-Claw-Plugin-Version": "none",
                "X-Claw-Trace-Id": uuid.uuid4().hex + uuid.uuid4().hex,
            },
        )
        try:
            with urlopen(request, timeout=30) as response:
                raw = response.read()
            payload = json.loads(raw.decode("utf-8", errors="replace"))
        except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            logger.warning("report-search failed: %s", exc)
            self.last_raw_response = {"status": "unavailable", "error": str(exc)}
            return [], "unavailable"
        self.last_raw_response = payload if isinstance(payload, dict) else {"data": payload}
        if str(payload.get("status_code", 0)) not in {"0", "200"}:
            return [], "unavailable"
        return _walk_report_records(payload.get("data")), "ok"


class IndustryResearchStore:
    def __init__(self, path: Path | None = None) -> None:
        # Respect VIBE_TRADING_HOME so the API, scheduled jobs, and research
        # cache all use the same writable runtime directory.
        self.path = path or (get_runtime_root() / "industry_research.db")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_db()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS research_jobs (
                    job_id TEXT PRIMARY KEY,
                    industry_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    progress INTEGER NOT NULL DEFAULT 0,
                    current_step TEXT NOT NULL DEFAULT '',
                    model_name TEXT,
                    data_as_of TEXT,
                    error_message TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS research_results (
                    job_id TEXT PRIMARY KEY,
                    industry_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(job_id) REFERENCES research_jobs(job_id)
                );
                CREATE TABLE IF NOT EXISTS research_evidence (
                    evidence_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    evidence_type TEXT NOT NULL,
                    source TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(job_id) REFERENCES research_jobs(job_id)
                );
                CREATE TABLE IF NOT EXISTS research_company_samples (
                    sample_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    code TEXT NOT NULL,
                    rank INTEGER NOT NULL,
                    selection_reason TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(job_id) REFERENCES research_jobs(job_id)
                );
                CREATE TABLE IF NOT EXISTS research_report_cache (
                    industry_id TEXT NOT NULL,
                    days INTEGER NOT NULL,
                    reports_json TEXT NOT NULL,
                    sources_json TEXT NOT NULL,
                    raw_sources_json TEXT,
                    refreshed_date TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    PRIMARY KEY(industry_id, days)
                );
                CREATE TABLE IF NOT EXISTS research_industries (
                    industry_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    demand TEXT NOT NULL DEFAULT '',
                    segments_json TEXT NOT NULL DEFAULT '[]',
                    upstream_json TEXT NOT NULL DEFAULT '[]',
                    sections_json TEXT NOT NULL DEFAULT '[]',
                    market_json TEXT,
                    source TEXT NOT NULL DEFAULT 'a-stock-data',
                    refreshed_date TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )

    def create_job(self, industry_id: str, model_name: str | None) -> str:
        job_id = f"job_{uuid.uuid4().hex[:16]}"
        now = _iso()
        with self._lock, self._connect() as conn:
            conn.execute("INSERT INTO research_jobs(job_id, industry_id, status, model_name, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)", (job_id, industry_id, "queued", model_name, now, now))
        return job_id

    def update_job(self, job_id: str, status: str, progress: int, step: str, error: str | None = None) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("UPDATE research_jobs SET status=?, progress=?, current_step=?, error_message=?, updated_at=? WHERE job_id=?", (status, max(0, min(progress, 100)), step, error, _iso(), job_id))

    def save(self, job_id: str, industry_id: str, payload: dict[str, Any], evidence: list[dict[str, Any]]) -> None:
        now = _iso()
        with self._lock, self._connect() as conn:
            conn.execute("INSERT OR REPLACE INTO research_results(job_id, industry_id, payload_json, created_at) VALUES (?, ?, ?, ?)", (job_id, industry_id, json.dumps(_safe_json(payload), ensure_ascii=False), now))
            conn.executemany("INSERT OR REPLACE INTO research_evidence(evidence_id, job_id, evidence_type, source, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?)", [(item["evidence_id"], job_id, item["evidence_type"], item["source"], json.dumps(_safe_json(item.get("payload")), ensure_ascii=False), now) for item in evidence])
            samples = [
                (job_id, str(item["payload"].get("code")), rank, "按行业报告代码或行业成分股选取代表公司", now)
                for rank, item in enumerate(evidence, start=1)
                if item.get("evidence_type") == "financials" and isinstance(item.get("payload"), dict) and item["payload"].get("code")
            ]
            if samples:
                conn.executemany("INSERT INTO research_company_samples(job_id, code, rank, selection_reason, created_at) VALUES (?, ?, ?, ?, ?)", samples)

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM research_jobs WHERE job_id=?", (job_id,)).fetchone()
            if row is None:
                return None
            result = conn.execute("SELECT payload_json FROM research_results WHERE job_id=?", (job_id,)).fetchone()
        data = dict(row)
        data["analysis"] = json.loads(result[0]) if result else None
        return data

    def latest(self, industry_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT job_id FROM research_jobs WHERE industry_id=? AND status='ready' ORDER BY updated_at DESC LIMIT 1", (industry_id,)).fetchone()
        return self.get_job(row[0]) if row else None

    def get_report_cache(self, industry_id: str, days: int) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM research_report_cache WHERE industry_id=? AND days=?",
                (industry_id, days),
            ).fetchone()
        if row is None:
            return None
        data = dict(row)
        for field in ("reports_json", "sources_json", "raw_sources_json"):
            raw = data.get(field)
            if raw:
                try:
                    data[field[:-5] if field.endswith("_json") else field] = json.loads(raw)
                except (TypeError, ValueError, json.JSONDecodeError):
                    data[field[:-5] if field.endswith("_json") else field] = None
        return data

    def save_report_cache(
        self,
        industry_id: str,
        days: int,
        reports: list[dict[str, Any]],
        sources: dict[str, Any],
        raw_sources: dict[str, Any],
        status: str,
    ) -> None:
        now = _iso()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO research_report_cache
                (industry_id, days, reports_json, sources_json, raw_sources_json,
                 refreshed_date, fetched_at, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    industry_id,
                    days,
                    json.dumps(_safe_json(reports), ensure_ascii=False),
                    json.dumps(_safe_json(sources), ensure_ascii=False),
                    json.dumps(_safe_json(raw_sources), ensure_ascii=False),
                    _local_date(),
                    now,
                    status,
                ),
            )

    def save_industries(
        self,
        industries: list[dict[str, Any]],
        source: str = "a-stock-data",
        replace: bool = False,
    ) -> None:
        now = _iso()
        refreshed_date = _local_date()
        rows = []
        for item in industries:
            industry_id = str(item.get("id") or "").strip()
            name = str(item.get("name") or "").strip()
            if not industry_id or not name:
                continue
            rows.append((
                industry_id,
                name,
                str(item.get("description") or ""),
                str(item.get("demand") or ""),
                json.dumps(_safe_json(item.get("segments") or []), ensure_ascii=False),
                json.dumps(_safe_json(item.get("upstream") or []), ensure_ascii=False),
                json.dumps(_safe_json(item.get("sections") or []), ensure_ascii=False),
                json.dumps(_safe_json(item.get("market")), ensure_ascii=False) if item.get("market") is not None else None,
                source,
                refreshed_date,
                now,
            ))
        if not rows:
            return
        with self._lock, self._connect() as conn:
            if replace:
                conn.execute("DELETE FROM research_industries")
            conn.executemany(
                """
                INSERT OR REPLACE INTO research_industries
                (industry_id, name, description, demand, segments_json,
                 upstream_json, sections_json, market_json, source,
                 refreshed_date, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

    def get_industries(self) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute("SELECT * FROM research_industries ORDER BY name COLLATE NOCASE").fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            for field in ("segments_json", "upstream_json", "sections_json", "market_json"):
                raw = item.pop(field, None)
                target = field[:-5] if field.endswith("_json") else field
                try:
                    item[target] = json.loads(raw) if raw else ([] if target != "market" else None)
                except (TypeError, ValueError, json.JSONDecodeError):
                    item[target] = [] if target != "market" else None
            item["id"] = item.pop("industry_id")
            result.append(item)
        return result

    def get_industry_refresh_date(self) -> str | None:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT MAX(refreshed_date) AS refreshed_date FROM research_industries").fetchone()
        return str(row["refreshed_date"]) if row and row["refreshed_date"] else None


def _card(title: str, summary: str, *, status: str = "ready", citations: list[str] | None = None, key_points: list[str] | None = None, risks: list[str] | None = None) -> dict[str, Any]:
    return {"title": title, "summary": summary, "status": status, "citations": citations or [], "key_points": key_points or [], "risks": risks or []}


def _period_rows(payload: Any, code: str) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    data = payload.get("data", {})
    item = data.get(code, {}) if isinstance(data, dict) else {}
    periods = item.get("periods", []) if isinstance(item, dict) else []
    return [row for row in periods if isinstance(row, dict)]


def _row_number(row: dict[str, Any], names: tuple[str, ...]) -> float | None:
    for name in names:
        value = row.get(name)
        try:
            if value not in (None, "", "-"):
                return float(str(value).replace(",", ""))
        except (TypeError, ValueError):
            continue
    return None


def _calculated_metrics(annual: list[dict[str, Any]], balance: list[dict[str, Any]], cashflow: list[dict[str, Any]]) -> dict[str, Any]:
    """Derive only ratios whose numerator and denominator are present."""
    if not annual:
        return {"status": "insufficient_data", "items": []}
    latest = annual[0]
    revenue = _row_number(latest, ("TOTAL_OPERATE_INCOME", "OPERATE_INCOME", "REVENUES", "Revenue"))
    net_income = _row_number(latest, ("NETPROFIT", "NET_INCOME", "NET_INCOME_LOSS", "NetIncomeLoss"))
    cfo = _row_number((cashflow or [{}])[0], ("NETCASH_OPERATE", "NET_CASH_OPERATING", "NetCashProvidedByUsedInOperatingActivities"))
    assets = _row_number((balance or [{}])[0], ("TOTAL_ASSETS", "ASSETS", "Assets"))
    liabilities = _row_number((balance or [{}])[0], ("TOTAL_LIABILITIES", "LIABILITIES", "Liabilities"))
    receivables = _row_number((balance or [{}])[0], ("ACCOUNTS_RECE", "ACCOUNTS_RECEIVABLE", "AccountsReceivable"))
    inventory = _row_number((balance or [{}])[0], ("INVENTORY", "Inventories", "Inventory"))
    research = _row_number(latest, ("RESEARCH_EXPENSE", "RD_EXPENSE", "ResearchAndDevelopmentExpense"))
    items: dict[str, Any] = {}
    for key, value in (("revenue", revenue), ("net_income", net_income), ("cfo", cfo), ("assets", assets), ("liabilities", liabilities)):
        if value is not None:
            items[key] = {"value": value, "report_period": latest.get("REPORT_DATE"), "kind": "fact"}
    ratios: list[tuple[str, float | None, str]] = [
        ("net_margin", net_income / revenue * 100 if revenue and net_income is not None else None, "%"),
        ("cfo_to_net_income", cfo / net_income if cfo is not None and net_income else None, "x"),
        ("receivables_to_revenue", receivables / revenue * 100 if receivables is not None and revenue else None, "%"),
        ("inventory_to_revenue", inventory / revenue * 100 if inventory is not None and revenue else None, "%"),
        ("debt_to_assets", liabilities / assets * 100 if liabilities is not None and assets else None, "%"),
        ("research_to_revenue", research / revenue * 100 if research is not None and revenue else None, "%"),
    ]
    for key, value, unit in ratios:
        if value is not None:
            items[key] = {"value": value, "unit": unit, "report_period": latest.get("REPORT_DATE"), "kind": "calculation"}
    return {"status": "ok" if items else "insufficient_data", "items": items}


class IndustryResearchService:
    def __init__(self, store: IndustryResearchStore | None = None) -> None:
        self.store = store or IndustryResearchStore()
        self.report_search = ReportSearchClient()
        self.last_a_stock_records: list[dict[str, Any]] = []
        self._industry_refresh_at: datetime | None = None
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="industry-research")
        self._load_persisted_industries()

    def _merge_persisted_industries(self, industries: list[dict[str, Any]]) -> None:
        for item in industries:
            industry_id = str(item.get("id") or "").strip()
            if not industry_id or not item.get("name"):
                continue
            # Seeded templates remain authoritative for their richer sections;
            # live/database entries fill in the selectable industry catalogue.
            if industry_id not in _INDUSTRIES:
                _INDUSTRIES[industry_id] = item
            elif item.get("market") and not _INDUSTRIES[industry_id].get("market"):
                _INDUSTRIES[industry_id]["market"] = item["market"]

    def _load_persisted_industries(self) -> None:
        try:
            self._merge_persisted_industries(self.store.get_industries())
        except (OSError, sqlite3.Error) as exc:
            logger.warning("persisted industry catalogue unavailable: %s", exc)

    def _ensure_live_industries(self) -> None:
        """Add the live Eastmoney industry-board taxonomy as selectable sectors."""
        if self._industry_refresh_at and (_now() - self._industry_refresh_at).total_seconds() < _INDUSTRY_REFRESH_SECONDS:
            return
        if self.store.get_industry_refresh_date() == _local_date():
            self._load_persisted_industries()
            # Persist newly added built-in templates alongside the cached live
            # directory so the database remains the complete catalogue.
            self.store.save_industries(list(_INDUSTRIES.values()), source="a-stock-data-cache")
            self._industry_refresh_at = _now()
            return
        try:
            from src.tools.sector_tool import SectorInfoTool
            response = json.loads(SectorInfoTool().execute(mode="ranking", limit=100))
            boards = response.get("data", {}).get("boards", []) if response.get("ok") else []
        except Exception as exc:
            logger.warning("industry taxonomy unavailable: %s", exc)
            # Keep the last known catalogue (including the built-in templates)
            # durable even when today's provider request is unavailable.
            self.store.save_industries(list(_INDUSTRIES.values()), source="a-stock-data-unavailable")
            self._industry_refresh_at = _now()
            return
        if not boards:
            logger.warning("industry taxonomy returned no boards")
            self.store.save_industries(list(_INDUSTRIES.values()), source="a-stock-data-unavailable")
            self._industry_refresh_at = _now()
            return
        template = _INDUSTRIES.get("humanoid-robot")
        _INDUSTRIES.clear()
        if template:
            _INDUSTRIES[template["id"]] = template
        for board in boards:
            name = str(board.get("board_name") or "").strip()
            if not name:
                continue
            industry_id = _industry_slug(name)
            _INDUSTRIES.setdefault(industry_id, {
                "id": industry_id,
                "name": name,
                "description": "A股行业板块，数据来自实时行业分类。",
                "demand": "当前数据不足，无法形成可靠判断。",
                "segments": [name],
                "upstream": [],
                "market": board,
                "sections": [
                    {"id": "overview", "label": "总览", "description": f"{name}行业总览。"},
                    {"id": "reports", "label": "研报库", "description": f"{name}行业研报。"},
                    {"id": "industry", "label": "行业分析", "description": f"{name}竞争格局、壁垒和财报研判。"},
                ],
            })
        # Persist the complete merged catalogue, including the seeded research
        # templates and all live A-share boards returned today.
        self.store.save_industries(list(_INDUSTRIES.values()), source="a-stock-data", replace=True)
        self._industry_refresh_at = _now()

    def _industry_for_name(self, name: str) -> dict[str, Any]:
        """Return a live/seeded industry or create a safe generic template."""
        normalized = name.strip().lower()
        for item in _INDUSTRIES.values():
            if str(item.get("name") or "").strip().lower() == normalized:
                return item

        industry_id = _industry_slug(name)
        _INDUSTRIES.setdefault(industry_id, {
            "id": industry_id,
            "name": name,
            "description": f"围绕{name}产业链建立的行业研究模板。",
            "demand": "当前数据不足，无法形成可靠判断。",
            "segments": [name],
            "upstream": [],
            "sections": [
                {"id": "overview", "label": "总览", "description": f"{name}行业总览。"},
                {"id": "reports", "label": "研报库", "description": f"{name}行业研报。"},
                {"id": "industry", "label": "行业分析", "description": f"{name}竞争格局、壁垒和财报研判。"},
            ],
        })
        return _INDUSTRIES[industry_id]

    def _semantic_industries(self, query: str) -> list[dict[str, Any]]:
        """Resolve an industry query from live semantic/report evidence.

        No industry names are embedded here.  If the optional iWenCai
        screener is unavailable, report-search supplies the live report text;
        the query itself is retained as a dynamic industry template so a user
        can still open and research an otherwise uncatalogued sector.
        """
        names: list[str] = []

        def add_name(value: Any) -> None:
            text = str(value or "").strip()
            if not (1 < len(text) < 32):
                return
            text = re.sub(r"^[\s:：,，、;；|/]+|[\s:：,，、;；|/]+$", "", text)
            if text and text not in names:
                names.append(text)

        def collect(value: Any, key_hint: str = "") -> None:
            if isinstance(value, dict):
                for key, child in value.items():
                    key_text = str(key)
                    if any(token in key_text.lower() for token in ("行业", "板块", "概念", "所属", "industry", "sector", "category")):
                        if isinstance(child, (str, list, tuple)):
                            for part in re.split(r"[,，;/；|、]", str(child)):
                                add_name(part)
                    collect(child, key_text)
            elif isinstance(value, (list, tuple)):
                for child in value:
                    collect(child, key_hint)
            elif isinstance(value, str) and key_hint in {"title", "summary", "name"}:
                for match in re.findall(r"([\u4e00-\u9fff]{2,16})(?=行业|板块|产业链)", value):
                    add_name(match)

        try:
            from src.tools.iwencai_tool import IWenCaiSearchTool
            raw = IWenCaiSearchTool().execute(query=f"{query} 相关A股所属行业和板块", limit=20)
            payload = json.loads(raw)
        except Exception as exc:
            logger.info("semantic industry search unavailable: %s", exc)
            payload = {}
        if payload.get("ok"):
            collect((payload.get("data") or {}).get("results", []))

        if not names:
            report_records, report_status = self.report_search.search(f"{query} 行业 细分板块 产业链", size=20)
            if report_status == "ok":
                collect(report_records)

        # Keep the user's own query as a dynamic result even when both
        # optional semantic sources are unavailable.  This is data-driven by
        # the request and is not a hardcoded industry catalogue.
        query_name = re.sub(r"(行业|板块|产业链|相关|研究|分析|概念|赛道|方向)", "", query).strip()
        if query_name:
            names.insert(0, query_name)
        result = [self._industry_for_name(name) for name in names[:10]]
        if result:
            self.store.save_industries(result, source="semantic-search")
        return result

    def list_industries(self, query: str = "", limit: int = 20) -> dict[str, Any]:
        self._ensure_live_industries()
        items = list(_INDUSTRIES.values())
        search_mode = "local"
        if query.strip():
            needle = query.strip().lower()
            intent = re.sub(r"(行业|板块|产业链|相关|研究|分析|概念|赛道|方向)", "", needle).strip()

            def relevance(item: dict[str, Any]) -> int:
                synonyms = _INDUSTRY_SYNONYMS.get(item.get("id"), ())
                searchable = " ".join([
                    str(item.get("name") or ""), str(item.get("id") or ""),
                    str(item.get("description") or ""), " ".join(item.get("segments") or []),
                    " ".join(item.get("upstream") or []),
                    " ".join(synonyms),
                ]).lower()
                if needle in searchable or (intent and intent in searchable):
                    return 100 + (30 if needle in str(item.get("name") or "").lower() else 0)
                if any(token in needle or (intent and token in intent) for token in synonyms):
                    return 80
                tokens = [token for token in re.findall(r"[\u4e00-\u9fff]{2,}|[a-z0-9]+", needle) if token]
                return sum(10 for token in tokens if token in searchable)

            ranked = [(relevance(item), item) for item in items]
            items = [item for score, item in sorted(ranked, key=lambda pair: pair[0], reverse=True) if score > 0]
            if not items:
                items = self._semantic_industries(query)
                search_mode = "semantic" if items else "local"
        return {
            "items": [
                {"id": item["id"], "name": item["name"], "description": item["description"], "segments": item["segments"]}
                for item in items[:max(1, min(limit, 50))]
            ],
            "updated_at": _iso(),
            "status": "ok",
            "search_mode": search_mode,
        }

    def _a_share_reports(self, industry_id: str, days: int, limit: int) -> tuple[list[dict[str, Any]], str]:
        item = _INDUSTRIES.get(industry_id, _INDUSTRIES["humanoid-robot"])
        try:
            records = eastmoney_industry_reports(days=days, limit=min(1000, limit * 5), max_pages=10)
        except Exception as exc:
            logger.warning("a-stock-data industry reports failed: %s", exc)
            return [], "unavailable"
        self.last_a_stock_records = [record for record in records if isinstance(record, dict)]
        reports = [_normalize_report(record, industry_id, "a-stock-data") for record in records]
        reports = [report for report in reports if report is not None]
        keywords = [item["name"], *item["segments"]]
        filtered = [report for report in reports if any(keyword.lower() in f"{report['title']} {report.get('summary') or ''}".lower() for keyword in keywords)]
        return (filtered or reports)[:limit], "ok"

    def _filter_reports(
        self,
        item: dict[str, Any],
        reports: list[dict[str, Any]],
        section_id: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        selected: list[dict[str, Any]] = []
        for report in reports:
            if section_id and section_id not in {str(report.get("section_id") or ""), "reports"}:
                haystack = f"{report.get('title') or ''} {report.get('summary') or ''}".lower()
                section = next((s for s in item["sections"] if s["id"] == section_id), None)
                if section and section["label"].lower() not in haystack:
                    continue
            selected.append(report)
        return sorted(selected, key=lambda value: str(value.get("publish_time") or ""), reverse=True)[:max(1, min(limit, _MAX_REPORTS))]

    def _report_response(
        self,
        item: dict[str, Any],
        reports: list[dict[str, Any]],
        sources: dict[str, str],
        raw_sources: dict[str, Any],
        days: int,
        limit: int,
        section_id: str | None,
        *,
        status: str | None = None,
        updated_at: str | None = None,
    ) -> dict[str, Any]:
        items = self._filter_reports(item, reports, section_id, limit)
        return {
            "items": items,
            "sources": sources,
            "raw_sources": raw_sources,
            "status": status or ("ok" if items else "unavailable"),
            "updated_at": updated_at or _iso(),
            "days": days,
        }

    def reports(self, industry_id: str, days: int = 90, limit: int = 50, section_id: str | None = None) -> dict[str, Any]:
        item = _INDUSTRIES.get(industry_id)
        if item is None:
            return {"items": [], "sources": {"a_stock_data": "unavailable", "report_search": "unavailable"}, "status": "unavailable", "updated_at": _iso()}

        cache = self.store.get_report_cache(industry_id, days)
        if cache and cache.get("refreshed_date") == _local_date():
            return self._report_response(
                item,
                cache.get("reports") or [],
                cache.get("sources") or {"a_stock_data": "unavailable", "report_search": "unavailable"},
                cache.get("raw_sources") or {},
                days,
                limit,
                section_id,
                status=cache.get("status") or "ok",
                updated_at=cache.get("fetched_at"),
            )

        base, base_status = self._a_share_reports(industry_id, days, limit)
        search_records, search_status = self.report_search.search(f"{item['name']} 行业 研报", size=min(limit, 20))
        enhanced = [_normalize_report(record, industry_id, "report-search") for record in search_records]
        enhanced = [report for report in enhanced if report is not None]
        merged: dict[str, dict[str, Any]] = {}
        for report in [*base, *enhanced]:
            key = _report_key(report)
            if key not in merged:
                merged[key] = report
            else:
                current = merged[key]
                for field in ("summary", "institution", "author", "rating", "target_price", "source_url", "pdf_url"):
                    if not current.get(field) and report.get(field):
                        current[field] = report[field]
                current["source"] = current["source"] if current["source"] == report["source"] else "a-stock-data"
                current["sources"] = sorted(set(current.get("sources", [current["source"]])) | set(report.get("sources", [report["source"]])))
        raw = {
            "a_stock_data": self.last_a_stock_records,
            "report_search": self.report_search.last_raw_response,
        }
        for item_report in merged.values():
            item_report.setdefault("sources", [item_report["source"]])
        merged_reports = list(merged.values())
        source_status = {"a_stock_data": base_status, "report_search": search_status}
        status = "ok" if merged_reports else "unavailable"
        # Keep the last successful daily snapshot when providers are down. A
        # transient outage must not overwrite usable local research with an
        # empty cache.
        if merged_reports or not cache:
            self.store.save_report_cache(industry_id, days, merged_reports, source_status, raw, status)
        if not merged_reports and cache and cache.get("reports"):
            cached_sources = {
                key: "cached" if value == "ok" else value
                for key, value in (cache.get("sources") or {}).items()
            }
            return self._report_response(item, cache["reports"], cached_sources, cache.get("raw_sources") or {}, days, limit, section_id, status="stale", updated_at=cache.get("fetched_at"))
        return self._report_response(item, merged_reports, source_status, raw, days, limit, section_id, status=status)

    def analysis(self, industry_id: str) -> dict[str, Any]:
        return self.store.latest(industry_id) or {"analysis": None, "status": "missing"}

    def start_analysis(self, industry_id: str, force: bool = False) -> dict[str, Any]:
        if industry_id not in _INDUSTRIES:
            self._ensure_live_industries()
        if industry_id not in _INDUSTRIES:
            return {"status": "failed", "error": "unknown industry"}
        if industry_id == "humanoid-robot":
            self._ensure_live_industries()
        from src.config.accessor import get_env_config
        model = get_env_config().llm.langchain_model_name.strip()
        latest = self.store.latest(industry_id)
        if latest and not force:
            try:
                updated = datetime.fromisoformat(latest["updated_at"])
                same_model = str(latest.get("model_name") or "") == model
                has_cutoff = bool((latest.get("analysis") or {}).get("data_as_of"))
                if same_model and has_cutoff and _now() - updated < timedelta(hours=_CACHE_HOURS):
                    return {"job_id": latest["job_id"], "status": "ready", "analysis": latest["analysis"]}
            except (KeyError, TypeError, ValueError):
                pass
        job_id = self.store.create_job(industry_id, model)
        self.executor.submit(self._run_analysis, job_id, industry_id, model)
        return {"job_id": job_id, "status": "queued"}

    def _run_analysis(self, job_id: str, industry_id: str, model: str) -> None:
        item = _INDUSTRIES[industry_id]
        evidence: list[dict[str, Any]] = []
        try:
            self.store.update_job(job_id, "fetching", 15, "正在获取行业和代表公司")
            self.store.update_job(job_id, "searching_reports", 30, "正在搜索行业研报")
            report_data = self.reports(industry_id, days=730, limit=50)
            evidence.append({"evidence_id": f"ev_{uuid.uuid4().hex[:12]}", "evidence_type": "reports", "source": "a-stock-data+report-search", "payload": report_data})
            self.store.update_job(job_id, "calculating", 45, "正在整理财报证据")
            financials = self._financial_evidence(item, report_data)
            evidence.extend(financials)
            self.store.update_job(job_id, "analyzing", 70, "正在生成行业板块研判")
            payload = self._generate_ai(item, evidence, model)
            self.store.update_job(job_id, "validating", 90, "正在校验证据引用")
            payload = self._validate_payload(payload, evidence, item)
            self.store.save(job_id, industry_id, payload, evidence)
            self.store.update_job(job_id, "ready", 100, "行业研判已完成")
        except Exception as exc:
            logger.exception("industry analysis failed for %s", industry_id)
            self.store.update_job(job_id, "failed", 100, "行业研判失败", str(exc))

    def _board_members(self, board_code: str) -> list[str]:
        try:
            from backtest.loaders.eastmoney_client import get_json
            payload = get_json(
                "https://push2.eastmoney.com/api/qt/clist/get",
                params={"fs": f"b:{board_code}", "fields": "f12,f14", "pn": "1", "pz": "10", "po": "1", "fid": "f3"},
            )
            diff = (payload.get("data") or {}).get("diff") if isinstance(payload, dict) else []
            rows = diff.values() if isinstance(diff, dict) else diff
            return [f"{str(row['f12']).zfill(6)}.{('SH' if str(row['f12']).startswith('6') else 'SZ')}" for row in rows if isinstance(row, dict) and row.get("f12")]
        except Exception as exc:
            logger.warning("industry members unavailable for %s: %s", board_code, exc)
            return []

    def _financial_evidence(self, item: dict[str, Any], report_data: dict[str, Any]) -> list[dict[str, Any]]:
        codes: list[str] = []
        for report in report_data.get("items", []):
            text = json.dumps(report, ensure_ascii=False)
            explicit_code = str(report.get("company_code") or "").strip()
            if explicit_code and explicit_code not in codes:
                codes.append(explicit_code)
            for match in re.findall(r"(?<!\d)(\d{6})\.(SH|SZ|BJ)\b", text, flags=re.IGNORECASE):
                code = f"{match[0]}.{match[1].upper()}"
                if code not in codes:
                    codes.append(code)
        if not codes:
            board = item.get("market") or {}
            board_code = str(board.get("board_code") or "") if isinstance(board, dict) else ""
            if board_code:
                codes.extend(self._board_members(board_code))
        codes = codes[:_MAX_COMPANIES]
        if not codes:
            return [{"evidence_id": f"ev_{uuid.uuid4().hex[:12]}", "evidence_type": "financials", "source": "a-stock-data", "payload": {"status": "unavailable", "reason": "industry reports did not expose representative stock codes"}}]
        from src.tools.a_share_data_tool import AShareDataTool
        from src.tools.financial_rigor_tool import FinancialRigorTool
        from src.tools.financial_statements_tool import FinancialStatementsTool
        out: list[dict[str, Any]] = []
        for code in codes:
            payload: dict[str, Any] = {"code": code}
            try:
                payload["fundamentals"] = json.loads(AShareDataTool().execute(operation="fundamentals", code=code, statement="all", limit=12))
            except Exception as exc:
                payload["fundamentals_error"] = str(exc)
            for period in ("annual", "quarter"):
                try:
                    raw_statements = FinancialStatementsTool().execute(code=code, statement="indicators", period=period)
                    payload[period] = json.loads(raw_statements)
                except Exception as exc:
                    payload[f"{period}_error"] = str(exc)
            for statement in ("balance", "cashflow"):
                try:
                    raw_statement = FinancialStatementsTool().execute(code=code, statement=statement, period="annual")
                    payload[statement] = json.loads(raw_statement)
                except Exception as exc:
                    payload[f"{statement}_error"] = str(exc)
            annual_rows = _period_rows(payload.get("annual"), code)
            quarter_rows = _period_rows(payload.get("quarter"), code)
            payload["calculated_metrics"] = _calculated_metrics(
                annual_rows,
                _period_rows(payload.get("balance"), code),
                _period_rows(payload.get("cashflow"), code),
            )
            try:
                payload["financial_rigor"] = json.loads(FinancialRigorTool().execute(
                    command="cross_validate",
                    field="statement_row_count",
                    source_values={"annual": len(annual_rows), "quarter": len(quarter_rows)},
                    unit="rows",
                ))
            except Exception as exc:
                payload["financial_rigor_error"] = str(exc)
            out.append({"evidence_id": f"ev_{uuid.uuid4().hex[:12]}", "evidence_type": "financials", "source": "a-stock-data", "payload": payload})
        return out

    def _generate_ai(self, item: dict[str, Any], evidence: list[dict[str, Any]], model: str) -> dict[str, Any]:
        prompt = {
            "industry": item,
            "evidence": evidence,
            "required": "Fill every overview and section card. Use Chinese. Do not invent numbers. Cite evidence_id for every factual claim. Include financial_judgment and conclusion for every section. Distinguish facts, calculations, forecasts and inferences. Do not give buy/sell instructions.",
            "schema": {
                "industry_id": "string",
                "industry_name": "string",
                "data_as_of": "ISO-8601 string",
                "overview": {"positioning": "card", "demand_endpoint": "card", "core_segments": "card", "upstream_materials": "card", "score_summary": "card", "core_companies": "card", "cost_structure": "card", "production_timeline": "card", "conclusion": "card"},
                "sections": [{"section_id": "string", "position": "card", "overseas_competition": "card", "domestic_competition": "card", "technology_barrier": "card", "capacity_barrier": "card", "financial_judgment": {"quality": "string", "summary": "string", "metrics": "array", "red_flags": "array", "citations": "evidence_id[]"}, "company_comparison": "array", "score": {"dimensions": "array", "summary": "string"}, "conclusion": "card"}],
                "card": {"title": "string", "summary": "string", "status": "ready|insufficient_data", "citations": "evidence_id[]", "key_points": "array", "risks": "array"},
            },
        }
        try:
            from src.providers.chat import ChatLLM
            response = ChatLLM(model_name=model or None).chat([
                {"role": "system", "content": "你是严谨的A股行业研究员。只基于提供的证据输出JSON，不要给出买卖建议。缺失数据必须明确写数据不足。"},
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ], timeout=120)
            content = response.content.strip()
            if content.startswith("```"):
                content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.S).strip()
            return json.loads(content)
        except Exception as exc:
            logger.warning("AI industry generation unavailable: %s", exc)
            return self._fallback_analysis(item, evidence, str(exc))

    def _fallback_analysis(self, item: dict[str, Any], evidence: list[dict[str, Any]], reason: str) -> dict[str, Any]:
        citation_ids = [entry["evidence_id"] for entry in evidence]
        insufficient = "当前数据不足，无法形成可靠判断。"
        overview = {
            "positioning": _card("行业定位", item["description"], citations=citation_ids),
            "demand_endpoint": _card("需求终端", item["demand"], citations=citation_ids),
            "core_segments": _card("核心环节", "、".join(item["segments"]), citations=citation_ids),
            "upstream_materials": _card("上游材料·设备", "、".join(item["upstream"]), citations=citation_ids),
            "score_summary": _card("板块评分总览", insufficient, status="insufficient_data"),
            "core_companies": _card("核心标的池", insufficient, status="insufficient_data"),
            "cost_structure": _card("整机成本构成", insufficient, status="insufficient_data"),
            "production_timeline": _card("量产时间轴", insufficient, status="insufficient_data"),
            "conclusion": _card("板块结论", "AI研判暂不可用，已保留可核验的数据源状态。", status="insufficient_data"),
        }
        sections = []
        for section in item["sections"]:
            if section["id"] in {"overview", "reports"}:
                continue
            sections.append({
                "section_id": section["id"],
                "section_name": section["label"],
                "position": _card("环节定位", insufficient, status="insufficient_data"),
                "overseas_competition": _card("海外竞争格局", insufficient, status="insufficient_data"),
                "domestic_competition": _card("国内竞争格局", insufficient, status="insufficient_data"),
                "technology_barrier": _card("科技壁垒", insufficient, status="insufficient_data"),
                "capacity_barrier": _card("产能壁垒", insufficient, status="insufficient_data"),
                "financial_judgment": {"quality": "insufficient_data", "summary": insufficient, "metrics": [], "red_flags": [], "citations": []},
                "company_comparison": [],
                "score": {"dimensions": [], "summary": insufficient},
                "conclusion": _card("板块结论", insufficient, status="insufficient_data"),
            })
        return {"industry_id": item["id"], "industry_name": item["name"], "generated_at": _iso(), "data_as_of": _iso(), "model_name": "fallback", "status": "partial", "error": reason, "overview": overview, "sections": sections, "evidence_ids": citation_ids}

    def _validate_payload(self, payload: dict[str, Any], evidence: list[dict[str, Any]], item: dict[str, Any]) -> dict[str, Any]:
        payload["industry_id"] = item["id"]
        payload["industry_name"] = item["name"]
        payload.setdefault("overview", {})
        payload.setdefault("sections", [])
        payload.setdefault("status", "ready")
        valid_ids = {entry["evidence_id"] for entry in evidence}
        payload["evidence_ids"] = [value for value in payload.get("evidence_ids", []) if value in valid_ids]
        def validate_card(value: Any, title: str) -> dict[str, Any]:
            if not isinstance(value, dict):
                return _card(title, "当前数据不足，无法形成可靠判断。", status="insufficient_data")
            result = dict(value)
            result.setdefault("title", title)
            result.setdefault("summary", "当前数据不足，无法形成可靠判断。")
            citations = [value for value in result.get("citations", []) if value in valid_ids]
            result["citations"] = citations
            if not citations and re.search(r"\d", str(result.get("summary") or "")):
                return _card(title, "当前数据不足，无法形成可靠判断。", status="insufficient_data")
            return result

        overview_keys = {
            "positioning": "行业定位",
            "demand_endpoint": "需求终端",
            "core_segments": "核心环节",
            "upstream_materials": "上下游产业链",
            "score_summary": "板块评分总览",
            "core_companies": "核心公司比较",
            "cost_structure": "成本结构",
            "production_timeline": "量产时间线",
            "conclusion": "板块结论",
        }
        payload["overview"] = {key: validate_card(payload["overview"].get(key), title) for key, title in overview_keys.items()}
        section_keys = {
            "position": "环节定位",
            "overseas_competition": "海外竞争格局",
            "domestic_competition": "国内竞争格局",
            "technology_barrier": "技术壁垒",
            "capacity_barrier": "产能壁垒",
            "conclusion": "板块结论",
        }
        existing = {section.get("section_id"): section for section in payload["sections"] if isinstance(section, dict)}
        sections: list[dict[str, Any]] = []
        for definition in item["sections"]:
            if definition["id"] in {"overview", "reports"}:
                continue
            section = dict(existing.get(definition["id"]) or {})
            section["section_id"] = definition["id"]
            section["section_name"] = definition["label"]
            for key, title in section_keys.items():
                section[key] = validate_card(section.get(key), title)
            financial = section.get("financial_judgment") if isinstance(section.get("financial_judgment"), dict) else {}
            section["financial_judgment"] = {
                **financial,
                "summary": financial.get("summary") or "当前数据不足，无法形成可靠判断。",
                "citations": [value for value in financial.get("citations", []) if value in valid_ids],
            }
            if re.search(r"\d", section["financial_judgment"]["summary"]) and not section["financial_judgment"]["citations"]:
                section["financial_judgment"] = {"quality": "insufficient_data", "summary": "当前数据不足，无法形成可靠判断。", "metrics": [], "red_flags": [], "citations": []}
            section.setdefault("company_comparison", [])
            score = section.get("score") if isinstance(section.get("score"), dict) else {}
            section["score"] = {**score, "summary": score.get("summary") or "当前数据不足，无法形成可靠判断。"}
            sections.append(section)
        payload["sections"] = sections
        return _safe_json(payload)

    def detail(self, industry_id: str) -> dict[str, Any]:
        item = _INDUSTRIES.get(industry_id)
        if item is None:
            return {"status": "unavailable", "error": "unknown industry"}
        latest = self.store.latest(industry_id)
        return {"industry": item, "analysis": latest["analysis"] if latest else None, "analysis_job_id": latest["job_id"] if latest else None, "analysis_status": latest["status"] if latest else "missing", "updated_at": _iso()}


_SERVICE: IndustryResearchService | None = None
_SERVICE_LOCK = threading.Lock()


def get_industry_research_service() -> IndustryResearchService:
    global _SERVICE
    if _SERVICE is None:
        with _SERVICE_LOCK:
            if _SERVICE is None:
                _SERVICE = IndustryResearchService()
    return _SERVICE
