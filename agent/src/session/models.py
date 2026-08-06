"""Session data models for the core Session, Message, and Attempt entities."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AuthMethod(str, Enum):
    """How a request proved it was allowed in.

    The distinction that matters is not which mechanism was used but whether the
    mechanism can name a human. A shared bearer key and loopback dev-trust both
    authorise; neither identifies. See :attr:`Principal.attributable`.
    """

    #: One process-wide static bearer key. Authorises, cannot identify.
    SHARED_KEY = "shared_key"
    #: No key configured; the request came from loopback and was trusted.
    LOOPBACK_TRUST = "loopback_trust"
    #: A named human authenticated through an identity provider. Not reachable
    #: today -- listed so that ``attributable`` has a True case to grow into and
    #: so downstream code branches on the enum rather than on a string it
    #: invented.
    FEDERATED_IDENTITY = "federated_identity"


#: Auth methods that can attribute an action to a named human. Everything else
#: proves only that *somebody with the secret* acted.
ATTRIBUTABLE_AUTH_METHODS: frozenset[AuthMethod] = frozenset({AuthMethod.FEDERATED_IDENTITY})


@dataclass(frozen=True)
class Principal:
    """Who a session belongs to, and how much that claim is worth.

    A ``Principal`` exists so that a number produced by this system can be
    traced to an actor. What it must never do is *manufacture* an identity the
    authentication layer could not establish.

    Today the API authenticates with one process-wide static bearer key, or with
    loopback dev-trust when no key is set. Under either, every request from
    every person looks identical. :attr:`attributable` is therefore False, and
    it stays False until an identity provider is wired in. Any control that
    needs a named human -- four-eyes approval, a MiFID II recipient log, SEC
    17a-4 attribution -- must check ``attributable`` and refuse rather than
    quote ``subject`` as if it were a person.

    Attributes:
        subject: Identifier for the actor. Under a shared secret this is a
            role label such as ``"shared-key-holder"``, not a person.
        auth_method: How the request was authorised.
        attributable: Whether ``subject`` names an actual human. Derived from
            ``auth_method`` at construction, never set by a caller -- a
            caller-settable flag is a caller-settable lie.
        tenant: Optional tenant scope, for a future multi-tenant runtime root.
        display_name: Optional human-readable label for the UI.
    """

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
        """Serialize the principal to a JSON-safe dictionary.

        Returns:
            A dictionary carrying ``attributable`` explicitly, so a consumer
            reading the serialized form cannot miss it.
        """
        return {
            "subject": self.subject,
            "auth_method": self.auth_method.value,
            "tenant": self.tenant,
            "display_name": self.display_name,
            "attributable": self.attributable,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Principal:
        """Rebuild a principal from its serialized form.

        ``attributable`` in the input is ignored and recomputed from
        ``auth_method``: a stored record whose flag was tampered with, or
        written by an older version, must not be able to assert attribution the
        auth method never supported.

        Args:
            data: Dictionary produced by :meth:`to_dict`.

        Returns:
            A Principal.

        Raises:
            ValueError: If ``auth_method`` is missing or unknown.
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


