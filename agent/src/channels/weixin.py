"""Multi-account wrapper for the personal Weixin adapter."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from src.channels import weixin_account as account_impl
from src.channels.base import BaseChannel
from src.channels.bus.events import OutboundMessage
from src.channels.bus.queue import MessageBus


class WeixinConfig(account_impl.WeixinAccountConfig):
    accounts: dict[str, dict[str, Any]] = Field(default_factory=dict)


class WeixinChannel(BaseChannel):
    name = "weixin"
    display_name = "WeChat"

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return WeixinConfig().model_dump(by_alias=True)

    def __init__(self, config: Any, bus: MessageBus) -> None:
        parsed = config if isinstance(config, WeixinConfig) else WeixinConfig.model_validate(config)
        super().__init__(parsed, bus)
        primary_payload = parsed.model_dump(exclude={"accounts"})
        self._accounts = {
            "primary": account_impl.WeixinAccountRuntime(
                account_impl.WeixinAccountConfig.model_validate(primary_payload),
                bus,
                account_id="primary",
            )
        }

    @property
    def account_ids(self) -> tuple[str, ...]:
        return tuple(self._accounts)

    def account(self, account_id: str) -> account_impl.WeixinAccountRuntime:
        return self._accounts[account_id]

    def route_for(self, account_id: str, peer_id: str) -> str:
        if account_id != "primary":
            raise KeyError(account_id)
        return str(peer_id)

    def _sync_flags(self) -> None:
        for runtime in self._accounts.values():
            runtime.send_progress = self.send_progress
            runtime.send_tool_hints = self.send_tool_hints
            runtime.show_reasoning = self.show_reasoning

    async def login(self, force: bool = False) -> bool:
        self._sync_flags()
        return await self._accounts["primary"].login(force=force)

    async def start(self) -> None:
        self._sync_flags()
        await self._accounts["primary"].start()

    async def stop(self) -> None:
        await self._accounts["primary"].stop()

    async def send(self, msg: OutboundMessage) -> None:
        self._sync_flags()
        await self._accounts["primary"].send(msg)

    async def send_delta(
        self, chat_id: str, delta: str, metadata: dict[str, Any] | None = None,
    ) -> None:
        self._sync_flags()
        await self._accounts["primary"].send_delta(chat_id, delta, metadata)

    @property
    def is_running(self) -> bool:
        return self._accounts["primary"].is_running
