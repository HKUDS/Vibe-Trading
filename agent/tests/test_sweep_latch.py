"""Tests for the restart-persistent preemptive-sweep latch.

The HALT sentinel is a file and survives restarts; the runner's in-memory
``_flatten_fired`` does not. The latch (src/live/runtime/sweep_latch.py) binds
the sweep's firing to the halt episode that caused it, so a restarted runner
with flatten orders still working does not replay the sweep, while a fresh
halt episode re-arms it.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Mapping

import pytest

from src.live import paths
from src.live.halt import broker_halt_path, clear_halt, halt_path
from src.live.runtime import sweep_latch
from src.live.runtime.runner import LiveRunner

BROKER = "robinhood"


@pytest.fixture
def live_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the live runtime root at an isolated tmp dir."""
    monkeypatch.setattr(paths, "get_runtime_root", lambda: tmp_path)
    return tmp_path


def _trip_with_timestamp(broker: str | None, tripped_at: str) -> None:
    path = broker_halt_path(broker) if broker else halt_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"tripped_at": tripped_at, "by": "cli", "reason": "test"}),
        encoding="utf-8",
    )


def _any_latch_files() -> bool:
    """True when any per-episode/legacy latch file exists for BROKER."""
    d = sweep_latch.latch_path(BROKER).parent
    return any(p.name.startswith("FLATTEN_FIRED") for p in d.glob("FLATTEN_FIRED*"))


def test_newer_global_halt_rearms_with_tied_mtimes(live_root: Path) -> None:
    # Regression for the combined-suite flake: broker + global sentinels
    # written within one filesystem timestamp quantum share an mtime.
    # Episode resolution must still rank by tripped_at (global wins), not
    # fall back to mtime order — otherwise the sweep for the newer global
    # halt is wrongly suppressed.
    _trip_with_timestamp(BROKER, "2026-08-27T01:00:00+00:00")
    sweep_latch.mark_sweep_fired(BROKER)
    assert sweep_latch.sweep_already_fired(BROKER) is True

    _trip_with_timestamp(None, "2026-08-27T10:00:00+00:00")
    stat = broker_halt_path(BROKER).stat()
    for path in (broker_halt_path(BROKER), halt_path()):
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))

    assert sweep_latch.sweep_already_fired(BROKER) is False  # global wins
    sweep_latch.mark_sweep_fired(BROKER)
    assert sweep_latch.sweep_already_fired(BROKER) is True


def test_mark_then_fired_for_same_episode(live_root: Path) -> None:
    _trip_with_timestamp(BROKER, "2026-08-27T01:00:00+00:00")
    assert sweep_latch.sweep_already_fired(BROKER) is False
    sweep_latch.mark_sweep_fired(BROKER)
    assert sweep_latch.sweep_already_fired(BROKER) is True


def test_fresh_halt_episode_rearms(live_root: Path) -> None:
    _trip_with_timestamp(BROKER, "2026-08-27T01:00:00+00:00")
    sweep_latch.mark_sweep_fired(BROKER)
    assert sweep_latch.sweep_already_fired(BROKER) is True
    # The operator clears the halt and a later incident trips it again: the
    # latch from the first episode must not suppress the second sweep.
    clear_halt(BROKER)
    _trip_with_timestamp(BROKER, "2026-08-27T09:30:00+00:00")
    assert sweep_latch.sweep_already_fired(BROKER) is False


def test_mark_without_halt_is_noop(live_root: Path) -> None:
    sweep_latch.mark_sweep_fired(BROKER)
    assert not _any_latch_files()


def test_hand_touched_halt_binds_via_mtime(live_root: Path) -> None:
    # A bare `touch` produces a sentinel with no JSON payload; the latch must
    # still bind to the episode (via the file mtime) rather than never firing.
    path = broker_halt_path(BROKER)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    assert sweep_latch.sweep_already_fired(BROKER) is False
    sweep_latch.mark_sweep_fired(BROKER)
    assert sweep_latch.sweep_already_fired(BROKER) is True


def test_global_halt_episode_visible_to_broker(live_root: Path) -> None:
    _trip_with_timestamp(None, "2026-08-27T02:00:00+00:00")
    sweep_latch.mark_sweep_fired(BROKER)
    assert sweep_latch.sweep_already_fired(BROKER) is True


def test_corrupt_latch_falls_back_to_not_fired(live_root: Path) -> None:
    _trip_with_timestamp(BROKER, "2026-08-27T01:00:00+00:00")
    latch = sweep_latch.latch_path(BROKER)
    latch.parent.mkdir(parents=True, exist_ok=True)
    latch.write_text("{not json", encoding="utf-8")
    assert sweep_latch.sweep_already_fired(BROKER) is False


