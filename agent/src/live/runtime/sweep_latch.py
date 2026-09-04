"""Persist the preemptive-sweep latch across runner restarts.

The HALT sentinel is a file, so it survives a process restart; the runner's
``_flatten_fired`` flag does not. Without a persisted latch, a restart with
flatten orders still working replays the whole sweep on the next tick: a fresh
cancel pass plus a new market order per position, which can flip the account
from long to net short. This module records the sweep's firing on disk, bound
to the halt *episode* that caused it.

The latch lives next to the per-broker HALT sentinel at
``<runtime_root>/live/<broker>/FLATTEN_FIRED`` and carries the identity of
every halt *episode* the sweep has fired for: the sentinel's ``tripped_at``
when it has one, otherwise the sentinel file's mtime. A later trip writes a
new sentinel (fresh ``tripped_at`` / fresh mtime), so a stale latch from a
previous episode never suppresses a new one; clearing HALT and re-tripping
therefore re-arms the sweep without anyone deleting the latch. When the
per-broker and the global HALTs are both tripped, the *newest* sentinel wins
the current-episode lookup — the global HALT is authoritative
(``halt_flag_set`` halts every channel), but only for its own, newer episode.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.live.halt import broker_halt_path, halt_path, read_halt
from src.live.paths import broker_dir

_LATCH_FILENAME = "FLATTEN_FIRED"
_CLAIM_FILENAME = "FLATTEN_CLAIM"


def latch_path(broker: str, episode: str | None = None) -> Path:
    """Return the per-broker, per-episode sweep latch path (not created here).

    One file per halt episode (``FLATTEN_FIRED-<sha16>(episode)``): the sweep
    record is never a shared read-merge-write object, so concurrent
    completions for different episodes cannot lose one another's entry —
    each atomic ``O_CREAT|O_EXCL`` create is independent. ``episode=None``
    returns the legacy single-record path (pre-per-episode format, read
    for compatibility only).
    """
    if episode is None:
        return broker_dir(broker) / _LATCH_FILENAME
    digest = hashlib.sha256(episode.encode("utf-8")).hexdigest()[:16]
    return broker_dir(broker) / f"{_LATCH_FILENAME}-{digest}"


def halt_episode(broker: str) -> str | None:
    """Return the identity of the newest tripped halt episode (public alias)."""
    return _halt_episode(broker)


def _claim_filename(episode: str) -> str:
    digest = hashlib.sha256(episode.encode("utf-8")).hexdigest()[:16]
    return f"{_CLAIM_FILENAME}-{digest}"


def claim_path(broker: str, episode: str) -> Path:
    """Return the per-broker, per-episode sweep-claim path.

    Claims are keyed by halt episode, so an orphaned claim from a crash can
    only ever block its OWN episode — never a future trip of the same broker
    (each new halt episode gets its own claim namespace).
    """
    return broker_dir(broker) / _claim_filename(episode)


def claim_sweep(broker: str, episode: str) -> bool:
    """Atomically claim the sweep for ``broker``'s ``episode`` — exclusive between processes.

    ``O_CREAT | O_EXCL`` guarantees a single winner even when two runners
    start simultaneously for the same episode: the loser of the race sees the
    claim file and must NOT sweep (the duplicate-close hazard the latch exists
    to prevent). The claim covers the whole check -> sweep -> durable-record
    window. A claim left behind by a crash means that episode's outcome is
    *unknowable*: re-sweeping could duplicate a close, so the runner skips and
    surfaces the claim for operator resolution. Because the claim is bound to
    the episode, a stale claim never blocks a later episode.

    Returns:
        ``True`` if this process now owns the sweep; ``False`` when a claim
        already exists for the same episode (another runner active, or a
        crashed prior run).
    """
    path = claim_path(broker, episode)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "claimed_at": datetime.now(timezone.utc).isoformat(),
                    "episode": episode,
                    "pid": os.getpid(),
                },
                f,
            )
    except Exception:
        try:
            os.unlink(path)
        except OSError:
            pass
        raise  # claim could not be recorded; caller decides (fail-closed)
    return True


def release_claim(broker: str, episode: str) -> None:
    """Drop this process's sweep claim for ``episode`` (no-op when absent)."""
    try:
        claim_path(broker, episode).unlink()
    except OSError:
        pass


