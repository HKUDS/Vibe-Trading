from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, Optional

from src.api.state import _get_session_service

logger = logging.getLogger(__name__)

# ============================================================================
# Live-channel SSE relay helpers
# ============================================================================

# These are the privileged SURFACE actions of the live-trading channel
# (live-trading SPEC, Consent §1/§3/§4). None is an agent tool:
#   - POST /mandate/commit  -> the single mandate writer (commit_mandate)
#   - POST /live/halt       -> trip the kill switch (P5 trip_halt)
#   - POST /live/resume     -> clear the kill switch (P5 clear_halt)
# Each best-effort relays a mandate.committed / live.halted / live.action event
# through the EXISTING session EventBus, so the frontend's already-wired
# /sessions/{id}/events SSE stream reflects the state change. No new bus.


def _emit_live_event(session_id: Optional[str], event_type: str, data: Dict[str, Any]) -> None:
    """Best-effort relay of a live-channel event through the existing bus.

    The event flows out the existing ``/sessions/{session_id}/events`` SSE
    stream. Notifications never gate autonomy (SPEC Consent §5): a relay failure
    or a missing session is swallowed — the state change already happened on disk.

    Args:
        session_id: Target session, or ``None`` to skip relay.
        event_type: SSE event name (``mandate.committed`` / ``live.halted`` /
            ``live.resumed`` / ``live.action``).
        data: JSON-serializable event payload.
    """
    if not session_id:
        return
    try:
        svc = _get_session_service()
        if svc and svc.get_session(session_id):
            svc.event_bus.emit(session_id, event_type, data)
    except Exception:  # pragma: no cover - relay is non-blocking by contract
        logger.debug("live event relay failed for %s/%s", session_id, event_type, exc_info=True)


# ---- C1: propose_mandate_profiles tool_result -> mandate.proposal SSE frame ----
#
# The agent surfaces a proposal by calling the read-only ``propose_mandate_profiles``
# tool whose tool_result JSON body is ``{"type":"mandate.proposal", ...}`` (SPEC
# Consent §1). The CLI / frontend listen for a TOP-LEVEL ``mandate.proposal`` SSE
# event. ``src/agent/loop.py`` only emits a truncated ``tool_result`` event
# (``preview = result[:200]``) and is PROTECTED — we do NOT edit it. Instead this
# open-file SSE seam (TASKS "Remaining integration items" #1, the recommended
# wiring) detects the propose tool's tool_result on the stream, recovers the
# ``proposal_id`` from the preview, reloads the FULL persisted proposal from the
# proposal store (written by the tool before it returned), and emits the
# ``mandate.proposal`` frame. No protected touch.

_PROPOSAL_TOOL_NAME = "propose_mandate_profiles"
_PROPOSAL_ID_RE = re.compile(r'"proposal_id"\s*:\s*"(mp_[0-9a-f]{32})"')


def _load_full_proposal(proposal_id: str) -> Optional[Dict[str, Any]]:
    """Reload a persisted ``mandate.proposal`` payload by id, broker-agnostic.

    The propose tool persists the full proposal under
    ``<runtime_root>/live/<broker>/proposals/<proposal_id>.json`` before
    returning. The SSE ``tool_result`` preview is too short to carry the full
    body, so the relay reloads it from disk. The broker segment is unknown from
    the preview alone, so every broker's proposals directory is searched.

    Args:
        proposal_id: The ``mp_...`` id parsed from the tool_result preview.

    Returns:
        The full proposal dict, or ``None`` when not found / unreadable.
    """
    try:
        from src.live.paths import live_root

        for proposal_path in live_root().glob(f"*/proposals/{proposal_id}.json"):
            try:
                data = json.loads(proposal_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(data, dict) and data.get("type") == "mandate.proposal":
                return data
    except Exception:  # pragma: no cover - relay must never break the stream
        logger.debug("mandate.proposal reload failed for %s", proposal_id, exc_info=True)
    return None


def _mandate_proposal_frame_from_tool_result(event: Any) -> Optional[str]:
    """Build a ``mandate.proposal`` SSE frame from a propose-tool tool_result.

    Args:
        event: An ``SSEEvent`` flowing through the session stream.

    Returns:
        A ready-to-yield SSE text frame for the ``mandate.proposal`` event, or
        ``None`` when ``event`` is not a successful propose-tool result or the
        proposal cannot be recovered.
    """
    data = getattr(event, "data", None)
    if getattr(event, "event_type", None) != "tool_result" or not isinstance(data, dict):
        return None
    if data.get("tool") != _PROPOSAL_TOOL_NAME or data.get("status") != "ok":
        return None
    match = _PROPOSAL_ID_RE.search(str(data.get("preview") or ""))
    if not match:
        return None
    proposal = _load_full_proposal(match.group(1))
    if proposal is None:
        return None

    from src.session.events import SSEEvent

    frame = SSEEvent(
        event_type="mandate.proposal",
        data=proposal,
        session_id=getattr(event, "session_id", "") or "",
    )
    return frame.to_sse()


_LIVE_ACTION_ID_RE = re.compile(r'"audit_id"\s*:\s*"(la_[0-9a-zA-Z]+)"')


def _load_live_action_record(audit_id: str) -> Optional[Dict[str, Any]]:
    """Reload a redacted live-action record from the ledger by ``audit_id``.

    The order guard embeds its (already-redacted) audit record under the
    ``live_action`` key of its tool_result, but the SSE ``tool_result`` preview
    is truncated to ~200 chars, so the full record is reloaded from the
    append-only ledger at ``<runtime_root>/live/audit.jsonl``.

    Args:
        audit_id: The ``la_...`` id parsed from the tool_result preview.

    Returns:
        The full redacted live-action record, or ``None`` when not found.
    """
    try:
        from src.live.paths import live_root

        ledger = live_root() / "audit.jsonl"
        if not ledger.exists():
            return None
        for line in reversed(ledger.read_text(encoding="utf-8").splitlines()):
            if audit_id not in line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict) and record.get("audit_id") == audit_id:
                return record
    except Exception:  # pragma: no cover - relay must never break the stream
        logger.debug("live.action reload failed for %s", audit_id, exc_info=True)
    return None


def _live_action_frame_from_tool_result(event: Any) -> Optional[str]:
    """Build a ``live.action`` SSE frame from an order-guard tool_result.

    The order guard stamps a ``live_action`` audit record onto its tool_result
    (and the ledger) for every live order placed/rejected. The interactive agent
    loop only emits a truncated ``tool_result`` event and is PROTECTED, so this
    open-file relay surfaces the live action as a top-level ``live.action`` event
    for the timeline — without touching ``src/agent/loop.py``. (Autonomous-runner
    actions already emit ``live.action`` natively via the runner's event bus.)

    Args:
        event: An ``SSEEvent`` flowing through the session stream.

    Returns:
        A ready-to-yield ``live.action`` SSE frame, or ``None`` when the event is
        not an order-guard result carrying a recoverable live-action record.
    """
    data = getattr(event, "data", None)
    if getattr(event, "event_type", None) != "tool_result" or not isinstance(data, dict):
        return None
    preview = str(data.get("preview") or "")
    if '"live_action"' not in preview:
        return None
    match = _LIVE_ACTION_ID_RE.search(preview)
    if not match:
        return None
    record = _load_live_action_record(match.group(1))
    if record is None:
        return None

    from src.session.events import SSEEvent

    frame = SSEEvent(
        event_type="live.action",
        data=record,
        session_id=getattr(event, "session_id", "") or "",
    )
    return frame.to_sse()
