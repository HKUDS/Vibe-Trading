"""Append-only per-account store (plan §11 layout, T5).

On-disk layout under ``<runtime_root>/paper_trade`` (``VIBE_TRADING_HOME``
honoured through :func:`src.config.paths.get_runtime_root`)::

    accounts/<account_id>/
      account.json          # the ONLY mutable file; temp file + os.replace + fsync
      .lock                 # account-level advisory lock (flock / msvcrt)
      recovery.json         # last crash-recovery decision (written only by recover)
      steps/<trade_date>/
        step.json           # input/end state, hashes, counts, provenance
        orders.jsonl  fills.jsonl  rejected.jsonl  canceled.jsonl
        positions.jsonl  events.jsonl
        bars/<symbol>.csv
        manifest.json       # sha256 + line count + bytes for every file above

Invariants: ``account.json`` is replaced atomically in its OWN directory (a crash
leaves the old or the new document, never half of one); a step is assembled under
``.staging-<date>-*`` and renamed into place, and an existing ``steps/<date>`` is
never overwritten; the lock is NON-BLOCKING, so a second step fails fast instead
of queueing behind a hung process; and nothing here reads a clock.

The plan's five data files are a minimum, not a maximum: ``rejected.jsonl`` and
``canceled.jsonl`` are written too, because the pt-v1.2 result carries those rows
(D2) and folding them into ``orders.jsonl`` would lose which order produced which
terminal verdict.
"""

from __future__ import annotations

import errno
import os
import re
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from src.config.paths import get_runtime_root

from .account import AccountError, PaperTradeAccount, require_date, validate_account_id
from .recovery import RecoveryResult, recover_locked
from .schema import PaperTradeSchemaError, parse_account_state
from .storage_io import (
    ACCOUNT_FILE,
    ACCOUNTS_DIRNAME,
    BASE_DIRNAME,
    LOCK_FILE,
    MANIFEST_FILE,
    STEPS_DIRNAME,
    STEP_FILE,
    StoreError,
    atomic_write,
    dumps,
    jsonl,
    read_json,
    verify_files,
    write_step_directory,
)

try:  # POSIX
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None  # type: ignore[assignment]
try:  # Windows
    import msvcrt
except ImportError:  # pragma: no cover - POSIX
    msvcrt = None  # type: ignore[assignment]

__all__ = [
    "ACCOUNT_FILE",
    "BASE_DIRNAME",
    "MANIFEST_FILE",
    "STEP_FILE",
    "AccountExists",
    "AccountLocked",
    "AccountNotFound",
    "AccountStore",
    "RecoveryResult",
    "StepExists",
    "StepNotFound",
    "StepRecord",
    "StoreError",
    "dumps",
]

_STEP_DIR_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _step_path(steps_dir: Path, account_id: str, day: str) -> Path:
    """Return ``steps_dir/day``, refusing a symlink or a non-directory.

    ``Path.exists()`` follows links and a dangling one reports ``False``, so a
    symlinked date would otherwise reach ``os.replace``/``read_text`` and raise
    a bare ``NotADirectoryError`` (or read through the link).
    """
    path = steps_dir / day
    if path.is_symlink():
        raise StoreError(
            "step_corrupt",
            f"step {day} for account {account_id!r} is a symbolic link; refusing to follow it",
        )
    if path.exists() and not path.is_dir():
        raise StoreError(
            "step_corrupt",
            f"step {day} for account {account_id!r} exists but is not a directory",
        )
    return path


class AccountNotFound(StoreError):
    def __init__(self, account_id: str) -> None:
        super().__init__("account_not_found", f"no paper-trade account {account_id!r} in this store")


class AccountExists(StoreError):
    def __init__(self, account_id: str) -> None:
        super().__init__("account_exists", f"paper-trade account {account_id!r} already exists")


class StepExists(StoreError):
    def __init__(self, account_id: str, trade_date: str) -> None:
        super().__init__(
            "step_exists",
            f"step {trade_date} for account {account_id!r} already exists; "
            "steps are append-only and are never overwritten",
        )


class StepNotFound(StoreError):
    def __init__(self, account_id: str, trade_date: str) -> None:
        super().__init__("step_not_found", f"no step {trade_date} for account {account_id!r}")


class AccountLocked(StoreError):
    def __init__(self, account_id: str) -> None:
        super().__init__(
            "account_locked",
            f"account {account_id!r} is locked by another paper-trade step; refusing to run "
            "concurrently (this call did not wait)",
        )


