"""Delegate a domain task to a specialist sub-agent with a fixed tool whitelist.

The main agent calls ``delegate_to_specialist(specialist, task)``; the
specialist runs as a nested agent loop holding only its whitelisted tools, so
each model decision inside the delegation reads a small domain surface
instead of the full registry. The nested run gets the same loop guarantees as
a top-level run — its own run directory, trace, manifest, grounding ledger
and stall watchdog — and the caller receives the specialist's self-contained
final message plus artifact paths.

Lifecycle and thread-safety contract:

- **Instance-stateless execute.** The registry (and on MCP, one process-wide
  registry) shares a single tool instance across sessions, and read-only
  tools in one turn run in parallel — so every per-call value lives in
  locals. The only mutable attribute is written once by ``bind_parent`` at
  loop-construction time.
- **Behavior contract injection.** The child loop runs under
  ``SPECIALIST_SYSTEM_PROMPT`` (imported from ``src.specialists.prompt``)
  with ``spec.prompt`` bound to the ``{role_prompt}`` slot, so the
  specialist sees its own slim system prompt instead of the main agent's.
- **Specialist skills semantics.** ``spec.skills`` is passed through
  verbatim (never ``or None``): an empty list means the specialist is shown
  no skill catalog and ``load_skill`` rejects every skill name. This
  deliberately diverges from the swarm worker "empty = unrestricted"
  convention.
- **Cancel relay (load-bearing).** The parent loop blocks on this tool's
  queue slot and only polls its own cancel event between tool batches, so
  without a relay a user cancel would not reach a running specialist until
  it finished or hit the outer tool timeout. A daemon relay thread forwards
  the parent event to the child loop within ~0.5s.
- **Layered timeout.** The specialist's own budget (``timeout_seconds``,
  default 600s) fires before the loop's read-only tool timeout (default
  1800s), so a delegation returns a structured timeout result instead of a
  bare thread cut. On expiry the child is cancelled and re-joined briefly;
  if it still will not exit, the daemon thread is abandoned and the child's
  LLM transport is closed under it (intentional — closing self-created
  transports breaks a blocked stream, and the child loop converts the error
  into a failed result nobody reads). A timeout payload always carries empty
  ``content``: a child result that lands during the cancel grace period is
  dropped from the payload so ``status: timeout`` never ships a late result,
  while ``run_dir`` is preserved for recovering partial work.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from typing import Any, Dict, Optional

from src.agent.tools import BaseTool
from src.specialists.loader import load_specialists
from src.specialists.prompt import SPECIALIST_SYSTEM_PROMPT

logger = logging.getLogger(__name__)

_CANCEL_RELAY_POLL_SECONDS = 0.5
# Grace period for a specialist to land on a cooperative checkpoint after its
# budget fires and cancel is requested. Bounded so a stuck child cannot hold
# the parent loop's tool slot open indefinitely.
_CANCEL_GRACE_SECONDS = 30.0


def _error(message: str, **extra: Any) -> str:
    payload: Dict[str, Any] = {"status": "error", "error": message}
    payload.update(extra)
    return json.dumps(payload, ensure_ascii=False)


class DelegateToSpecialistTool(BaseTool):
    """Run one named specialist on a self-contained task brief."""

    name = "delegate_to_specialist"
    description = (
        "Delegate a self-contained domain task to a named specialist sub-agent. "
        "The specialist roster and its routing rules are listed in the system "
        "prompt's specialist-delegation section. Write `task` as a complete "
        "brief — objective, expected output, constraints, and the exact inputs "
        "the specialist needs — because it cannot see this conversation. The "
        "result is the specialist's final message plus the paths of any "
        "artifacts it wrote; trust and relay them instead of redoing the work."
    )
    repeatable = True
    is_readonly = True

    def __init__(self, event_callback: Any = None) -> None:
        self._event_callback = event_callback
        # Written once by bind_parent at loop construction; never per call.
        self._parent_cancel: threading.Event | None = None
        names = sorted(load_specialists())
        self.parameters = {
            "type": "object",
            "properties": {
                "specialist": {
                    "type": "string",
                    "enum": names,
                    "description": "Specialist name from the delegation section of the system prompt.",
                },
                "task": {
                    "type": "string",
                    "description": (
                        "Self-contained task brief: objective, expected output, "
                        "constraints, and the exact inputs the specialist needs."
                    ),
                },
            },
            "required": ["specialist", "task"],
        }

    @classmethod
    def check_available(cls) -> bool:
        """Register only when the specialists gate is on and the roster loads.

        Evaluated at registry build time, so toggling
        ``VIBE_TRADING_SPECIALISTS_ENABLED`` takes effect on the next process
        start (the MCP server also builds its registry once at boot).
        """
        try:
            from src.config.accessor import get_env_config

            if not get_env_config().agent_tuning.vibe_trading_specialists_enabled:
                return False
            return bool(load_specialists())
        except Exception:  # noqa: BLE001 — a broken roster must not break builds
            logger.warning("specialist roster unavailable", exc_info=True)
            return False

    def bind_parent(self, *, cancel_event: threading.Event) -> None:
        """Attach the parent loop's cancel event for delegation-time relay.

        Called once by ``AgentLoop`` right after construction. The same event
        object is reused across the loop's runs (``run()`` clears it on
        reuse), so the binding stays valid for the loop's lifetime; if a
        future change swaps in a fresh event per run, this binding must move
        to run start.
        """
        self._parent_cancel = cancel_event

    def _emit(self, event_type: str, **data: Any) -> None:
        if self._event_callback is None:
            return
        try:
            self._event_callback(event_type, data)
        except Exception:  # noqa: BLE001 — event emission never breaks a run
            logger.debug("event_callback failed for %s", event_type, exc_info=True)

    def execute(self, **kwargs: Any) -> str:
        """Run the named specialist and return its self-contained result."""
        from src.agent.loop import AgentLoop
        from src.agent.skills import SkillsLoader
        from src.providers.chat import ChatLLM
        from src.tools import build_filtered_registry

        name = str(kwargs.get("specialist", "")).strip()
        task = str(kwargs.get("task", "")).strip()
        specs = load_specialists()
        spec = specs.get(name)
        if spec is None:
            return _error(
                f"Unknown specialist {name!r}.",
                available_specialists=sorted(specs),
            )
        if not task:
            return _error(
                "task must be a non-empty, self-contained brief — the "
                "specialist cannot see this conversation."
            )

        self._emit("subagent_started", specialist=name)
        started = time.monotonic()

        registry = build_filtered_registry(
            spec.tools,
            include_shell_tools=False,
            skill_allowlist=spec.skills,
        )
        skills_loader = SkillsLoader(only=spec.skills)
        llm = ChatLLM(model_name=spec.model_name)
        child = AgentLoop(
            registry=registry,
            llm=llm,
            event_callback=None,
            max_iterations=spec.max_iterations,
            skills_loader=skills_loader,
            system_template=SPECIALIST_SYSTEM_PROMPT,
            role_prompt=spec.prompt,
        )

        # Per-call state below is local by contract (see module docstring).
        child_done = threading.Event()
        outcome: Dict[str, Any] = {}
        run_tag = uuid.uuid4().hex[:8]

        def _child_body() -> None:
            try:
                outcome["result"] = child.run(task, session_id="")
            except (
                Exception
            ) as exc:  # noqa: BLE001 — last-resort guard; the child loop normally converts errors into its result dict
                outcome["error"] = f"{type(exc).__name__}: {exc}"
            finally:
                child_done.set()

        parent_cancel = self._parent_cancel

        def _cancel_relay() -> None:
            while not child_done.wait(_CANCEL_RELAY_POLL_SECONDS):
                if parent_cancel is not None and parent_cancel.is_set():
                    child.cancel()
                    return

        child_thread = threading.Thread(
            target=_child_body, name=f"specialist-{name}-{run_tag}", daemon=True
        )
        relay_thread = threading.Thread(
            target=_cancel_relay, name=f"specialist-relay-{name}-{run_tag}", daemon=True
        )
        # Defensive default, not a bug fix: every current path through the try
        # either assigns timed_out or propagates, so nothing today reads it
        # unbound. Pre-initializing hardens against future edits that add an
        # early-exit path past the try.
        timed_out = False
        try:
            child_thread.start()
            relay_thread.start()
            child_thread.join(spec.timeout_seconds)
            timed_out = child_thread.is_alive()
            if timed_out:
                child.cancel()
                child_thread.join(_CANCEL_GRACE_SECONDS)
        finally:
            child_done.set()
            # Close the child transport even when the thread is abandoned:
            # under a zombie, closing the self-created HTTP client breaks its
            # blocked stream so the daemon thread can die instead of leaking
            # an open connection.
            try:
                llm.close()
            except Exception:  # noqa: BLE001
                logger.debug("child llm close failed", exc_info=True)

        duration_s = round(time.monotonic() - started, 1)
        result = outcome.get("result")
        if timed_out:
            status = "timeout"
            if child_thread.is_alive():
                logger.warning(
                    "specialist %s did not exit within the cancel grace period; "
                    "daemon thread %s abandoned",
                    name,
                    child_thread.name,
                )
        elif outcome.get("error"):
            status = "error"
        elif isinstance(result, dict):
            status = str(result.get("status", "ok"))
        else:
            status = "error"
            outcome["error"] = "specialist returned no result"

        usage = self._read_child_usage(result if isinstance(result, dict) else None)
        payload: Dict[str, Any] = {
            "status": status,
            "specialist": name,
            "duration_s": duration_s,
            "content": (
                (result or {}).get("content", "") if isinstance(result, dict) else ""
            ),
            "run_dir": (
                (result or {}).get("run_dir") if isinstance(result, dict) else None
            ),
            "iterations": (
                (result or {}).get("iterations") if isinstance(result, dict) else None
            ),
        }
        if outcome.get("error"):
            payload["error"] = outcome["error"]
        if isinstance(result, dict) and result.get("reason"):
            payload["reason"] = result["reason"]
        if usage is not None:
            payload["usage"] = usage
        if timed_out:
            # A child result that lands during the cancel grace window must
            # not ride along on a timeout payload: status=timeout always
            # carries empty content. run_dir stays for partial-work recovery.
            payload["content"] = ""
            payload["error"] = (
                f"specialist exceeded its {spec.timeout_seconds}s budget and was "
                "cancelled; any partial work is in run_dir"
            )

        self._emit(
            "subagent_completed",
            specialist=name,
            status=status,
            duration_s=duration_s,
            iterations=payload.get("iterations"),
        )
        return json.dumps(payload, ensure_ascii=False)

    @staticmethod
    def _read_child_usage(result: Optional[Dict[str, Any]]) -> Optional[Dict[str, int]]:
        """Read the child run's provider-reported token totals, if any.

        The nested run persists ``llm_usage.json`` in its own run directory
        like any other run; the totals are surfaced so the caller can account
        for the delegation's cost. Missing or malformed data yields ``None``.
        """
        if not result:
            return None
        run_dir = result.get("run_dir")
        if not run_dir:
            return None
        try:
            from pathlib import Path

            usage_path = Path(run_dir) / "llm_usage.json"
            data = json.loads(usage_path.read_text(encoding="utf-8"))
            totals = data.get("totals")
            if not isinstance(totals, dict) or not totals.get("calls"):
                return None
            return {
                "input_tokens": int(totals.get("input_tokens") or 0),
                "output_tokens": int(totals.get("output_tokens") or 0),
                "calls": int(totals.get("calls") or 0),
            }
        except Exception:  # noqa: BLE001 — usage is advisory, never fatal
            logger.debug("child usage unreadable", exc_info=True)
            return None