def _sentinel_identity(path: Path, payload: dict[str, Any]) -> tuple[int, str] | None:
    """Return ``(instant_ns, identity)`` for one halt sentinel, or ``None``.

    ``tripped_at`` is the identity when the sentinel carries a parseable one;
    a hand-touched/malformed sentinel falls back to its file mtime (which
    still changes on every fresh ``touch``). Ranking by mtime alone is not
    safe — two sentinels written within one filesystem timestamp quantum
    share an mtime — so ``tripped_at`` wins whenever present.
    """
    try:
        mtime_ns = path.stat().st_mtime_ns
    except OSError:
        return None
    tripped_at = payload.get("tripped_at")
    if tripped_at:
        try:
            trip = datetime.fromisoformat(str(tripped_at))
            if trip.tzinfo is None:
                trip = trip.replace(tzinfo=timezone.utc)
            return int(trip.timestamp() * 1_000_000_000), str(tripped_at)
        except ValueError:
            pass
    return mtime_ns, f"mtime:{mtime_ns}"


def _active_episodes(broker: str) -> list[str]:
    """Return the identity of EVERY currently tripped halt episode.

    Both the per-broker and the global sentinel can be tripped at the same
    time, and both are live until their sentinel is cleared. Recording the
    sweep as fired only for its *newest* episode leaves the other active one
    unrecorded: clearing the recorded halt would re-fire the sweep while the
    other halt is still tripped. Both identities must therefore be latched
    together.
    """
    return halt_snapshot(broker)[0]


def halt_snapshot(broker: str) -> tuple[list[str], str | None]:
    """One coherent read of every tripped sentinel.

    Returns ``(active_episodes, newest_episode)`` from a single pass over
    both sentinels. The runner MUST capture this snapshot once, before
    claiming, and pass the captured episode list into
    :func:`mark_sweep_fired` — re-reading the sentinels later would let a
    mid-sweep clear/re-trip change what the latch records (recording an
    episode whose sweep never ran, which would silently skip it).
    """
    candidates: list[tuple[int, str]] = []
    for path, payload in (
        (broker_halt_path(broker), read_halt(broker)),
        (halt_path(), read_halt()),
    ):
        if payload is None:
            continue
        resolved = _sentinel_identity(path, payload)
        if resolved is not None:
            candidates.append(resolved)
    if not candidates:
        return [], None
    newest = max(candidates, key=lambda item: item[0])[1]
    return [identity for _, identity in candidates], newest


def _halt_episode(broker: str) -> str | None:
    """Return the identity of the *newest* tripped halt episode, if any.

    Both the per-broker and the global sentinel can be tripped, at different
    times. The global HALT is authoritative (``halt_flag_set`` halts every
    channel), but a stale per-broker episode must not suppress the sweep for
    a newer global trip — nor an older global trip override a newer
    per-broker one. The newest sentinel therefore wins.
    """
    return halt_snapshot(broker)[1]


def sweep_already_fired(broker: str, episode: str | None = None) -> bool:
    """Return True when the sweep already fired for ``broker``'s ``episode``.

    ``episode=None`` resolves the newest currently tripped episode (legacy
    signature). The per-episode latch file is authoritative; the legacy
    single-record file is consulted only as a compatibility fallback for
    latches written by pre-per-episode versions.
    """
    if episode is None:
        episode = _halt_episode(broker)
        if episode is None:
            return False
    if latch_path(broker, episode).exists():
        return True
    try:
        record = json.loads(latch_path(broker).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(record, dict):
        return False
    episodes = record.get("episodes")
    if isinstance(episodes, list):
        return episode in episodes
    return record.get("episode") == episode  # legacy single-episode record


def mark_sweep_fired(broker: str, episodes: list[str] | None = None) -> None:
    """Atomically record that the sweep fired for every episode in ``episodes``.

    One ``O_CREAT|O_EXCL`` latch file per episode identity — no shared
    read-merge-write record exists to race on: each create is independent and
    idempotent (an existing file is a prior completion, left untouched). This
    is what makes concurrent completions for different episodes safe without
    a lock, and a re-trip never loses a completed episode's record.

    The caller MUST pass the episode snapshot it captured BEFORE claiming
    (see :func:`halt_snapshot`) — never re-read the sentinels here: a
    mid-sweep clear/re-trip would record an episode whose sweep never ran,
    causing the next runner to skip it. ``episodes=None`` resolves the
    currently active episodes (legacy signature, for standalone use).
    """
    if episodes is None:
        episodes = _active_episodes(broker)
    for episode in episodes:
        path = latch_path(broker, episode)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            continue  # already latched by a prior completion
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "fired_at": datetime.now(timezone.utc).isoformat(),
                        "episode": episode,
                    },
                    f,
                )
        except Exception:
            try:
                os.unlink(path)
            except OSError:
                pass
            raise  # durability failure; caller decides (audit + flag)

