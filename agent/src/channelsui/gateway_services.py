"""Gateway services used by the WebSocket channel."""

from __future__ import annotations

import json
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.config.paths import get_workspace_path
from src.security.workspace_access import WorkspaceScopeError


@dataclass
class WebSocketTokenIssuer:
    """Short-lived one-time token issuer for WebSocket clients."""

    _issued: dict[str, float] = field(default_factory=dict)

    def issue_token(self, *, ttl_s: int = 300) -> tuple[str, int]:
        """Issue a one-time token.

        Args:
            ttl_s: Token lifetime in seconds.

        Returns:
            ``(token, expires_in_seconds)``.
        """
        self._gc()
        token = secrets.token_urlsafe(32)
        self._issued[token] = time.time() + ttl_s
        return token, ttl_s

    def take_issued_token_if_valid(self, token: str | None) -> bool:
        """Consume a valid issued token exactly once."""
        if not token:
            return False
        self._gc()
        expires_at = self._issued.pop(token, None)
        return bool(expires_at and expires_at >= time.time())

    def clear(self) -> None:
        """Clear all issued tokens."""
        self._issued.clear()

    def _gc(self) -> None:
        now = time.time()
        for token, expires_at in list(self._issued.items()):
            if expires_at < now:
                self._issued.pop(token, None)


@dataclass(frozen=True)
class WorkspaceScope:
    """Workspace scope snapshot carried in WebSocket session metadata."""

    root: str
    restrict_to_workspace: bool = True

    def payload(self) -> dict[str, Any]:
        """Return the client-facing workspace scope."""
        return {
            "root": self.root,
            "restrict_to_workspace": self.restrict_to_workspace,
        }

    def metadata(self) -> dict[str, Any]:
        """Return the session metadata representation."""
        return self.payload()


@dataclass
class WorkspaceService:
    """Resolve and persist per-chat workspace scope."""

    workspace_path: Path = field(default_factory=get_workspace_path)
    default_restrict_to_workspace: bool = True
    _scopes: dict[str, WorkspaceScope] = field(default_factory=dict)

    def _default_scope(self) -> WorkspaceScope:
        return WorkspaceScope(
            root=str(self.workspace_path.expanduser().resolve()),
            restrict_to_workspace=self.default_restrict_to_workspace,
        )

    def scope_for_new_chat(self, envelope: dict[str, Any], *, controls_available: bool) -> WorkspaceScope:
        """Build a scope for a new chat envelope."""
        del controls_available
        return self._scope_from_envelope(envelope) or self._default_scope()

    def scope_for_set_request(
        self,
        envelope: dict[str, Any],
        *,
        chat_id: str,
        chat_running: bool,
        controls_available: bool,
    ) -> WorkspaceScope:
        """Build a scope update from a client request."""
        del chat_running, controls_available
        return self._scope_from_envelope(envelope) or self._scopes.get(chat_id) or self._default_scope()

    def scope_for_message(
        self,
        envelope: dict[str, Any],
        *,
        chat_id: str,
        chat_running: bool,
        controls_available: bool,
    ) -> WorkspaceScope:
        """Return the active scope for a message."""
        del chat_running, controls_available
        return self._scope_from_envelope(envelope) or self._scopes.get(chat_id) or self._default_scope()

    def persist_scope(self, chat_id: str, scope: WorkspaceScope) -> None:
        """Persist an in-memory scope for the current gateway process."""
        self._scopes[chat_id] = scope

    def _scope_from_envelope(self, envelope: dict[str, Any]) -> WorkspaceScope | None:
        raw = envelope.get("workspace_scope")
        if not isinstance(raw, dict):
            return None
        root = raw.get("root")
        if not isinstance(root, str) or not root.strip():
            return None
        resolved = Path(root).expanduser().resolve()
        default_root = self.workspace_path.expanduser().resolve()
        if self.default_restrict_to_workspace and not _is_relative_to(resolved, default_root):
            raise WorkspaceScopeError(f"workspace root must stay under {default_root}")
        restrict = raw.get("restrict_to_workspace", self.default_restrict_to_workspace)
        return WorkspaceScope(root=str(resolved), restrict_to_workspace=bool(restrict))


class SimpleHttpRouter:
    """Small HTTP fallback router for WebSocket server requests."""

    def workspace_controls_available(self, connection: Any) -> bool:
        """Return whether workspace controls may be shown to this connection."""
        del connection
        return True

    async def dispatch(self, connection: Any, request: Any) -> Any:
        """Return a compact JSON 404 for non-WebSocket HTTP requests."""
        del request
        return connection.respond(
            404,
            json.dumps({"detail": "not found"}, ensure_ascii=False),
        )