def _build_runner(
    live_root: Path, fired: list[str], flatten_fn: Any = None
) -> LiveRunner:
    """A runner whose only observable behavior is recording sweep invocations."""
    async def _agent_caller(session_id: str, prompt: str) -> Mapping[str, Any]:
        return {"status": "success"}

    def _submit(request: dict[str, Any]) -> dict[str, Any]:
        return {"status": "ok"}

    def _default_flatten(broker, submit, read_positions, read_open_orders):
        fired.append(broker)
        return {"side_effects_attempted": True}

    def _audit(event) -> Mapping[str, Any]:
        return {"audit_id": "a1"}

    return LiveRunner(
        BROKER,
        agent_caller=_agent_caller,
        reconcile_fn=lambda *a, **k: None,
        read_positions=list,
        read_balance=list,
        read_open_orders=list,
        write_audit_fn=_audit,
        halt_flag_fn=lambda broker: True,
        submit_fn=_submit,
        flatten_fn=flatten_fn or _default_flatten,
        session_id="latch-test",
    )


def test_restart_does_not_replay_the_sweep(live_root: Path) -> None:
    _trip_with_timestamp(BROKER, "2026-08-27T01:00:00+00:00")
    fired: list[str] = []
    asyncio.run(_build_runner(live_root, fired).run_once())
    assert fired == [BROKER]
    # A new runner instance over the same runtime root (the restart): the
    # in-memory latch is gone, but the on-disk one suppresses the replay.
    asyncio.run(_build_runner(live_root, fired).run_once())
    assert fired == [BROKER]


def test_new_episode_after_restart_fires_again(live_root: Path) -> None:
    _trip_with_timestamp(BROKER, "2026-08-27T01:00:00+00:00")
    fired: list[str] = []
    asyncio.run(_build_runner(live_root, fired).run_once())
    clear_halt(BROKER)
    _trip_with_timestamp(BROKER, "2026-08-27T09:30:00+00:00")
    asyncio.run(_build_runner(live_root, fired).run_once())
    assert fired == [BROKER, BROKER]


def test_newer_global_halt_rearms_stale_broker_latch(live_root: Path) -> None:
    # A broker episode latched first; a NEWER global HALT must not be
    # suppressed — the global halt is authoritative (halt_flag_set), and a
    # stale per-broker latch must not skip the kill action for the new
    # episode. Clearing the global halt must not re-fire the sweep for the
    # already-swept broker episode either.
    _trip_with_timestamp(BROKER, "2026-08-27T01:00:00+00:00")
    sweep_latch.mark_sweep_fired(BROKER)
    assert sweep_latch.sweep_already_fired(BROKER) is True

    _trip_with_timestamp(None, "2026-08-27T10:00:00+00:00")
    assert sweep_latch.sweep_already_fired(BROKER) is False  # re-armed

    sweep_latch.mark_sweep_fired(BROKER)
    assert sweep_latch.sweep_already_fired(BROKER) is True
    clear_halt()  # global gone; only the old broker episode remains
    assert sweep_latch.sweep_already_fired(BROKER) is True  # still latched


def test_read_failure_does_not_latch_and_restart_replays(live_root: Path) -> None:
    # The reviewer-reported safety hole: a sweep whose broker-state read
    # failed must NOT persist the latch, or a restart suppresses the kill
    # action for the episode forever. The read failure is the flattened
    # report shape flatten_and_cancel now produces for an adapter error
    # envelope / non-list read.
    _trip_with_timestamp(BROKER, "2026-08-27T01:00:00+00:00")
    fired: list[str] = []

    def _flatten(broker, submit, read_positions, read_open_orders):
        fired.append(broker)
        return {"errors": [{"phase": "read_positions", "error": "broker read failed"}]}

    asyncio.run(_build_runner(live_root, fired, _flatten).run_once())
    assert fired == [BROKER]
    assert not sweep_latch.latch_path(BROKER, "2026-08-27T01:00:00+00:00").exists()  # not latched
    # Restart: the failed sweep must re-fire, not be suppressed.
    asyncio.run(_build_runner(live_root, fired, _flatten).run_once())
    assert fired == [BROKER, BROKER]