@dataclass(frozen=True, slots=True)
class StepRecord:
    """One materialized step directory (parsed ``step.json`` + manifest)."""

    account_id: str
    trade_date: str
    directory: Path
    step: Mapping[str, Any]
    manifest: Mapping[str, Any]

    @property
    def engine_fingerprint(self) -> str:
        return str(self.step.get("engine_fingerprint") or "")

    @property
    def input_state_hash(self) -> str:
        return str(self.step.get("input_state_hash") or "")

    @property
    def end_state_hash(self) -> str:
        return str(self.step.get("end_state_hash") or "")

    @property
    def end_state(self) -> Any:
        try:
            return parse_account_state(self.step.get("end_state"), "end_state")
        except PaperTradeSchemaError as exc:
            raise StoreError("step_corrupt", f"step {self.trade_date}: {exc}") from exc


def _lock_fd(fd: int, account_id: str) -> None:
    """Acquire the account lock or raise :class:`AccountLocked` immediately."""
    if fcntl is not None:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in (errno.EACCES, errno.EAGAIN):
                raise AccountLocked(account_id) from exc
            raise
        return
    if msvcrt is not None:  # pragma: no cover - exercised on Windows only
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise AccountLocked(account_id) from exc
        return
    raise StoreError(
        "lock_unavailable",
        "no advisory file locking primitive is available on this platform; refusing to run an "
        "account step without concurrency protection",
    )


def _unlock_fd(fd: int) -> None:
    try:
        if fcntl is not None:
            fcntl.flock(fd, fcntl.LOCK_UN)
        elif msvcrt is not None:  # pragma: no cover - Windows only
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    except OSError:  # closing the descriptor releases the lock regardless
        pass