class MediaService:
    """Media staging helpers for WebSocket payloads."""

    def rewrite_local_markdown_images(self, text: str) -> str:
        """Return text unchanged until an HTTP media server is configured."""
        return text

    def sign_or_stage_media_path(self, path: Path) -> dict[str, str] | None:
        """Return metadata for a local media path when it exists."""
        try:
            resolved = path.expanduser().resolve()
        except OSError:
            return None
        if not resolved.exists() or not resolved.is_file():
            return None
        return {"name": resolved.name, "path": str(resolved)}


@dataclass
class TranscriptService:
    """In-process transcript event bridge for the WebSocket channel."""

    events: list[dict[str, Any]] = field(default_factory=list)

    def client_turn_metadata(self, turn_id: Any) -> dict[str, Any]:
        """Return metadata derived from a client turn id."""
        return {"turn_id": turn_id} if isinstance(turn_id, str) and turn_id else {}

    def append_user_message(
        self,
        chat_id: str,
        content: str,
        *,
        metadata: dict[str, Any] | None = None,
        media_paths: list[str] | None = None,
        cli_apps: list[str] | None = None,
        mcp_presets: list[str] | None = None,
    ) -> None:
        """Record a user-message transcript event for the current process."""
        self.events.append(
            {
                "phase": "user",
                "chat_id": chat_id,
                "content": content,
                "metadata": metadata or {},
                "media_paths": media_paths or [],
                "cli_apps": cli_apps or [],
                "mcp_presets": mcp_presets or [],
            }
        )

    def prepare_and_append(
        self,
        chat_id: str,
        payload: dict[str, Any],
        *,
        metadata: dict[str, Any] | None = None,
        phase: str = "",
        include_source: bool = False,
        transcript_overrides: dict[str, Any] | None = None,
    ) -> None:
        """Record a generated transcript event for the current process."""
        self.events.append(
            {
                "phase": phase,
                "chat_id": chat_id,
                "payload": payload,
                "metadata": metadata or {},
                "include_source": include_source,
                "transcript_overrides": transcript_overrides or {},
            }
        )


class GatewaySessionManagerAdapter:
    """Adapt Vibe-Trading SessionService to the WebSocket gateway contract."""

    def __init__(self, service: Any) -> None:
        self._service = service

    def __getattr__(self, name: str) -> Any:
        return getattr(self._service, name)

    def read_session_file(self, session_id: str) -> dict[str, Any]:
        """Return a JSON-like session row for WebSocket hydration."""
        getter = getattr(self._service, "get_session", None)
        if not callable(getter):
            return {"metadata": {}}
        session = getter(session_id)
        if session is None and ":" in session_id:
            session = getter(session_id.split(":", 1)[1])
        if session is None:
            return {"metadata": {}}
        data = session.to_dict() if hasattr(session, "to_dict") else dict(getattr(session, "__dict__", {}))
        config = data.get("config") if isinstance(data.get("config"), dict) else {}
        metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else config.get("metadata", {})
        data["metadata"] = metadata if isinstance(metadata, dict) else {}
        return data


@dataclass
class GatewayServices:
    """Service bundle required by :class:`src.channels.websocket.WebSocketChannel`."""

    session_manager: Any = None
    cron_service: Any = None
    runtime_model_name: Any = None
    cron_pending_job_ids: Any = None
    static_dist_path: Any = None
    workspace_path: Path | None = None
    default_restrict_to_workspace: bool = True
    disabled_skills: set[str] = field(default_factory=set)
    logger: Any = None
    runtime_surface: str = "browser"
    runtime_capabilities: dict[str, Any] = field(default_factory=dict)
    http: SimpleHttpRouter = field(default_factory=SimpleHttpRouter)
    tokens: WebSocketTokenIssuer = field(default_factory=WebSocketTokenIssuer)
    media: MediaService = field(default_factory=MediaService)
    transcripts: TranscriptService = field(default_factory=TranscriptService)
    workspaces: WorkspaceService = field(default_factory=WorkspaceService)


def build_gateway_services(**kwargs: Any) -> GatewayServices:
    """Build a gateway service bundle from optional overrides."""
    allowed = {
        key: value
        for key, value in kwargs.items()
        if key in GatewayServices.__dataclass_fields__
    }
    session_manager = allowed.get("session_manager")
    if session_manager is not None and not hasattr(session_manager, "read_session_file"):
        allowed["session_manager"] = GatewaySessionManagerAdapter(session_manager)
    workspace_path = allowed.get("workspace_path")
    if workspace_path is not None and "workspaces" not in allowed:
        allowed["workspaces"] = WorkspaceService(
            workspace_path=Path(workspace_path),
            default_restrict_to_workspace=bool(
                allowed.get("default_restrict_to_workspace", True)
            ),
        )
    return GatewayServices(**allowed)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
