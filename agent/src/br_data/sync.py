"""Run every Brazilian dataset sync, once or as a daily daemon."""

from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta
from typing import Callable, Iterable
from zoneinfo import ZoneInfo

from src.br_data import bcb, cotahist, cvm_companies, cvm_funds, tesouro
from src.br_data.store import connect, init_db
from src.config.accessor import get_env_config

logger = logging.getLogger(__name__)

TZ = ZoneInfo("America/Sao_Paulo")
SOURCES = ("cotahist", "cvm_funds", "cvm_companies", "bcb", "tesouro")


def _today() -> date:
    return datetime.now(TZ).date()


def run_sync(only: Iterable[str] | None = None, *, cotahist_from: int | None = None,
             cvm_from: int | None = None) -> dict[str, object]:
    """Sync the selected sources; a failing source is reported, not fatal."""
    data_cfg = get_env_config().data
    selected = [s for s in SOURCES if not only or s in set(only)]
    today = _today()
    cot_year = cotahist_from or data_cfg.vibe_br_cotahist_start_year
    cvm_year = cvm_from or data_cfg.vibe_br_cvm_start_year
    jobs: dict[str, Callable] = {
        "cotahist": lambda c: cotahist.sync(c, cot_year, today),
        "cvm_funds": lambda c: cvm_funds.sync_register(c) + cvm_funds.sync_daily(c, cvm_year, today),
        "cvm_companies": lambda c: cvm_companies.sync(c, cvm_year, today),
        "bcb": lambda c: bcb.sync(c, min(cot_year, cvm_year), today),
        "tesouro": lambda c: tesouro.sync(c),
    }
    path = init_db()
    report: dict[str, object] = {"db": str(path)}
    for name in selected:
        started = time.monotonic()
        try:
            with connect(path, write=True) as conn:
                rows = jobs[name](conn)
            report[name] = {"rows": rows, "seconds": round(time.monotonic() - started, 1)}
            logger.info("br-data: %s ok (%s rows)", name, rows)
        except Exception as exc:  # noqa: BLE001 - keep the other sources going
            report[name] = {"error": f"{type(exc).__name__}: {exc}"}
            logger.warning("br-data: %s failed: %s", name, exc)
    return report


def _next_run(now: datetime, hhmm: str) -> datetime:
    hour, minute = (int(part) for part in hhmm.split(":", 1))
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target


def run_daemon(only: Iterable[str] | None = None) -> None:
    """Sync now, then every day at ``VIBE_BR_SYNC_TIME`` (São Paulo time)."""
    only = list(only or [])
    while True:
        logger.info("br-data: sync report %s", run_sync(only))
        target = _next_run(datetime.now(TZ), get_env_config().data.vibe_br_sync_time)
        logger.info("br-data: next sync at %s", target.isoformat())
        time.sleep(max((target - datetime.now(TZ)).total_seconds(), 60))