def test_nothing_to_do_does_not_latch_and_rechecks(live_root: Path) -> None:
    # Reads succeed but there are no open orders/positions: no broker write
    # was attempted, so per policy nothing must be latched — the sweep
    # re-checks on the next tick/restart (and would cancel a late-appearing
    # order), never suppressing the kill action for the episode.
    _trip_with_timestamp(BROKER, "2026-08-27T01:00:00+00:00")
    fired: list[str] = []

    def _flatten(broker, submit, read_positions, read_open_orders):
        fired.append(broker)
        return {"errors": []}  # reads ok, nothing to act on

    asyncio.run(_build_runner(live_root, fired, _flatten).run_once())
    assert fired == [BROKER]
    assert not sweep_latch.latch_path(BROKER, "2026-08-27T01:00:00+00:00").exists()
    asyncio.run(_build_runner(live_root, fired, _flatten).run_once())
    assert fired == [BROKER, BROKER]


def test_side_effect_attempted_latches_even_with_read_error(
    live_root: Path,
) -> None:
    # Reviewer sequence: order read fails, position read succeeds, a close
    # order is submitted. The report carries a read error AND a side effect.
    # Latching must key on the side effect: replaying that close after a
    # restart would be a duplicate market close (the failure the latch
    # exists to prevent).
    _trip_with_timestamp(BROKER, "2026-08-27T01:00:00+00:00")
    fired: list[str] = []

    def _flatten(broker, submit, read_positions, read_open_orders):
        fired.append(broker)
        return {
            "side_effects_attempted": True,
            "errors": [{"phase": "read_open_orders", "error": "orders read failed"}],
        }

    asyncio.run(_build_runner(live_root, fired, _flatten).run_once())
    assert fired == [BROKER]
    assert sweep_latch.latch_path(BROKER, "2026-08-27T01:00:00+00:00").exists()
    # Restart: the on-disk latch suppresses the duplicate close.
    asyncio.run(_build_runner(live_root, fired, _flatten).run_once())
    assert fired == [BROKER]


# ---------------------------------------------------------------------------
# Inter-process claim protocol (#1244 hardening)
# ---------------------------------------------------------------------------


def test_claim_is_exclusive_and_releasable(live_root: Path) -> None:
    ep = "2026-08-27T01:00:00+00:00"
    assert sweep_latch.claim_sweep(BROKER, ep) is True  # first wins
    assert sweep_latch.claim_sweep(BROKER, ep) is False  # second cannot claim
    sweep_latch.release_claim(BROKER, ep)
    assert sweep_latch.claim_sweep(BROKER, ep) is True  # claimable again
    sweep_latch.release_claim(BROKER, ep)


def test_orphan_claim_does_not_block_future_episode(live_root: Path) -> None:
    # Crash mid-sweep leaves a claim for episode 1 (never released). An
    # episode-keyed claim must NOT block episode 2: each trip gets its own
    # claim namespace, so a new halt still sweeps.
    _trip_with_timestamp(BROKER, "2026-08-27T01:00:00+00:00")
    ep1 = sweep_latch.halt_episode(BROKER)
    assert sweep_latch.claim_sweep(BROKER, ep1) is True  # crashed: never released
    clear_halt(BROKER)
    _trip_with_timestamp(BROKER, "2026-08-27T10:00:00+00:00")
    ep2 = sweep_latch.halt_episode(BROKER)
    assert ep2 != ep1
    assert sweep_latch.claim_sweep(BROKER, ep2) is True  # new episode claimable
    sweep_latch.release_claim(BROKER, ep2)


def test_runner_skips_when_claim_held_by_other_process(live_root: Path) -> None:
    # A second runner for the same broker must not sweep concurrently
    # (check-then-act would let both pass sweep_already_fired and duplicate
    # market closes). The held claim forces this process to skip + audit.
    _trip_with_timestamp(BROKER, "2026-08-27T01:00:00+00:00")
    ep = sweep_latch.halt_episode(BROKER)
    assert sweep_latch.claim_sweep(BROKER, ep) is True  # "other" process holds it
    fired: list[str] = []
    asyncio.run(_build_runner(live_root, fired).run_once())
    assert fired == []  # never swept
    assert not sweep_latch.latch_path(BROKER).exists()
    # The other process's claim must remain untouched (the runner must never
    # release a claim it does not own).
    assert sweep_latch.claim_path(BROKER, "2026-08-27T01:00:00+00:00").exists()
    sweep_latch.release_claim(BROKER, ep)


def test_runner_claims_and_releases_around_sweep(live_root: Path) -> None:
    _trip_with_timestamp(BROKER, "2026-08-27T01:00:00+00:00")
    fired: list[str] = []
    asyncio.run(_build_runner(live_root, fired).run_once())
    assert fired == [BROKER]
    # The claim must be released after the sweep (crash-free path), so a
    # later re-check can claim again.
    ep = sweep_latch.halt_episode(BROKER)
    assert not sweep_latch.claim_path(BROKER, ep).exists()


