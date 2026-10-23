"""T5 — append-only account store (``store.py`` + ``storage_io.py``).

Every test injects a temporary ``base_dir``; the default resolution test proves
``VIBE_TRADING_HOME`` / the sandboxed ``~/.vibe-trading`` are honoured without
ever writing to the developer's real home.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from src.config.paths import get_runtime_root
from src.tools.paper_trade.account import create_account
from src.tools.paper_trade.schema import AccountState
from src.tools.paper_trade.state_hash import state_hash
from src.tools.paper_trade.storage_io import verify_files, write_step_directory
from src.tools.paper_trade.store import (
    ACCOUNT_FILE,
    MANIFEST_FILE,
    STEP_FILE,
    AccountExists,
    AccountLocked,
    AccountNotFound,
    AccountStore,
    StepExists,
    StepNotFound,
    StoreError,
)

AGENT_DIR = Path(__file__).resolve().parent.parent
TODAY = "2026-03-02"
NOW = "2026-03-02T15:05:00+08:00"
ACCOUNT_ID = "acct_store"


def _account(**overrides):
    kwargs = {
        "account_id": ACCOUNT_ID,
        "market": "cn_a",
        "start_date": TODAY,
        "initial_cash": 100000.0,
        "today": TODAY,
        "next_trading_day": "2026-03-03",
        "now": NOW,
    }
    kwargs.update(overrides)
    return create_account(**kwargs)


def _store(tmp_path: Path) -> AccountStore:
    return AccountStore(tmp_path / "paper_trade")


def _step_document(account, day: str, cash: float, *, input_hash: str | None = None):
    end_state = {"cash": cash, "positions": []}
    return {
        "account_id": account.account_id,
        "trade_date": day,
        "input_state": account.state_payload(),
        "input_state_hash": account.state_digest() if input_hash is None else input_hash,
        "end_state": end_state,
        "end_state_hash": state_hash(end_state),
        "engine_fingerprint": "fp-test",
        "created_at": NOW,
    }


# ── create / load / save ──


def test_create_writes_the_plan_layout_and_load_round_trips(tmp_path: Path) -> None:
    store = _store(tmp_path)
    account = _account()
    directory = store.create(account)

    assert directory == store.account_dir(ACCOUNT_ID)
    assert (directory / ACCOUNT_FILE).is_file()
    assert (directory / "steps").is_dir()
    assert store.load(ACCOUNT_ID) == account
    document = json.loads((directory / ACCOUNT_FILE).read_text(encoding="utf-8"))
    assert document["account_id"] == ACCOUNT_ID
    assert document["watermark"] is None
    assert (directory / ACCOUNT_FILE).read_text(encoding="utf-8").endswith("\n")


def test_create_is_exclusive(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create(_account())
    with pytest.raises(AccountExists) as excinfo:
        store.create(_account())
    assert excinfo.value.code == "account_exists"


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits")
def test_account_directories_are_owner_only_despite_the_umask(tmp_path: Path) -> None:
    previous = os.umask(0o022)
    try:
        store = _store(tmp_path)
        store.create(_account())
    finally:
        os.umask(previous)
    assert stat.S_IMODE(store.base_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(store.accounts_dir.stat().st_mode) == 0o700


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits")
def test_create_tightens_a_preexisting_accounts_directory(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.accounts_dir.mkdir(parents=True)
    os.chmod(store.accounts_dir, 0o755)
    store.create(_account())
    assert stat.S_IMODE(store.accounts_dir.stat().st_mode) == 0o700


def test_create_refuses_a_watermarked_account(tmp_path: Path) -> None:
    store = _store(tmp_path)
    watermarked = _account().with_non_trading_day(TODAY)
    with pytest.raises(StoreError) as excinfo:
        store.create(watermarked)
    assert excinfo.value.code == "invalid_account"


def test_load_missing_account_reports_a_stable_code(tmp_path: Path) -> None:
    with pytest.raises(AccountNotFound) as excinfo:
        _store(tmp_path).load("nope")
    assert excinfo.value.code == "account_not_found"


def test_save_refuses_an_account_that_was_never_created(tmp_path: Path) -> None:
    with pytest.raises(AccountNotFound):
        _store(tmp_path).save_account_atomic(_account())
    assert not _store(tmp_path).account_dir(ACCOUNT_ID).exists()


def test_atomic_save_leaves_no_temp_files(tmp_path: Path) -> None:
    store = _store(tmp_path)
    account = store.create(_account()) or None
    loaded = store.load(ACCOUNT_ID)
    store.save_account_atomic(loaded.with_non_trading_day(TODAY))
    directory = store.account_dir(ACCOUNT_ID)
    assert [path.name for path in directory.iterdir() if path.name.startswith(".tmp-")] == []
    assert store.load(ACCOUNT_ID).watermark == TODAY
    assert account is not None


# ── steps ──


def test_write_step_materializes_every_file_and_a_complete_manifest(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create(_account())
    account = store.load(ACCOUNT_ID)
    record = store.write_step(
        ACCOUNT_ID,
        TODAY,
        step=_step_document(account, TODAY, 99000.0),
        orders=[{"symbol": "600519.SH", "side": "buy", "qty": 100}],
        fills=({"trade_date": TODAY, "symbol": "600519.SH", "side": "buy", "qty": 100},),
        rejected=(),
        canceled=(),
        positions=[{"trade_date": TODAY, "symbol": "600519.SH", "qty": 100, "avg_cost": 10.0}],
        events=[{"trade_date": TODAY, "event_type": "auction_window"}],
        bars={"600519.SH": "trade_date,open,high,low,close\n2026-03-02,1,2,0.5,1.5\n"},
    )

    expected = {
        STEP_FILE,
        MANIFEST_FILE,
        "orders.jsonl",
        "fills.jsonl",
        "rejected.jsonl",
        "canceled.jsonl",
        "positions.jsonl",
        "events.jsonl",
        "bars/600519.SH.csv",
    }
    assert {path.relative_to(record.directory).as_posix() for path in record.directory.rglob("*") if path.is_file()} == expected
    assert record.step["trade_date"] == TODAY
    assert record.step["input_state_hash"] == account.state_digest()

    manifest = json.loads((record.directory / MANIFEST_FILE).read_text(encoding="utf-8"))
    assert set(manifest["files"]) == expected - {MANIFEST_FILE}
    assert manifest["excludes"] == [MANIFEST_FILE]
    assert store.verify_step(record) == ()

    step_bytes = (record.directory / STEP_FILE).read_bytes()
    assert manifest["files"][STEP_FILE] == {
        "sha256": hashlib.sha256(step_bytes).hexdigest(),
        "lines": step_bytes.count(b"\n"),
        "bytes": len(step_bytes),
    }
    assert manifest["files"]["fills.jsonl"]["lines"] == 1
    assert manifest["files"]["rejected.jsonl"]["lines"] == 0


def test_write_step_never_overwrites_an_existing_step(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create(_account())
    account = store.load(ACCOUNT_ID)
    first = store.write_step(ACCOUNT_ID, TODAY, step=_step_document(account, TODAY, 99000.0))
    before = (first.directory / STEP_FILE).read_bytes()

    with pytest.raises(StepExists) as excinfo:
        store.write_step(ACCOUNT_ID, TODAY, step=_step_document(account, TODAY, 1.0))
    assert excinfo.value.code == "step_exists"
    assert (first.directory / STEP_FILE).read_bytes() == before


def test_write_step_refuses_a_mismatched_document(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create(_account())
    account = store.load(ACCOUNT_ID)
    document = _step_document(account, TODAY, 99000.0)
    document["trade_date"] = "2026-03-03"
    with pytest.raises(StoreError) as excinfo:
        store.write_step(ACCOUNT_ID, TODAY, step=document)
    assert excinfo.value.code == "step_mismatch"


def test_unsafe_bar_symbol_is_refused_and_leaves_no_residue(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create(_account())
    account = store.load(ACCOUNT_ID)
    with pytest.raises(StoreError) as excinfo:
        store.write_step(
            ACCOUNT_ID,
            TODAY,
            step=_step_document(account, TODAY, 1.0),
            bars={"../../etc/passwd": "x\n"},
        )
    assert excinfo.value.code == "invalid_bar_symbol"
    steps_dir = store.steps_dir(ACCOUNT_ID)
    assert list(steps_dir.iterdir()) == []


def test_manifest_verification_detects_tampering(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create(_account())
    account = store.load(ACCOUNT_ID)
    record = store.write_step(ACCOUNT_ID, TODAY, step=_step_document(account, TODAY, 1.0))
    (record.directory / "fills.jsonl").write_text('{"tampered":true}\n', encoding="utf-8")
    assert "sha256:fills.jsonl" in store.verify_step(record)


def test_manifest_verification_fails_closed_without_a_manifest(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create(_account())
    account = store.load(ACCOUNT_ID)
    record = store.write_step(ACCOUNT_ID, TODAY, step=_step_document(account, TODAY, 1.0))
    (record.directory / "manifest.json").unlink()

    reread = store.read_step(ACCOUNT_ID, TODAY)
    assert store.verify_step(reread) == ("manifest:<files>",)


def test_manifest_verification_refuses_paths_outside_the_step(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create(_account())
    account = store.load(ACCOUNT_ID)
    record = store.write_step(ACCOUNT_ID, TODAY, step=_step_document(account, TODAY, 1.0))

    outsider = tmp_path / "outside.txt"
    outsider.write_text("outside the step\n", encoding="utf-8")
    entry = {
        "sha256": hashlib.sha256(outsider.read_bytes()).hexdigest(),
        "lines": 1,
        "bytes": outsider.stat().st_size,
    }
    keys = ("../outside.txt", str(outsider), "bars/../../outside.txt")
    problems = verify_files(record.directory, {"files": {key: entry for key in keys}})

    # The outsider exists and matches the forged digest: a read would have been
    # silently accepted, so only the path guard can produce these problems.
    assert set(problems) == {f"path:{key}" for key in keys}
    assert store.verify_step(record) == ()


def test_write_step_directory_refuses_a_symlinked_target(tmp_path: Path) -> None:
    target = tmp_path / TODAY
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        target.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are not available on this platform")

    with pytest.raises(StoreError) as excinfo:
        write_step_directory(
            target, files={"step.json": b"{}\n"}, manifest_fields={"account_id": ACCOUNT_ID}
        )
    assert excinfo.value.code == "step_corrupt"
    assert list(outside.iterdir()) == []
    assert target.is_symlink()
    assert [path.name for path in tmp_path.iterdir() if path.name.startswith(".staging-")] == []


def test_list_steps_is_sorted_and_ignores_residue(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create(_account())
    account = store.load(ACCOUNT_ID)
    for day in ("2026-03-03", TODAY):
        store.write_step(ACCOUNT_ID, day, step=_step_document(account, day, 1.0))
    (store.steps_dir(ACCOUNT_ID) / ".staging-junk").mkdir()
    (store.steps_dir(ACCOUNT_ID) / "not-a-date").mkdir()
    assert store.list_steps(ACCOUNT_ID) == (TODAY, "2026-03-03")


def test_read_step_missing_date(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create(_account())
    with pytest.raises(StepNotFound) as excinfo:
        store.read_step(ACCOUNT_ID, TODAY)
    assert excinfo.value.code == "step_not_found"


def test_step_directory_symlink_is_refused(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create(_account())
    outside = tmp_path / "outside-step"
    outside.mkdir()
    link = store.steps_dir(ACCOUNT_ID) / TODAY
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are not available on this platform")

    with pytest.raises(StoreError) as excinfo:
        store.read_step(ACCOUNT_ID, TODAY)
    assert excinfo.value.code == "step_corrupt"

    account = store.load(ACCOUNT_ID)
    with pytest.raises(StoreError) as excinfo:
        store.write_step(ACCOUNT_ID, TODAY, step=_step_document(account, TODAY, 1.0))
    assert excinfo.value.code == "step_corrupt"
    assert list(outside.iterdir()) == []
    assert link.is_symlink()


def test_dangling_step_symlink_is_refused(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create(_account())
    link = store.steps_dir(ACCOUNT_ID) / TODAY
    try:
        link.symlink_to(tmp_path / "does-not-exist", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are not available on this platform")
    assert not link.exists()

    with pytest.raises(StoreError) as excinfo:
        store.read_step(ACCOUNT_ID, TODAY)
    assert excinfo.value.code == "step_corrupt"

    account = store.load(ACCOUNT_ID)
    with pytest.raises(StoreError) as excinfo:
        store.write_step(ACCOUNT_ID, TODAY, step=_step_document(account, TODAY, 1.0))
    assert excinfo.value.code == "step_corrupt"
    assert link.is_symlink()


def test_step_path_that_is_not_a_directory_is_refused(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create(_account())
    blocker = store.steps_dir(ACCOUNT_ID) / TODAY
    blocker.write_text("not a step directory\n", encoding="utf-8")

    with pytest.raises(StoreError) as excinfo:
        store.read_step(ACCOUNT_ID, TODAY)
    assert excinfo.value.code == "step_corrupt"

    account = store.load(ACCOUNT_ID)
    with pytest.raises(StoreError) as excinfo:
        store.write_step(ACCOUNT_ID, TODAY, step=_step_document(account, TODAY, 1.0))
    assert excinfo.value.code == "step_corrupt"
    assert blocker.read_text(encoding="utf-8") == "not a step directory\n"


# ── lock ──


def test_lock_is_exclusive_within_a_process(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create(_account())
    with store.lock(ACCOUNT_ID):
        with pytest.raises(AccountLocked) as excinfo:
            with store.lock(ACCOUNT_ID):
                pass
    assert excinfo.value.code == "account_locked"
    # Released: the next acquisition succeeds immediately.
    with store.lock(ACCOUNT_ID):
        pass


def test_lock_is_released_when_the_block_raises(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create(_account())
    with pytest.raises(RuntimeError, match="boom"):
        with store.lock(ACCOUNT_ID):
            raise RuntimeError("boom")
    with store.lock(ACCOUNT_ID):
        pass


def test_lock_on_a_missing_account(tmp_path: Path) -> None:
    with pytest.raises(AccountNotFound):
        with _store(tmp_path).lock("nope"):
            pass


_CHILD_LOCK_PROBE = """
import sys
import time
from src.tools.paper_trade.store import AccountLocked, AccountStore

