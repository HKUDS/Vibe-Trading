"""Crash reconciliation for a paper-trade account (T5).

The write order is fixed — step directory first, ``account.json`` second — so
the only crash window is "the step landed, the ledger did not".  This module
resolves exactly that window and refuses everything else:

* exactly one step directory is ahead of the watermark AND the step document is
  internally consistent (its ``end_state_hash`` is the digest of its own
  ``end_state``) AND its ``input_state_hash`` equals the account's current
  state digest → ADOPT (apply the step's end_state, advance the watermark) and
  write ``recovery.json`` as the audit record of the decision;
* more than one step ahead, a manifest mismatch, an internally inconsistent
  step, or an input hash that does not match → ``recovery_required`` with the
  reason.  Nothing is written, so the operator sees the contradiction instead
  of a silently re-based ledger;
* no step ahead → verify the chain tail (the account must still hash to the last
  adopted step's ``end_state_hash``) and report ``clean``.

It also removes ``.staging-*`` directories and ``.tmp-*`` files left by the
interrupted write.  That is safe ONLY under the account lock (a live writer's
staging directory is unreachable then), which is why the store calls this while
holding it.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .account import PaperTradeAccount, account_state_payload
from .state_hash import state_hash
from .storage_io import (
    RECOVERY_FILE,
    STAGING_PREFIX,
    STEPS_DIRNAME,
    TMP_PREFIX,
    atomic_write,
    dumps,
    verify_files,
)

if TYPE_CHECKING:
    from .store import AccountStore

__all__ = ["RecoveryResult", "recover_locked"]


@dataclass(frozen=True, slots=True)
class RecoveryResult:
    """Outcome of a reconciliation.

    ``status`` is ``clean`` (nothing to do), ``adopted`` (the orphaned step was
    applied because its input state is exactly the account's current state) or
    ``recovery_required`` (the store refuses to guess — ``code`` says why).
    """

    account: PaperTradeAccount
    status: str
    code: str = ""
    message: str = ""
    trade_date: str | None = None
    cleaned: tuple[str, ...] = ()

    @property
    def watermark(self) -> str | None:
        return self.account.watermark


def _clean_residue(store: "AccountStore", account_id: str) -> tuple[str, ...]:
    removed: list[str] = []
    steps_dir = store.steps_dir(account_id)
    if steps_dir.is_dir():
        for path in sorted(steps_dir.iterdir()):
            if path.is_dir() and path.name.startswith(STAGING_PREFIX):
                shutil.rmtree(path, ignore_errors=True)
                removed.append(f"{STEPS_DIRNAME}/{path.name}")
    for path in sorted(store.account_dir(account_id).iterdir()):
        if path.is_file() and path.name.startswith(TMP_PREFIX):
            path.unlink(missing_ok=True)
            removed.append(path.name)
    return tuple(removed)


def recover_locked(store: "AccountStore", account_id: str, now: str) -> RecoveryResult:
    """Reconcile one account while the caller already holds its lock."""
    account = store.load(account_id)
    cleaned = _clean_residue(store, account_id)
    steps = store.list_steps(account_id)
    ahead = [day for day in steps if account.watermark is None or day > account.watermark]

    def refuse(code: str, message: str, trade_date: str | None = None) -> RecoveryResult:
        return RecoveryResult(account, "recovery_required", code, message, trade_date, cleaned)

    if len(ahead) > 1:
        return refuse(
            "multiple_steps_ahead",
            f"{len(ahead)} step directories ({', '.join(ahead)}) are ahead of watermark "
            f"{account.watermark!r}; refusing to guess which one this account state belongs to",
        )
    if ahead:
        record = store.read_step(account_id, ahead[0])
        problems = verify_files(record.directory, record.manifest)
        if problems:
            return refuse(
                "step_corrupt",
                f"step {record.trade_date} failed manifest verification: {', '.join(problems)}",
                record.trade_date,
            )
        recorded_end = record.end_state_hash
        if not recorded_end:
            return refuse(
                "step_corrupt",
                f"step {record.trade_date} records no end_state_hash; refusing to adopt a "
                "step whose end state cannot be verified",
                record.trade_date,
            )
        recomputed_end = state_hash(account_state_payload(record.end_state))
        if recorded_end != recomputed_end:
            return refuse(
                "step_corrupt",
                f"step {record.trade_date} records end_state_hash {recorded_end}, but its own "
                f"end_state hashes to {recomputed_end}; refusing to adopt an internally "
                "inconsistent step",
                record.trade_date,
            )
        current = account.state_digest()
        if record.input_state_hash != current:
            return refuse(
                "state_mismatch",
                f"step {record.trade_date} was computed from account state "
                f"{record.input_state_hash or '<missing>'}, but the stored account state hashes "
                f"to {current}; adopting it would apply a transition that never started from "
                "this ledger",
                record.trade_date,
            )
        adopted = account.with_advance(
            end_state=record.end_state,
            watermark=record.trade_date,
            engine_fingerprint=record.engine_fingerprint or None,
        )
        store.save_account_atomic(adopted)
        atomic_write(
            store.account_dir(account_id) / RECOVERY_FILE,
            (
                dumps(
                    {
                        "account_id": account_id,
                        "action": "adopted_orphaned_step",
                        "adopted_trade_date": record.trade_date,
                        "previous_watermark": account.watermark,
                        "account_state_hash": current,
                        "step_created_at": record.step.get("created_at", ""),
                        "recovered_at": now,
                    }
                )
                + "\n"
            ).encode("utf-8"),
        )
        return RecoveryResult(
            adopted,
            "adopted",
            "",
            f"adopted step {record.trade_date} into the ledger "
            f"(watermark {account.watermark!r} -> {record.trade_date!r})",
            record.trade_date,
            cleaned,
        )

    if account.watermark is not None and account.watermark in steps:
        record = store.read_step(account_id, account.watermark)
        expected = record.step.get("end_state_hash")
        if expected and expected != account.state_digest():
            return refuse(
                "state_mismatch",
                f"account state does not match the end_state_hash of step {account.watermark}: "
                f"account.json hashes to {account.state_digest()}, the step recorded {expected}",
                account.watermark,
            )
    return RecoveryResult(account, "clean", "", "", None, cleaned)
