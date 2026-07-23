"""Multi-account wrapper for the personal Weixin adapter."""

from __future__ import annotations

import asyncio
from typing import Any

from pydantic import BaseModel, Field, field_validator

from src.channels import weixin_account as account_impl
from src.channels.base import BaseChannel
from src.channels.bus.events import OutboundMessage
from src.channels.bus.queue import MessageBus
from src.channels.utils import get_runtime_subdir
from src.channels.weixin_routing import validate_account_alias


class AuxiliaryWeixinAccountConfig(BaseModel):
    enabled: bool = False
    allow_from: list[str] = Field(default_factory=list)
    base_url: str = "https://ilinkai.weixin.qq.com"
    cdn_base_url: str = "https://novac2c.cdn.weixin.qq.com/c2c"
    route_tag: str | int | None = None
    poll_timeout: int = account_impl.DEFAULT_LONG_POLL_TIMEOUT_S


class WeixinConfig(account_impl.WeixinAccountConfig):
    accounts: dict[str, AuxiliaryWeixinAccountConfig] = Field(default_factory=dict)

    @field_validator("accounts")
    @classmethod
    def validate_accounts(
        cls,
        value: dict[str, AuxiliaryWeixinAccountConfig],
    ) -> dict[str, AuxiliaryWeixinAccountConfig]:
        return {
            validate_account_alias(alias): config
            for alias, config in value.items()
        }


class WeixinChannel(BaseChannel):
    name = "weixin"
    display_name = "WeChat"

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return WeixinConfig().model_dump(by_alias=True)

    def __init__(self, config: Any, bus: MessageBus) -> None:
        parsed = config if isinstance(config, WeixinConfig) else WeixinConfig.model_validate(config)
        super().__init__(parsed, bus)
        self._accounts = self._build_accounts(parsed)
        self._account_tasks: dict[str, asyncio.Task[None]] = {}
        self._account_errors: dict[str, str] = {}
        self._login_required: set[str] = set()
        self._lifecycle_lock = asyncio.Lock()

    def _runtime_config_for_auxiliary(
        self,
        alias: str,
        config: AuxiliaryWeixinAccountConfig,
    ) -> account_impl.WeixinAccountConfig:
        state_dir = get_runtime_subdir("weixin") / "accounts" / alias
        return account_impl.WeixinAccountConfig(
            **config.model_dump(),
            state_dir=str(state_dir),
        )

    def _build_accounts(
        self,
        parsed: WeixinConfig,
    ) -> dict[str, account_impl.WeixinAccountRuntime]:
        primary_payload = parsed.model_dump(exclude={"accounts"})
        runtimes = {
            "primary": account_impl.WeixinAccountRuntime(
                account_impl.WeixinAccountConfig.model_validate(primary_payload),
                self.bus,
                account_id="primary",
            )
        }
        for alias, auxiliary in parsed.accounts.items():
            runtimes[alias] = account_impl.WeixinAccountRuntime(
                self._runtime_config_for_auxiliary(alias, auxiliary),
                self.bus,
                account_id=alias,
            )
        return runtimes

    @property
    def account_ids(self) -> tuple[str, ...]:
        return tuple(self._accounts)

    def account(self, account_id: str) -> account_impl.WeixinAccountRuntime:
        return self._accounts[account_id]

    @property
    def login_required_accounts(self) -> frozenset[str]:
        return frozenset(self._login_required)

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

    async def _run_account(self, alias: str) -> None:
        runtime = self._accounts[alias]
        try:
            await runtime.start(allow_qr_login=False)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._account_errors[alias] = type(exc).__name__
            self.logger.exception("Weixin account %s stopped unexpectedly", alias)

    async def start(self) -> None:
        self._sync_flags()
        async with self._lifecycle_lock:
            account_tasks = tuple(self._account_tasks.values())
            if not any(not task.done() for task in account_tasks):
                self._account_errors.clear()
                enabled_accounts = {
                    alias: runtime
                    for alias, runtime in self._accounts.items()
                    if runtime.config.enabled
                }
                credentials = {
                    alias: runtime.has_saved_credentials
                    for alias, runtime in enabled_accounts.items()
                }
                self._login_required = {
                    alias
                    for alias, has_credentials in credentials.items()
                    if not has_credentials
                }
                self._account_tasks = {
                    alias: asyncio.create_task(self._run_account(alias))
                    for alias, has_credentials in credentials.items()
                    if has_credentials
                }
                account_tasks = tuple(self._account_tasks.values())
        if not account_tasks:
            return
        await asyncio.gather(*account_tasks, return_exceptions=True)

    async def stop(self) -> None:
        async with self._lifecycle_lock:
            account_tasks = self._account_tasks
            cancelled_error: asyncio.CancelledError | None = None
            try:
                for alias in tuple(account_tasks):
                    try:
                        await self._accounts[alias].stop()
                    except asyncio.CancelledError as exc:
                        cancelled_error = exc
                    except Exception as exc:
                        self._account_errors[alias] = type(exc).__name__
            finally:
                for task in account_tasks.values():
                    if not task.done():
                        task.cancel()
                try:
                    await asyncio.gather(
                        *account_tasks.values(),
                        return_exceptions=True,
                    )
                finally:
                    self._account_tasks.clear()
            if cancelled_error is not None:
                raise cancelled_error

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