store = AccountStore(sys.argv[1])
started = time.monotonic()
try:
    with store.lock(sys.argv[2]):
        print("acquired")
except AccountLocked:
    print(f"locked {(time.monotonic() - started) * 1000:.3f}")
"""


def test_lock_is_exclusive_across_processes_and_fails_fast(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create(_account())
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(filter(None, (str(AGENT_DIR), os.environ.get("PYTHONPATH", ""))))}
    with store.lock(ACCOUNT_ID):
        completed = subprocess.run(
            [sys.executable, "-c", _CHILD_LOCK_PROBE, str(store.base_dir), ACCOUNT_ID],
            capture_output=True,
            text=True,
            timeout=20,
            env=env,
            check=False,
        )
    assert completed.returncode == 0, completed.stderr
    stdout = completed.stdout.strip()
    assert stdout.startswith("locked "), stdout
    # The child measures its OWN lock attempt: interpreter startup and import
    # cost are excluded, so this asserts fail-fast rather than parent wall clock.
    # A blocking child would still exceed the subprocess timeout above.
    assert float(stdout.split()[1]) < 5000


# ── recovery ──


def test_recover_is_clean_on_a_fresh_account(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create(_account())
    result = store.recover(ACCOUNT_ID, now=NOW)
    assert result.status == "clean"
    assert result.watermark is None
    assert not (store.account_dir(ACCOUNT_ID) / "recovery.json").exists()


def test_recover_adopts_an_orphaned_step_whose_input_matches(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create(_account())
    account = store.load(ACCOUNT_ID)
    store.write_step(ACCOUNT_ID, TODAY, step=_step_document(account, TODAY, 99000.0))

    result = store.recover(ACCOUNT_ID, now=NOW)
    assert result.status == "adopted"
    assert result.trade_date == TODAY
    assert result.watermark == TODAY
    assert result.account.cash == 99000.0
    assert store.load(ACCOUNT_ID).cash == 99000.0

    marker = json.loads((store.account_dir(ACCOUNT_ID) / "recovery.json").read_text(encoding="utf-8"))
    assert marker["action"] == "adopted_orphaned_step"
    assert marker["adopted_trade_date"] == TODAY
    assert marker["previous_watermark"] is None
    assert marker["account_state_hash"] == account.state_digest()


def test_recover_refuses_a_step_that_started_from_another_ledger(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create(_account())
    account = store.load(ACCOUNT_ID)
    store.write_step(
        ACCOUNT_ID, TODAY, step=_step_document(account, TODAY, 1.0, input_hash="deadbeef")
    )
    before = (store.account_dir(ACCOUNT_ID) / ACCOUNT_FILE).read_bytes()

    result = store.recover(ACCOUNT_ID, now=NOW)
    assert result.status == "recovery_required"
    assert result.code == "state_mismatch"
    assert "deadbeef" in result.message
    assert result.watermark is None
    assert (store.account_dir(ACCOUNT_ID) / ACCOUNT_FILE).read_bytes() == before


def test_recover_refuses_two_steps_ahead(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create(_account())
    account = store.load(ACCOUNT_ID)
    store.write_step(ACCOUNT_ID, TODAY, step=_step_document(account, TODAY, 1.0))
    store.write_step(ACCOUNT_ID, "2026-03-03", step=_step_document(account, "2026-03-03", 2.0))

    result = store.recover(ACCOUNT_ID, now=NOW)
    assert result.status == "recovery_required"
    assert result.code == "multiple_steps_ahead"
    assert "2026-03-02, 2026-03-03" in result.message


def test_recover_cleans_staging_and_temp_residue(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create(_account())
    staging = store.steps_dir(ACCOUNT_ID) / ".staging-2026-03-02-abcd"
    staging.mkdir()
    (staging / "step.json").write_text("{}\n", encoding="utf-8")
    temp = store.account_dir(ACCOUNT_ID) / ".tmp-account.json-xyz"
    temp.write_text("partial", encoding="utf-8")

    result = store.recover(ACCOUNT_ID, now=NOW)
    assert result.status == "clean"
    assert "steps/.staging-2026-03-02-abcd" in result.cleaned
    assert not staging.exists()
    assert not temp.exists()


def test_recover_refuses_an_account_that_diverged_from_its_last_step(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create(_account())
    account = store.load(ACCOUNT_ID)
    store.write_step(ACCOUNT_ID, TODAY, step=_step_document(account, TODAY, 99000.0))
    store.save_account_atomic(
        account.with_advance(end_state=AccountState(cash=99000.0), watermark=TODAY)
    )
    assert store.recover(ACCOUNT_ID, now=NOW).status == "clean"

    store.save_account_atomic(dataclasses.replace(store.load(ACCOUNT_ID), cash=123.0))
    mismatch = store.recover(ACCOUNT_ID, now=NOW)
    assert mismatch.status == "recovery_required"
    assert mismatch.code == "state_mismatch"
    assert "end_state_hash" in mismatch.message


# ── default root resolution (never the real home) ──


def test_default_base_dir_honours_vibe_trading_home(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("VIBE_TRADING_HOME", str(tmp_path / "runtime"))
    assert AccountStore().base_dir == tmp_path / "runtime" / "paper_trade"


def test_default_base_dir_falls_back_to_the_sandboxed_home(monkeypatch) -> None:
    monkeypatch.delenv("VIBE_TRADING_HOME", raising=False)
    expected = get_runtime_root() / "paper_trade"
    assert AccountStore().base_dir == expected
    assert str(expected).startswith(str(Path.home()))


# ── Identity and link guards (the ledger must describe the thing it names) ──


def test_load_refuses_a_mislabelled_account_json(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create(_account())
    path = store.account_path(ACCOUNT_ID)
    document = json.loads(path.read_text("utf-8"))
    document["account_id"] = "someone_else"
    path.write_text(json.dumps(document), "utf-8")

    with pytest.raises(StoreError) as caught:
        store.load(ACCOUNT_ID)
    assert caught.value.code == "account_corrupt"
    assert "someone_else" in caught.value.message


def test_read_step_refuses_a_mislabelled_step(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create(_account())
    account = store.load(ACCOUNT_ID)
    store.write_step(ACCOUNT_ID, TODAY, step=_step_document(account, TODAY, 99999.0))
    step_path = store.step_dir(ACCOUNT_ID, TODAY) / STEP_FILE
    document = json.loads(step_path.read_text("utf-8"))
    document["account_id"] = "someone_else"
    step_path.write_text(json.dumps(document), "utf-8")

    with pytest.raises(StoreError) as caught:
        store.read_step(ACCOUNT_ID, TODAY)
    assert caught.value.code == "step_corrupt"
    assert "someone_else" in caught.value.message


def test_account_directory_symlink_is_refused(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.accounts_dir.mkdir(parents=True, exist_ok=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    target = store.accounts_dir / "linked"
    target.symlink_to(outside, target_is_directory=True)

    with pytest.raises(StoreError) as caught:
        store.load("linked")
    assert caught.value.code == "account_corrupt"
    assert "symbolic link" in caught.value.message


def test_lock_file_symlink_is_refused(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create(_account())
    outside = tmp_path / "outside.lock"
    outside.write_text("", "utf-8")
    lock_path = store.account_dir(ACCOUNT_ID) / ".lock"
    lock_path.unlink(missing_ok=True)
    lock_path.symlink_to(outside)

    with pytest.raises(StoreError) as caught:
        with store.lock(ACCOUNT_ID):
            pass
    assert caught.value.code == "account_corrupt"
    assert "symbolic link" in caught.value.message
