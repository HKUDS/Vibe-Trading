"""Channel manager for coordinating chat channels."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Any

from src.channels.base import BaseChannel
from src.channels.bus.events import OutboundMessage
from src.channels.bus.queue import MessageBus
from src.channels.registry import (
    discover_channel_names,
    discover_plugins,
    inspect_channels,
    load_channel_class,
)
from src.config.paths import get_workspace_path

logger = logging.getLogger(__name__)

# Retry delays for message sending (exponential backoff: 1s, 2s, 4s)
_SEND_RETRY_DELAYS = (1, 2, 4)

_BOOL_CAMEL_ALIASES: dict[str, str] = {
    "send_progress": "sendProgress",
    "send_tool_hints": "sendToolHints",
    "show_reasoning": "showReasoning",
}


class ChannelManager:
    """Manages chat channels and coordinates message routing.

    Responsibilities:
    - Initialize enabled channels (Telegram, Discord, Slack, etc.)
    - Start/stop channels
    - Route outbound messages
    """

    def __init__(
        self,
        config: Any,  # ChannelsConfig or dict
        bus: MessageBus,
        *,
        session_service: Any | None = None,
        cron_service: Any | None = None,
    ) -> None:
        self.config = config
        self.bus = bus
        self._session_service = session_service
        self._cron_service = cron_service
        self.channels: dict[str, BaseChannel] = {}
        self._dispatch_task: asyncio.Task | None = None
        self._origin_reply_fingerprints: dict[tuple[str, str, str], str] = {}
        self._status: dict[str, dict[str, Any]] = {}

        self._init_channels()

    def _init_channels(self) -> None:
        """Initialize channels discovered via pkgutil scan + entry_points plugins."""
        self._status = inspect_channels(self.config)
        enabled_names = {
            name
            for name, status in self._status.items()
            if status.get("enabled") is True
        }
        plugin_classes = discover_plugins(enabled_names)
        builtins = set(discover_channel_names())

        for name in sorted(enabled_names):
            section = self._get_channel_config(name)
            if section is None:
                continue
            if self._status.get(name, {}).get("available") is False:
                logger.warning(
                    "%s channel not available: %s",
                    name,
                    self._status[name].get("error", "unavailable"),
                )
                continue
            try:
                cls = load_channel_class(name) if name in builtins else plugin_classes[name]
            except Exception as exc:  # noqa: BLE001 - status endpoint must explain startup gaps
                self._status.setdefault(name, {})
                self._status[name].update(
                    {
                        "available": False,
                        "loaded": False,
                        "running": False,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
                logger.warning("%s channel not available: %s", name, exc)
                continue

            try:
                kwargs = self._build_channel_kwargs(name)
                channel = cls(section, self.bus, **kwargs)
                # Resolve global → per-channel boolean overrides
                channel.send_progress = self._resolve_bool_override(
                    section, "send_progress", self._global_bool("send_progress", True),
                )
                channel.send_tool_hints = self._resolve_bool_override(
                    section, "send_tool_hints", self._global_bool("send_tool_hints", False),
                )
                channel.show_reasoning = self._resolve_bool_override(
                    section, "show_reasoning", self._global_bool("show_reasoning", True),
                )
                self.channels[name] = channel
                self._status.setdefault(name, {})
                self._status[name].update(
                    {
                        "available": True,
                        "loaded": True,
                        "running": channel.is_running,
                        "display_name": getattr(cls, "display_name", name),
                        "error": "",
                    }
                )
                logger.info("%s channel enabled", cls.display_name)
            except Exception as exc:
                self._status.setdefault(name, {})
                self._status[name].update(
                    {
                        "loaded": False,
                        "running": False,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
                logger.warning("%s channel not available", name, exc_info=True)

        self._validate_allow_from()

    def _build_channel_kwargs(self, name: str) -> dict[str, Any]:
        """Build adapter-specific constructor kwargs for channels that need services."""
        if name == "websocket":
            from src.channelsui.gateway_services import build_gateway_services

            return {
                "gateway": build_gateway_services(
                    session_manager=self._session_service,
                    cron_service=self._cron_service,
                    workspace_path=get_workspace_path(),
                )
            }
        if name == "matrix":
            return {
                "restrict_to_workspace": self._global_bool("restrict_to_workspace", False),
                "workspace": get_workspace_path(),
            }
        return {}

    def _get_channel_config(self, name: str) -> dict | None:
        """Get the config section for channel *name*."""
        if isinstance(self.config, dict):
            return self.config.get(name)
        return getattr(self.config, name, None)

    def _global_bool(self, key: str, default: bool) -> bool:
        """Read a global boolean from the top-level channels config."""
        if isinstance(self.config, dict):
            return self.config.get(key, default)
        return getattr(self.config, key, default)

    def _validate_allow_from(self) -> None:
        for name, ch in self.channels.items():
            cfg = ch.config
            if isinstance(cfg, dict):
                allow = cfg.get("allow_from") if "allow_from" in cfg else cfg.get("allowFrom")
            else:
                allow = getattr(cfg, "allow_from", None)
            if allow is None:
                logger.info(
                    '"%s" has no allowFrom; unapproved users will receive a pairing code',
                    name,
                )

    def _should_send_progress(self, channel_name: str, *, tool_hint: bool = False) -> bool:
        """Return whether progress (or tool-hints) may be sent to *channel_name*."""
        ch = self.channels.get(channel_name)
        if ch is None:
            logger.debug("Progress check for unknown channel: %s", channel_name)
            return False
        return ch.send_tool_hints if tool_hint else ch.send_progress

    def _resolve_bool_override(self, section: Any, key: str, default: bool) -> bool:
        """Return *key* from *section* if it is a bool, otherwise *default*.

        For dict configs also checks the camelCase alias.
        """
        if isinstance(section, dict):
            value = section.get(key)
            if value is None:
                camel = _BOOL_CAMEL_ALIASES.get(key)
                if camel:
                    value = section.get(camel)
            return value if isinstance(value, bool) else default
        value = getattr(section, key, None)
        return value if isinstance(value, bool) else default

    async def _start_channel(self, name: str, channel: BaseChannel) -> None:
        """Start a channel and log any exceptions."""
        try:
            await channel.start()
        except Exception:
            logger.exception("Failed to start channel %s", name)

    async def start_all(self) -> None:
        """Start all channels and the outbound dispatcher."""
        if not self.channels:
            logger.warning("No channels enabled")
            return

        self._dispatch_task = asyncio.create_task(self._dispatch_outbound())

        tasks = []
        for name, channel in self.channels.items():
            logger.info("Starting %s channel...", name)
            tasks.append(asyncio.create_task(self._start_channel(name, channel)))

        await asyncio.gather(*tasks, return_exceptions=True)
        for name, channel in self.channels.items():
            self._status.setdefault(name, {})
            self._status[name]["running"] = channel.is_running

    async def stop_all(self) -> None:
        """Stop all channels and the dispatcher."""
        logger.info("Stopping all channels...")

        if self._dispatch_task:
            self._dispatch_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._dispatch_task

        for name, channel in self.channels.items():
            try:
                await channel.stop()
                logger.info("Stopped %s channel", name)
            except asyncio.CancelledError:
                if asyncio.current_task() and asyncio.current_task().cancelling():
                    raise
                logger.debug("Channel %s stop task was already cancelled", name)
            except Exception:
                logger.exception("Error stopping %s", name)
            finally:
                self._status.setdefault(name, {})
                self._status[name]["running"] = channel.is_running

    # --- Outbound dispatch ---

    @staticmethod
    def _fingerprint_content(content: str) -> str:
        normalized = " ".join(content.split())
        return hashlib.sha1(normalized.encode("utf-8")).hexdigest() if normalized else ""

    def _should_suppress_outbound(self, msg: OutboundMessage) -> bool:
        metadata = msg.metadata or {}
        if metadata.get("_progress"):
            return False
        fingerprint = self._fingerprint_content(msg.content)
        if not fingerprint:
            return False

        origin_message_id = metadata.get("origin_message_id")
        if isinstance(origin_message_id, str) and origin_message_id:
            key = (msg.channel, msg.chat_id, origin_message_id)
            if self._origin_reply_fingerprints.get(key) == fingerprint:
                return True
            self._origin_reply_fingerprints[key] = fingerprint

        message_id = metadata.get("message_id")
        if isinstance(message_id, str) and message_id:
            key = (msg.channel, msg.chat_id, message_id)
            self._origin_reply_fingerprints[key] = fingerprint

        return False

    async def _dispatch_outbound(self) -> None:
        """Dispatch outbound messages to the appropriate channel."""
        logger.info("Outbound dispatcher started")

        pending: list[OutboundMessage] = []

        while True:
            try:
                if pending:
                    msg = pending.pop(0)
                else:
                    msg = await asyncio.wait_for(
                        self.bus.consume_outbound(), timeout=1.0,
                    )

                # Reasoning routing
                if (
                    msg.metadata.get("_reasoning_delta")
                    or msg.metadata.get("_reasoning_end")
                    or msg.metadata.get("_reasoning")
                ):
                    channel = self.channels.get(msg.channel)
                    if channel is not None and channel.show_reasoning:
                        await self._send_with_retry(channel, msg)
                    continue

                # Progress / tool-hint filtering
                if msg.metadata.get("_progress"):
                    if msg.metadata.get("_tool_hint") and not self._should_send_progress(
                        msg.channel, tool_hint=True,
                    ):
                        continue
                    if not msg.metadata.get("_tool_hint") and not self._should_send_progress(
                        msg.channel, tool_hint=False,
                    ):
                        continue

                if msg.metadata.get("_retry_wait"):
                    continue

                # Coalesce consecutive _stream_delta messages
                if msg.metadata.get("_stream_delta") and not msg.metadata.get("_stream_end"):
                    msg, extra_pending = self._coalesce_stream_deltas(msg)
                    pending.extend(extra_pending)

                channel = self.channels.get(msg.channel)
                if channel:
                    if (
                        not msg.metadata.get("_stream_delta")
                        and not msg.metadata.get("_stream_end")
                        and not msg.metadata.get("_streamed")
                    ):
                        if self._should_suppress_outbound(msg):
                            logger.info(
                                "Suppressing duplicate outbound message to %s:%s",
                                msg.channel, msg.chat_id,
                            )
                            continue
                    await self._send_with_retry(channel, msg)
                else:
                    logger.warning("Unknown channel: %s", msg.channel)

            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

    @staticmethod
    async def _send_once(channel: BaseChannel, msg: OutboundMessage) -> None:
        """Send one outbound message without retry policy."""
        if msg.metadata.get("_reasoning_end"):
            await channel.send_reasoning_end(msg.chat_id, msg.metadata)
        elif msg.metadata.get("_reasoning_delta"):
            await channel.send_reasoning_delta(msg.chat_id, msg.content, msg.metadata)
        elif msg.metadata.get("_reasoning"):
            await channel.send_reasoning(msg)
        elif msg.metadata.get("_file_edit_events"):
            edits = msg.metadata.get("_file_edit_events")
            await channel.send_file_edit_events(
                msg.chat_id,
                edits if isinstance(edits, list) else [],
                msg.metadata,
            )
        elif msg.metadata.get("_stream_delta") or msg.metadata.get("_stream_end"):
            await channel.send_delta(msg.chat_id, msg.content, msg.metadata)
        elif not msg.metadata.get("_streamed"):
            await channel.send(msg)

    def _coalesce_stream_deltas(
        self, first_msg: OutboundMessage,
    ) -> tuple[OutboundMessage, list[OutboundMessage]]:
        """Merge consecutive _stream_delta messages for the same target.

        This reduces the number of API calls when the queue has accumulated
        multiple deltas.
        """
        first_metadata = first_msg.metadata or {}
        target_key = (
            first_msg.channel,
            first_msg.chat_id,
            first_metadata.get("_stream_id"),
        )
        combined_content = first_msg.content
        final_metadata = dict(first_msg.metadata or {})
        non_matching: list[OutboundMessage] = []

        while True:
            try:
                next_msg = self.bus.outbound.get_nowait()
            except asyncio.QueueEmpty:
                break

            next_metadata = next_msg.metadata or {}
            same_target = (
                next_msg.channel,
                next_msg.chat_id,
                next_metadata.get("_stream_id"),
            ) == target_key
            is_delta = next_metadata.get("_stream_delta")
            is_end = next_metadata.get("_stream_end")

            if same_target and is_delta and not final_metadata.get("_stream_end"):
                combined_content += next_msg.content
                if is_end:
                    final_metadata["_stream_end"] = True
                    break
            else:
                non_matching.append(next_msg)
                break

        merged = OutboundMessage(
            channel=first_msg.channel,
            chat_id=first_msg.chat_id,
            content=combined_content,
            metadata=final_metadata,
        )
        return merged, non_matching

    async def _send_with_retry(
        self, channel: BaseChannel, msg: OutboundMessage,
    ) -> None:
        """Send a message with retry on failure using exponential backoff."""
        max_attempts = 2  # conservative default
        if isinstance(self.config, dict):
            max_attempts = max(self.config.get("send_max_retries", 2), 1)
        elif hasattr(self.config, "send_max_retries"):
            max_attempts = max(self.config.send_max_retries, 1)

        for attempt in range(max_attempts):
            try:
                await self._send_once(channel, msg)
                return
            except asyncio.CancelledError:
                raise
            except Exception as e:
                if attempt == max_attempts - 1:
                    logger.exception(
                        "Failed to send to %s after %d attempts",
                        msg.channel, max_attempts,
                    )
                    return
                delay = _SEND_RETRY_DELAYS[min(attempt, len(_SEND_RETRY_DELAYS) - 1)]
                logger.warning(
                    "Send to %s failed (attempt %d/%d): %s, retrying in %ds",
                    msg.channel, attempt + 1, max_attempts, type(e).__name__, delay,
                )
                try:
                    await asyncio.sleep(delay)
                except asyncio.CancelledError:
                    raise

    # --- Public API ---

    def get_channel(self, name: str) -> BaseChannel | None:
        """Get a channel by name."""
        return self.channels.get(name)

    def get_status(self) -> dict[str, Any]:
        """Get status of all channels."""
        status = {name: dict(item) for name, item in self._status.items()}
        for name, channel in self.channels.items():
            status.setdefault(name, {})
            status[name].update(
                {
                    "enabled": True,
                    "loaded": True,
                    "running": channel.is_running,
                    "display_name": getattr(channel, "display_name", name),
                }
            )
        return status

    @property
    def enabled_channels(self) -> list[str]:
        """Get list of enabled channel names."""
        return list(self.channels.keys())
