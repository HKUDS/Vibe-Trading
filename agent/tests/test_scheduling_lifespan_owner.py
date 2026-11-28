"""Single-owner lifespan contracts for the scheduled-research scheduler (T12).

Pins the scheduler-unification ownership invariant end to end:

* the FastAPI lifespan is the SOLE production start point of the kernel —
  a duplicate ``start()`` in one process is a no-op (exactly one task);
* ``ensure_system_jobs`` runs BEFORE the executor starts, so every enabled
  protected system job is in the store before the first tick can run
  (system_jobs timing contract (i));
* ``stop()`` genuinely awaits the kernel task and stays bounded even while
  a tick is wedged inside a dispatch (kernel ``cancel()`` fallback);
* ``scheduler_status()`` resolves the executor through BOTH documented
  attribute paths (``api_server`` module attr, ``scheduled_routes`` fallback);
* flag-off keeps the pre-existing semantics: early return, zero writes, CRUD
  still 2xx, nothing executes;
* the session-terminal event → ``request_sweep`` wiring survives, and sweeps
  still coalesce instead of double-running;
* two executors sharing one store path are DOCUMENTED-UNSUPPORTED: the
  honest failure mode (second instance's stale recovery resurrects the
  first's in-flight job → double dispatch) is pinned here so the invariant
  in the ``store.py`` module docstring can never become vacuous.

Harness note: the app-assembly pattern (isolated store singleton via
``monkeypatch``, loopback ``TestClient``, ``_API_KEY`` cleared) mirrors
``test_scheduled_routes.py``; the lifespan tests additionally neutralize
``run_preflight`` / ``migrate_legacy_state`` so only the scheduler wiring
under test does real work.
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Callable

import pytest
from fastapi.testclient import TestClient

import api_server
from src.api import scheduled_routes
from src.config.accessor import reset_env_config
from src.scheduled_research.executor import ScheduledResearchExecutor
from src.scheduled_research.models import JobStatus, ScheduledResearchJob
from src.scheduled_research.service import scheduler_status
from src.scheduled_research.store import ScheduledResearchJobStore
from src.scheduling import system_jobs

_SCHEDULER_ENV = "VIBE_TRADING_ENABLE_SCHEDULER"
_MEMORY_JOB_ENV = "VT_MEMORY_CONSOLIDATION"
_MEMORY_JOB_ID = "system:memory-consolidation"


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ScheduledResearchJobStore:
    """Isolate the module singletons onto a temp store with no executor."""
    isolated = ScheduledResearchJobStore(path=tmp_path / "scheduled_jobs.json")
    monkeypatch.setattr(scheduled_routes, "_scheduled_research_store", isolated)
    monkeypatch.setattr(scheduled_routes, "_scheduled_research_executor", None)
    return isolated


@pytest.fixture
def env_flags(monkeypatch: pytest.MonkeyPatch) -> Callable[..., None]:
    """Drive the real config path: set env vars, reset the cached config.

    Starts from a known flag-off baseline (master scheduler, both system-job
    spec flags, channel auto-start) so a developer's shell environment can
    never leak into an assertion, and restores the config cache afterwards.
    """
    for name in (
        _SCHEDULER_ENV,
        _MEMORY_JOB_ENV,
        "VIBE_BR_SYNC_ENABLED",
        "VIBE_TRADING_CHANNELS_AUTO_START",
    ):
        monkeypatch.delenv(name, raising=False)
    reset_env_config()

    def _apply(**flags: str) -> None:
        for name, value in flags.items():
            monkeypatch.setenv(name, value)
        reset_env_config()

    yield _apply
    reset_env_config()


@pytest.fixture
def client(store: ScheduledResearchJobStore, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Plain TestClient (no lifespan) with loopback auth, as in the battery."""
    monkeypatch.delenv("API_AUTH_KEY", raising=False)
    monkeypatch.setattr(api_server, "_API_KEY", "")
    return TestClient(api_server.app, client=("127.0.0.1", 50000))