class AccountStore:
    """A directory of paper-trade accounts (default: the runtime root).

    ``base_dir`` is injected by every test; production leaves it unset so the
    path resolves through ``VIBE_TRADING_HOME`` / ``~/.vibe-trading`` via
    :func:`get_runtime_root` — resolved at CONSTRUCTION, so a test that
    monkeypatches the environment after import still gets its own sandbox.
    """

    def __init__(self, base_dir: str | Path | None = None) -> None:
        self._base_dir = (
            Path(base_dir).expanduser()
            if base_dir is not None
            else get_runtime_root() / BASE_DIRNAME
        )

    @property
    def base_dir(self) -> Path:
        return self._base_dir

    @property
    def accounts_dir(self) -> Path:
        return self._base_dir / ACCOUNTS_DIRNAME

    def account_dir(self, account_id: str) -> Path:
        return self.accounts_dir / validate_account_id(account_id)

    def account_path(self, account_id: str) -> Path:
        return self.account_dir(account_id) / ACCOUNT_FILE

    def steps_dir(self, account_id: str) -> Path:
        return self.account_dir(account_id) / STEPS_DIRNAME

    def step_dir(self, account_id: str, trade_date: str) -> Path:
        return self.steps_dir(account_id) / require_date(trade_date, "trade_date")

    # ── account lifecycle ──

    def create(self, account: PaperTradeAccount) -> Path:
        """Create the account tree and write ``account.json`` exactly once."""
        if account.watermark is not None:
            raise StoreError(
                "invalid_account", "a freshly created account must not carry a watermark"
            )
        self.accounts_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        # ``parents=True`` applies ``mode`` to the leaf only, so the directory
        # that lists every account id would otherwise keep the umask default.
        os.chmod(self._base_dir, 0o700)
        os.chmod(self.accounts_dir, 0o700)
        directory = self.account_dir(account.account_id)
        directory.mkdir(exist_ok=True, mode=0o700)
        self.steps_dir(account.account_id).mkdir(exist_ok=True, mode=0o700)
        with self.lock(account.account_id):
            if self.account_path(account.account_id).exists():
                raise AccountExists(account.account_id)
            self.save_account_atomic(account)
        return directory

    def load(self, account_id: str) -> PaperTradeAccount:
        path = self.account_path(account_id)
        if not path.is_file():
            raise AccountNotFound(account_id)
        try:
            return PaperTradeAccount.from_dict(read_json(path, "account_corrupt"))
        except AccountError as exc:
            raise StoreError(
                "account_corrupt", f"account.json for {account_id}: {exc.message}"
            ) from exc

    def save_account_atomic(self, account: PaperTradeAccount) -> Path:
        """Replace ``account.json`` atomically (temp file + rename + fsync).

        Refuses an id that was never :meth:`create`-d: silently materializing a
        directory from a typo would leave a half-account behind.
        """
        if not self.account_dir(account.account_id).is_dir():
            raise AccountNotFound(account.account_id)
        path = self.account_path(account.account_id)
        atomic_write(path, (dumps(account.to_dict()) + "\n").encode("utf-8"))
        return path

    # ── steps ──

    def write_step(
        self,
        account_id: str,
        trade_date: str,
        *,
        step: Mapping[str, Any],
        orders: Sequence[Any] = (),
        fills: Sequence[Any] = (),
        rejected: Sequence[Any] = (),
        canceled: Sequence[Any] = (),
        positions: Sequence[Any] = (),
        events: Sequence[Any] = (),
        bars: Mapping[str, str] | None = None,
    ) -> StepRecord:
        """Assemble one step directory under a staging name and rename it.

        Raises :class:`StepExists` when the date is already materialized: a
        stored step is evidence of what the account actually did, so silently
        rewriting it would disconnect the ledger from its own history.
        """
        account_id = validate_account_id(account_id)
        day = require_date(trade_date, "trade_date")
        steps_dir = self.steps_dir(account_id)
        if not steps_dir.is_dir():
            raise AccountNotFound(account_id)
        final = _step_path(steps_dir, account_id, day)
        if final.exists():
            raise StepExists(account_id, day)
        document = dict(step)
        if document.get("account_id") not in (None, account_id):
            raise StoreError("step_mismatch", "step.account_id does not match the target account")
        if document.get("trade_date") not in (None, day):
            raise StoreError("step_mismatch", "step.trade_date does not match the target date")
        document["account_id"] = account_id
        document["trade_date"] = day

        files = {
            STEP_FILE: (dumps(document) + "\n").encode("utf-8"),
            "orders.jsonl": jsonl(orders),
            "fills.jsonl": jsonl(fills),
            "rejected.jsonl": jsonl(rejected),
            "canceled.jsonl": jsonl(canceled),
            "positions.jsonl": jsonl(positions),
            "events.jsonl": jsonl(events),
        }
        try:
            write_step_directory(
                final,
                files=files,
                bars=bars,
                manifest_fields={
                    "account_id": account_id,
                    "trade_date": day,
                    "created_at": document.get("created_at", ""),
                },
            )
        except OSError as exc:
            if final.exists():
                raise StepExists(account_id, day) from exc
            raise
        return self.read_step(account_id, day)

    def read_step(self, account_id: str, trade_date: str) -> StepRecord:
        day = require_date(trade_date, "trade_date")
        directory = _step_path(self.steps_dir(account_id), account_id, day)
        step_path = directory / STEP_FILE
        if not step_path.is_file():
            raise StepNotFound(account_id, day)
        step = read_json(step_path, "step_corrupt")
        if not isinstance(step, dict):
            raise StoreError("step_corrupt", f"{step_path} is not a JSON object")
        if step.get("trade_date") not in (None, day):
            raise StoreError(
                "step_corrupt", f"{step_path} carries trade_date {step.get('trade_date')!r}"
            )
        manifest_path = directory / MANIFEST_FILE
        manifest = read_json(manifest_path, "step_corrupt") if manifest_path.is_file() else {}
        return StepRecord(account_id, day, directory, step, manifest)

    def list_steps(self, account_id: str) -> tuple[str, ...]:
        steps_dir = self.steps_dir(account_id)
        if not steps_dir.is_dir():
            return ()
        return tuple(
            sorted(
                path.name
                for path in steps_dir.iterdir()
                if path.is_dir()
                and _STEP_DIR_RE.match(path.name)
                and (path / STEP_FILE).is_file()
            )
        )

    def verify_step(self, record: StepRecord) -> tuple[str, ...]:
        """Return manifest mismatches (``missing:`` / ``sha256:`` / ``lines:``)."""
        return verify_files(record.directory, record.manifest)

    # ── lock ──

    @contextmanager
    def lock(self, account_id: str) -> Iterator[None]:
        """Hold the account lock for the ``with`` block (non-blocking).

        Raises :class:`AccountLocked` immediately when another holder exists —
        never waits, so a hung or long-running writer cannot stall the caller.
        The descriptor is closed (and the lock released) on every exit path,
        including an exception inside the block.
        """
        directory = self.account_dir(account_id)
        if not directory.is_dir():
            raise AccountNotFound(account_id)
        fd = os.open(str(directory / LOCK_FILE), os.O_RDWR | os.O_CREAT, 0o600)
        try:
            if msvcrt is not None and os.fstat(fd).st_size == 0:  # pragma: no cover
                try:
                    os.write(fd, b"\0")
                except OSError:
                    pass
            _lock_fd(fd, account_id)
            try:
                yield
            finally:
                _unlock_fd(fd)
        finally:
            os.close(fd)

    # ── crash recovery ──

    def recover(self, account_id: str, *, now: str, lock_held: bool = False) -> RecoveryResult:
        """Reconcile a crash between the step write and the account write.

        ``lock_held=True`` is for :mod:`runner`, which already owns the lock for
        the step it is performing; flock is per open file description, so a
        nested acquisition from the same thread would block rather than
        re-enter.  See :mod:`recovery` for the decision rules.
        """
        if lock_held:
            return recover_locked(self, account_id, now)
        with self.lock(account_id):
            return recover_locked(self, account_id, now)
