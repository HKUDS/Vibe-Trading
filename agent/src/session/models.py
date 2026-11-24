"""Session data models for the core Session, Message, and Attempt entities."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional

from src.tools.redaction import redact_text


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AuthMethod(str, Enum):
    """How a request proved it was allowed in."""

    #: One process-wide static bearer key. Authorises, cannot identify.
    SHARED_KEY = "shared_key"
    #: No key configured; the request came from loopback and was trusted.
    LOOPBACK_TRUST = "loopback_trust"
    #: Named human authenticated through an identity provider.
    FEDERATED_IDENTITY = "federated_identity"


#: Auth methods that can attribute an action to a named human. Everything else
#: proves only that *somebody with the secret* acted.
ATTRIBUTABLE_AUTH_METHODS: frozenset[AuthMethod] = frozenset({AuthMethod.FEDERATED_IDENTITY})


@dataclass(frozen=True)
class Principal:
    """Represent authentication, with named attribution available only through an identity provider."""

    subject: str
    auth_method: AuthMethod
    tenant: Optional[str] = None
    display_name: Optional[str] = None
    attributable: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        if not str(self.subject).strip():
            raise ValueError("a principal must have a non-empty subject")
        object.__setattr__(
            self, "attributable", self.auth_method in ATTRIBUTABLE_AUTH_METHODS
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the principal to a JSON-safe dictionary."""
        return {
            "subject": self.subject,
            "auth_method": self.auth_method.value,
            "tenant": self.tenant,
            "display_name": self.display_name,
            "attributable": self.attributable,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Principal:
        """Recompute attribution from the authentication method so stored records cannot grant it.

        Raises:
            ValueError: The authentication method is missing or unknown.
        """
        return cls(
            subject=data["subject"],
            auth_method=AuthMethod(data["auth_method"]),
            tenant=data.get("tenant"),
            display_name=data.get("display_name"),
        )


class SessionStatus(str, Enum):
    """Session lifecycle states."""

    ACTIVE = "active"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class AttemptStatus(str, Enum):
    """Statuses for a single execution attempt."""

    PENDING = "pending"
    RUNNING = "running"
    WAITING_USER = "waiting_user"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


@dataclass
class Session:
    """A multi-turn conversation session."""

    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    title: str = ""
    status: SessionStatus = SessionStatus.ACTIVE
    created_at: str = field(default_factory=_utc_now_iso)
    updated_at: str = field(default_factory=_utc_now_iso)
    last_attempt_id: Optional[str] = None
    config: Dict[str, Any] = field(default_factory=dict)
    owner: Optional[Principal] = None
    forked_from_session_id: Optional[str] = None
    forked_from_turn_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the session to a dictionary."""
        data = asdict(self)
        data["status"] = self.status.value
        data["owner"] = self.owner.to_dict() if self.owner else None
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Session:
        """Deserialize a session from a dictionary."""
        data = dict(data)
        if "status" in data:
            data["status"] = SessionStatus(data["status"])
        owner = data.get("owner")
        if isinstance(owner, dict):
            data["owner"] = Principal.from_dict(owner)
        elif owner is None:
            data.pop("owner", None)
        return cls(**data)


@dataclass
class Message:
    """A session message such as user input or system output."""

    message_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    session_id: str = ""
    role: str = "user"
    content: str = ""
    created_at: str = field(default_factory=_utc_now_iso)
    linked_attempt_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the message to a dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Message:
        """Deserialize a message from a dictionary."""
        data = dict(data)
        return cls(**data)


@dataclass
class Attempt:
    """A strategy execution attempt corresponding to one pipeline run."""

    attempt_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    session_id: str = ""
    parent_attempt_id: Optional[str] = None
    status: AttemptStatus = AttemptStatus.PENDING
    prompt: str = ""
    run_dir: Optional[str] = None
    summary: Optional[str] = None
    created_at: str = field(default_factory=_utc_now_iso)
    started_at: Optional[float] = None
    completed_at: Optional[str] = None
    error: Optional[str] = None
    metrics: Optional[Dict[str, Any]] = None
    queued_input_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the attempt to a dictionary."""
        data = asdict(self)
        if self.queued_input_id is None:
            data.pop("queued_input_id")
        data["status"] = self.status.value
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Attempt:
        """Deserialize an attempt from a dictionary."""
        data = dict(data)
        if "status" in data:
            data["status"] = AttemptStatus(data["status"])
        if data.get("error"):
            data["error"] = redact_text(data["error"])
        return cls(**data)

    def mark_running(self) -> None:
        """Mark the attempt as running and record when execution began."""
        self.status = AttemptStatus.RUNNING
        self.started_at = time.time()
        self.completed_at = None

    def mark_completed(self, summary: Optional[str] = None) -> None:
        """Mark the attempt as completed."""
        self._mark_terminal(AttemptStatus.COMPLETED)
        if summary:
            self.summary = summary

    def mark_waiting_user(self, summary: Optional[str] = None) -> None:
        """Pause the attempt while a structured question awaits an answer."""
        self._mark_terminal(AttemptStatus.WAITING_USER)
        if summary:
            self.summary = summary

    def mark_failed(self, error: str) -> None:
        """Mark the attempt as failed."""
        self._mark_terminal(AttemptStatus.FAILED)
        self.error = redact_text(error)

    def mark_cancelled(self, reason: str = "") -> None:
        """Mark the attempt as user-cancelled."""
        self._mark_terminal(AttemptStatus.CANCELLED)
        if reason:
            self.error = redact_text(reason)

    def mark_interrupted(self, reason: str = "") -> None:
        """Mark the attempt as interrupted by process lifecycle."""
        self._mark_terminal(AttemptStatus.INTERRUPTED)
        if reason:
            self.error = redact_text(reason)

    def _mark_terminal(self, status: AttemptStatus) -> None:
        self.status = status
        self.completed_at = _utc_now_iso()


class SessionBusyError(RuntimeError):
    """Raised when a session already has an in-flight run."""