def test_runner_claim_released_after_read_failure(live_root: Path) -> None:
    _trip_with_timestamp(BROKER, "2026-08-27T01:00:00+00:00")
    fired: list[str] = []

    def _flatten(broker, submit, read_positions, read_open_orders):
        fired.append(broker)
        return {"errors": [{"phase": "read_positions", "error": "read failed"}]}

    asyncio.run(_build_runner(live_root, fired, _flatten).run_once())
    assert fired == [BROKER]
    ep = sweep_latch.halt_episode(BROKER)
    assert not sweep_latch.claim_path(BROKER, ep).exists()
    assert not sweep_latch.latch_path(BROKER, "2026-08-27T01:00:00+00:00").exists()


def test_mark_records_both_active_episodes_older_global_newer_broker(
    live_root: Path,
) -> None:
    # Reviewer residual A: the sweep covers the halt state as a whole — with
    # an older global AND a newer broker halt both active, clearing the
    # broker halt must NOT re-fire the sweep while the (still active, older)
    # global halt remains tripped. mark_sweep_fired must record BOTH
    # episodes.
    _trip_with_timestamp(None, "2026-08-27T01:00:00+00:00")  # global, older
    _trip_with_timestamp(BROKER, "2026-08-27T10:00:00+00:00")  # broker, newer
    sweep_latch.mark_sweep_fired(BROKER)
    assert sweep_latch.sweep_already_fired(BROKER) is True

    clear_halt(BROKER)  # newer (broker) halt cleared
    assert sweep_latch.sweep_already_fired(BROKER) is True  # global still recorded


