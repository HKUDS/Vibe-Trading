from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class IncomingMessage:
    """Standardized representation of an incoming message from any platform."""
    platform: str
    chat_id: str
    message_id: str
    content: str
    sender_id: str
    timestamp: float
    raw_payload: Dict[str, Any] = field(default_factory=dict)


class BasePlatformAdapter(ABC):
    """Abstract Base Class for all messaging platform adapters (Feishu, Telegram, DingTalk, etc.)."""

    @property
    @abstractmethod
    def platform_name(self) -> str:
        """The identifier name of the platform (e.g. 'feishu')."""
        pass

    @abstractmethod
    async def initialize(self, manager: Any) -> None:
        """Initialize connection, start listeners or webhooks, register platform manager reference."""
        pass

    @abstractmethod
    async def send_message(
        self,
        chat_id: str,
        content: str,
        title: Optional[str] = None,
    ) -> str:
        """Send a message to a specific chat channel.

        Returns:
            The platform-specific message ID.
        """
        pass

    @abstractmethod
    async def update_message(
        self,
        chat_id: str,
        message_id: str,
        content: str,
        title: Optional[str] = None,
    ) -> None:
        """Update an existing message (if supported by the platform, such as Feishu message cards)."""
        pass

    @abstractmethod
    async def close(self) -> None:
        """Clean up connections, threads, and socket clients."""
        pass