def _job(**overrides: object) -> ScheduledResearchJob:
    base: dict[str, object] = {
        "id": "j1",
        "prompt": "p",
        "schedule": "60000",
        "next_run_at": 0,
        "created_at": 0,
    }
    base.update(overrides)
    return ScheduledResearchJob(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# (a) duplicate start() in one process = no-op (exactly one asyncio task)
# ---------------------------------------------------------------------------


def test_duplicate_start_is_a_noop_with_exactly_one_kernel_task(tmp_path: Path) -> None:
    async def _scenario() -> None:
        store = ScheduledResearchJobStore(tmp_path / "jobs.json")

        async def _dispatch(_job: ScheduledResearchJob) -> None:
            return None

        executor = ScheduledResearchExecutor(
            store, _dispatch, enabled=True, tick_interval_ms=60_000, now_fn=lambda: 1000
        )
        executor.start()
        first_task = executor._kernel._task
        assert first_task is not None

        executor.start()
        executor.start()

        assert executor._kernel._task is first_task
        named = [
            t for t in asyncio.all_tasks() if t.get_name() == "scheduled-research-executor"
        ]
        assert len(named) == 1

        await executor.stop()
        assert executor._kernel._task is None
        assert not executor.is_running

    asyncio.run(_scenario())


# ---------------------------------------------------------------------------
# Shutdown genuinely awaits the kernel task, bounded even with a wedged tick
# ---------------------------------------------------------------------------


def test_stop_is_bounded_while_a_tick_is_stuck_in_dispatch(tmp_path: Path) -> None:
    """Plan QA (b): a wedged tick must never hang the lifespan shutdown.

    ``asyncio.wait_for`` bounds ``stop()``; a timeout fails the test, which is
    exactly the plan's acceptance criterion. The kernel's ``task.cancel()``
    fallback is what releases the dispatch await, and ``kernel.stop`` swallows
    the resulting ``CancelledError`` so ``executor.stop()`` returns normally.
    """
    store = ScheduledResearchJobStore(tmp_path / "jobs.json")
    store.upsert(_job())
    entered = asyncio.Event()

    async def _stuck_dispatch(_job: ScheduledResearchJob) -> None:
        entered.set()
        await asyncio.Event().wait()  # never set; only cancellation frees it

    async def _scenario() -> None:
        executor = ScheduledResearchExecutor(
            store, _stuck_dispatch, enabled=True, tick_interval_ms=60_000, now_fn=lambda: 1000
        )
        executor.start()
        await asyncio.wait_for(entered.wait(), timeout=5)
        assert store.get("j1").status is JobStatus.RUNNING

        await asyncio.wait_for(executor.stop(), timeout=5)

        assert not executor.is_running
        # Pinned T4 semantics: a cancelled mid-dispatch job stays RUNNING for
        # the next start's stale recovery rather than gaining a terminal write.
        assert store.get("j1").status is JobStatus.RUNNING

    asyncio.run(_scenario())


# ---------------------------------------------------------------------------
# (b) two executors on one store: DOCUMENTED-UNSUPPORTED, honest failure mode
# ---------------------------------------------------------------------------


def test_second_executor_on_the_same_store_double_dispatches(tmp_path: Path) -> None:
    """The failure the single-writer invariant exists to prevent.

    DECISION (T12, option b): two executor instances sharing one store path
    are documented-unsupported (``store.py`` module docstring) rather than
    silently serialized. This test pins the honest failure mode: the second
    instance's one-shot ``recover_stale_running`` cannot distinguish the
    first's LIVE in-flight RUNNING job from a crashed-process leftover, so it
    resets the row to PENDING and dispatches it a second time.
    """
    store = ScheduledResearchJobStore(tmp_path / "jobs.json")
    store.upsert(_job())
    dispatches: list[str] = []
    release = asyncio.Event()

    async def _slow_dispatch(job: ScheduledResearchJob) -> None:
        dispatches.append(job.id)
        await release.wait()
        return None

    async def _scenario() -> None:
        first = ScheduledResearchExecutor(
            store, _slow_dispatch, enabled=False, now_fn=lambda: 1000
        )
        second = ScheduledResearchExecutor(
            store, _slow_dispatch, enabled=False, now_fn=lambda: 1000
        )

        tick_first = asyncio.create_task(first.tick(now_ms=1000))
        for _ in range(10):
            await asyncio.sleep(0)
            if dispatches:
                break
        assert dispatches == ["j1"]
        assert store.get("j1").status is JobStatus.RUNNING

        tick_second = asyncio.create_task(second.tick(now_ms=1000))
        for _ in range(10):
            await asyncio.sleep(0)
            if len(dispatches) == 2:
                break

        assert dispatches == ["j1", "j1"], (
            "documented-unsupported failure mode changed: a second executor "
            "on one store no longer double-dispatches — update the invariant "
            "docs in store.py if this is now a supported shape"
        )

        release.set()
        await asyncio.gather(tick_first, tick_second)

    asyncio.run(_scenario())


# ---------------------------------------------------------------------------
# scheduler_status() dual attribute resolution
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("attach_to", ["api_server", "scheduled_routes"])
@pytest.mark.parametrize("running", [True, False])
def test_scheduler_status_resolves_both_attribute_paths(
    attach_to: str, running: bool, monkeypatch: pytest.MonkeyPatch, env_flags: Callable[..., None]
) -> None:
    """Both documented resolution paths report the same correct ``running``.

    ``service.scheduler_status()`` first reads ``_scheduled_research_executor``
    off the host ``api_server`` module and falls back to the
    ``scheduled_routes`` module attribute (where the production singleton
    lives). Neither path may go stale.
    """
    env_flags(**{_SCHEDULER_ENV: "1"})
    monkeypatch.delattr(api_server, "_scheduled_research_executor", raising=False)
    monkeypatch.setattr(scheduled_routes, "_scheduled_research_executor", None)

    fake = SimpleNamespace(is_running=running)
    if attach_to == "api_server":
        monkeypatch.setattr(api_server, "_scheduled_research_executor", fake, raising=False)
    else:
        monkeypatch.setattr(scheduled_routes, "_scheduled_research_executor", fake)

    body = scheduler_status()
    assert body["enabled"] is True
    assert body["running"] is running
    assert body["executable"] is running


# ---------------------------------------------------------------------------
# Flag-off semantics unchanged: early return, zero writes, CRUD 2xx
# ---------------------------------------------------------------------------


def test_flag_off_start_early_returns_without_seeding_or_starting(
    store: ScheduledResearchJobStore, monkeypatch: pytest.MonkeyPatch, env_flags: Callable[..., None]
) -> None:
    ensure_calls: list[object] = []
    monkeypatch.setattr(
        system_jobs, "ensure_system_jobs", lambda *a, **k: ensure_calls.append((a, k))
    )

    assert scheduled_routes._scheduled_research_scheduler_enabled() is False
    scheduled_routes._start_scheduled_research_executor()

    assert ensure_calls == []
    assert scheduled_routes._scheduled_research_executor is None
    assert not store.path.exists()


def test_flag_off_crud_works_and_status_reports_all_false(
    client: TestClient, env_flags: Callable[..., None]
) -> None:
    """Without the flag the API still creates/lists/deletes; nothing executes."""
    created = client.post(
        "/scheduled-runs",
        json={"id": "job-off", "prompt": "scan", "schedule": "60000"},
    )
    assert created.status_code == 201

    listed = client.get("/scheduled-runs")
    assert listed.status_code == 200
    assert [job["id"] for job in listed.json()] == ["job-off"]

    status_body = client.get("/scheduled-runs/status").json()
    assert status_body["enabled"] is False
    assert status_body["running"] is False
    assert status_body["executable"] is False

    deleted = client.delete("/scheduled-runs/job-off")
    assert deleted.status_code == 204
    assert client.get("/scheduled-runs").json() == []


# ---------------------------------------------------------------------------
# (i) timing contract: ensure_system_jobs BEFORE executor start()
# ---------------------------------------------------------------------------


def test_ensure_system_jobs_runs_before_executor_start(
    store: ScheduledResearchJobStore, monkeypatch: pytest.MonkeyPatch, env_flags: Callable[..., None]
) -> None:
    """Ordering spy on the real production call path (flag on, spec on)."""
    env_flags(**{_SCHEDULER_ENV: "1", _MEMORY_JOB_ENV: "1"})
    calls: list[str] = []
    real_ensure = system_jobs.ensure_system_jobs

    def _spy_ensure(target, **kwargs):
        calls.append("ensure")
        return real_ensure(target, **kwargs)

    monkeypatch.setattr(system_jobs, "ensure_system_jobs", _spy_ensure)
    fake_executor = SimpleNamespace(start=lambda: calls.append("start"))
    monkeypatch.setattr(scheduled_routes, "_get_scheduled_research_executor", lambda: fake_executor)

    scheduled_routes._start_scheduled_research_executor()

    assert calls == ["ensure", "start"]
    seeded = store.get(_MEMORY_JOB_ID)
    assert seeded is not None
    assert seeded.status is JobStatus.PENDING


def test_flag_on_lifespan_seeds_system_jobs_before_first_tick(
    store: ScheduledResearchJobStore, monkeypatch: pytest.MonkeyPatch, env_flags: Callable[..., None]
) -> None:
    """QA happy path, through the REAL lifespan: one start, seeded, running.

    The probe executor records whether the enabled system job was already in
    the store when the first tick began — the direct observation of timing
    contract (i). The seeded cron job's next fire is a future slot, so the
    tick must not dispatch anything.
    """
    env_flags(**{_SCHEDULER_ENV: "1", _MEMORY_JOB_ENV: "1"})
    monkeypatch.setattr("src.preflight.run_preflight", lambda *_a, **_k: None)
    monkeypatch.setattr("src.config.migrate.migrate_legacy_state", lambda *_a, **_k: None)
    monkeypatch.delenv("API_AUTH_KEY", raising=False)
    monkeypatch.setattr(api_server, "_API_KEY", "")

    observations: list[bool] = []
    dispatches: list[str] = []
    # The kernel task runs on the TestClient portal loop (another thread), so
    # the test thread handshakes with an Event instead of sleep-polling.
    first_tick_ran = threading.Event()

    async def _recording_dispatch(job: ScheduledResearchJob) -> None:
        dispatches.append(job.id)
        return None

    executor = ScheduledResearchExecutor(
        store, _recording_dispatch, enabled=True, tick_interval_ms=60_000
    )
    original_tick = executor.tick

    async def _observed_tick(now_ms: int | None = None) -> None:
        observations.append(store.get(_MEMORY_JOB_ID) is not None)
        first_tick_ran.set()
        await original_tick(now_ms)

    executor.tick = _observed_tick  # type: ignore[method-assign]
    monkeypatch.setattr(scheduled_routes, "_scheduled_research_executor", executor)

    with TestClient(api_server.app, client=("127.0.0.1", 50000)) as client:
        assert executor.is_running
        assert first_tick_ran.wait(5), "the kernel's first tick never ran"
        assert observations and all(observations), (
            "first tick observed a store without the enabled system job — "
            "ensure_system_jobs must run before executor start()"
        )
        seeded = store.get(_MEMORY_JOB_ID)
        assert seeded is not None
        assert seeded.status is JobStatus.PENDING
        assert dispatches == []

        body = client.get("/scheduled-runs/status").json()
        assert body["enabled"] is True
        assert body["running"] is True
        assert body["executable"] is True

    # Lifespan shutdown genuinely awaited the kernel task to completion.
    assert not executor.is_running


# ---------------------------------------------------------------------------
# Sole production start point (source-level guard, T5 pattern)
# ---------------------------------------------------------------------------


def test_the_lifespan_is_the_sole_production_start_call_site() -> None:
    """``_start_scheduled_research_executor()`` is called from api_server only.

    A second production call site would break the single-writer invariant
    (double start attempts, seeding from two owners), so the call-site count
    is guarded mechanically rather than by review.
    """
    agent_root = Path(api_server.__file__).resolve().parent
    scanned = [agent_root / "api_server.py", agent_root / "mcp_server.py"]
    scanned += sorted((agent_root / "src").rglob("*.py"))
    scanned += sorted((agent_root / "cli").rglob("*.py"))

    call_sites: list[str] = []
    for path in scanned:
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith(("#", "def ", "async def ")):
                continue
            if "_start_scheduled_research_executor()" in stripped:
                call_sites.append(f"{path.relative_to(agent_root)}: {stripped}")

    assert call_sites == ["api_server.py: _start_scheduled_research_executor()"]


# ---------------------------------------------------------------------------
# Session-terminal event → request_sweep wiring survives; sweeps coalesce
# ---------------------------------------------------------------------------


def test_session_terminal_event_still_reaches_request_sweep(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.api.state import _attach_delivery_listener
    from src.session.events import EventBus

    swept: list[str] = []
    fake_executor = SimpleNamespace(request_sweep=lambda: swept.append("sweep"))
    monkeypatch.setattr(
        scheduled_routes, "_get_scheduled_research_executor", lambda: fake_executor
    )

    bus = EventBus()
    _attach_delivery_listener(bus)

    bus.emit("s1", "message.delta", {})
    assert swept == []

    for event_type in ("run.completed", "run.failed", "run.cancelled"):
        bus.emit("s1", event_type, {})
    assert swept == ["sweep", "sweep", "sweep"]


def test_request_sweep_coalesces_instead_of_double_running(tmp_path: Path) -> None:
    """QA (c): concurrent requests merge into ONE in-flight sweep; a request
    after completion arms a fresh one (the hook stays prompt, never doubled).
    """
    store = ScheduledResearchJobStore(tmp_path / "jobs.json")
    sweeps: list[int] = []
    hold = asyncio.Event()

    async def _scenario() -> None:
        async def _dispatch(_job: ScheduledResearchJob) -> None:
            return None

        executor = ScheduledResearchExecutor(store, _dispatch, enabled=False)

        async def _slow_sweep() -> int:
            sweeps.append(1)
            await hold.wait()
            return 0

        executor.sweep_deliveries = _slow_sweep  # type: ignore[method-assign]
        executor._loop = asyncio.get_running_loop()

        executor.request_sweep()
        executor.request_sweep()
        executor.request_sweep()
        for _ in range(10):
            await asyncio.sleep(0)
            if sweeps:
                break
        executor.request_sweep()  # in-flight → must coalesce, not double-run
        await asyncio.sleep(0)
        assert len(sweeps) == 1

        hold.set()
        await executor._sweep_task
        executor.request_sweep()  # completed → arms exactly one fresh sweep
        for _ in range(10):
            await asyncio.sleep(0)
        assert len(sweeps) == 2

    asyncio.run(_scenario())