def test_double_failure_latch_write_does_not_escape_run_once(
    live_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Reviewer residual B: sweep raises AND the durable latch write raises.
    # Neither exception may escape run_once — the tick must still complete
    # with the halted outcome and an audit trail.
    from src.live.runtime import runner as runner_mod

    _trip_with_timestamp(BROKER, "2026-08-27T01:00:00+00:00")
    fired: list[str] = []

    def _flatten(broker, submit, read_positions, read_open_orders):
        fired.append(broker)
        raise RuntimeError("sweep exploded")

    def _broken_mark(broker):
        raise RuntimeError("disk exploded")

    monkeypatch.setattr(runner_mod, "mark_sweep_fired", _broken_mark)
    result = asyncio.run(_build_runner(live_root, fired, _flatten).run_once())
    assert result["outcome"] == "halted"  # did not escape
    assert fired == [BROKER]


def test_mid_sweep_retrip_does_not_release_new_episode_claim(
    live_root: Path,
) -> None:
    # A halt is cleared + re-tripped while our sweep is in flight (ep1 ->
    # ep2), and a second process claims ep2. The ep1 owner's release must
    # delete only ITS claim — never the ep2 claim (re-resolving the episode
    # at release time would delete another process's protection and open a
    # duplicate-close window).
    _trip_with_timestamp(BROKER, "2026-08-27T01:00:00+00:00")
    captured: dict[str, str | None] = {}

    def _flatten(broker, submit, read_positions, read_open_orders):
        clear_halt(BROKER)
        _trip_with_timestamp(BROKER, "2026-08-27T10:00:00+00:00")
        ep2 = sweep_latch.halt_episode(BROKER)
        captured["ep2"] = ep2
        captured["other_claim"] = sweep_latch.claim_sweep(BROKER, ep2)
        return {"submitted": [], "errors": []}

    asyncio.run(_build_runner(live_root, [], _flatten).run_once())
    assert captured["other_claim"] is True
    # Other process's ep2 claim must survive the ep1 owner's release.
    assert sweep_latch.claim_path(BROKER, captured["ep2"]).exists()
    # The ep1 owner's own claim must be gone (released normally).
    assert not sweep_latch.claim_path(BROKER, "2026-08-27T01:00:00+00:00").exists()
    sweep_latch.release_claim(BROKER, captured["ep2"])


def _count_audits(live_root: Path, flatten_fn: Any, ticks: int) -> tuple[int, list[str]]:
    """Run one runner over ``ticks`` halted ticks; return audit count + kinds."""
    kinds: list[str] = []

    async def _agent_caller(session_id: str, prompt: str) -> Mapping[str, Any]:
        return {"status": "success"}

    def _audit(event) -> Mapping[str, Any]:
        kinds.append(getattr(event, "kind", "?"))
        return {"audit_id": "a1"}

    runner = LiveRunner(
        BROKER,
        agent_caller=_agent_caller,
        reconcile_fn=lambda *a, **k: None,
        read_positions=list,
        read_balance=list,
        read_open_orders=list,
        write_audit_fn=_audit,
        halt_flag_fn=lambda broker: True,
        submit_fn=lambda request: {"status": "ok"},
        flatten_fn=flatten_fn,
        session_id="latch-test",
    )
    for _ in range(ticks):
        asyncio.run(runner.run_once())
    return len(kinds), kinds


def test_flat_book_recheck_audits_once_not_once_per_tick(live_root: Path) -> None:
    # The no-side-effect branch re-runs every halted tick by design. Its audit
    # record must not: a channel left halted overnight at a 1-minute tick would
    # append ~1440 identical records to the hash-chained ledger. One record per
    # (episode, condition) per runner; the rest is logging.
    _trip_with_timestamp(BROKER, "2026-08-27T01:00:00+00:00")

    def _flatten(broker, submit, read_positions, read_open_orders):
        return {"errors": []}  # reads ok, nothing to act on

    total, kinds = _count_audits(live_root, _flatten, ticks=5)
    # 5 halt_tripped tick records + exactly ONE re-check record.
    assert total == 6, kinds
    # A flat book is not a breach.
    assert "breach" not in kinds, kinds


def test_persistent_read_failure_audits_the_breach_once_per_episode(
    live_root: Path,
) -> None:
    _trip_with_timestamp(BROKER, "2026-08-27T01:00:00+00:00")

    def _flatten(broker, submit, read_positions, read_open_orders):
        return {"errors": [{"phase": "read_positions", "error": "broker read failed"}]}

    total, kinds = _count_audits(live_root, _flatten, ticks=5)
    assert total == 6, kinds
    assert kinds.count("breach") == 1, kinds


def test_mid_sweep_retrip_records_only_swept_episode(live_root: Path) -> None:
    # Reviewer merge-blocker: the latch must record the episodes the sweep
    # COVERED (captured before claiming), never what the sentinels say AFTER
    # the sweep. With a mid-sweep clear + re-trip (ep1 -> ep2), recording ep2
    # would make the next runner skip it — positions stay open.
    _trip_with_timestamp(BROKER, "2026-08-27T01:00:00+00:00")
    fired: list[str] = []

    def _retripping_flatten(broker, submit, read_positions, read_open_orders):
        fired.append(broker)
        clear_halt(BROKER)
        _trip_with_timestamp(BROKER, "2026-08-27T10:00:00+00:00")
        return {"side_effects_attempted": True}

    asyncio.run(_build_runner(live_root, fired, _retripping_flatten).run_once())
    # ep1 (the swept episode) is latched; ep2 (never swept) is not.
    assert sweep_latch.sweep_already_fired(BROKER, "2026-08-27T01:00:00+00:00") is True
    ep2 = sweep_latch.halt_episode(BROKER)
    assert ep2 == "2026-08-27T10:00:00+00:00"
    assert sweep_latch.sweep_already_fired(BROKER, ep2) is False
    # A subsequent runner must therefore sweep the NEW episode (not skip it).
    asyncio.run(_build_runner(live_root, fired).run_once())
    assert fired == [BROKER, BROKER]


def test_concurrent_latch_updates_both_episodes_recorded(
    live_root: Path,
) -> None:
    # Reviewer finding 2: two concurrent completions for DIFFERENT episodes
    # must not lose one another's record (the old shared read-merge-write
    # could drop an entry). Per-episode latch files make each create
    # independent — even with true thread interleaving, both must survive.
    import threading
    from concurrent.futures import ThreadPoolExecutor

    barriers = [threading.Barrier(2)]
    results: list[bool] = []

    def _marker(episode: str, barrier: threading.Barrier) -> None:
        barrier.wait()
        sweep_latch.mark_sweep_fired(BROKER, [episode])
        results.append(True)

    with ThreadPoolExecutor(max_workers=2) as pool:
        pool.submit(_marker, "2026-08-27T01:00:00+00:00", barriers[0])
        pool.submit(_marker, "2026-08-27T10:00:00+00:00", barriers[0])
    assert len(results) == 2
    assert (
        sweep_latch.sweep_already_fired(BROKER, "2026-08-27T01:00:00+00:00")
        is True
    )
    assert (
        sweep_latch.sweep_already_fired(BROKER, "2026-08-27T10:00:00+00:00")
        is True
    )
