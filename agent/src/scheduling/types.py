"""Shared vocabulary types for the scheduling kernel (scheduler unification).

Two pieces live here, both pure and domain-free:

* :data:`ExecutorKind` — how a job is executed (``"prompt"`` dispatches an
  agent session; ``"internal"`` runs a registered in-process callable). The
  value domain is defined here once, and the job model validates against it
  (:func:`is_executor_kind`), so model and registry cannot drift apart.
* The kernel callback aliases (:data:`NowFn`, :data:`OnTickFn`) — the
  injection seams of :class:`src.scheduling.kernel.SchedulerKernel`,
  declared here so the kernel module stays free of domain imports.
"""

from __future__ import annotations

from typing import Awaitable, Callable, Literal

# ---------------------------------------------------------------------------
# Executor kind
# ---------------------------------------------------------------------------

#: How a job is executed: ``"prompt"`` dispatches an agent session,
#: ``"internal"`` runs a callable from the explicit in-process registry
#: (:mod:`src.scheduling.registry`).
ExecutorKind = Literal["prompt", "internal"]

#: The closed value domain of :data:`ExecutorKind`, for runtime validation.
EXECUTOR_KINDS: tuple[str, ...] = ("prompt", "internal")


def is_executor_kind(value: object) -> bool:
    """Return whether *value* is a member of :data:`EXECUTOR_KINDS`."""
    return value in EXECUTOR_KINDS


# ---------------------------------------------------------------------------
# Kernel callback seams
# ---------------------------------------------------------------------------

#: Injectable wall-clock source returning epoch milliseconds.
NowFn = Callable[[], int]

#: Called by the kernel loop once per tick with the current epoch-ms. The
#: kernel isolates exceptions per tick (one failing tick never kills the
#: loop); ``asyncio.CancelledError`` propagates so ``stop()`` stays bounded.
OnTickFn = Callable[[int], Awaitable[None]]

#: Consumer-provided "next deadline" sleep hint, in epoch-ms and duration-ms.
#: Called by the kernel after each tick with a freshly read ``now_ms``; the
#: return value replaces the fixed ``tick_interval_ms`` as the inter-tick
#: sleep (clamped to be non-negative). This is the seam that lets an
#: adaptive-sleep consumer — one that sleeps until the earliest job deadline
#: rather than polling on a fixed cadence — adopt the kernel without giving
#: up its sleep shape. The kernel never interprets the number: bounding the
#: sleep (e.g. a max re-check cap) is the consumer's own composition. A hint
#: that raises is logged and falls back to ``tick_interval_ms`` so a buggy
#: hint cannot kill the loop.
SleepHintFn = Callable[[int], int]