@dataclass
class Session:
    """A multi-turn conversation session.

    Attributes:
        session_id: Unique identifier.
        title: User-visible session title.
        status: Session status.
        created_at: Creation time in ISO format.
        updated_at: Last update time in ISO format.
        last_attempt_id: ID of the most recent Attempt.
        config: Session-level configuration such as model overrides or strategy parameters.
        owner: Principal the session belongs to, or None for a session created
            before principals existed or by a path that has no request context.
            None means "unknown owner", which is different from an
            unattributable one -- do not collapse the two.
    """

    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    title: str = ""
    status: SessionStatus = SessionStatus.ACTIVE
    created_at: str = field(default_factory=_utc_now_iso)
    updated_at: str = field(default_factory=_utc_now_iso)
    last_attempt_id: Optional[str] = None
    config: Dict[str, Any] = field(default_factory=dict)
    owner: Optional[Principal] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the session to a dictionary.

        Returns:
            A JSON-serializable dictionary.
        """
        data = asdict(self)
        data["status"] = self.status.value
        data["owner"] = self.owner.to_dict() if self.owner else None
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Session:
        """Deserialize a session from a dictionary.

        Args:
            data: Dictionary produced from parsed JSON.

        Returns:
            A Session instance.
        """
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
    """A session message such as user input or system output.

    Attributes:
        message_id: Unique identifier.
        session_id: Owning session ID.
        role: Message role: user / assistant / system.
        content: Message text content.
        created_at: Creation time in ISO format.
        linked_attempt_id: Related Attempt ID, if any.
        metadata: Additional metadata.
        tool_trail: Compact completed tool-call records for history hydration.
    """

    message_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    session_id: str = ""
    role: str = "user"
    content: str = ""
    created_at: str = field(default_factory=_utc_now_iso)
    linked_attempt_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    tool_trail: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the message to a dictionary.

        Returns:
            A JSON-serializable dictionary.
        """
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Message:
        """Deserialize a message from a dictionary.

        Args:
            data: Dictionary produced from parsed JSON.

        Returns:
            A Message instance.
        """
        return cls(**data)


@dataclass
class Attempt:
    """A strategy execution attempt corresponding to one pipeline run.

    Attributes:
        attempt_id: Unique identifier.
        session_id: Owning session ID.
        parent_attempt_id: Parent Attempt ID for follow-up modification scenarios.
        status: Execution status.
        prompt: User input that triggered this execution.
        run_dir: Run directory path.
        summary: Execution summary.
        react_trace: ReAct agent trace records.
        created_at: Creation time in ISO format.
        completed_at: Completion time in ISO format, if available.
        error: Error message when the attempt fails.
        metrics: Snapshot of backtest metrics.
    """

    attempt_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    session_id: str = ""
    parent_attempt_id: Optional[str] = None
    status: AttemptStatus = AttemptStatus.PENDING
    prompt: str = ""
    run_dir: Optional[str] = None
    summary: Optional[str] = None
    react_trace: List[Dict[str, Any]] = field(default_factory=list)
    created_at: str = field(default_factory=_utc_now_iso)
    completed_at: Optional[str] = None
    error: Optional[str] = None
    metrics: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the attempt to a dictionary.

        Returns:
            A JSON-serializable dictionary.
        """
        data = asdict(self)
        data["status"] = self.status.value
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Attempt:
        """Deserialize an attempt from a dictionary.

        Args:
            data: Dictionary produced from parsed JSON.

        Returns:
            An Attempt instance.
        """
        data = dict(data)
        if "status" in data:
            data["status"] = AttemptStatus(data["status"])
        return cls(**data)

    def mark_running(self) -> None:
        """Mark the attempt as running."""
        self.status = AttemptStatus.RUNNING
        self.completed_at = None

    def mark_completed(self, summary: Optional[str] = None) -> None:
        """Mark the attempt as completed.

        Args:
            summary: Execution summary.
        """
        self.status = AttemptStatus.COMPLETED
        self.completed_at = _utc_now_iso()
        if summary:
            self.summary = summary

    def mark_failed(self, error: str) -> None:
        """Mark the attempt as failed.

        Args:
            error: Error message.
        """
        self.status = AttemptStatus.FAILED
        self.completed_at = _utc_now_iso()
        self.error = error

    def mark_cancelled(self, reason: str = "") -> None:
        """Mark the attempt as user-cancelled.

        Cancelled is a distinct terminal status from FAILED so the UI does
        not misreport a cooperative cancel as an outage. ``AttemptStatus.CANCELLED``
        was previously dead code: ``SessionService._run_attempt`` lumped the
        result in with the failure branch and overwrote the status with FAILED.

        Args:
            reason: Optional free-text reason (usually ``"cancelled by user"``).
        """
        self.status = AttemptStatus.CANCELLED
        self.completed_at = _utc_now_iso()
        if reason:
            self.error = reason
