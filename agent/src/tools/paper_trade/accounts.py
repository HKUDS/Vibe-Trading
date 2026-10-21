"""Local forward paper accounts shared by CLI and Web API; no broker writes.

The pure step tool remains available for caller-owned ledgers/replays. This
service owns wall-clock eligibility and commits each successful step atomically.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from functools import partial
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from src.config.paths import get_runtime_root
from .schema import MARKETS, parse_account_state, parse_request

# Daily bars may remain provisional shortly after the regular market close.
_MARKET_TIME = {
    "cn_a": ("Asia/Shanghai", 15, 30),
    "hk": ("Asia/Hong_Kong", 16, 30),
    "us": ("America/New_York", 16, 30),
}


class AccountConflict(ValueError):
    """Another request has already advanced this account."""


class PaperAccounts:
    """SQLite ledger with optimistic concurrency across processes and surfaces."""

    def __init__(
        self,
        path: Path | None = None,
        *,
        clock: Callable | None = None,
        step: Callable | None = None,
    ):
        self.path = path or get_runtime_root() / "paper-trading" / "accounts.db"
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        if step is None:
            from .tool import run_paper_trade_step

            step = partial(run_paper_trade_step, _orders_at_end=True)
        self.step = step
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS accounts (id TEXT PRIMARY KEY, document TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS steps (account_id TEXT, revision INTEGER, document TEXT NOT NULL, "
                "PRIMARY KEY(account_id, revision))"
            )

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def _now(self, market):
        return self.clock().astimezone(ZoneInfo(_MARKET_TIME[market][0]))

    def create(
        self,
        *,
        label: str,
        market: str,
        account_state: dict,
        start: str = "today",
        fee_model: dict | None = None,
    ) -> dict:
        """Create a ledger eligible today or at the next observed trading session.

        Args:
            label: Human-readable account name.
            market: cn_a, hk, or us.
            account_state: Initial cash and positions, in the market's currency.
            start: today or next_session; holidays are resolved by actual bars.
            fee_model: Optional overrides supported by the selected market.
        """
        if not isinstance(label, str) or not label.strip() or len(label) > 80:
            raise ValueError("label must contain 1–80 characters")
        if market not in MARKETS or start not in ("today", "next_session"):
            raise ValueError("invalid market or start mode")
        state = parse_account_state(account_state)
        if state.cash < 0 or any(
            p.qty <= 0 or p.avg_cost <= 0 or not p.symbol.strip()
            for p in state.positions
        ):
            raise ValueError(
                "Initial cash must be non-negative; positions require positive quantity and average cost"
            )
        if len({p.symbol for p in state.positions}) != len(state.positions):
            raise ValueError("Initial positions must have unique symbols")
        today = self._now(market).date()
        earliest = today + timedelta(days=int(start == "next_session"))
        while earliest.weekday() >= 5:
            earliest += timedelta(days=1)
        document = {
            "id": uuid.uuid4().hex,
            "label": label.strip(),
            "market": market,
            "currency": {"cn_a": "CNY", "hk": "HKD", "us": "USD"}[market],
            "created_at": self.clock().isoformat(),
            "start": start,
            "start_on": earliest.isoformat(),
            "last_date": None,
            "revision": 0,
            "initial_state": asdict(state),
            "account_state": asdict(state),
            "fee_model": fee_model if fee_model is not None else {},
            "last_result": None,
        }
        # Reuse the tool's strict numeric/fee validation at every entrance.
        parse_request(
            {
                "account_id": document["id"],
                "market": market,
                "account_state": account_state,
                "from_date": document["start_on"],
                "to_date": document["start_on"],
                "orders": [],
                "fee_model": document["fee_model"],
            }
        )
        if any(value < 0 for value in document["fee_model"].values()):
            raise ValueError("Fees must be non-negative")
        document = json.loads(json.dumps(document))
        with self._connect() as db:
            db.execute(
                "INSERT INTO accounts VALUES (?, ?)",
                (document["id"], json.dumps(document)),
            )
        return document

    def list(self) -> list[dict]:
        with self._connect() as db:
            return [
                json.loads(row[0])
                for row in db.execute(
                    "SELECT document FROM accounts ORDER BY rowid DESC"
                )
            ]

    def get(self, account_id: str) -> dict:
        with self._connect() as db:
            row = db.execute(
                "SELECT document FROM accounts WHERE id = ?", (account_id,)
            ).fetchone()
        if row is None:
            raise KeyError("paper account not found")
        return json.loads(row[0])

    def history(self, account_id: str) -> list[dict]:
        self.get(account_id)
        with self._connect() as db:
            return [
                json.loads(row[0])
                for row in db.execute(
                    "SELECT document FROM steps WHERE account_id = ? ORDER BY revision",
                    (account_id,),
                )
            ]

    def advance(
        self,
        account_id: str,
        *,
        expected_revision: int,
        to_date: str,
        orders: list | None = None,
        strategy_path: str | None = None,
    ) -> dict:
        """Match completed daily bars and atomically commit, refusing stale callers.

        Args:
            account_id: Saved account identifier.
            expected_revision: Revision last read by the caller.
            to_date: Last completed execution day (YYYY-MM-DD).
            orders: Explicit orders for a single day, including [] for valuation.
            strategy_path: Strategy under the configured runtime strategies folder.
        """
        account = self.get(account_id)
        if (
            not isinstance(expected_revision, int)
            or isinstance(expected_revision, bool)
            or expected_revision != account["revision"]
        ):
            raise AccountConflict("Account changed; reload before advancing")
        now = self._now(account["market"])
        _, hour, minute = _MARKET_TIME[account["market"]]
        latest = now.date() - timedelta(
            days=int((now.hour, now.minute) < (hour, minute))
        )
        earliest = account["start_on"]
        if account["last_date"]:
            earliest = (
                datetime.fromisoformat(account["last_date"]).date() + timedelta(days=1)
            ).isoformat()
        if (
            not isinstance(to_date, str)
            or not earliest <= to_date <= latest.isoformat()
        ):
            raise ValueError(
                f"Execution date must be between {earliest} and {latest.isoformat()}; "
                "wait for a completed session after account creation"
            )
        payload = {
            "account_id": account_id,
            "market": account["market"],
            "account_state": account["account_state"],
            "fee_model": account["fee_model"],
            "from_date": earliest,
            "to_date": to_date,
        }
        if orders is not None:
            payload["orders"] = orders
        if strategy_path is not None:
            payload["strategy_path"] = strategy_path
        parse_request(payload)
        result = json.loads(self.step(payload))
        if "code" in result:
            return {"account": account, "result": result, "committed": False}
        # Closed dates must not consume the account's first eligible session.
        if not result.get("nav_series"):
            return {"account": account, "result": result, "committed": False}
        previous = json.dumps(account)
        account.update(
            account_state=result["end_state"],
            last_date=to_date,
            revision=expected_revision + 1,
            last_result=result,
        )
        with self._connect() as db:
            updated = db.execute(
                "UPDATE accounts SET document = ? WHERE id = ? AND document = ?",
                (json.dumps(account), account_id, previous),
            ).rowcount
            if updated != 1:
                raise AccountConflict(
                    "Account advanced concurrently; result discarded, reload"
                )
            db.execute(
                "INSERT INTO steps VALUES (?, ?, ?)",
                (account_id, account["revision"], json.dumps(result)),
            )
        return {"account": account, "result": result, "committed": True}
